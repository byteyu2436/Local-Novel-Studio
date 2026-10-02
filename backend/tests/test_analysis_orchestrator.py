import asyncio
import json

from app.adapters.sqlite import bootstrap_local_runtime, session_scope
from app.adapters.sqlite.models import ChapterVersion
from app.domain.jobs import JobState, UnitState
from app.main import app
from app.services import catalog
from app.services.analysis import get_chapter_analysis, persist_chapter_analysis
from app.services.analysis_orchestrator import job_progress, run_novel_analysis
from fastapi.testclient import TestClient
from tests.test_chapter_analysis import _trace, _valid_payload


class RecordingProvider:
    def __init__(self, payload: str, *, fail_tokens: set[str] | None = None) -> None:
        self.payload = payload
        self.fail_tokens = fail_tokens or set()
        self.bodies: list[str] = []

    async def chat(self, messages, profile, *, response_format=None) -> str:  # type: ignore[no-untyped-def]
        body = next(message.content for message in messages if "<<<CHAPTER>>>" in message.content)
        text = body.split("<<<CHAPTER>>>\n", 1)[1].split("\n<<<END>>>", 1)[0]
        self.bodies.append(text)
        if any(token in text for token in self.fail_tokens):
            return "not-json"
        return self.payload


def _seed(session, title: str, bodies: list[str]):  # type: ignore[no-untyped-def]
    novel = catalog.create_novel(session, title)
    chapters = [catalog.create_chapter(session, novel.id, body=body) for body in bodies]
    return novel, chapters


def _run(session, novel_id: str, provider):  # type: ignore[no-untyped-def]
    return asyncio.run(run_novel_analysis(session, novel_id, provider))


def test_eighteen_chapters_run_in_order_and_rerun_skips_completed(isolated_data_dir) -> None:
    payload = json.dumps(_valid_payload(), ensure_ascii=False)
    provider = RecordingProvider(payload)
    bodies = [f"第{index}章正文" for index in range(1, 19)]
    _settings, engine, factory = bootstrap_local_runtime()
    try:
        for session in session_scope(factory):
            novel, chapters = _seed(session, "十八章", bodies)
            job = _run(session, novel.id, provider)
            progress = job_progress(job)
            assert progress.state == JobState.COMPLETED.value
            assert progress.total == 18
            assert progress.completed == 18
            assert progress.failed_chapter_ids == []
            assert progress.current_chapter_id is None
            assert provider.bodies == bodies
            again = _run(session, novel.id, provider)
            assert again.id == job.id
            assert provider.bodies == bodies
            for chapter in chapters:
                assert chapter.current_canon_version_id is not None
                stored = get_chapter_analysis(session, chapter.id, chapter.current_canon_version_id)
                assert stored is not None
    finally:
        engine.dispose()


def test_one_chapter_failure_continues_and_retry_skips_successes(isolated_data_dir) -> None:
    payload = json.dumps(_valid_payload(), ensure_ascii=False)
    failing = RecordingProvider(payload, fail_tokens={"第二章"})
    _settings, engine, factory = bootstrap_local_runtime()
    try:
        for session in session_scope(factory):
            novel, chapters = _seed(session, "雨巷", ["第一章正文", "第二章正文", "第三章正文"])
            job = _run(session, novel.id, failing)
            progress = job_progress(job)
            assert progress.state == JobState.FAILED.value
            assert progress.completed == 2
            assert progress.total == 3
            assert progress.failed_chapter_ids == [chapters[1].id]
            assert failing.bodies == ["第一章正文", "第二章正文", "第二章正文", "第三章正文"]
            failed = next(unit for unit in job.units if unit.chapter_id == chapters[1].id)
            assert failed.state == UnitState.FAILED.value
            assert failed.error_code == "analysis_repair_exhausted"
            first = get_chapter_analysis(
                session, chapters[0].id, chapters[0].current_canon_version_id or ""
            )
            assert first is not None

            retry = RecordingProvider(payload)
            recovered = _run(session, novel.id, retry)
            assert recovered.id == job.id
            assert job_progress(recovered).state == JobState.COMPLETED.value
            assert job_progress(recovered).completed == 3
            assert job_progress(recovered).failed_chapter_ids == []
            assert retry.bodies == ["第二章正文"]
            reused = get_chapter_analysis(
                session, chapters[0].id, chapters[0].current_canon_version_id or ""
            )
            assert reused is not None
            assert reused.id == first.id
    finally:
        engine.dispose()


def test_existing_analysis_is_reused_without_model_call(isolated_data_dir) -> None:
    payload = json.dumps(_valid_payload(), ensure_ascii=False)
    provider = RecordingProvider(payload)
    _settings, engine, factory = bootstrap_local_runtime()
    try:
        for session in session_scope(factory):
            novel, chapters = _seed(session, "雨巷", ["已有分析", "待分析"])
            canon = session.get(ChapterVersion, chapters[0].current_canon_version_id)
            assert canon is not None
            persist_chapter_analysis(
                session, chapters[0], canon, payload=_valid_payload(), **_trace()
            )
            job = _run(session, novel.id, provider)
            assert provider.bodies == ["待分析"]
            assert job_progress(job).state == JobState.COMPLETED.value
            assert job_progress(job).completed == 2
    finally:
        engine.dispose()


def test_running_unit_is_visible_as_current_chapter(isolated_data_dir) -> None:
    payload = json.dumps(_valid_payload(), ensure_ascii=False)
    _settings, engine, factory = bootstrap_local_runtime()
    seen: list[str | None] = []
    novel_id = ""

    class WatchingProvider(RecordingProvider):
        async def chat(self, messages, profile, *, response_format=None) -> str:  # type: ignore[no-untyped-def]
            from app.services.analysis_orchestrator import find_active_analysis_job

            for reader in session_scope(factory):
                job = find_active_analysis_job(reader, novel_id)
                assert job is not None
                seen.append(job_progress(job).current_chapter_id)
            return await super().chat(messages, profile, response_format=response_format)

    provider = WatchingProvider(payload)
    try:
        for session in session_scope(factory):
            novel, chapters = _seed(session, "雨巷", ["甲章", "乙章"])
            novel_id = novel.id
            _run(session, novel_id, provider)
            assert seen == [chapters[0].id, chapters[1].id]
    finally:
        engine.dispose()


def test_progress_api_reports_completion_failure_and_identity(
    client: TestClient, monkeypatch
) -> None:
    payload = json.dumps(_valid_payload(), ensure_ascii=False)
    provider = RecordingProvider(payload, fail_tokens={"失败章"})
    monkeypatch.setattr("app.api.analysis.create_llm_provider", lambda settings=None: provider)
    factory = app.state.session_factory
    novel_id = ""
    failed_id = ""
    for session in session_scope(factory):
        novel, chapters = _seed(session, "进度", ["成功章", "失败章"])
        novel_id = novel.id
        failed_id = chapters[1].id

    missing = client.get(f"/api/novels/{novel_id}/analysis-jobs")
    assert missing.status_code == 404
    assert missing.json()["detail"]["code"] == "analysis_job_not_found"

    started = client.post(f"/api/novels/{novel_id}/analysis-jobs")
    assert started.status_code == 200, started.text
    body = started.json()
    assert body["novel_id"] == novel_id
    assert body["state"] == "failed"
    assert body["total"] == 2
    assert body["completed"] == 1
    assert body["failed_chapter_ids"] == [failed_id]
    assert body["current_chapter_id"] is None

    fetched = client.get(f"/api/novels/{novel_id}/analysis-jobs")
    assert fetched.status_code == 200
    assert fetched.json() == body
    by_id = client.get(f"/api/analysis-jobs/{body['job_id']}")
    assert by_id.status_code == 200
    assert by_id.json()["job_id"] == body["job_id"]
    unknown = client.get("/api/analysis-jobs/missing")
    assert unknown.status_code == 404

    absent = client.post("/api/novels/missing/analysis-jobs")
    assert absent.status_code == 404
    assert absent.json()["detail"]["code"] == "novel_not_found"


def test_progress_api_rejects_novel_without_chapters(client: TestClient) -> None:
    factory = app.state.session_factory
    for session in session_scope(factory):
        novel = catalog.create_novel(session, "空书")
        novel_id = novel.id
    response = client.post(f"/api/novels/{novel_id}/analysis-jobs")
    assert response.status_code == 400
    assert response.json()["detail"]["code"] == "chapters_empty"
