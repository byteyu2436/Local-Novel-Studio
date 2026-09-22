import pytest
from app.adapters.sqlite import bootstrap_local_runtime, session_scope
from app.adapters.sqlite.models import ChapterVersion
from app.domain.analysis import CHAPTER_ANALYSIS_SCHEMA_VERSION
from app.domain.jobs import JobError, JobKind, JobState, UnitState, require_job_transition
from app.prompts.chapter_analyzer import CHAPTER_ANALYZER_PROMPT_VERSION
from app.services import catalog, jobs
from app.services.analysis import persist_chapter_analysis
from sqlalchemy import inspect, text
from tests.test_chapter_analysis import _trace, _valid_payload


def test_illegal_transitions_are_rejected() -> None:
    require_job_transition(JobState.QUEUED, JobState.RUNNING)
    require_job_transition(JobState.RUNNING, JobState.RUNNING)
    with pytest.raises(JobError) as caught:
        require_job_transition(JobState.COMPLETED, JobState.RUNNING)
    assert caught.value.code == "illegal_job_transition"
    with pytest.raises(JobError):
        require_job_transition(JobState.CANCELLED, JobState.QUEUED)


def test_job_survives_engine_reopen(isolated_data_dir) -> None:
    _settings, engine, factory = bootstrap_local_runtime()
    try:
        for session in session_scope(factory):
            novel = catalog.create_novel(session, "雨巷")
            created = jobs.create_job(
                session, kind=JobKind.ANALYZE_CHAPTER, novel_id=novel.id, progress_total=18
            )
            jobs.transition_job(session, created, JobState.RUNNING)
            job_id = created.id
            fingerprint = created.input_fingerprint
        engine.dispose()
        _settings, engine, factory = bootstrap_local_runtime()
        for session in session_scope(factory):
            stored = jobs.get_job(session, job_id)
            assert stored.state == JobState.RUNNING.value
            assert stored.progress_total == 18
            assert stored.input_fingerprint == fingerprint
            assert stored.started_at is not None
    finally:
        engine.dispose()


def test_pause_resume_cancel_retry_and_errors(isolated_data_dir) -> None:
    _settings, engine, factory = bootstrap_local_runtime()
    try:
        for session in session_scope(factory):
            novel = catalog.create_novel(session, "雨巷")
            job = jobs.create_job(session, kind=JobKind.BACKUP, novel_id=novel.id)
            jobs.transition_job(session, job, JobState.RUNNING)
            jobs.pause_job(session, job)
            assert job.state == JobState.PAUSED.value
            jobs.pause_job(session, job)
            jobs.resume_job(session, job)
            jobs.fail_job(session, job, code="llm_timeout", message="timed out")
            assert job.retry_count == 0
            assert job.error_code == "llm_timeout"
            jobs.retry_job(session, job)
            assert job.state == JobState.QUEUED.value
            assert job.retry_count == 1
            assert job.error_code == "llm_timeout"
            jobs.transition_job(session, job, JobState.RUNNING)
            jobs.cancel_job(session, job)
            assert job.state == JobState.CANCELLED.value
            with pytest.raises(JobError):
                jobs.resume_job(session, job)
    finally:
        engine.dispose()


def test_analysis_unit_links_result(isolated_data_dir) -> None:
    _settings, engine, factory = bootstrap_local_runtime()
    try:
        for session in session_scope(factory):
            novel = catalog.create_novel(session, "雨巷")
            chapter = catalog.create_chapter(session, novel.id, body="林深走进雨里。")
            job = jobs.create_job(
                session, kind=JobKind.ANALYZE_CHAPTER, novel_id=novel.id
            )
            unit = jobs.add_analysis_unit(
                session,
                job,
                chapter,
                schema_version=CHAPTER_ANALYSIS_SCHEMA_VERSION,
                analyzer_version=CHAPTER_ANALYZER_PROMPT_VERSION,
                prompt_version=CHAPTER_ANALYZER_PROMPT_VERSION,
            )
            assert unit.state == UnitState.QUEUED.value
            assert job.progress_total == 1
            canon = session.get(ChapterVersion, chapter.current_canon_version_id)
            assert canon is not None
            row = persist_chapter_analysis(
                session, chapter, canon, payload=_valid_payload(), **_trace()
            )
            jobs.complete_analysis_unit(
                session, unit, analysis_id=row.id, checkpoint={"offset": 1}
            )
            assert unit.analysis_id == row.id
            assert unit.checkpoint == {"offset": 1}
            assert job.progress_done == 1
            failed = jobs.add_analysis_unit(
                session,
                job,
                catalog.create_chapter(session, novel.id, body="夜雨不停。"),
                schema_version=CHAPTER_ANALYSIS_SCHEMA_VERSION,
                analyzer_version=CHAPTER_ANALYZER_PROMPT_VERSION,
                prompt_version=CHAPTER_ANALYZER_PROMPT_VERSION,
            )
            jobs.fail_analysis_unit(
                session, failed, code="analysis_repair_exhausted", message="bad json"
            )
            assert failed.retry_count == 1
            assert failed.error_code == "analysis_repair_exhausted"
            assert job.progress_done == 1
            assert job.progress_total == 2
    finally:
        engine.dispose()


def test_migration_creates_job_tables(isolated_data_dir) -> None:
    _settings, engine, _factory = bootstrap_local_runtime()
    try:
        names = inspect(engine).get_table_names()
        assert "jobs" in names
        assert "analysis_chapter_units" in names
        with engine.connect() as connection:
            version = connection.execute(
                text("SELECT version_num FROM alembic_version")
            ).scalar_one()
        assert version == "0007_jobs"
    finally:
        engine.dispose()
