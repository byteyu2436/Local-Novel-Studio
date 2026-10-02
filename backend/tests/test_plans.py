import asyncio
import json

import pytest
from app.adapters.llm.fake import FakeLLMProvider
from app.adapters.sqlite import bootstrap_local_runtime, session_scope
from app.schemas.plan import ChapterPlan
from app.services import catalog
from app.services.planner import generate_plan
from app.services.plans import (
    PlanError,
    confirm_plan,
    edit_plan,
    list_plans,
    reorder_scenes,
    require_confirmed_plan,
)


def _plan(**updates) -> dict:
    payload = {
        "chapter_goal": "林深离开雨巷",
        "target_length": 2000,
        "pace": "慢",
        "emotion": "静",
        "new_character_policy": "forbid",
        "scenes": [
            {
                "scene_id": "meet",
                "order": 1,
                "goal": "遇见鹿",
                "pov": "林深",
                "participants": ["林深"],
                "location": "雨巷",
                "beats": ["雨"],
                "constraints": [],
                "expected_transition": "停步",
            },
            {
                "scene_id": "leave",
                "order": 2,
                "goal": "离开",
                "pov": "林深",
                "participants": ["林深"],
                "location": "巷口",
                "beats": [],
                "constraints": [],
                "expected_transition": "回头",
            },
        ],
        "characters": ["林深"],
        "locations": ["雨巷"],
        "conflicts": [],
        "character_changes": [],
        "foreshadowing_actions": [],
        "forbidden_items": [],
        "ending_hook": "鹿还在",
    }
    payload.update(updates)
    return payload


def test_plan_edit_reorder_and_confirm_keep_versions(isolated_data_dir) -> None:
    _settings, engine, factory = bootstrap_local_runtime()
    try:
        for session in session_scope(factory):
            novel = catalog.create_novel(session, "雨巷")
            provider = FakeLLMProvider(response=json.dumps(_plan(), ensure_ascii=False))
            created = asyncio.run(
                generate_plan(
                    session,
                    provider,
                    novel.id,
                    chapter_goal="林深离开雨巷",
                    target_sequence=19,
                )
            )
            assert created["status"] == "generated"
            assert created["version_number"] == 1
            assert created["prompt_version"] == "chapter-planner.v1"
            assert created["schema_version"] == "chapter-plan.v1"
            assert created["repaired"] is False
            edited_payload = ChapterPlan.model_validate(_plan(chapter_goal="林深在巷口停一下"))
            edited = edit_plan(session, novel.id, created["id"], edited_payload)
            assert edited.id != created["id"]
            assert edited.version_number == 2
            assert edited.status == "edited"
            assert edited.parent_id == created["id"]
            reordered = reorder_scenes(session, novel.id, edited.id, ["leave", "meet"])
            scenes = ChapterPlan.model_validate(reordered.payload).scenes
            assert [scene.scene_id for scene in scenes] == ["leave", "meet"]
            assert [scene.order for scene in scenes] == [1, 2]
            confirmed = confirm_plan(session, novel.id, reordered.id)
            again = confirm_plan(session, novel.id, reordered.id)
            assert again.id == confirmed.id
            assert confirmed.is_confirmed_pointer is True
            usable = require_confirmed_plan(session, novel.id, confirmed.id)
            assert usable.id == confirmed.id
            with pytest.raises(PlanError) as caught:
                require_confirmed_plan(session, novel.id, created["id"])
            assert caught.value.code == "plan_not_confirmed"
            replacement = confirm_plan(session, novel.id, edited.id)
            assert replacement.is_confirmed_pointer is True
            session.refresh(confirmed)
            assert confirmed.status == "superseded"
            assert confirmed.is_confirmed_pointer is False
            with pytest.raises(PlanError) as blocked:
                confirm_plan(session, novel.id, confirmed.id)
            assert blocked.value.code == "plan_not_confirmable"
            assert len(list_plans(session, novel.id)) == 3
    finally:
        engine.dispose()


def test_constraint_conflict_and_invalid_json_do_not_persist(isolated_data_dir) -> None:
    _settings, engine, factory = bootstrap_local_runtime()
    try:
        for session in session_scope(factory):
            novel = catalog.create_novel(session, "雨巷")
            conflict = FakeLLMProvider(
                response=json.dumps({"constraint_conflict": "雨巷不可改"}, ensure_ascii=False)
            )
            with pytest.raises(PlanError) as caught:
                asyncio.run(
                    generate_plan(
                        session,
                        conflict,
                        novel.id,
                        chapter_goal="改掉雨巷",
                        target_sequence=19,
                        locked_facts=["雨巷不可改"],
                    )
                )
            assert caught.value.code == "constraint_conflict"
            forbidden = _plan(forbidden_items=["雨巷不可改"])
            leaked = FakeLLMProvider(response=json.dumps(forbidden, ensure_ascii=False))
            with pytest.raises(PlanError) as leaked_error:
                asyncio.run(
                    generate_plan(
                        session,
                        leaked,
                        novel.id,
                        chapter_goal="改掉雨巷",
                        target_sequence=19,
                        locked_facts=["雨巷不可改"],
                    )
                )
            assert leaked_error.value.code == "constraint_conflict"
            broken = FakeLLMProvider(responses=["not-json", "still-not-json"])
            with pytest.raises(PlanError) as invalid:
                asyncio.run(
                    generate_plan(
                        session,
                        broken,
                        novel.id,
                        chapter_goal="林深离开雨巷",
                        target_sequence=19,
                    )
                )
            assert invalid.value.code == "planner_repair_exhausted"
            repaired = FakeLLMProvider(
                responses=["not-json", json.dumps(_plan(), ensure_ascii=False)]
            )
            created = asyncio.run(
                generate_plan(
                    session,
                    repaired,
                    novel.id,
                    chapter_goal="林深离开雨巷",
                    target_sequence=19,
                )
            )
            assert created["repaired"] is True
            assert len(list_plans(session, novel.id)) == 1
    finally:
        engine.dispose()
