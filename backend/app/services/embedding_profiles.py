from sqlalchemy import select
from sqlalchemy.orm import Session

from app.adapters.embedding.errors import EmbeddingProfileMismatchError
from app.adapters.sqlite.embeddings import EmbeddingProfileRecord, embedding_now
from app.domain.embedding_profile import (
    EmbeddingProfileSpec,
    index_version_for,
    profile_fingerprint,
)


def activate_embedding_profile(
    session: Session, spec: EmbeddingProfileSpec
) -> EmbeddingProfileRecord:
    fingerprint = profile_fingerprint(spec)
    current = get_active_embedding_profile(session)
    changed = current is None or current.id != fingerprint
    if current is not None and current.id != fingerprint:
        current.is_active = False
        session.flush()
    row = session.get(EmbeddingProfileRecord, fingerprint)
    if row is None:
        row = EmbeddingProfileRecord(
            id=fingerprint,
            embedding_model_id=spec.embedding_model_id,
            embedding_model_tag=spec.embedding_model_tag,
            embedding_model_version=spec.embedding_model_version,
            dimension=spec.dimension,
            normalization=spec.normalization,
            chunking_version=spec.chunking_version,
            index_version=index_version_for(fingerprint),
            rebuild_required=changed,
            is_active=True,
            created_at=embedding_now(),
        )
        session.add(row)
    else:
        row.is_active = True
        if changed:
            row.rebuild_required = True
    session.flush()
    return row


def get_active_embedding_profile(session: Session) -> EmbeddingProfileRecord | None:
    return session.scalar(
        select(EmbeddingProfileRecord).where(EmbeddingProfileRecord.is_active.is_(True))
    )


def require_active_embedding_profile(session: Session) -> EmbeddingProfileRecord:
    row = get_active_embedding_profile(session)
    if row is None:
        raise EmbeddingProfileMismatchError("No active embedding profile is selected.")
    return row


def require_same_embedding_profile(active_id: str, requested_id: str) -> None:
    if active_id != requested_id:
        raise EmbeddingProfileMismatchError(
            "Query and chunk embeddings must use the same active profile."
        )
