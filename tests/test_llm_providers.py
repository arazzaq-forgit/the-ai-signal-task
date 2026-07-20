from unittest.mock import AsyncMock, patch

import pytest

from src.llm.providers import call_deepseek, call_gemini, call_groq


@pytest.mark.asyncio
async def test_call_gemini_parses_response_shape():
    gemini_resp = {"candidates": [{"content": {"parts": [{"text": '{"title": "Test"}'}]}}]}
    with patch("src.llm.providers._post_json", new=AsyncMock(return_value=gemini_resp)):
        result = await call_gemini(None, "prompt", "fake-key")
    assert result == '{"title": "Test"}'


@pytest.mark.asyncio
async def test_call_groq_parses_openai_compatible_shape():
    resp = {"choices": [{"message": {"content": '{"title": "Test2"}'}}]}
    with patch("src.llm.providers._post_json", new=AsyncMock(return_value=resp)):
        result = await call_groq(None, "prompt", "fake-key")
    assert result == '{"title": "Test2"}'


@pytest.mark.asyncio
async def test_call_deepseek_parses_openai_compatible_shape():
    resp = {"choices": [{"message": {"content": '{"title": "Test3"}'}}]}
    with patch("src.llm.providers._post_json", new=AsyncMock(return_value=resp)):
        result = await call_deepseek(None, "prompt", "fake-key")
    assert result == '{"title": "Test3"}'


@pytest.mark.asyncio
async def test_missing_api_key_raises_without_network_call():
    with pytest.raises(ValueError):
        await call_gemini(None, "prompt", None)


@pytest.mark.asyncio
async def test_malformed_response_shape_raises_clear_error():
    with patch("src.llm.providers._post_json", new=AsyncMock(return_value={"unexpected": "shape"})):
        with pytest.raises(ValueError):
            await call_gemini(None, "prompt", "fake-key")
