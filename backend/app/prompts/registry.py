from enum import StrEnum

from pydantic import BaseModel

from app.domain.analysis import CHAPTER_ANALYSIS_SCHEMA_VERSION, AnalysisError
from app.prompts.chapter_analyzer import CHAPTER_ANALYZER_PROMPT_V1, CHAPTER_ANALYZER_PROMPT_VERSION


class PromptKind(StrEnum):
    CHAPTER_ANALYZER = "chapter_analyzer"
    MEMORY_MERGE = "memory_merge"
    CHAPTER_PLANNER = "chapter_planner"
    TITLE_GENERATOR = "title_generator"


class PromptRecord(BaseModel):
    kind: PromptKind
    version: str
    schema_version: str
    text: str


_CHAPTER_ANALYZER_PROMPTS: dict[str, PromptRecord] = {
    CHAPTER_ANALYZER_PROMPT_VERSION: PromptRecord(
        kind=PromptKind.CHAPTER_ANALYZER,
        version=CHAPTER_ANALYZER_PROMPT_VERSION,
        schema_version=CHAPTER_ANALYSIS_SCHEMA_VERSION,
        text=CHAPTER_ANALYZER_PROMPT_V1,
    )
}

_PROMPTS: dict[PromptKind, dict[str, PromptRecord]] = {
    PromptKind.CHAPTER_ANALYZER: _CHAPTER_ANALYZER_PROMPTS,
}

CURRENT_PROMPT_VERSIONS: dict[PromptKind, str] = {
    PromptKind.CHAPTER_ANALYZER: CHAPTER_ANALYZER_PROMPT_VERSION,
}


def get_prompt(kind: PromptKind | str, version: str) -> PromptRecord:
    try:
        resolved_kind = PromptKind(kind)
    except ValueError as exc:
        raise AnalysisError(
            "prompt_kind_not_registered",
            f"Prompt kind {kind!r} is reserved but not registered.",
        ) from exc
    catalog = _PROMPTS.get(resolved_kind)
    if not catalog:
        raise AnalysisError(
            "prompt_kind_not_registered",
            f"Prompt kind {resolved_kind.value!r} is reserved but not registered.",
        )
    record = catalog.get(version.strip())
    if record is None:
        raise AnalysisError(
            "prompt_version_not_found",
            f"Prompt {resolved_kind.value!r} version {version!r} was not found.",
        )
    return record


def current_prompt(kind: PromptKind | str) -> PromptRecord:
    try:
        resolved_kind = PromptKind(kind)
    except ValueError as exc:
        raise AnalysisError(
            "prompt_kind_not_registered",
            f"Prompt kind {kind!r} is reserved but not registered.",
        ) from exc
    version = CURRENT_PROMPT_VERSIONS.get(resolved_kind)
    if version is None:
        raise AnalysisError(
            "prompt_kind_not_registered",
            f"Prompt kind {resolved_kind.value!r} is reserved but not registered.",
        )
    return get_prompt(resolved_kind, version)
