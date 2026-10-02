import json
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.adapters.milvus.collections import MilvusCollectionClient
from app.adapters.sqlite.index_registry import IndexVersionRecord, registry_now
from app.domain.index_registry import index_manifest
from app.services.milvus_collections import drop_profile_collection


class IndexRegistryError(Exception):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


def open_index_version(
    session: Session,
    *,
    collection_name: str,
    embedding_profile_id: str,
    chunking_version: str,
    index_version: str,
    record_count: int,
    corpus_checksum: str = "",
) -> IndexVersionRecord:
    existing = session.scalar(
        select(IndexVersionRecord).where(
            IndexVersionRecord.collection_name == collection_name,
            IndexVersionRecord.status.in_(("building", "validating", "active")),
        )
    )
    if existing is not None:
        return existing
    manifest_json, checksum = index_manifest(
        collection_name=collection_name,
        embedding_profile_id=embedding_profile_id,
        chunking_version=chunking_version,
        index_version=index_version,
        record_count=record_count,
        corpus_checksum=corpus_checksum,
    )
    row = IndexVersionRecord(
        id=str(uuid4()),
        collection_name=collection_name,
        embedding_profile_id=embedding_profile_id,
        chunking_version=chunking_version,
        index_version=index_version,
        status="building",
        record_count=record_count,
        manifest_json=manifest_json,
        manifest_checksum=checksum,
        failure_code=None,
        created_at=registry_now(),
        activated_at=None,
    )
    session.add(row)
    session.flush()
    return row


def mark_index_validating(session: Session, index_id: str) -> IndexVersionRecord:
    row = _require(session, index_id)
    if row.status == "validating":
        return row
    if row.status != "building":
        raise IndexRegistryError("index_not_building", "Only a building index can be validated.")
    row.status = "validating"
    session.flush()
    return row


def mark_index_failed(session: Session, index_id: str, *, code: str) -> IndexVersionRecord:
    row = _require(session, index_id)
    if row.status == "active":
        raise IndexRegistryError(
            "active_index_protected",
            "The serving index cannot be marked failed.",
        )
    if row.status not in {"building", "validating"}:
        raise IndexRegistryError(
            "index_not_open",
            "Only a building or validating index can fail.",
        )
    row.status = "failed"
    row.failure_code = code
    session.flush()
    return row


def activate_index(session: Session, index_id: str) -> IndexVersionRecord:
    target = _require(session, index_id)
    if target.status == "active":
        return target
    if target.status != "validating":
        raise IndexRegistryError(
            "index_not_validated",
            "Retrieval can switch only to an index that finished validation.",
        )
    try:
        with session.begin_nested():
            _expected_manifest(target)
            current = serving_index(session)
            if current is not None and current.id != target.id:
                current.status = "superseded"
                session.flush()
            target.status = "active"
            target.activated_at = registry_now()
            session.flush()
    except IndexRegistryError:
        session.expire_all()
        raise
    return target


def retire_index(session: Session, index_id: str) -> IndexVersionRecord:
    row = _require(session, index_id)
    if row.status == "retired":
        return row
    if row.status != "superseded":
        raise IndexRegistryError(
            "index_not_superseded",
            "Retire the previous index only after a newer one is serving.",
        )
    row.status = "retired"
    session.flush()
    return row


async def cleanup_retired_index(
    session: Session, client: MilvusCollectionClient, index_id: str
) -> IndexVersionRecord:
    row = _require(session, index_id)
    if row.status != "retired":
        raise IndexRegistryError(
            "index_not_retired",
            "A collection is dropped only after its index version is retired.",
        )
    await drop_profile_collection(client, row.collection_name)
    return row


def serving_index(session: Session) -> IndexVersionRecord | None:
    return session.scalar(select(IndexVersionRecord).where(IndexVersionRecord.status == "active"))


def require_serving_index(session: Session) -> IndexVersionRecord:
    row = serving_index(session)
    if row is None:
        raise IndexRegistryError("no_active_index", "Retrieval has no active index version.")
    return row


def _require(session: Session, index_id: str) -> IndexVersionRecord:
    row = session.get(IndexVersionRecord, index_id)
    if row is None:
        raise IndexRegistryError("index_not_found", "Index version does not exist.")
    return row


def _expected_manifest(row: IndexVersionRecord) -> None:
    stored = json.loads(row.manifest_json)
    _text, checksum = index_manifest(
        collection_name=row.collection_name,
        embedding_profile_id=row.embedding_profile_id,
        chunking_version=row.chunking_version,
        index_version=row.index_version,
        record_count=row.record_count,
        corpus_checksum=str(stored.get("corpus_checksum") or ""),
    )
    if checksum != row.manifest_checksum:
        raise IndexRegistryError(
            "manifest_mismatch",
            "Index manifest does not match the registered collection.",
        )
