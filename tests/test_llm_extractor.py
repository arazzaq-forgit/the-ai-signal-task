from unittest.mock import AsyncMock, patch

import pytest

from src.llm.extractor import LLMKeys, _strip_json_fences, _try_parse_json, extract_structured


def test_strip_json_fences_removes_markdown_wrapper():
    assert _strip_json_fences('```json\n{"a": 1}\n```') == '{"a": 1}'


def test_try_parse_json_valid():
    assert _try_parse_json('{"a": 1}') == {"a": 1}


def test_try_parse_json_invalid_returns_none():
    assert _try_parse_json("not json") is None


def test_try_parse_json_non_dict_returns_none():
    assert _try_parse_json("[1, 2, 3]") is None


@pytest.fixture
def keys():
    return LLMKeys(gemini="g", groq="q", deepseek="d")


@pytest.mark.asyncio
async def test_first_provider_success_short_circuits_rest(keys):
    with patch("src.llm.extractor.call_gemini", new=AsyncMock(return_value='{"title": "From Gemini"}')), \
         patch("src.llm.extractor.call_groq", new=AsyncMock(side_effect=Exception("should not be called"))):
        result = await extract_structured(None, "text", "schema", keys)
    assert result.provider_used == "gemini"
    assert result.data == {"title": "From Gemini"}


@pytest.mark.asyncio
async def test_falls_back_through_chain_on_failures(keys):
    with patch("src.llm.extractor.call_gemini", new=AsyncMock(side_effect=Exception("fail"))), \
         patch("src.llm.extractor.call_groq", new=AsyncMock(side_effect=Exception("fail"))), \
         patch("src.llm.extractor.call_deepseek", new=AsyncMock(return_value='{"title": "From DeepSeek"}')):
        result = await extract_structured(None, "text", "schema", keys)
    assert result.provider_used == "deepseek"


@pytest.mark.asyncio
async def test_all_providers_failing_returns_none_not_exception(keys):
    with patch("src.llm.extractor.call_gemini", new=AsyncMock(side_effect=Exception("fail"))), \
         patch("src.llm.extractor.call_groq", new=AsyncMock(side_effect=Exception("fail"))), \
         patch("src.llm.extractor.call_deepseek", new=AsyncMock(side_effect=Exception("fail"))):
        result = await extract_structured(None, "text", "schema", keys)
    assert result.data is None
    assert result.provider_used is None


@pytest.mark.asyncio
async def test_garbage_json_falls_through_to_next_provider(keys):
    with patch("src.llm.extractor.call_gemini", new=AsyncMock(return_value="Sure! Here's your data.")), \
         patch("src.llm.extractor.call_groq", new=AsyncMock(return_value='{"title": "Groq saved it"}')):
        result = await extract_structured(None, "text", "schema", keys)
    assert result.provider_used == "groq"


@pytest.mark.asyncio
async def test_missing_keys_are_skipped_without_network_call():
    partial_keys = LLMKeys(gemini=None, groq="q", deepseek=None)
    with patch("src.llm.extractor.call_groq", new=AsyncMock(return_value='{"title": "Groq only"}')):
        result = await extract_structured(None, "text", "schema", partial_keys)
    assert result.provider_used == "groq"
    assert "skipped" in result.attempts[0]
