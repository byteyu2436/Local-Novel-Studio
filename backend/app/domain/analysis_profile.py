from pydantic import BaseModel, Field

from app.adapters.llm.types import ModelProfile, ModelRole, ThinkingPolicy
from app.domain.analysis import AnalysisError

ANALYZER_PROFILE_VERSION = "analyzer-profile.v1"
ANALYZER_TEMPERATURE_MIN = 0.0
ANALYZER_TEMPERATURE_MAX = 0.2


class AnalysisSamplingProfile(BaseModel):
    """Stable-first Analyzer sampling. Writer profiles must not be used here."""

    profile_id: str
    profile_version: str = ANALYZER_PROFILE_VERSION
    role: ModelRole = ModelRole.ANALYZER
    temperature: float = Field(ge=ANALYZER_TEMPERATURE_MIN, le=ANALYZER_TEMPERATURE_MAX)
    thinking_policy: ThinkingPolicy = ThinkingPolicy.OFF
    context_default: int = Field(gt=0)
    context_max_product_limit: int = Field(gt=0)
    model_ref: str


def build_analysis_profile(
    model: ModelProfile, *, profile_version: str = ANALYZER_PROFILE_VERSION
) -> AnalysisSamplingProfile:
    if model.role != ModelRole.ANALYZER:
        raise AnalysisError(
            "illegal_analysis_profile",
            "Analysis sampling requires an Analyzer ModelProfile.",
        )
    version = profile_version.strip()
    if version != ANALYZER_PROFILE_VERSION:
        raise AnalysisError(
            "illegal_analysis_profile",
            f"Analysis profile version {profile_version!r} is not supported.",
        )
    if not (ANALYZER_TEMPERATURE_MIN <= model.temperature <= ANALYZER_TEMPERATURE_MAX):
        raise AnalysisError(
            "illegal_analysis_profile",
            "Analyzer temperature must be between 0 and 0.2 inclusive.",
        )
    if model.context_default <= 0 or model.context_max_product_limit < model.context_default:
        raise AnalysisError(
            "illegal_analysis_profile",
            "Analyzer context budget is invalid.",
        )
    return AnalysisSamplingProfile(
        profile_id=model.profile_id,
        profile_version=version,
        role=ModelRole.ANALYZER,
        temperature=model.temperature,
        thinking_policy=model.thinking_policy,
        context_default=model.context_default,
        context_max_product_limit=model.context_max_product_limit,
        model_ref=model.model_ref,
    )
