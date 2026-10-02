import json

from app.adapters.sqlite import bootstrap_local_runtime, session_scope
from app.domain.jobs import JobState, UnitState
from app.main import app
from app.services.analysis_orchestrator import (
    cancel_novel_analysis,
    find_active_analysis_job,
    pause_novel_analysis,
    resume_novel_analysis,
    retry_failed_chapter,
)
from fastapi.testclient import TestClient
from tests.test_analysis_orchestrator import RecordingProvider, _run, _seed
from tests.test_chapter_analysis import _valid_payload


def test_pause_resume_eighteen_chapters_and_repeated_pause(isolated_data_dir) -> None:
    payload = json.dumps(_valid_payload(), ensure_ascii=False)
    bodies = [f"第{index}章正文" for index in range(1, 19)]
    _settings, engine, factory = bootstrap_local_runtime()
    novel_id = ""

    class PauseAfterFirst(RecordingProvider):
        async def chat(self, messages, profile, *, response_format=None) -> str:  # type: ignore[no-untyped-def]
            text = await super().chat(messages, profile, response_format=response_format)
            if len(self.bodies) == 1:
                for reader in session_scope(factory):
                    job = find_active_analysis_job(reader, novel_id)
                    assert job is not None
                    pause_novel_analysis(reader, job.id)
            return text

    provider = PauseAfterFirst(payload)
    try:
        for session in session_scope(factory):
            novel, _chapters = _seed(session, "十八章", bodies)
            novel_id = novel.id
            paused = _run(session, novel_id, provider)
            assert paused.state == JobState.PAUSED.value
            assert paused.progress_done == 1
            assert provider.bodies == [bodies[0]]
            assert all(unit.state != UnitState.RUNNING.value for unit in paused.units)
            again = pause_novel_analysis(session, paused.id)
            assert again.state == JobState.PAUSED.value

            rest = RecordingProvider(payload)
            resumed = awaitable(resume_novel_analysis(session, paused.id, rest))
            assert resumed.state == JobState.COMPLETED.value
            assert resumed.progress_done == 18
            assert rest.bodies == bodies[1:]
            repeated = awaitable(resume_novel_analysis(session, paused.id, rest))
            assert repeated.state == JobState.COMPLETED.value
            assert rest.bodies == bodies[1:]
    finally:
        engine.dispose()


def test_cancel_leaves_no_running_unit_and_is_idempotent(isolated_data_dir) -> None:
    payload = json.dumps(_valid_payload(), ensure_ascii=False)
    _settings, engine, factory = bootstrap_local_runtime()
    novel_id = ""

    class CancelOnFirst(RecordingProvider):
        async def chat(self, messages, profile, *, response_format=None) -> str:  # type: ignore[no-untyped-def]
            text = await super().chat(messages, profile, response_format=response_format)
            if len(self.bodies) == 1:
                for reader in session_scope(factory):
                    job = find_active_analysis_job(reader, novel_id)
                    assert job is not None
                    cancel_novel_analysis(reader, job.id)
            return text

    provider = CancelOnFirst(payload)
    try:
        for session in session_scope(factory):
            novel, chapters = _seed(session, "雨巷", ["第一章正文", "第二章正文", "第三章正文"])
            novel_id = novel.id
            cancelled = _run(session, novel_id, provider)
            assert cancelled.state == JobState.CANCELLED.value
            assert all(unit.state != UnitState.RUNNING.value for unit in cancelled.units)
            assert provider.bodies == ["第一章正文"]
            states = {unit.chapter_id: unit.state for unit in cancelled.units}
            assert states[chapters[0].id] == UnitState.COMPLETED.value
            assert states[chapters[1].id] == UnitState.CANCELLED.value
            assert states[chapters[2].id] == UnitState.CANCELLED.value
            repeated = cancel_novel_analysis(session, cancelled.id)
            assert repeated.state == JobState.CANCELLED.value
            assert {unit.state for unit in repeated.units} == {
                UnitState.COMPLETED.value,
                UnitState.CANCELLED.value,
            }
    finally:
        engine.dispose()


def test_retry_reruns_only_the_failed_chapter_and_keeps_history(isolated_data_dir) -> None:
    payload = json.dumps(_valid_payload(), ensure_ascii=False)
    failing = RecordingProvider(payload, fail_tokens={"第二章", "第三章"})
    _settings, engine, factory = bootstrap_local_runtime()
    try:
        for session in session_scope(factory):
            novel, chapters = _seed(session, "雨巷", ["第一章正文", "第二章正文", "第三章正文"])
            job = _run(session, novel.id, failing)
            assert job.state == JobState.FAILED.value
            failed = next(unit for unit in job.units if unit.chapter_id == chapters[1].id)
            assert failed.retry_count == 1
            retry = RecordingProvider(payload)
            recovered = awaitable(retry_failed_chapter(session, job.id, chapters[1].id, retry))
            assert retry.bodies == ["第二章正文"]
            assert recovered.state == JobState.FAILED.value
            retried = next(unit for unit in recovered.units if unit.chapter_id == chapters[1].id)
            assert retried.state == UnitState.COMPLETED.value
            assert retried.retry_count == 1
            assert retried.checkpoint is not None
            assert retried.checkpoint["last_error_code"] == "analysis_repair_exhausted"
            still_failed = next(
                unit for unit in recovered.units if unit.chapter_id == chapters[2].id
            )
            assert still_failed.state == UnitState.FAILED.value
            awaitable(retry_failed_chapter(session, job.id, chapters[1].id, retry))
            assert retry.bodies == ["第二章正文"]
            awaitable(retry_failed_chapter(session, job.id, chapters[0].id, retry))
            assert retry.bodies == ["第二章正文"]
    finally:
        engine.dispose()


def awaitable(coro):  # type: ignore[no-untyped-def]
    import asyncio

    return asyncio.run(coro)


def test_control_api_is_idempotent(client: TestClient, monkeypatch) -> None:
    payload = json.dumps(_valid_payload(), ensure_ascii=False)
    provider = RecordingProvider(payload, fail_tokens={"失败章"})
    monkeypatch.setattr("app.api.analysis.create_llm_provider", lambda settings=None: provider)
    factory = app.state.session_factory
    novel_id = ""
    failed_id = ""
    for session in session_scope(factory):
        novel, chapters = _seed(session, "控制", ["成功章", "失败章"])
        novel_id = novel.id
        failed_id = chapters[1].id
    started = client.post(f"/api/novels/{novel_id}/analysis-jobs")
    assert started.status_code == 200, started.text
    job_id = started.json()["job_id"]
    success_id = started.json()["failed_chapter_ids"]
    assert success_id == [failed_id]

    provider.fail_tokens.clear()
    retried = client.post(f"/api/analysis-jobs/{job_id}/chapters/{failed_id}/retry")
    assert retried.status_code == 200, retried.text
    assert retried.json()["state"] == "completed"
    assert retried.json()["failed_chapter_ids"] == []
    calls = len(provider.bodies)
    again = client.post(f"/api/analysis-jobs/{job_id}/chapters/{failed_id}/retry")
    assert again.status_code == 200
    assert again.json()["state"] == "completed"
    assert len(provider.bodies) == calls

    paused = client.post(f"/api/analysis-jobs/{job_id}/pause")
    assert paused.status_code == 409
    missing = client.post("/api/analysis-jobs/missing/cancel")
    assert missing.status_code == 404
    assert missing.json()["detail"]["code"] == "analysis_job_not_found"
