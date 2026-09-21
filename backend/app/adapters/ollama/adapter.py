from collections.abc import AsyncIterator

from app.adapters.llm.types import (
    ChatChunk,
    ChatMessage,
    LLMProvider,
    ModelProfile,
    RuntimeHealth,
)
from app.adapters.ollama.client import OllamaClient
from app.settings import Settings


class OllamaAdapter:
    def __init__(self, settings: Settings, *, client: OllamaClient | None = None) -> None:
        self._settings = settings
        self._client = client or OllamaClient(
            settings.ollama_base_url,
            timeout=settings.ollama_timeout_seconds,
        )

    async def health(self) -> RuntimeHealth:
        try:
            models = await self._client.list_models()
            version = await self._client.version()
        except Exception as exc:
            return RuntimeHealth(
                runtime="ollama",
                reachable=False,
                status="unavailable",
                version=None,
                installed_models=[],
                default_model=self._settings.writer_model,
                default_model_installed=False,
                message=str(exc),
            )

        installed = self._settings.writer_model in models or any(
            item.startswith(f"{self._settings.writer_model}") for item in models
        )
        return RuntimeHealth(
            runtime="ollama",
            reachable=True,
            status="ok" if installed else "degraded",
            version=version,
            installed_models=models,
            default_model=self._settings.writer_model,
            default_model_installed=installed,
            message=None
            if installed
            else (
                f"Ollama is reachable, but {self._settings.writer_model} is not installed. "
                "Do not download it from CPU_DEV; pull it on the Windows GPU machine."
            ),
        )

    async def list_models(self) -> list[str]:
        return await self._client.list_models()

    async def chat(self, messages: list[ChatMessage], profile: ModelProfile) -> str:
        return await self._client.chat(
            [message.model_dump() for message in messages],
            profile,
        )

    async def generate(self, prompt: str, profile: ModelProfile) -> str:
        return await self._client.generate(prompt, profile)

    async def stream_chat(
        self, messages: list[ChatMessage], profile: ModelProfile
    ) -> AsyncIterator[ChatChunk]:
        last_text = ""
        async for text in self._client.stream_chat(
            [message.model_dump() for message in messages],
            profile,
        ):
            last_text = text
            yield ChatChunk(text=text, done=False)
        yield ChatChunk(text=last_text, done=True)

    async def aclose(self) -> None:
        await self._client.aclose()


def as_provider(adapter: OllamaAdapter) -> LLMProvider:
    return adapter
