import json
import logging
import os

import httpx
import pytest
from app.adapters.llm.fake import FakeLLMProvider
from app.adapters.llm.profiles import default_model_profiles
from app.adapters.llm.types import ChatMessage, ModelRole
from app.adapters.ollama import OllamaAdapter
from app.adapters.ollama.client import OllamaClient
from app.domain.analysis import AnalysisError, extract_json_object
from app.prompts.chapter_analyzer import CHAPTER_ANALYZER_PROMPT_VERSION
from app.schemas.analysis import chapter_analysis_json_schema
from app.services.chapter_analyzer import analyze_chapter_text
from app.settings import get_settings
from tests.test_chapter_analysis import _valid_payload

CHAPTER_BODY = "林深走进雨巷，遇见一只鹿。"


def test_extract_json_object_strips_fences() -> None:
    payload = extract_json_object("```json\n{\"ok\": true}\n```")
    assert payload == {"ok": True}
    with pytest.raises(AnalysisError) as caught:
        extract_json_object("not-json")
    assert caught.value.code == "analysis_schema_invalid"


def test_structured_output_validates_without_logging_body(
    caplog: pytest.LogCaptureFixture,
) -> None:
    provider = FakeLLMProvider(response=json.dumps(_valid_payload(), ensure_ascii=False))
    caplog.set_level(logging.INFO, logger="lns.analysis")

    async def _run() -> None:
        result = await analyze_chapter_text(
            provider,
            CHAPTER_BODY,
            chapter_id="c1",
            source_version_id="v1",
        )
        assert result.payload.summary.synopsis.startswith("林深")
        assert result.repaired is False
        assert result.attempts == 1
        assert result.prompt_version == CHAPTER_ANALYZER_PROMPT_VERSION
        assert result.schema_version == "chapter-analysis.v1"
        assert provider.response_formats[0] == chapter_analysis_json_schema()

    import asyncio

    asyncio.run(_run())
    joined = "\n".join(record.getMessage() for record in caplog.records)
    assert "c1" in joined
    assert CHAPTER_BODY not in joined
    assert "<<<CHAPTER>>>" not in joined


def test_invalid_json_is_repaired_once() -> None:
    valid = json.dumps(_valid_payload(), ensure_ascii=False)
    provider = FakeLLMProvider(responses=["not-json", valid])

    async def _run() -> None:
        result = await analyze_chapter_text(provider, CHAPTER_BODY)
        assert result.repaired is True
        assert result.attempts == 2
        assert result.payload.characters[0].name == "林深"
        assert len(provider.calls) == 2

    import asyncio

    asyncio.run(_run())


def test_second_invalid_output_does_not_become_analysis_result() -> None:
    broken = json.dumps({"summary": {"synopsis": ""}}, ensure_ascii=False)
    provider = FakeLLMProvider(responses=[broken, broken])

    async def _run() -> None:
        with pytest.raises(AnalysisError) as caught:
            await analyze_chapter_text(provider, CHAPTER_BODY)
        assert caught.value.code == "analysis_repair_exhausted"

    import asyncio

    asyncio.run(_run())


def test_llm_errors_are_mapped_for_jobs() -> None:
    async def _run() -> None:
        with pytest.raises(AnalysisError) as timeout:
            await analyze_chapter_text(FakeLLMProvider(mode="timeout"), CHAPTER_BODY)
        assert timeout.value.code == "llm_timeout"
        with pytest.raises(AnalysisError) as missing:
            await analyze_chapter_text(FakeLLMProvider(mode="model_not_found"), CHAPTER_BODY)
        assert missing.value.code == "llm_model_not_found"
        with pytest.raises(AnalysisError) as invalid:
            await analyze_chapter_text(FakeLLMProvider(mode="invalid_output"), CHAPTER_BODY)
        assert invalid.value.code == "llm_invalid_output"

    import asyncio

    asyncio.run(_run())


def test_ollama_chat_sends_json_schema_format() -> None:
    captured: dict = {}

    def handler(request: httpx.Request) -> httpx.Response:
        payload = json.loads(request.content.decode("utf-8") or "{}")
        captured.update(payload)
        return httpx.Response(
            200,
            json={"message": {"content": json.dumps(_valid_payload(), ensure_ascii=False)}},
        )

    settings = get_settings()
    http_client = httpx.AsyncClient(
        transport=httpx.MockTransport(handler),
        base_url=settings.ollama_base_url,
        timeout=5,
    )
    adapter = OllamaAdapter(
        settings,
        client=OllamaClient(settings.ollama_base_url, timeout=5, client=http_client),
    )
    profile = default_model_profiles(settings)[ModelRole.ANALYZER]

    async def _run() -> None:
        content = await adapter.chat(
            [ChatMessage(role="user", content="hi")],
            profile,
            response_format=chapter_analysis_json_schema(),
        )
        await adapter.aclose()
        assert json.loads(content)["summary"]["synopsis"]

    import asyncio

    asyncio.run(_run())
    assert captured["format"] == chapter_analysis_json_schema()
    assert captured["model"] == settings.writer_model


@pytest.mark.skipif(
    os.getenv("LNS_OLLAMA_SMOKE") != "1",
    reason="Set LNS_OLLAMA_SMOKE=1 to hit local Ollama. Not Windows GPU evidence.",
)
def test_local_ollama_structured_smoke_not_gpu_evidence() -> None:
    """CPU_DEV/local smoke only. Do not register as WINDOWS_GPU acceptance."""

    import asyncio

    from app.adapters.ollama.adapter import OllamaAdapter as LiveAdapter

    settings = get_settings()
    adapter = LiveAdapter(settings)

    async def _run() -> None:
        health = await adapter.health()
        if not health.reachable or not health.default_model_installed:
            pytest.skip("Local Ollama or qwen3.5:9b is unavailable.")
        result = await analyze_chapter_text(adapter, CHAPTER_BODY)
        await adapter.aclose()
        assert result.payload.summary.synopsis

    asyncio.run(_run())
