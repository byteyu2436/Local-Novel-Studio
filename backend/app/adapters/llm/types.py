from collections.abc import AsyncIterator
from enum import StrEnum
from typing import Literal, Protocol

from pydantic import BaseModel, Field


class ModelRole(StrEnum):
    WRITER = "writer"
    ANALYZER = "analyzer"


class ThinkingPolicy(StrEnum):
    OFF = "off"
    ON = "on"
    AUTO = "auto"


class ModelProfile(BaseModel):
    profile_id: str
    role: ModelRole
    runtime: str = "ollama"
    model_name: str
    model_tag: str
    quantization: str | None = None
    context_default: int = 8192
    context_max_product_limit: int = 16384
    thinking_policy: ThinkingPolicy = ThinkingPolicy.OFF
    temperature: float = 0.7
    estimated_vram_mb: int | None = None
    preferred_device: str | None = None
    is_enabled: bool = True

    @property
    def model_ref(self) -> str:
        return f"{self.model_name}:{self.model_tag}"


class ChatMessage(BaseModel):
    role: Literal["system", "user", "assistant"]
    content: str


class ChatChunk(BaseModel):
    text: str
    done: bool = False


class RuntimeHealth(BaseModel):
    runtime: str
    reachable: bool
    status: Literal["ok", "degraded", "unavailable"]
    version: str | None = None
    installed_models: list[str] = Field(default_factory=list)
    default_model: str
    default_model_installed: bool = False
    message: str | None = None


class LLMProvider(Protocol):
    async def health(self) -> RuntimeHealth: ...

    async def list_models(self) -> list[str]: ...

    async def chat(
        self,
        messages: list[ChatMessage],
        profile: ModelProfile,
        *,
        response_format: dict | str | None = None,
    ) -> str: ...

    async def generate(self, prompt: str, profile: ModelProfile) -> str: ...

    def stream_chat(
        self, messages: list[ChatMessage], profile: ModelProfile
    ) -> AsyncIterator[ChatChunk]: ...
