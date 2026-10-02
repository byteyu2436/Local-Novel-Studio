import math
from hashlib import sha256

from app.adapters.embedding.errors import (
    EmbeddingDimensionError,
    EmbeddingModelNotFoundError,
    EmbeddingTimeoutError,
    EmbeddingUnavailableError,
)
from app.adapters.embedding.types import EmbeddingModelInfo
from app.adapters.llm.types import RuntimeHealth


def l2_normalize(vector: list[float]) -> list[float]:
    norm = math.sqrt(sum(value * value for value in vector))
    if norm == 0:
        return list(vector)
    return [value / norm for value in vector]


class FakeEmbeddingProvider:
    """Deterministic stand-in. Same text and dimension always yield the same vector."""

    def __init__(
        self,
        *,
        model_ref: str = "fake-embedding:test",
        dimension: int = 8,
        normalization: str = "l2",
        fail_on_calls: set[int] | None = None,
        mode: str = "success",
    ) -> None:
        self.model_ref = model_ref
        self.dimension = dimension
        self.normalization = normalization
        self.fail_on_calls = fail_on_calls or set()
        self.mode = mode
        self.calls: list[list[str]] = []
        self._documents_calls = 0

    async def health(self) -> RuntimeHealth:
        reachable = self.mode != "unavailable"
        return RuntimeHealth(
            runtime="fake-embedding",
            reachable=reachable,
            status="ok" if reachable else "unavailable",
            default_model=self.model_ref,
            default_model_installed=self.mode != "model_not_found",
            installed_models=[] if self.mode == "model_not_found" else [self.model_ref],
        )

    async def model_info(self) -> EmbeddingModelInfo:
        self._raise_for_mode()
        return EmbeddingModelInfo(
            model_ref=self.model_ref,
            dimension=self.dimension,
            normalization="l2" if self.normalization == "l2" else "none",
        )

    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        self._documents_calls += 1
        self.calls.append(list(texts))
        if self._documents_calls in self.fail_on_calls:
            raise EmbeddingUnavailableError("embedding batch failed")
        self._raise_for_mode()
        return [self._vector(text) for text in texts]

    async def embed_query(self, text: str) -> list[float]:
        self._raise_for_mode()
        return self._vector(text)

    def _vector(self, text: str) -> list[float]:
        digest = sha256(f"{self.model_ref}\n{self.dimension}\n{text}".encode()).digest()
        values = [byte / 255 for byte in digest]
        while len(values) < self.dimension:
            values.extend(values)
        vector = values[: self.dimension]
        if self.normalization == "l2":
            return l2_normalize(vector)
        return vector

    def _raise_for_mode(self) -> None:
        if self.mode == "timeout":
            raise EmbeddingTimeoutError()
        if self.mode == "model_not_found":
            raise EmbeddingModelNotFoundError(f"{self.model_ref} is not installed.")
        if self.mode == "unavailable":
            raise EmbeddingUnavailableError()
        if self.mode == "dimension":
            raise EmbeddingDimensionError("Provider returned a different dimension.")
