from pydantic import ValidationError
from sqlalchemy.orm import Session

from app.adapters.llm.errors import LLMError
from app.adapters.llm.profiles import default_model_profiles
from app.adapters.llm.types import ChatMessage, LLMProvider, ModelRole
from app.adapters.sqlite.models import Chapter, ChapterVersion
from app.domain.analysis import AnalysisError, extract_json_object
from app.domain.titles import apply_display_title
from app.prompts import PromptKind, current_prompt
from app.schemas.analysis import ChapterAnalysisPayload
from app.schemas.title import TitleCandidate, TitleCandidateList
from app.services import catalog
from app.settings import get_settings


async def generate_title_candidates(
    session: Session,
    provider: LLMProvider,
    chapter: Chapter,
    version: ChapterVersion,
    payload: ChapterAnalysisPayload,
) -> list[TitleCandidate]:
    """Return 1–3 candidates for an untitled chapter. A titled chapter skips the model."""

    if chapter.original_title.strip():
        return []
    prompt = current_prompt(PromptKind.TITLE_GENERATOR)
    message = (
        f"{prompt.text}\n\n本章正文：\n{version.body}\n\n本章分析：\n{payload.model_dump_json()}"
    )
    try:
        model = default_model_profiles(get_settings())[ModelRole.ANALYZER]
        raw = await provider.chat(
            [ChatMessage(role="user", content=message)],
            model,
            response_format=TitleCandidateList.model_json_schema(),
        )
        parsed = TitleCandidateList.model_validate(extract_json_object(raw))
    except (AnalysisError, LLMError, ValidationError, TypeError, ValueError):
        return []
    novel = catalog.require_novel(session, chapter.novel_id)
    apply_display_title(chapter, list(parsed.candidates), auto_title=novel.auto_title_enabled)
    session.flush()
    return list(parsed.candidates)
