from datetime import datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.adapters.milvus.collections import MilvusCollectionClient
from app.adapters.sqlite.chunks import CanonChunk
from app.adapters.sqlite.embeddings import ChunkEmbedding, EmbeddingProfileRecord
from app.domain.chapter import VersionKind
from app.domain.milvus_collection import MilvusCollectionError
from app.services.canon_chunks import list_canon_chunks
from app.services.milvus_collections import ensure_profile_collection


def metadata_filter(*, novel_id: str, canon_status: str = "active") -> str:
    return " and ".join(
        [
            _equals("novel_id", novel_id),
            _equals("canon_status", canon_status),
        ]
    )


def retrieval_filter(
    *,
    novel_id: str,
    characters: list[str] | None = None,
    locations: list[str] | None = None,
) -> str:
    """Canon filter for one novel. Stored canon_status is active, never Draft."""

    parts = [metadata_filter(novel_id=novel_id)]
    character_match = _json_any("characters", characters or [])
    location_match = _json_any("locations", locations or [])
    if character_match:
        parts.append(character_match)
    if location_match:
        parts.append(location_match)
    return " and ".join(parts)


def deletion_filter(
    *,
    chunk_id: str | None = None,
    chapter_id: str | None = None,
    novel_id: str | None = None,
) -> str:
    parts: list[str] = []
    if chunk_id is not None:
        parts.append(_equals("chunk_id", chunk_id))
    if chapter_id is not None:
        parts.append(_equals("chapter_id", chapter_id))
    if novel_id is not None:
        parts.append(_equals("novel_id", novel_id))
    if not parts:
        raise MilvusCollectionError(
            "filter_empty", "A delete filter needs a chunk, chapter, or novel."
        )
    return " and ".join(parts)


def canon_vector_row(
    chunk: CanonChunk, vector: list[float], profile: EmbeddingProfileRecord
) -> dict:
    if chunk.source_version_kind == VersionKind.DRAFT.value:
        raise MilvusCollectionError(
            "draft_cannot_enter_index",
            "A Draft chunk cannot enter the official Canon collection.",
        )
    if chunk.canon_status != "active":
        raise MilvusCollectionError(
            "chunk_not_active",
            "Only an active Canon chunk can enter the official collection.",
        )
    if len(vector) != profile.dimension:
        raise MilvusCollectionError(
            "dimension_mismatch",
            f"Vector dimension {len(vector)} does not match profile {profile.dimension}.",
        )
    return {
        "id": chunk.id,
        "novel_id": chunk.novel_id,
        "chapter_id": chunk.chapter_id,
        "chunk_id": chunk.id,
        "sequence": chunk.sequence,
        "text_hash": chunk.text_checksum,
        "characters": list(chunk.characters),
        "locations": list(chunk.locations),
        "canon_status": chunk.canon_status,
        "embedding_model": f"{profile.embedding_model_id}:{profile.embedding_model_tag}",
        "embedding_version": profile.embedding_model_version,
        "embedding": list(vector),
        "created_at": _millis(chunk.created_at),
    }


async def upsert_canon_embeddings(
    session: Session,
    client: MilvusCollectionClient,
    novel_id: str,
    profile: EmbeddingProfileRecord,
) -> int:
    described = await ensure_profile_collection(client, profile)
    if described.metadata.get("index_version") != profile.index_version:
        raise MilvusCollectionError(
            "collection_profile_mismatch",
            "Collection index version does not match the active profile.",
        )
    ready = {
        row.chunk_id: row
        for row in session.scalars(
            select(ChunkEmbedding).where(
                ChunkEmbedding.novel_id == novel_id,
                ChunkEmbedding.profile_id == profile.id,
                ChunkEmbedding.status == "ready",
            )
        )
    }
    rows: list[dict] = []
    for chunk in list_canon_chunks(session, novel_id):
        stored = ready.get(chunk.id)
        if stored is None or not stored.vector:
            continue
        if stored.text_checksum != chunk.text_checksum:
            continue
        rows.append(canon_vector_row(chunk, list(stored.vector), profile))
    if rows:
        await client.upsert(described.name, rows)
    return len(rows)


async def delete_canon_embeddings(
    client: MilvusCollectionClient,
    profile: EmbeddingProfileRecord,
    *,
    chunk_id: str | None = None,
    chapter_id: str | None = None,
    novel_id: str | None = None,
) -> None:
    described = await ensure_profile_collection(client, profile)
    await client.delete_where(
        described.name,
        deletion_filter(chunk_id=chunk_id, chapter_id=chapter_id, novel_id=novel_id),
    )


def _json_any(field: str, values: list[str]) -> str:
    clauses = [f"json_contains({field}, {_quoted(value)})" for value in values if value.strip()]
    if not clauses:
        return ""
    if len(clauses) == 1:
        return clauses[0]
    return "(" + " or ".join(clauses) + ")"


def _quoted(value: str) -> str:
    cleaned = value.strip()
    if '"' in cleaned or "\\" in cleaned:
        raise MilvusCollectionError("filter_value_invalid", "Filter values cannot contain quotes.")
    return f'"{cleaned}"'


def _equals(field: str, value: str) -> str:
    if '"' in value or "\\" in value:
        raise MilvusCollectionError("filter_value_invalid", "Filter values cannot contain quotes.")
    return f'{field} == "{value}"'


def _millis(value: datetime) -> int:
    return int(value.timestamp() * 1000)
