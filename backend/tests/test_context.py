from datetime import UTC, datetime
from uuid import uuid4

import pytest
from app.adapters.llm.profiles import default_model_profiles
from app.adapters.llm.types import ModelProfile, ModelRole
from app.adapters.sqlite import bootstrap_local_runtime, session_scope
from app.adapters.sqlite.memory import MemoryFact, MemoryForeshadowing
from app.adapters.sqlite.models import ChapterVersion
from app.domain.chapter_canon import add_draft_version
from app.domain.context_budget import (
    ESTIMATOR_VERSION,
    ContextBudgetError,
    budget_for_profile,
    trim_sections,
)
from app.schemas.context import SECTION_TYPES, ContextSection
from app.services import catalog
from app.services.context_builder import build_context, render_context
from app.settings import get_settings


def _profile(default: int, maximum: int) -> ModelProfile:
    return ModelProfile(
        profile_id=f"budget-{default}",
        role=ModelRole.WRITER,
        model_name="qwen",
        model_tag="test",
        context_default=default,
        context_max_product_limit=maximum,
    )


def _section(section_type: str, text: str, **kwargs) -> ContextSection:
    return ContextSection(
        section_type=section_type,
        source_type=kwargs.pop("source_type", "memory"),
        source_id=kwargs.pop("source_id", section_type),
        text=text,
        token_estimate=len(text),
        checksum="abc",
        **kwargs,
    )


def test_budgets_follow_profiles_and_keep_output_reserve() -> None:
    profiles = default_model_profiles(get_settings())
    writer = budget_for_profile(profiles[ModelRole.WRITER])
    analyzer = budget_for_profile(profiles[ModelRole.ANALYZER])
    assert writer.profile_id == "writer-default"
    assert writer.input_budget == 12288
    assert analyzer.input_budget == 8192
    assert writer.input_budget != analyzer.input_budget
    assert writer.output_reserve > 0
    used = writer.input_budget + writer.output_reserve + writer.safety_margin
    assert used <= writer.max_context_tokens
    with pytest.raises(ContextBudgetError) as caught:
        budget_for_profile(_profile(100, 100))
    assert caught.value.code == "context_budget_exceeded"


def test_trim_drops_low_score_evidence_before_locked_facts() -> None:
    budget = budget_for_profile(_profile(30, 30 + 1024 + 256))
    assert budget.input_budget == 30
    locked = _section("locked_facts", "锁" * 10, locked=True, priority=90)
    low = _section(
        "retrieved_evidence", "低" * 15, source_type="retrieval", score=0.1, priority=10
    )
    high = _section(
        "retrieved_evidence",
        "高" * 10,
        source_type="retrieval",
        source_id="high",
        score=0.9,
        priority=10,
    )
    trimmed = trim_sections([locked, low, high], budget)
    by_id = {item.source_id: item for item in trimmed}
    assert by_id["locked_facts"].included is True
    assert by_id["retrieved_evidence"].included is False
    assert by_id["retrieved_evidence"].trimmed_reason == "low_score_evidence"
    assert by_id["retrieved_evidence"].before_tokens == 15
    assert by_id["high"].included is True
    summary = _section(
        "global_summary",
        "总" * 25,
        source_id="summary",
        priority=20,
        compressed_text="总" * 5,
    )
    compressed = trim_sections([locked, summary], budget)
    summary_row = {item.source_id: item for item in compressed}["summary"]
    assert summary_row.text == "总" * 5
    assert summary_row.trimmed_reason == "summary_compressed"
    assert [item.section_type for item in trimmed] == sorted(
        [item.section_type for item in trimmed], key=SECTION_TYPES.index
    )


def test_trim_keeps_newest_recent_text_and_refuses_oversized_locks() -> None:
    budget = budget_for_profile(_profile(12, 12 + 1024 + 256))
    older = _section(
        "recent_text", "旧" * 8, source_type="canon", source_id="old", recency=1, priority=50
    )
    newer = _section(
        "recent_text", "新" * 8, source_type="canon", source_id="new", recency=2, priority=50
    )
    trimmed = trim_sections([older, newer], budget)
    by_id = {item.source_id: item for item in trimmed}
    assert by_id["old"].included is False
    assert by_id["old"].trimmed_reason == "distant_recent_text"
    assert by_id["new"].included is True
    locked = _section("character_state", "人" * 40, locked=True, priority=80)
    with pytest.raises(ContextBudgetError) as caught:
        trim_sections([locked], budget)
    assert caught.value.code == "context_budget_exceeded"


def test_builder_orders_sections_and_degrades_missing_sources(isolated_data_dir) -> None:
    _settings, engine, factory = bootstrap_local_runtime()
    try:
        for session in session_scope(factory):
            novel = catalog.create_novel(session, "雨巷")
            now = datetime.now(UTC)
            session.add(
                MemoryFact(
                    id=str(uuid4()),
                    novel_id=novel.id,
                    subject_kind="world_fact",
                    subject_id=str(uuid4()),
                    fact_key="rule",
                    fact_value={"text": "雨巷不可改"},
                    revision=1,
                    active=True,
                    origin="inferred",
                    status="active",
                    confidence=1,
                    locked=True,
                    created_at=now,
                    updated_at=now,
                )
            )
            session.add(
                MemoryForeshadowing(
                    id=str(uuid4()),
                    novel_id=novel.id,
                    label="鹿回头",
                    status="planted",
                    created_at=now,
                    updated_at=now,
                )
            )
            session.add(
                MemoryForeshadowing(
                    id=str(uuid4()),
                    novel_id=novel.id,
                    label="已收束",
                    status="resolved",
                    created_at=now,
                    updated_at=now,
                )
            )
            first = catalog.create_chapter(session, novel.id, body="第一章独有")
            draft = add_draft_version(
                first,
                body="草稿不该进上下文",
                parent=session.get(ChapterVersion, first.current_canon_version_id),
                created_at=now,
            )
            session.add(draft)
            for index in range(2, 19):
                catalog.create_chapter(session, novel.id, body=f"第{index}章正文")
            profile = default_model_profiles(get_settings())[ModelRole.WRITER]
            manifest = build_context(
                session,
                novel.id,
                profile,
                chapter_goal="林深离开雨巷",
                evidence=[{"id": "e1", "score": 0.4, "text": "巷口有灯"}],
                plan_text="先写离开",
            )
            order = [item.section_type for item in manifest.sections]
            assert order == sorted(order, key=SECTION_TYPES.index)
            assert manifest.estimator_version == ESTIMATOR_VERSION
            assert manifest.profile_id == "writer-default"
            assert manifest.total_tokens == sum(item.token_estimate for item in manifest.sections)
            assert "global_summary" in manifest.degraded
            assert "retrieval" not in manifest.degraded
            rendered = render_context(manifest)
            assert "雨巷不可改" in rendered
            assert "鹿回头" in rendered
            assert "已收束" not in rendered
            assert "第18章正文" in rendered
            assert "第17章正文" in rendered
            assert "第一章独有" not in rendered
            assert "草稿不该进上下文" not in rendered
            assert all(item.source_type != "draft" for item in manifest.sections)
            recent = [item for item in manifest.sections if item.section_type == "recent_text"]
            assert [item.source_type for item in recent] == ["canon", "canon"]
            with pytest.raises(ContextBudgetError) as caught:
                build_context(session, novel.id, profile, chapter_goal="  ")
            assert caught.value.code == "chapter_goal_empty"
    finally:
        engine.dispose()


def test_missing_retrieval_is_degraded(isolated_data_dir) -> None:
    _settings, engine, factory = bootstrap_local_runtime()
    try:
        for session in session_scope(factory):
            novel = catalog.create_novel(session, "雨巷")
            profile = default_model_profiles(get_settings())[ModelRole.ANALYZER]
            manifest = build_context(
                session, novel.id, profile, chapter_goal="看一看", evidence=None
            )
            assert "retrieval" in manifest.degraded
            assert "global_summary" in manifest.degraded
            assert all(item.section_type != "retrieved_evidence" for item in manifest.sections)
    finally:
        engine.dispose()
