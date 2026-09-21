import pytest
from app.adapters.llm.profiles import default_model_profiles
from app.adapters.llm.types import ModelRole
from app.adapters.sqlite import bootstrap_local_runtime, session_scope
from app.adapters.sqlite.models import ChapterVersion
from app.domain.analysis import AnalysisError
from app.domain.analysis_profile import (
    ANALYZER_PROFILE_VERSION,
    ANALYZER_TEMPERATURE_MAX,
    build_analysis_profile,
)
from app.prompts import PromptKind, current_prompt, get_prompt
from app.prompts.chapter_analyzer import CHAPTER_ANALYZER_PROMPT_VERSION
from app.services import catalog
from app.services.analysis import analysis_result_dto, persist_chapter_analysis
from app.settings import get_settings
from tests.test_chapter_analysis import _valid_payload


def test_current_analyzer_prompt_is_versioned_and_canon_only() -> None:
    prompt = current_prompt(PromptKind.CHAPTER_ANALYZER)
    assert prompt.version == CHAPTER_ANALYZER_PROMPT_VERSION
    assert prompt is get_prompt(PromptKind.CHAPTER_ANALYZER, CHAPTER_ANALYZER_PROMPT_VERSION)
    assert "Canon" in prompt.text
    assert "Draft" in prompt.text
    assert "不得补写" in prompt.text
    assert "chapter-analysis.v1" in prompt.text
    assert "标题" in prompt.text


def test_missing_prompt_version_and_reserved_kind_are_rejected() -> None:
    with pytest.raises(AnalysisError) as missing:
        get_prompt(PromptKind.CHAPTER_ANALYZER, "chapter-analyzer.v9")
    assert missing.value.code == "prompt_version_not_found"
    with pytest.raises(AnalysisError) as reserved:
        current_prompt(PromptKind.MEMORY_MERGE)
    assert reserved.value.code == "prompt_kind_not_registered"
    with pytest.raises(AnalysisError) as unregistered:
        get_prompt(PromptKind.TITLE_GENERATOR, "title.v1")
    assert unregistered.value.code == "prompt_kind_not_registered"


def test_default_analyzer_profile_is_low_temperature() -> None:
    model = default_model_profiles(get_settings())[ModelRole.ANALYZER]
    profile = build_analysis_profile(model)
    assert profile.profile_version == ANALYZER_PROFILE_VERSION
    assert profile.temperature == 0.1
    assert profile.temperature <= ANALYZER_TEMPERATURE_MAX
    assert profile.thinking_policy.value == "off"
    assert profile.context_default == 8192
    assert profile.profile_id == "analyzer-default"


def test_writer_profile_and_hot_temperature_are_illegal() -> None:
    profiles = default_model_profiles(get_settings())
    with pytest.raises(AnalysisError) as writer:
        build_analysis_profile(profiles[ModelRole.WRITER])
    assert writer.value.code == "illegal_analysis_profile"
    hot = profiles[ModelRole.ANALYZER].model_copy(update={"temperature": 0.8})
    with pytest.raises(AnalysisError) as temp:
        build_analysis_profile(hot)
    assert temp.value.code == "illegal_analysis_profile"
    with pytest.raises(AnalysisError) as version:
        build_analysis_profile(profiles[ModelRole.ANALYZER], profile_version="analyzer-profile.v9")
    assert version.value.code == "illegal_analysis_profile"


def test_persisted_analysis_records_prompt_and_profile_versions(isolated_data_dir) -> None:
    _settings, engine, factory = bootstrap_local_runtime()
    try:
        for session in session_scope(factory):
            novel = catalog.create_novel(session, "雨巷")
            chapter = catalog.create_chapter(session, novel.id, body="林深走进雨里。")
            canon = session.get(ChapterVersion, chapter.current_canon_version_id)
            assert canon is not None
            sampling = build_analysis_profile(
                default_model_profiles(get_settings())[ModelRole.ANALYZER]
            )
            prompt = current_prompt(PromptKind.CHAPTER_ANALYZER)
            row = persist_chapter_analysis(
                session,
                chapter,
                canon,
                payload=_valid_payload(),
                analyzer_version=prompt.version,
                model_profile_id=sampling.profile_id,
                prompt_version=prompt.version,
                profile_version=sampling.profile_version,
                model_ref=sampling.model_ref,
            )
            dto = analysis_result_dto(row)
            assert dto.prompt_version == CHAPTER_ANALYZER_PROMPT_VERSION
            assert dto.profile_version == ANALYZER_PROFILE_VERSION
            assert dto.analyzer_version == prompt.version
    finally:
        engine.dispose()
