from __future__ import annotations

import logging
from dataclasses import dataclass

from app.adapters.llm.errors import LLMError
from app.adapters.llm.profiles import default_model_profiles
from app.adapters.llm.types import ChatMessage, LLMProvider, ModelProfile, ModelRole
from app.domain.analysis import (
    CHAPTER_ANALYSIS_SCHEMA_VERSION,
    AnalysisError,
    extract_json_object,
)
from app.domain.analysis_profile import build_analysis_profile
from app.prompts import PromptKind, current_prompt
from app.prompts.chapter_analyzer import CHAPTER_ANALYZER_REPAIR_V1
from app.schemas.analysis import (
    ChapterAnalysisPayload,
    chapter_analysis_json_schema,
    parse_chapter_analysis_payload,
)
from app.settings import Settings, get_settings

logger = logging.getLogger("lns.analysis")


@dataclass(frozen=True)
class AnalysisCallResult:
    payload: ChapterAnalysisPayload
    schema_version: str
    prompt_version: str
    analyzer_version: str
    profile_version: str
    model_profile_id: str
    model_ref: str
    attempts: int
    repaired: bool


def _map_llm_error(exc: LLMError) -> AnalysisError:
    return AnalysisError(exc.code, str(exc))


def _chapter_user_message(body: str) -> str:
    return f"当前 Canon 章节正文如下。只分析这段正文。\n\n<<<CHAPTER>>>\n{body}\n<<<END>>>"


def _log_attempt(
    *,
    chapter_id: str | None,
    source_version_id: str | None,
    prompt_version: str,
    schema_version: str,
    model_ref: str,
    attempt: int,
    repaired: bool,
    outcome: str,
) -> None:
    logger.info(
        "chapter analysis %s attempt=%s repaired=%s chapter_id=%s source_version_id=%s "
        "prompt=%s schema=%s model=%s",
        outcome,
        attempt,
        repaired,
        chapter_id or "-",
        source_version_id or "-",
        prompt_version,
        schema_version,
        model_ref,
    )


async def analyze_chapter_text(
    provider: LLMProvider,
    body: str,
    *,
    settings: Settings | None = None,
    model_profile: ModelProfile | None = None,
    chapter_id: str | None = None,
    source_version_id: str | None = None,
) -> AnalysisCallResult:
    """Call Analyzer with structured output. Repair at most once. Never logs chapter body."""

    resolved = settings or get_settings()
    prompt = current_prompt(PromptKind.CHAPTER_ANALYZER)
    model = model_profile or default_model_profiles(resolved)[ModelRole.ANALYZER]
    sampling = build_analysis_profile(model)
    schema = chapter_analysis_json_schema()
    messages = [
        ChatMessage(role="system", content=prompt.text),
        ChatMessage(role="user", content=_chapter_user_message(body)),
    ]
    last_error: AnalysisError | None = None
    for attempt in (1, 2):
        try:
            raw = await provider.chat(messages, model, response_format=schema)
        except LLMError as exc:
            mapped = _map_llm_error(exc)
            _log_attempt(
                chapter_id=chapter_id,
                source_version_id=source_version_id,
                prompt_version=prompt.version,
                schema_version=CHAPTER_ANALYSIS_SCHEMA_VERSION,
                model_ref=sampling.model_ref,
                attempt=attempt,
                repaired=attempt == 2,
                outcome=mapped.code,
            )
            raise mapped from exc
        try:
            payload = parse_chapter_analysis_payload(extract_json_object(raw))
        except AnalysisError as exc:
            last_error = exc
            _log_attempt(
                chapter_id=chapter_id,
                source_version_id=source_version_id,
                prompt_version=prompt.version,
                schema_version=CHAPTER_ANALYSIS_SCHEMA_VERSION,
                model_ref=sampling.model_ref,
                attempt=attempt,
                repaired=attempt == 2,
                outcome=exc.code,
            )
            if attempt == 1:
                messages = [
                    *messages,
                    ChatMessage(role="assistant", content=raw),
                    ChatMessage(
                        role="user",
                        content=CHAPTER_ANALYZER_REPAIR_V1.format(error=exc.message),
                    ),
                ]
                continue
            raise AnalysisError(
                "analysis_repair_exhausted",
                "Structured analysis failed schema validation after one repair attempt.",
            ) from exc
        _log_attempt(
            chapter_id=chapter_id,
            source_version_id=source_version_id,
            prompt_version=prompt.version,
            schema_version=CHAPTER_ANALYSIS_SCHEMA_VERSION,
            model_ref=sampling.model_ref,
            attempt=attempt,
            repaired=attempt == 2,
            outcome="ok",
        )
        return AnalysisCallResult(
            payload=payload,
            schema_version=CHAPTER_ANALYSIS_SCHEMA_VERSION,
            prompt_version=prompt.version,
            analyzer_version=prompt.version,
            profile_version=sampling.profile_version,
            model_profile_id=sampling.profile_id,
            model_ref=sampling.model_ref,
            attempts=attempt,
            repaired=attempt == 2,
        )
    assert last_error is not None
    raise last_error
