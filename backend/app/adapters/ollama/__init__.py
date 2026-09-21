from app.adapters.llm.types import LLMProvider
from app.adapters.ollama.adapter import OllamaAdapter
from app.adapters.ollama.client import OllamaClient
from app.settings import Settings, get_settings


def create_llm_provider(settings: Settings | None = None) -> LLMProvider:
    """Services should depend on LLMProvider, not Ollama HTTP details."""

    return OllamaAdapter(settings or get_settings())


__all__ = ["OllamaAdapter", "OllamaClient", "create_llm_provider"]
