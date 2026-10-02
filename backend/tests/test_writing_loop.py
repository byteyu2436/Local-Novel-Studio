import asyncio
import json

import pytest
from app.adapters.llm.fake import FakeLLMProvider
from app.adapters.llm.types import ChatChunk, ChatMessage, ModelProfile
from app.adapters.sqlite import bootstrap_local_runtime, session_scope
from app.adapters.sqlite.continuation import ConsistencyIssueRecord, continuation_now
from app.adapters.sqlite.models import Chapter, ChapterVersion, Job
from app.domain.chapter import VersionKind
from app.domain.jobs import JobState
from app.schemas.plan import ChapterPlan, PlanStatus
from app.services import catalog
from app.services.accept import accept_draft
from app.services.consistency import check_draft, list_issues
from app.services.drafts import DraftError, restore_draft, rewrite_draft, save_draft, splice_rewrite
from app.services.plans import confirm_plan, save_plan_version
from app.services.scene_writer import cancel_scene, generate_scene, resume_scene
from sqlalchemy import delete, func, select
from tests.test_chapter_analysis import _valid_payload
from tests.test_plans import _plan


def _confirmed(session, novel_id: str):
    row = save_plan_version(
        session,
        novel_id=novel_id,
        target_sequence=1,
        plan=ChapterPlan.model_validate(_plan()),
        status=PlanStatus.GENERATED,
    )
    return confirm_plan(session, novel_id, row.id)


class _CancelAfterFirst(FakeLLMProvider):
    def __init__(self, session) -> None:
        super().__init__(chunks=["甲", "乙"])
        self.session = session

    async def stream_chat(
        self, messages: list[ChatMessage], profile: ModelProfile
    ):
        self.calls.append("stream_chat")
        yield ChatChunk(text="甲", done=False)
        job = self.session.scalars(select(Job).where(Job.kind == "GENERATE_SCENE")).one()
        job.state = JobState.CANCELLED.value
        self.session.flush()
        yield ChatChunk(text="乙", done=False)


def test_rewrite_range_keeps_the_surrounding_text() -> None:
    assert splice_rewrite("甲乙丙", 1, 2, "丁") == "甲丁丙"
    with pytest.raises(DraftError) as caught:
        splice_rewrite("甲乙丙", 1, 2, "改甲丁丙")
    assert caught.value.code == "rewrite_outside_range"


def test_scene_cancel_resume_and_multi_scene(isolated_data_dir) -> None:
    _settings, engine, factory = bootstrap_local_runtime()
    try:
        for session in session_scope(factory):
            novel = catalog.create_novel(session, "雨巷")
            plan = _confirmed(session, novel.id)
            stopped = asyncio.run(
                generate_scene(
                    session,
                    _CancelAfterFirst(session),
                    novel.id,
                    plan_id=plan.id,
                    scene_id="meet",
                )
            )
            assert stopped["state"] == JobState.CANCELLED.value
            assert stopped["text"] == "甲"
            assert stopped["draft"] is not None
            resumed = asyncio.run(
                resume_scene(
                    session,
                    FakeLLMProvider(chunks=["续写"]),
                    novel.id,
                    stopped["job_id"],
                )
            )
            assert resumed["text"] == "甲续写"
            assert resumed["state"] == JobState.COMPLETED.value
            second = asyncio.run(
                generate_scene(
                    session,
                    FakeLLMProvider(chunks=["离开巷口"]),
                    novel.id,
                    plan_id=plan.id,
                    scene_id="leave",
                )
            )
            assert second["text"] == "离开巷口"
            assert second["draft"]["id"] != resumed["draft"]["id"]
            listed = cancel_scene(session, novel.id, stopped["job_id"])
            assert listed["state"] == JobState.CANCELLED.value
    finally:
        engine.dispose()


def test_consistency_and_accept_are_idempotent(isolated_data_dir) -> None:
    _settings, engine, factory = bootstrap_local_runtime()
    try:
        for session in session_scope(factory):
            novel = catalog.create_novel(session, "雨巷")
            plan = _confirmed(session, novel.id)
            draft = save_draft(
                session,
                novel_id=novel.id,
                target_sequence=1,
                body="甲乙丙",
                origin="user",
                plan_id=plan.id,
            )
            rewritten = asyncio.run(
                rewrite_draft(
                    session,
                    FakeLLMProvider(response="丁"),
                    novel.id,
                    draft.id,
                    start=1,
                    end=2,
                    instruction="把中间一字改掉",
                )
            )
            assert rewritten.body == "甲丁丙"
            assert rewritten.parent_id == draft.id
            assert rewritten.body.startswith("甲")
            assert rewritten.body.endswith("丙")
            restored = restore_draft(session, novel.id, draft.id)
            assert restored.body == draft.body
            assert restored.parent_id == draft.id
            assert restored.id != rewritten.id
            broken = FakeLLMProvider(responses=["nope", "still-nope"])
            with pytest.raises(DraftError) as invalid:
                asyncio.run(check_draft(session, broken, novel.id, rewritten.id))
            assert invalid.value.code == "consistency_invalid"
            assert list_issues(session, novel.id, rewritten.id) == []
            checked = asyncio.run(
                check_draft(
                    session,
                    FakeLLMProvider(
                        response=json.dumps(
                            [
                                {
                                    "severity": "warning",
                                    "category": "canon",
                                    "summary": "语气偏硬",
                                    "evidence_ids": ["e1"],
                                }
                            ],
                            ensure_ascii=False,
                        )
                    ),
                    novel.id,
                    rewritten.id,
                )
            )
            assert checked["issues"][0]["severity"] == "warning"
            session.add(
                ConsistencyIssueRecord(
                    id="block-1",
                    novel_id=novel.id,
                    draft_id=rewritten.id,
                    severity="blocking",
                    category="canon",
                    summary="雨巷被改掉了",
                    evidence=["fact-1"],
                    created_at=continuation_now(),
                )
            )
            session.flush()
            with pytest.raises(DraftError) as blocked:
                asyncio.run(accept_draft(session, novel.id, rewritten.id, plan.id))
            assert blocked.value.code == "accept_blocked"
            assert session.scalar(select(func.count()).select_from(Chapter)) == 0
            session.execute(delete(ConsistencyIssueRecord))
            session.flush()
            accepted = asyncio.run(
                accept_draft(
                    session,
                    novel.id,
                    rewritten.id,
                    plan.id,
                    llm=FakeLLMProvider(response=json.dumps(_valid_payload(), ensure_ascii=False)),
                )
            )
            assert accepted["memory_status"] == "completed"
            assert accepted["index_status"] == "skipped"
            again = asyncio.run(accept_draft(session, novel.id, rewritten.id, plan.id))
            assert again["chapter_id"] == accepted["chapter_id"]
            assert session.scalar(select(func.count()).select_from(Chapter)) == 1
            chapter = session.get(Chapter, accepted["chapter_id"])
            version = session.get(ChapterVersion, chapter.current_canon_version_id)
            assert version.version_kind == VersionKind.ACCEPTED.value
            assert version.body == "甲丁丙"
            assert version.id != rewritten.id
    finally:
        engine.dispose()


def test_writing_api_reports_missing_goal_and_plan(client) -> None:
    payload = json.dumps(_plan(), ensure_ascii=False)
    client.app.state.llm_provider = FakeLLMProvider(response=payload)
    factory = client.app.state.session_factory
    for session in session_scope(factory):
        novel = catalog.create_novel(session, "雨巷")
        novel_id = novel.id
    empty = client.post(f"/api/novels/{novel_id}/context", json={"chapter_goal": "  "})
    assert empty.status_code == 400
    assert empty.json()["detail"]["code"] == "chapter_goal_empty"
    missing = client.get(f"/api/novels/{novel_id}/plans/missing")
    assert missing.status_code == 404
    created = client.post(
        f"/api/novels/{novel_id}/plans",
        json={"chapter_goal": "林深离开雨巷", "target_sequence": 1},
    )
    assert created.status_code == 200
    plan_id = created.json()["id"]
    blocked = client.post(
        f"/api/novels/{novel_id}/scenes",
        json={"plan_id": plan_id, "scene_id": "meet"},
    )
    assert blocked.status_code == 409
    assert blocked.json()["detail"]["code"] == "plan_not_confirmed"
    confirmed = client.post(f"/api/novels/{novel_id}/plans/{plan_id}/confirm")
    assert confirmed.status_code == 200
    assert confirmed.json()["status"] == "confirmed"
