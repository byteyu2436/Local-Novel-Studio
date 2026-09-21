from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Literal

from app.adapters.llm.errors import (
    LLMCancelledError,
    LLMContextTooLargeError,
    LLMInvalidOutputError,
    LLMModelNotFoundError,
    LLMTimeoutError,
    LLMUnavailableError,
)
from app.adapters.llm.types import ChatChunk, ChatMessage, LLMProvider, ModelProfile, RuntimeHealth


class FakeLLMProvider:
    """Deterministic provider for CPU_DEV contract tests. Not GPU evidence."""

    def __init__(
        self,
        *,
        mode: Literal[
            "success",
            "timeout",
            "cancel",
            "model_not_found",
            "invalid_output",
            "stream_interrupt",
            "unavailable",
        ] = "success",
        models: list[str] | None = None,
        response: str = "ok",
        chunks: list[str] | None = None,
    ) -> None:
        self.mode = mode
        self.models = models or ["qwen3.5:9b"]
        self.response = response
        self.chunks = chunks or ["ok"]
        self.calls: list[str] = []

    async def health(self) -> RuntimeHealth:
        reachable = self.mode != "unavailable"
        default_model = self.models[0]
        return RuntimeHealth(
            runtime="fake",
            reachable=reachable,
            status="ok" if reachable else "unavailable",
            version="fake",
            installed_models=self.models if reachable else [],
            default_model=default_model,
            default_model_installed=reachable,
            message=None if reachable else "Fake provider is in unavailable mode.",
        )

    async def list_models(self) -> list[str]:
        self._raise_if_needed()
        return list(self.models)

    async def chat(self, messages: list[ChatMessage], profile: ModelProfile) -> str:
        self.calls.append("chat")
        self._raise_if_needed(profile)
        return self.response

    async def generate(self, prompt: str, profile: ModelProfile) -> str:
        self.calls.append("generate")
        self._raise_if_needed(profile)
        return self.response

    async def stream_chat(
        self, messages: list[ChatMessage], profile: ModelProfile
    ) -> AsyncIterator[ChatChunk]:
        self.calls.append("stream_chat")
        self._raise_if_needed(profile)
        if self.mode == "stream_interrupt":
            yield ChatChunk(text=self.chunks[0], done=False)
            raise LLMInvalidOutputError("Streaming output was interrupted.")
        for index, chunk in enumerate(self.chunks):
            yield ChatChunk(text=chunk, done=index == len(self.chunks) - 1)

    def _raise_if_needed(self, profile: ModelProfile | None = None) -> None:
        if self.mode == "unavailable":
            raise LLMUnavailableError()
        if self.mode == "timeout":
            raise LLMTimeoutError()
        if self.mode == "cancel":
            raise LLMCancelledError()
        if self.mode == "model_not_found":
            model_ref = profile.model_ref if profile is not None else "unknown"
            raise LLMModelNotFoundError(f"Model {model_ref} is not installed.")
        if self.mode == "invalid_output":
            raise LLMInvalidOutputError("Model returned invalid structured output.")
        if profile is not None and profile.context_default > profile.context_max_product_limit:
            raise LLMContextTooLargeError("Requested context exceeds the product limit.")


def as_provider(fake: FakeLLMProvider) -> LLMProvider:
    return fake
