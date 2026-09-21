class LLMError(Exception):
    code = "llm_error"

    def __init__(self, message: str, *, retryable: bool = False) -> None:
        super().__init__(message)
        self.retryable = retryable


class LLMUnavailableError(LLMError):
    code = "llm_unavailable"

    def __init__(self, message: str = "Ollama is not reachable.") -> None:
        super().__init__(message, retryable=True)


class LLMModelNotFoundError(LLMError):
    code = "llm_model_not_found"


class LLMTimeoutError(LLMError):
    code = "llm_timeout"

    def __init__(self, message: str = "The model request timed out.") -> None:
        super().__init__(message, retryable=True)


class LLMContextTooLargeError(LLMError):
    code = "llm_context_too_large"


class LLMCancelledError(LLMError):
    code = "llm_cancelled"

    def __init__(self, message: str = "The model request was cancelled.") -> None:
        super().__init__(message, retryable=False)


class LLMInvalidOutputError(LLMError):
    code = "llm_invalid_output"
