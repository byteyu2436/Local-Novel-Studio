import pytest
from app.adapters.sqlite import bootstrap_local_runtime, session_scope
from app.adapters.sqlite.index_registry import IndexVersionRecord
from app.services.index_registry import (
    IndexRegistryError,
    activate_index,
    cleanup_retired_index,
    mark_index_failed,
    mark_index_validating,
    open_index_version,
    require_serving_index,
    retire_index,
    serving_index,
)
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError


def _open(session, name: str, *, count: int = 3):
    return open_index_version(
        session,
        collection_name=name,
        embedding_profile_id="profile-a",
        chunking_version="chunking.v1",
        index_version="index-a",
        record_count=count,
    )


def test_switch_is_atomic_and_retrieval_ignores_unready_indexes(isolated_data_dir) -> None:
    _settings, engine, factory = bootstrap_local_runtime()
    try:
        for session in session_scope(factory):
            building = _open(session, "novel_chunks_one")
            again = _open(session, "novel_chunks_one")
            assert again.id == building.id
            assert serving_index(session) is None
            with pytest.raises(IndexRegistryError) as missing:
                require_serving_index(session)
            assert missing.value.code == "no_active_index"
            with pytest.raises(IndexRegistryError) as early:
                activate_index(session, building.id)
            assert early.value.code == "index_not_validated"

            mark_index_validating(session, building.id)
            active = activate_index(session, building.id)
            assert activate_index(session, building.id).id == active.id
            assert require_serving_index(session).collection_name == "novel_chunks_one"
            assert active.activated_at is not None

            failed = _open(session, "novel_chunks_bad")
            mark_index_failed(session, failed.id, code="validate_failed")
            assert serving_index(session).id == active.id
            with pytest.raises(IndexRegistryError) as protected:
                mark_index_failed(session, active.id, code="nope")
            assert protected.value.code == "active_index_protected"

            nxt = _open(session, "novel_chunks_two")
            nxt.manifest_checksum = "broken"
            mark_index_validating(session, nxt.id)
            with pytest.raises(IndexRegistryError) as mismatch:
                activate_index(session, nxt.id)
            assert mismatch.value.code == "manifest_mismatch"
            session.expire_all()
            assert session.get(IndexVersionRecord, active.id).status == "active"
            assert session.get(IndexVersionRecord, nxt.id).status == "validating"

            nxt.manifest_checksum = active.manifest_checksum
            ready = index_manifest_for(nxt)
            nxt.manifest_checksum = ready
            switched = activate_index(session, nxt.id)
            assert switched.status == "active"
            assert session.get(IndexVersionRecord, active.id).status == "superseded"
            assert serving_index(session).id == switched.id
            assert (
                session.scalar(
                    select(func.count())
                    .select_from(IndexVersionRecord)
                    .where(IndexVersionRecord.status == "active")
                )
                == 1
            )
    finally:
        engine.dispose()


def test_retired_index_can_be_dropped_without_touching_the_serving_one(isolated_data_dir) -> None:
    import asyncio

    _settings, engine, factory = bootstrap_local_runtime()
    try:
        for session in session_scope(factory):
            first = mark_index_validating(session, _open(session, "novel_chunks_old").id)
            activate_index(session, first.id)
            second = mark_index_validating(session, _open(session, "novel_chunks_new").id)
            activate_index(session, second.id)
            with pytest.raises(IndexRegistryError) as serving:
                asyncio.run(cleanup_retired_index(session, _Drop(), first.id))
            assert serving.value.code == "index_not_retired"
            retire_index(session, first.id)
            dropped = _Drop()

            async def _run(session=session, first=first, dropped=dropped) -> None:
                await cleanup_retired_index(session, dropped, first.id)

            asyncio.run(_run())
            assert dropped.names == ["novel_chunks_old"]
            assert session.get(IndexVersionRecord, first.id).status == "retired"
            assert require_serving_index(session).id == second.id
    finally:
        engine.dispose()


def test_two_active_rows_are_rejected(isolated_data_dir) -> None:
    _settings, engine, factory = bootstrap_local_runtime()
    try:
        for session in session_scope(factory):
            first = mark_index_validating(session, _open(session, "novel_chunks_a").id)
            activate_index(session, first.id)
            second = mark_index_validating(session, _open(session, "novel_chunks_b").id)
            second.status = "active"
            with pytest.raises(IntegrityError):
                session.flush()
            session.rollback()
    finally:
        engine.dispose()


def index_manifest_for(row: IndexVersionRecord) -> str:
    from app.domain.index_registry import index_manifest

    _text, checksum = index_manifest(
        collection_name=row.collection_name,
        embedding_profile_id=row.embedding_profile_id,
        chunking_version=row.chunking_version,
        index_version=row.index_version,
        record_count=row.record_count,
    )
    return checksum


class _Drop:
    def __init__(self) -> None:
        self.names: list[str] = []

    async def exists(self, name: str) -> bool:
        return True

    async def drop(self, name: str) -> None:
        self.names.append(name)
