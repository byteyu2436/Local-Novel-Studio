import asyncio
import json

import httpx
import pytest
from app.adapters.llm import (
    ChatMessage,
    FakeLLMProvider,
    LLMCancelledError,
    LLMContextTooLargeError,
    LLMInvalidOutputError,
    LLMModelNotFoundError,
    LLMTimeoutError,
    LLMUnavailableError,
    ModelRole,
    default_model_profiles,
)
from app.adapters.ollama import OllamaAdapter
from app.adapters.ollama.client import OllamaClient
from app.adapters.ollama.client import normalize_ollama_error as client_normalize
from app.settings import get_settings


def test_writer_and_analyzer_share_model_ref() -> None:
    profiles = default_model_profiles(get_settings())
    writer = profiles[ModelRole.WRITER]
    analyzer = profiles[ModelRole.ANALYZER]
    assert writer.model_ref == analyzer.model_ref == get_settings().writer_model
    assert writer.temperature != analyzer.temperature


def test_error_normalization() -> None:
    assert isinstance(
        client_normalize("model 'x' not found", status_code=404), LLMModelNotFoundError
    )
    assert isinstance(
        client_normalize("prompt is too long for context length"), LLMContextTooLargeError
    )
    assert isinstance(client_normalize("timed out"), LLMTimeoutError)


def test_fake_provider_contract_modes() -> None:
    profile = default_model_profiles(get_settings())[ModelRole.WRITER]
    messages = [ChatMessage(role="user", content="hello")]

    async def _run() -> None:
        success = FakeLLMProvider(mode="success", response="done")
        assert await success.chat(messages, profile) == "done"
        health = await FakeLLMProvider(mode="unavailable").health()
        assert health.status == "unavailable"

        with pytest.raises(LLMTimeoutError):
            await FakeLLMProvider(mode="timeout").chat(messages, profile)
        with pytest.raises(LLMCancelledError):
            await FakeLLMProvider(mode="cancel").generate("hello", profile)
        with pytest.raises(LLMModelNotFoundError):
            await FakeLLMProvider(mode="model_not_found").list_models()
        with pytest.raises(LLMInvalidOutputError):
            await FakeLLMProvider(mode="invalid_output").chat(messages, profile)
        with pytest.raises(LLMUnavailableError):
            await FakeLLMProvider(mode="unavailable").chat(messages, profile)

        chunks: list[str] = []
        with pytest.raises(LLMInvalidOutputError):
            async for chunk in FakeLLMProvider(
                mode="stream_interrupt", chunks=["partial"]
            ).stream_chat(messages, profile):
                chunks.append(chunk.text)
        assert chunks == ["partial"]

    asyncio.run(_run())


def _json_body(request: httpx.Request) -> dict:
    return json.loads(request.content.decode("utf-8") or "{}")


def _mock_transport() -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/tags":
            return httpx.Response(200, json={"models": [{"name": "qwen3.5:9b"}]})
        if request.url.path == "/api/version":
            return httpx.Response(200, json={"version": "0.11.0"})
        if request.url.path == "/api/chat":
            payload = _json_body(request)
            if payload.get("model") == "missing:model":
                return httpx.Response(404, json={"error": "model 'missing:model' not found"})
            if payload.get("stream"):
                return httpx.Response(
                    200,
                    text=(
                        '{"message":{"content":"hel"},"done":false}\n'
                        '{"message":{"content":"lo"},"done":true}\n'
                    ),
                )
            return httpx.Response(
                200,
                json={"message": {"role": "assistant", "content": "hello"}},
            )
        if request.url.path == "/api/generate":
            return httpx.Response(200, json={"response": "generated"})
        return httpx.Response(404, json={"error": "not found"})

    return httpx.MockTransport(handler)


def test_ollama_adapter_mock_chat_stream_and_health() -> None:
    settings = get_settings()
    http_client = httpx.AsyncClient(
        transport=_mock_transport(),
        base_url=settings.ollama_base_url,
        timeout=5,
    )
    adapter = OllamaAdapter(
        settings,
        client=OllamaClient(settings.ollama_base_url, timeout=5, client=http_client),
    )
    profile = default_model_profiles(settings)[ModelRole.WRITER]
    messages = [ChatMessage(role="user", content="hi")]

    async def _run() -> None:
        health = await adapter.health()
        assert health.reachable is True
        assert health.default_model_installed is True
        assert await adapter.chat(messages, profile) == "hello"
        assert await adapter.generate("hi", profile) == "generated"
        streamed: list[str] = []
        done_flags: list[bool] = []
        async for chunk in adapter.stream_chat(messages, profile):
            streamed.append(chunk.text)
            done_flags.append(chunk.done)
        assert "".join(streamed) == "hello"
        assert done_flags[-1] is True
        assert done_flags.count(True) == 1
        assert streamed[-1] == ""
        await adapter.aclose()

    asyncio.run(_run())


def _stream_only_transport(lines: str) -> httpx.MockTransport:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/api/chat" and _json_body(request).get("stream"):
            return httpx.Response(200, text=lines)
        return httpx.Response(404, json={"error": "not found"})

    return httpx.MockTransport(handler)


async def _join_stream(adapter: OllamaAdapter) -> tuple[str, list[bool]]:
    profile = default_model_profiles(get_settings())[ModelRole.WRITER]
    messages = [ChatMessage(role="user", content="hi")]
    texts: list[str] = []
    done_flags: list[bool] = []
    async for chunk in adapter.stream_chat(messages, profile):
        texts.append(chunk.text)
        done_flags.append(chunk.done)
    await adapter.aclose()
    return "".join(texts), done_flags


def test_stream_concatenates_all_chunks_without_duplicating_the_tail() -> None:
    settings = get_settings()

    async def _run_with(lines: str, expected: str) -> None:
        http_client = httpx.AsyncClient(
            transport=_stream_only_transport(lines),
            base_url=settings.ollama_base_url,
            timeout=5,
        )
        adapter = OllamaAdapter(
            settings,
            client=OllamaClient(settings.ollama_base_url, timeout=5, client=http_client),
        )
        joined, done_flags = await _join_stream(adapter)
        assert joined == expected
        assert done_flags[-1] is True
        assert done_flags.count(True) == 1
        assert done_flags[:-1] == [False] * (len(done_flags) - 1)

    async def _run() -> None:
        await _run_with(
            '{"message":{"content":"hel"},"done":false}\n{"message":{"content":"lo"},"done":true}\n',
            "hello",
        )
        await _run_with('{"message":{"content":"OK"},"done":true}\n', "OK")
        await _run_with('{"message":{"content":""},"done":true}\n', "")

    asyncio.run(_run())


def test_fake_stream_matches_ollama_done_marker_contract() -> None:
    profile = default_model_profiles(get_settings())[ModelRole.WRITER]
    messages = [ChatMessage(role="user", content="hello")]

    async def _join(fake: FakeLLMProvider) -> tuple[str, list[bool]]:
        texts: list[str] = []
        done_flags: list[bool] = []
        async for chunk in fake.stream_chat(messages, profile):
            texts.append(chunk.text)
            done_flags.append(chunk.done)
        return "".join(texts), done_flags

    async def _run() -> None:
        joined, done_flags = await _join(FakeLLMProvider(chunks=["hel", "lo"]))
        assert joined == "hello"
        assert done_flags == [False, False, True]
        single, single_done = await _join(FakeLLMProvider(chunks=["OK"]))
        assert single == "OK"
        assert single_done == [False, True]
        empty, empty_done = await _join(FakeLLMProvider(chunks=[]))
        assert empty == ""
        assert empty_done == [True]

    asyncio.run(_run())


def test_ollama_adapter_normalizes_missing_model() -> None:
    settings = get_settings()
    http_client = httpx.AsyncClient(
        transport=_mock_transport(),
        base_url=settings.ollama_base_url,
        timeout=5,
    )
    adapter = OllamaAdapter(
        settings,
        client=OllamaClient(settings.ollama_base_url, timeout=5, client=http_client),
    )
    profile = default_model_profiles(settings)[ModelRole.WRITER].model_copy(
        update={"model_name": "missing", "model_tag": "model"}
    )

    async def _run() -> None:
        with pytest.raises(LLMModelNotFoundError):
            await adapter.chat([ChatMessage(role="user", content="hi")], profile)
        await adapter.aclose()

    asyncio.run(_run())


def _is_windows_gpu() -> bool:
    get_settings.cache_clear()
    return get_settings().lns_execution_profile.value == "windows-gpu"


@pytest.mark.skipif(
    not _is_windows_gpu(),
    reason="Real Ollama/qwen3.5:9b smoke is deferred to WINDOWS_GPU.",
)
def test_real_ollama_qwen_smoke() -> None:
    settings = get_settings()
    adapter = OllamaAdapter(settings)
    profile = default_model_profiles(settings)[ModelRole.WRITER]

    async def _run() -> None:
        health = await adapter.health()
        assert health.reachable is True
        assert health.default_model == "qwen3.5:9b"
        assert health.default_model_installed is True

        non_stream = await adapter.chat(
            [ChatMessage(role="user", content="Reply with exactly the word OK.")],
            profile,
        )
        assert non_stream.strip()

        streamed: list[str] = []
        async for chunk in adapter.stream_chat(
            [ChatMessage(role="user", content="Reply with exactly the word STREAM.")],
            profile,
        ):
            if chunk.text:
                streamed.append(chunk.text)
        assert any(text.strip() for text in streamed)

        first_token = asyncio.Event()

        async def _cancellable_stream() -> None:
            async for chunk in adapter.stream_chat(
                [
                    ChatMessage(
                        role="user",
                        content="Count slowly from 1 to 200, one number per line.",
                    )
                ],
                profile,
            ):
                if chunk.text and not first_token.is_set():
                    first_token.set()

        task = asyncio.create_task(_cancellable_stream())
        await asyncio.wait_for(first_token.wait(), timeout=settings.ollama_timeout_seconds)
        assert not task.done(), "stream completed before cancel could be requested"
        task.cancel()
        with pytest.raises(LLMCancelledError):
            await task

        await adapter.aclose()

    asyncio.run(_run())
