class EmbeddingError(Exception):
    code = "embedding_error"

    def __init__(self, message: str, *, retryable: bool = False) -> None:
        super().__init__(message)
        self.retryable = retryable


class EmbeddingUnavailableError(EmbeddingError):
    code = "embedding_unavailable"

    def __init__(self, message: str = "The local embedding runtime is not reachable.") -> None:
        super().__init__(message, retryable=True)


class EmbeddingModelNotFoundError(EmbeddingError):
    code = "embedding_model_not_found"


class EmbeddingTimeoutError(EmbeddingError):
    code = "embedding_timeout"

    def __init__(self, message: str = "The embedding request timed out.") -> None:
        super().__init__(message, retryable=True)


class EmbeddingDimensionError(EmbeddingError):
    code = "embedding_dimension_mismatch"


class EmbeddingProfileMismatchError(EmbeddingError):
    code = "embedding_profile_mismatch"
