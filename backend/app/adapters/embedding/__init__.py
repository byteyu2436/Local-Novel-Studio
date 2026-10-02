from app.adapters.embedding.errors import (
    EmbeddingDimensionError,
    EmbeddingError,
    EmbeddingModelNotFoundError,
    EmbeddingProfileMismatchError,
    EmbeddingTimeoutError,
    EmbeddingUnavailableError,
)
from app.adapters.embedding.fake import FakeEmbeddingProvider
from app.adapters.embedding.ollama import OllamaEmbeddingAdapter
from app.adapters.embedding.types import EmbeddingModelInfo, EmbeddingProvider

__all__ = [
    "EmbeddingDimensionError",
    "EmbeddingError",
    "EmbeddingModelInfo",
    "EmbeddingModelNotFoundError",
    "EmbeddingProfileMismatchError",
    "EmbeddingProvider",
    "EmbeddingTimeoutError",
    "EmbeddingUnavailableError",
    "FakeEmbeddingProvider",
    "OllamaEmbeddingAdapter",
]
