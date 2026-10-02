import time
from dataclasses import dataclass, field
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.adapters.embedding.errors import EmbeddingDimensionError, EmbeddingError
from app.adapters.embedding.types import EmbeddingProvider
from app.adapters.sqlite.chunks import CanonChunk
from app.adapters.sqlite.embeddings import ChunkEmbedding, embedding_now
from app.services.canon_chunks import list_canon_chunks
from app.services.embedding_profiles import (
    require_active_embedding_profile,
    require_same_embedding_profile,
)


@dataclass(frozen=True)
class EmbeddingExecutionStrategy:
    """P0 strategy. Device selection stays a label until a scheduler exists."""

    batch_size: int = 16
    device: str = "default"

    def __post_init__(self) -> None:
        if self.batch_size < 1:
            raise ValueError("batch_size must be positive")


@dataclass
class EmbeddingBatchReport:
    profile_id: str
    index_version: str
    embedded: int = 0
    skipped_ready: int = 0
    failed: int = 0
    batches: int = 0
    elapsed_ms: int = 0
    failed_chunk_ids: list[str] = field(default_factory=list)


async def embed_canon_chunks(
    session: Session,
    novel_id: str,
    provider: EmbeddingProvider,
    *,
    profile_id: str | None = None,
    strategy: EmbeddingExecutionStrategy | None = None,
) -> EmbeddingBatchReport:
    profile = require_active_embedding_profile(session)
    if profile_id is not None:
        require_same_embedding_profile(profile.id, profile_id)
    resolved = strategy or EmbeddingExecutionStrategy()
    chunks = list_canon_chunks(session, novel_id)
    existing = {
        row.chunk_id: row
        for row in session.scalars(
            select(ChunkEmbedding).where(
                ChunkEmbedding.novel_id == novel_id,
                ChunkEmbedding.profile_id == profile.id,
            )
        )
    }
    pending: list[CanonChunk] = []
    skipped = 0
    for chunk in chunks:
        row = existing.get(chunk.id)
        if (
            row is not None
            and row.status == "ready"
            and row.text_checksum == chunk.text_checksum
            and row.dimension == profile.dimension
        ):
            skipped += 1
            continue
        pending.append(chunk)
    report = EmbeddingBatchReport(
        profile_id=profile.id,
        index_version=profile.index_version,
        skipped_ready=skipped,
    )
    started = time.perf_counter()
    for offset in range(0, len(pending), resolved.batch_size):
        batch = pending[offset : offset + resolved.batch_size]
        report.batches += 1
        batch_started = time.perf_counter()
        try:
            vectors = await provider.embed_documents([chunk.text for chunk in batch])
        except EmbeddingError as exc:
            _mark_failed(session, batch, profile.id, report.batches, exc.code, batch_started)
            report.failed += len(batch)
            report.failed_chunk_ids.extend(chunk.id for chunk in batch)
            continue
        _store_batch(
            session,
            batch,
            vectors,
            profile.id,
            profile.dimension,
            report,
            batch_started,
        )
    report.elapsed_ms = int((time.perf_counter() - started) * 1000)
    return report


async def embed_query_text(
    session: Session,
    provider: EmbeddingProvider,
    text: str,
    *,
    profile_id: str | None = None,
) -> list[float]:
    profile = require_active_embedding_profile(session)
    if profile_id is not None:
        require_same_embedding_profile(profile.id, profile_id)
    vector = await provider.embed_query(text)
    if len(vector) != profile.dimension:
        raise EmbeddingDimensionError(
            f"Query dimension {len(vector)} does not match profile {profile.dimension}."
        )
    return vector


def _store_batch(
    session: Session,
    batch: list[CanonChunk],
    vectors: list[list[float]],
    profile_id: str,
    dimension: int,
    report: EmbeddingBatchReport,
    started: float,
) -> None:
    if len(vectors) != len(batch):
        _mark_failed(
            session,
            batch,
            profile_id,
            report.batches,
            EmbeddingDimensionError.code,
            time.perf_counter(),
        )
        report.failed += len(batch)
        report.failed_chunk_ids.extend(chunk.id for chunk in batch)
        return
    elapsed = max(0, int((time.perf_counter() - started) * 1000))
    for chunk, vector in zip(batch, vectors, strict=True):
        if len(vector) != dimension:
            _upsert(
                session,
                chunk,
                profile_id,
                status="failed",
                vector=None,
                error_code=EmbeddingDimensionError.code,
                batch_no=report.batches,
                elapsed_ms=elapsed,
            )
            report.failed += 1
            report.failed_chunk_ids.append(chunk.id)
            continue
        _upsert(
            session,
            chunk,
            profile_id,
            status="ready",
            vector=vector,
            error_code=None,
            batch_no=report.batches,
            elapsed_ms=elapsed,
        )
        chunk.embedding_profile_id = profile_id
        report.embedded += 1
    session.flush()


def _mark_failed(
    session: Session,
    batch: list[CanonChunk],
    profile_id: str,
    batch_no: int,
    error_code: str,
    started: float,
) -> None:
    elapsed = max(0, int((time.perf_counter() - started) * 1000))
    for chunk in batch:
        _upsert(
            session,
            chunk,
            profile_id,
            status="failed",
            vector=None,
            error_code=error_code,
            batch_no=batch_no,
            elapsed_ms=elapsed,
        )
    session.flush()


def _upsert(
    session: Session,
    chunk: CanonChunk,
    profile_id: str,
    *,
    status: str,
    vector: list[float] | None,
    error_code: str | None,
    batch_no: int,
    elapsed_ms: int,
) -> None:
    row = session.scalar(
        select(ChunkEmbedding).where(
            ChunkEmbedding.chunk_id == chunk.id,
            ChunkEmbedding.profile_id == profile_id,
        )
    )
    now = embedding_now()
    if row is None:
        row = ChunkEmbedding(
            id=str(uuid4()),
            chunk_id=chunk.id,
            novel_id=chunk.novel_id,
            profile_id=profile_id,
            text_checksum=chunk.text_checksum,
            status=status,
            dimension=len(vector) if vector is not None else None,
            vector=vector,
            error_code=error_code,
            batch_no=batch_no,
            elapsed_ms=elapsed_ms,
            created_at=now,
            updated_at=now,
        )
        session.add(row)
        return
    row.text_checksum = chunk.text_checksum
    row.status = status
    row.dimension = len(vector) if vector is not None else None
    row.vector = vector
    row.error_code = error_code
    row.batch_no = batch_no
    row.elapsed_ms = elapsed_ms
    row.updated_at = now
