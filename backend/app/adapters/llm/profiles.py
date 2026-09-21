from app.adapters.llm.types import ModelProfile, ModelRole, ThinkingPolicy
from app.settings import Settings


def parse_model_ref(model_ref: str) -> tuple[str, str]:
    name, tag = model_ref.split(":", 1)
    return name, tag


def default_model_profiles(settings: Settings) -> dict[ModelRole, ModelProfile]:
    """Writer and Analyzer share one Ollama model and differ only by sampling policy."""

    name, tag = parse_model_ref(settings.writer_model)
    writer = ModelProfile(
        profile_id="writer-default",
        role=ModelRole.WRITER,
        model_name=name,
        model_tag=tag,
        context_default=12288,
        context_max_product_limit=16384,
        thinking_policy=ThinkingPolicy.OFF,
        temperature=0.8,
    )
    analyzer = writer.model_copy(
        update={
            "profile_id": "analyzer-default",
            "role": ModelRole.ANALYZER,
            "context_default": 8192,
            "thinking_policy": ThinkingPolicy.OFF,
            "temperature": 0.1,
        }
    )
    return {ModelRole.WRITER: writer, ModelRole.ANALYZER: analyzer}
