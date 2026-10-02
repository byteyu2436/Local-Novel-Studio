from typing import Literal, Protocol

from pydantic import BaseModel, Field

from app.adapters.llm.types import RuntimeHealth


class EmbeddingModelInfo(BaseModel):
    model_ref: str
    dimension: int = Field(gt=0)
    normalization: Literal["none", "l2"]


class EmbeddingProvider(Protocol):
    async def health(self) -> RuntimeHealth: ...

    async def model_info(self) -> EmbeddingModelInfo: ...

    async def embed_documents(self, texts: list[str]) -> list[list[float]]: ...

    async def embed_query(self, text: str) -> list[float]: ...
