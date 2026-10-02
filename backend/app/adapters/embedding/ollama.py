import math

from app.adapters.embedding.errors import (
    EmbeddingDimensionError,
    EmbeddingError,
    EmbeddingModelNotFoundError,
    EmbeddingTimeoutError,
    EmbeddingUnavailableError,
)
from app.adapters.embedding.types import EmbeddingModelInfo
from app.adapters.llm.errors import (
    LLMError,
    LLMModelNotFoundError,
    LLMTimeoutError,
)
from app.adapters.llm.types import RuntimeHealth
from app.adapters.ollama.client import OllamaClient
from app.settings import Settings


def l2_normalize(vector: list[float]) -> list[float]:
    norm = math.sqrt(sum(value * value for value in vector))
    if norm == 0:
        return list(vector)
    return [value / norm for value in vector]


def map_embedding_error(exc: LLMError) -> EmbeddingError:
    if isinstance(exc, LLMModelNotFoundError):
        return EmbeddingModelNotFoundError(str(exc))
    if isinstance(exc, LLMTimeoutError):
        return EmbeddingTimeoutError(str(exc))
    return EmbeddingUnavailableError(str(exc))


class OllamaEmbeddingAdapter:
    """Local Ollama adapter. It never calls a cloud embedding API."""

    def __init__(
        self,
        settings: Settings,
        *,
        client: OllamaClient | None = None,
        model_ref: str | None = None,
        expected_dimension: int | None = None,
        normalization: str = "l2",
    ) -> None:
        if normalization not in {"none", "l2"}:
            raise ValueError("normalization must be none or l2")
        self._settings = settings
        self._client = client or OllamaClient(
            settings.ollama_base_url,
            timeout=settings.ollama_timeout_seconds,
        )
        self.model_ref = model_ref or settings.embedding_model
        self.expected_dimension = expected_dimension
        self.normalization = normalization

    async def health(self) -> RuntimeHealth:
        try:
            models = await self._client.list_models()
            version = await self._client.version()
        except Exception as exc:
            return RuntimeHealth(
                runtime="ollama",
                reachable=False,
                status="unavailable",
                installed_models=[],
                default_model=self.model_ref,
                default_model_installed=False,
                message=str(exc),
            )
        installed = self.model_ref in models
        return RuntimeHealth(
            runtime="ollama",
            reachable=True,
            status="ok" if installed else "degraded",
            version=version,
            installed_models=models,
            default_model=self.model_ref,
            default_model_installed=installed,
            message=None if installed else f"{self.model_ref} is not installed.",
        )

    async def model_info(self) -> EmbeddingModelInfo:
        dimension = self.expected_dimension
        if dimension is None:
            probe = await self.embed_query("probe")
            dimension = len(probe)
            self.expected_dimension = dimension
        return EmbeddingModelInfo(
            model_ref=self.model_ref,
            dimension=dimension,
            normalization="l2" if self.normalization == "l2" else "none",
        )

    async def embed_documents(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        try:
            vectors = await self._client.embed(self.model_ref, texts)
        except LLMError as exc:
            raise map_embedding_error(exc) from exc
        return self._finish(vectors, expected_count=len(texts))

    async def embed_query(self, text: str) -> list[float]:
        vectors = await self.embed_documents([text])
        return vectors[0]

    async def aclose(self) -> None:
        await self._client.aclose()

    def _finish(self, vectors: list[list[float]], *, expected_count: int) -> list[list[float]]:
        if len(vectors) != expected_count:
            raise EmbeddingDimensionError("Embedding count does not match the input batch.")
        expected = self.expected_dimension
        finished: list[list[float]] = []
        for vector in vectors:
            if expected is None:
                expected = len(vector)
                self.expected_dimension = expected
            if len(vector) != expected or not vector:
                raise EmbeddingDimensionError(f"Expected dimension {expected}, got {len(vector)}.")
            finished.append(l2_normalize(vector) if self.normalization == "l2" else list(vector))
        return finished
