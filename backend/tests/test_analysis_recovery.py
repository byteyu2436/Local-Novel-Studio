import asyncio
import json
from datetime import UTC, datetime, timedelta

from app.adapters.sqlite import bootstrap_local_runtime, session_scope
from app.adapters.sqlite.models import ChapterVersion
from app.domain.analysis import CHAPTER_ANALYSIS_SCHEMA_VERSION
from app.domain.jobs import JobState, UnitState
from app.main import app
from app.prompts.chapter_analyzer import CHAPTER_ANALYZER_PROMPT_VERSION
from app.services import jobs
from app.services.analysis import persist_chapter_analysis
from app.services.analysis_orchestrator import resume_novel_analysis
from app.services.analysis_recovery import analysis_recovery_report
from fastapi.testclient import TestClient
from tests.test_analysis_orchestrator import RecordingProvider, _seed
from tests.test_chapter_analysis import _trace, _valid_payload


def _interrupt_after_first_chapter(session, title: str):  # type: ignore[no-untyped-def]
    novel, chapters = _seed(session, title, ["第一章正文", "第二章正文", "第三章正文"])
    job = jobs.create_job(
        session,
        kind="ANALYZE_CHAPTER",
        novel_id=novel.id,
        input_fingerprint="recovery-test",
    )
    jobs.transition_job(session, job, JobState.RUNNING)
    units = [
        jobs.add_analysis_unit(
            session,
            job,
            chapter,
            schema_version=CHAPTER_ANALYSIS_SCHEMA_VERSION,
            analyzer_version=CHAPTER_ANALYZER_PROMPT_VERSION,
            prompt_version=CHAPTER_ANALYZER_PROMPT_VERSION,
        )
        for chapter in chapters
    ]
    canon = session.get(ChapterVersion, chapters[0].current_canon_version_id)
    assert canon is not None
    saved = persist_chapter_analysis(
        session, chapters[0], canon, payload=_valid_payload(), **_trace()
    )
    jobs.complete_analysis_unit(session, units[0], analysis_id=saved.id, checkpoint={"offset": 1})
    jobs.start_analysis_unit(session, units[1])
    job.heartbeat_at = datetime.now(UTC) - timedelta(minutes=5)
    job.checkpoint = {"current_chapter_id": chapters[1].id}
    return novel, chapters, job, units


def test_restart_requeues_interrupted_chapter_without_rerunning_completed(
    isolated_data_dir,
) -> None:
    payload = json.dumps(_valid_payload(), ensure_ascii=False)
    _settings, engine, factory = bootstrap_local_runtime()
    try:
        for session in session_scope(factory):
            _novel, chapters, job, units = _interrupt_after_first_chapter(session, "雨巷")
            novel_id = _novel.id
            job_id = job.id
            unit_ids = {unit.id for unit in units}
            interrupted_id = chapters[1].id
        engine.dispose()
        _settings, engine, factory = bootstrap_local_runtime()
        for session in session_scope(factory):
            report = analysis_recovery_report(session)
            assert len(report) == 1
            assert report[0].job_id == job_id
            assert report[0].novel_id == novel_id
            assert report[0].state == JobState.PAUSED.value
            assert report[0].recommended_action == "resume"
            assert report[0].completed == 1
            assert report[0].interrupted_chapter_ids == [interrupted_id]
            again = analysis_recovery_report(session)
            assert again[0].job_id == job_id
            assert {unit.id for unit in jobs.get_job(session, job_id).units} == unit_ids
            states = {unit.chapter_id: unit.state for unit in jobs.get_job(session, job_id).units}
            assert states[chapters[0].id] == UnitState.COMPLETED.value
            assert states[interrupted_id] == UnitState.QUEUED.value
            assert states[chapters[2].id] == UnitState.QUEUED.value

            provider = RecordingProvider(payload)
            resumed = asyncio.run(resume_novel_analysis(session, job_id, provider))
            assert resumed.state == JobState.COMPLETED.value
            assert provider.bodies == ["第二章正文", "第三章正文"]
            assert analysis_recovery_report(session) == []
    finally:
        engine.dispose()


def test_fresh_heartbeat_is_not_recovered(isolated_data_dir) -> None:
    _settings, engine, factory = bootstrap_local_runtime()
    try:
        for session in session_scope(factory):
            _novel, _chapters, job, units = _interrupt_after_first_chapter(session, "雨巷")
            jobs.heartbeat_job(session, job)
            report = analysis_recovery_report(session, now=datetime.now(UTC))
            assert report[0].state == JobState.RUNNING.value
            assert report[0].recommended_action == "wait"
            assert units[1].state == UnitState.RUNNING.value
            assert job.id == report[0].job_id
    finally:
        engine.dispose()


def test_startup_recovery_is_idempotent(isolated_data_dir) -> None:
    _settings, engine, factory = bootstrap_local_runtime()
    try:
        for session in session_scope(factory):
            _interrupt_after_first_chapter(session, "雨巷")
        engine.dispose()
        with TestClient(app) as client:
            first = client.get("/api/analysis-jobs/recovery")
            assert first.status_code == 200, first.text
            body = first.json()["jobs"]
            assert len(body) == 1
            assert body[0]["recommended_action"] == "resume"
            second = client.get("/api/analysis-jobs/recovery")
            assert second.json()["jobs"][0]["job_id"] == body[0]["job_id"]
            assert len(second.json()["jobs"]) == 1
            assert (
                second.json()["jobs"][0]["interrupted_chapter_ids"]
                == body[0]["interrupted_chapter_ids"]
            )
    finally:
        engine.dispose()
