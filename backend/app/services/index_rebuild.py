from dataclasses import dataclass
from hashlib import sha256
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.adapters.embedding.types import EmbeddingProvider
from app.adapters.milvus.collections import CollectionDescription, MilvusCollectionClient
from app.adapters.sqlite.chunks import CanonChunk
from app.adapters.sqlite.embeddings import ChunkEmbedding, EmbeddingProfileRecord
from app.adapters.sqlite.index_registry import IndexVersionRecord
from app.adapters.sqlite.models import ChapterVersion
from app.domain.chunking import ChunkingProfile
from app.domain.index_registry import index_manifest
from app.domain.milvus_collection import build_collection_spec
from app.services import catalog
from app.services.canon_chunks import build_chapter_chunks, list_canon_chunks
from app.services.embedding_batches import embed_canon_chunks
from app.services.embedding_profiles import (
    require_active_embedding_profile,
    require_same_embedding_profile,
)
from app.services.index_registry import (
    IndexRegistryError,
    activate_index,
    mark_index_failed,
    mark_index_validating,
    open_index_version,
    serving_index,
)
from app.services.milvus_collections import drop_profile_collection
from app.services.milvus_vectors import canon_vector_row


class RebuildError(Exception):
    def __init__(self, code: str, message: str, *, index_id: str | None = None) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.index_id = index_id


@dataclass(frozen=True)
class RebuildReport:
    index_id: str
    collection_name: str
    status: str
    chunk_count: int
    vector_count: int
    manifest_checksum: str
    switched: bool


async def rebuild_canon_index(
    session: Session,
    client: MilvusCollectionClient,
    provider: EmbeddingProvider,
    *,
    profile_id: str | None = None,
) -> RebuildReport:
    """Rebuild a new collection from SQLite Canon, then switch only after validation."""

    profile = require_active_embedding_profile(session)
    if profile_id is not None:
        require_same_embedding_profile(profile.id, profile_id)
    previous = serving_index(session)
    chunks = _ensure_chunks(session, profile.chunking_version)
    corpus = corpus_checksum(chunks)
    spec = build_collection_spec(
        profile_id=profile.id,
        embedding_model_id=profile.embedding_model_id,
        embedding_model_tag=profile.embedding_model_tag,
        embedding_model_version=profile.embedding_model_version,
        dimension=profile.dimension,
        chunking_version=profile.chunking_version,
        index_version=profile.index_version,
        name_suffix=uuid4().hex[:12],
    )
    index_row = open_index_version(
        session,
        collection_name=spec.name,
        embedding_profile_id=profile.id,
        chunking_version=profile.chunking_version,
        index_version=profile.index_version,
        record_count=len(chunks),
        corpus_checksum=corpus,
    )
    created = False
    try:
        await client.create(spec)
        created = True
        await _embed_novels(session, provider, profile.id)
        rows = _vector_rows(session, chunks, profile)
        if len(rows) != len(chunks):
            raise RebuildError(
                "rebuild_count_mismatch",
                "Ready vectors do not cover every active Canon chunk.",
                index_id=index_row.id,
            )
        if rows:
            await client.upsert(spec.name, rows)
        described = await client.describe(spec.name)
        validate_rebuild(
            described=described,
            profile_id=profile.id,
            index_version=profile.index_version,
            dimension=profile.dimension,
            chunks=chunks,
            vector_count=len(rows),
            manifest_checksum=index_row.manifest_checksum,
            collection_name=spec.name,
        )
        mark_index_validating(session, index_row.id)
        active = activate_index(session, index_row.id)
        profile.rebuild_required = False
        session.flush()
        return RebuildReport(
            index_id=active.id,
            collection_name=active.collection_name,
            status=active.status,
            chunk_count=len(chunks),
            vector_count=len(rows),
            manifest_checksum=active.manifest_checksum,
            switched=previous is None or previous.id != active.id,
        )
    except Exception as exc:
        _mark_failed(session, index_row, exc)
        if created and (previous is None or previous.collection_name != spec.name):
            await _drop_quietly(client, spec.name)
        if isinstance(exc, RebuildError):
            if exc.index_id is None:
                exc.index_id = index_row.id
            raise
        code = getattr(exc, "code", "rebuild_failed")
        raise RebuildError(str(code), str(exc), index_id=index_row.id) from exc


def corpus_checksum(chunks: list[CanonChunk]) -> str:
    lines = [
        f"{chunk.novel_id}:{chunk.id}:{chunk.text_checksum}"
        for chunk in sorted(chunks, key=lambda item: (item.sequence, item.id))
    ]
    return sha256("\n".join(lines).encode()).hexdigest()


def validate_rebuild(
    *,
    described: CollectionDescription,
    profile_id: str,
    index_version: str,
    dimension: int,
    chunks: list[CanonChunk],
    vector_count: int,
    manifest_checksum: str,
    collection_name: str,
) -> None:
    if described.dimension != dimension or described.metadata.get("profile_id") != profile_id:
        raise RebuildError(
            "rebuild_profile_mismatch",
            "The new collection does not match the active embedding profile.",
        )
    if described.metadata.get("index_version") != index_version:
        raise RebuildError(
            "rebuild_profile_mismatch",
            "The new collection index version does not match the active profile.",
        )
    if vector_count != len(chunks):
        raise RebuildError(
            "rebuild_count_mismatch",
            "Vector count does not match the Canon chunk count.",
        )
    _text, checksum = index_manifest(
        collection_name=collection_name,
        embedding_profile_id=profile_id,
        chunking_version=described.metadata.get("chunking_version") or "",
        index_version=index_version,
        record_count=len(chunks),
        corpus_checksum=corpus_checksum(chunks),
    )
    if checksum != manifest_checksum:
        raise RebuildError(
            "manifest_mismatch",
            "Rebuild manifest does not match the Canon chunk checksum.",
        )


def _ensure_chunks(session: Session, chunking_version: str) -> list[CanonChunk]:
    chunking = ChunkingProfile(version=chunking_version)
    found: list[CanonChunk] = []
    for novel in catalog.list_novels(session):
        for chapter in catalog.list_chapters(session, novel.id):
            if chapter.current_canon_version_id is None:
                continue
            existing = [
                chunk
                for chunk in list_canon_chunks(session, novel.id, chapter_id=chapter.id)
                if chunk.chunking_version == chunking_version
            ]
            if existing:
                continue
            version = session.get(ChapterVersion, chapter.current_canon_version_id)
            if version is None:
                continue
            build_chapter_chunks(session, novel.id, chapter, version, chunking)
        found.extend(
            chunk
            for chunk in list_canon_chunks(session, novel.id)
            if chunk.chunking_version == chunking_version
        )
    return found


async def _embed_novels(session: Session, provider: EmbeddingProvider, profile_id: str) -> None:
    for novel in catalog.list_novels(session):
        report = await embed_canon_chunks(session, novel.id, provider, profile_id=profile_id)
        if report.failed:
            raise RebuildError(
                "rebuild_embedding_failed",
                "A chunk embedding batch failed, so the new index was not switched.",
            )


def _vector_rows(
    session: Session, chunks: list[CanonChunk], profile: EmbeddingProfileRecord
) -> list[dict]:
    ready = {
        row.chunk_id: row
        for row in session.scalars(
            select(ChunkEmbedding).where(
                ChunkEmbedding.profile_id == profile.id,
                ChunkEmbedding.status == "ready",
            )
        )
    }
    rows: list[dict] = []
    for chunk in chunks:
        stored = ready.get(chunk.id)
        if stored is None or not stored.vector or stored.text_checksum != chunk.text_checksum:
            continue
        rows.append(canon_vector_row(chunk, list(stored.vector), profile))
    return rows


def _mark_failed(session: Session, index_row: IndexVersionRecord, exc: Exception) -> None:
    if index_row.status not in {"building", "validating"}:
        return
    code = getattr(exc, "code", "rebuild_failed")
    try:
        mark_index_failed(session, index_row.id, code=str(code)[:64])
    except IndexRegistryError:
        return


async def _drop_quietly(client: MilvusCollectionClient, name: str) -> None:
    try:
        await drop_profile_collection(client, name)
    except Exception:
        return
