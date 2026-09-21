from __future__ import annotations

import json
from collections.abc import AsyncIterator
from typing import Any

import httpx

from app.adapters.llm.errors import (
    LLMCancelledError,
    LLMContextTooLargeError,
    LLMError,
    LLMModelNotFoundError,
    LLMTimeoutError,
    LLMUnavailableError,
)
from app.adapters.llm.types import ModelProfile, ThinkingPolicy


def normalize_ollama_error(message: str, *, status_code: int | None = None) -> LLMError:
    lowered = message.lower()
    if status_code == 404 or "not found" in lowered:
        return LLMModelNotFoundError(message)
    if "timed out" in lowered or "timeout" in lowered:
        return LLMTimeoutError(message)
    if any(token in lowered for token in ("context length", "too long", "too large", "num_ctx")):
        return LLMContextTooLargeError(message)
    if "cancel" in lowered:
        return LLMCancelledError(message)
    return LLMUnavailableError(message)


class OllamaClient:
    def __init__(
        self,
        base_url: str,
        *,
        timeout: float,
        client: httpx.AsyncClient | None = None,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self._client = client
        self._owns_client = client is None

    async def _client_obj(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(base_url=self.base_url, timeout=self.timeout)
        return self._client

    async def aclose(self) -> None:
        if self._owns_client and self._client is not None:
            await self._client.aclose()
            self._client = None

    async def version(self) -> str | None:
        response = await self._request("GET", "/api/version")
        payload = response.json()
        version = payload.get("version")
        return str(version) if version is not None else None

    async def list_models(self) -> list[str]:
        response = await self._request("GET", "/api/tags")
        payload = response.json()
        models = payload.get("models", [])
        names: list[str] = []
        for item in models:
            name = item.get("name") or item.get("model")
            if name:
                names.append(str(name))
        return names

    async def chat(self, messages: list[dict[str, str]], profile: ModelProfile) -> str:
        payload = self._chat_payload(messages, profile, stream=False)
        response = await self._request("POST", "/api/chat", json=payload)
        return str(response.json().get("message", {}).get("content", ""))

    async def generate(self, prompt: str, profile: ModelProfile) -> str:
        payload = {
            "model": profile.model_ref,
            "prompt": prompt,
            "stream": False,
            **self._options(profile),
        }
        response = await self._request("POST", "/api/generate", json=payload)
        return str(response.json().get("response", ""))

    async def stream_chat(
        self, messages: list[dict[str, str]], profile: ModelProfile
    ) -> AsyncIterator[str]:
        payload = self._chat_payload(messages, profile, stream=True)
        client = await self._client_obj()
        try:
            async with client.stream("POST", "/api/chat", json=payload) as response:
                await self._raise_for_response(response)
                async for line in response.aiter_lines():
                    if not line:
                        continue
                    data = json.loads(line)
                    content = data.get("message", {}).get("content") or data.get("response") or ""
                    if content:
                        yield str(content)
                    if data.get("done"):
                        return
        except httpx.TimeoutException as exc:
            raise LLMTimeoutError() from exc
        except (httpx.ConnectError, httpx.ConnectTimeout, httpx.NetworkError) as exc:
            raise LLMUnavailableError() from exc
        except httpx.HTTPError as exc:
            raise LLMCancelledError(str(exc)) from exc

    def _chat_payload(
        self, messages: list[dict[str, str]], profile: ModelProfile, *, stream: bool
    ) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "model": profile.model_ref,
            "messages": messages,
            "stream": stream,
            **self._options(profile),
        }
        return payload

    def _options(self, profile: ModelProfile) -> dict[str, Any]:
        options: dict[str, Any] = {
            "options": {
                "temperature": profile.temperature,
                "num_ctx": profile.context_default,
            }
        }
        if profile.thinking_policy is not ThinkingPolicy.AUTO:
            options["think"] = profile.thinking_policy is ThinkingPolicy.ON
        return options

    async def _request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        client = await self._client_obj()
        try:
            response = await client.request(method, path, **kwargs)
        except httpx.TimeoutException as exc:
            raise LLMTimeoutError() from exc
        except (httpx.ConnectError, httpx.ConnectTimeout, httpx.NetworkError) as exc:
            raise LLMUnavailableError() from exc
        await self._raise_for_response(response)
        return response

    async def _raise_for_response(self, response: httpx.Response) -> None:
        if response.is_success:
            return
        body = (await response.aread()).decode("utf-8", errors="replace")
        try:
            payload = json.loads(body)
            message = str(payload.get("error") or body)
        except json.JSONDecodeError:
            message = body or f"Ollama HTTP {response.status_code}"
        raise normalize_ollama_error(message, status_code=response.status_code)
