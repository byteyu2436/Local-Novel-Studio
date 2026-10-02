from enum import StrEnum

from pydantic import BaseModel

from app.domain.analysis import CHAPTER_ANALYSIS_SCHEMA_VERSION, AnalysisError
from app.prompts.chapter_analyzer import CHAPTER_ANALYZER_PROMPT_V1, CHAPTER_ANALYZER_PROMPT_VERSION
from app.prompts.chapter_planner import (
    CHAPTER_PLAN_SCHEMA_VERSION,
    CHAPTER_PLANNER_PROMPT_V1,
    CHAPTER_PLANNER_PROMPT_VERSION,
)
from app.prompts.consistency_checker import (
    CONSISTENCY_CHECKER_PROMPT_V1,
    CONSISTENCY_CHECKER_PROMPT_VERSION,
    CONSISTENCY_SCHEMA_VERSION,
)
from app.prompts.rewrite import REWRITE_PROMPT_V1, REWRITE_PROMPT_VERSION
from app.prompts.scene_writer import SCENE_WRITER_PROMPT_V1, SCENE_WRITER_PROMPT_VERSION
from app.prompts.title_generator import TITLE_GENERATOR_PROMPT_V1, TITLE_GENERATOR_PROMPT_VERSION


class PromptKind(StrEnum):
    CHAPTER_ANALYZER = "chapter_analyzer"
    MEMORY_MERGE = "memory_merge"
    CHAPTER_PLANNER = "chapter_planner"
    TITLE_GENERATOR = "title_generator"
    SCENE_WRITER = "scene_writer"
    REWRITE = "rewrite"
    CONSISTENCY_CHECKER = "consistency_checker"


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

_TITLE_PROMPTS: dict[str, PromptRecord] = {
    TITLE_GENERATOR_PROMPT_VERSION: PromptRecord(
        kind=PromptKind.TITLE_GENERATOR,
        version=TITLE_GENERATOR_PROMPT_VERSION,
        schema_version="title-candidate.v1",
        text=TITLE_GENERATOR_PROMPT_V1,
    )
}

_PLANNER_PROMPTS: dict[str, PromptRecord] = {
    CHAPTER_PLANNER_PROMPT_VERSION: PromptRecord(
        kind=PromptKind.CHAPTER_PLANNER,
        version=CHAPTER_PLANNER_PROMPT_VERSION,
        schema_version=CHAPTER_PLAN_SCHEMA_VERSION,
        text=CHAPTER_PLANNER_PROMPT_V1,
    )
}
_SCENE_PROMPTS: dict[str, PromptRecord] = {
    SCENE_WRITER_PROMPT_VERSION: PromptRecord(
        kind=PromptKind.SCENE_WRITER,
        version=SCENE_WRITER_PROMPT_VERSION,
        schema_version="scene-writer.v1",
        text=SCENE_WRITER_PROMPT_V1,
    )
}
_REWRITE_PROMPTS: dict[str, PromptRecord] = {
    REWRITE_PROMPT_VERSION: PromptRecord(
        kind=PromptKind.REWRITE,
        version=REWRITE_PROMPT_VERSION,
        schema_version="rewrite.v1",
        text=REWRITE_PROMPT_V1,
    )
}
_CHECKER_PROMPTS: dict[str, PromptRecord] = {
    CONSISTENCY_CHECKER_PROMPT_VERSION: PromptRecord(
        kind=PromptKind.CONSISTENCY_CHECKER,
        version=CONSISTENCY_CHECKER_PROMPT_VERSION,
        schema_version=CONSISTENCY_SCHEMA_VERSION,
        text=CONSISTENCY_CHECKER_PROMPT_V1,
    )
}

_PROMPTS: dict[PromptKind, dict[str, PromptRecord]] = {
    PromptKind.CHAPTER_ANALYZER: _CHAPTER_ANALYZER_PROMPTS,
    PromptKind.TITLE_GENERATOR: _TITLE_PROMPTS,
    PromptKind.CHAPTER_PLANNER: _PLANNER_PROMPTS,
    PromptKind.SCENE_WRITER: _SCENE_PROMPTS,
    PromptKind.REWRITE: _REWRITE_PROMPTS,
    PromptKind.CONSISTENCY_CHECKER: _CHECKER_PROMPTS,
}

CURRENT_PROMPT_VERSIONS: dict[PromptKind, str] = {
    PromptKind.CHAPTER_ANALYZER: CHAPTER_ANALYZER_PROMPT_VERSION,
    PromptKind.TITLE_GENERATOR: TITLE_GENERATOR_PROMPT_VERSION,
    PromptKind.CHAPTER_PLANNER: CHAPTER_PLANNER_PROMPT_VERSION,
    PromptKind.SCENE_WRITER: SCENE_WRITER_PROMPT_VERSION,
    PromptKind.REWRITE: REWRITE_PROMPT_VERSION,
    PromptKind.CONSISTENCY_CHECKER: CONSISTENCY_CHECKER_PROMPT_VERSION,
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
