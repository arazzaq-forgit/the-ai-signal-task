from unittest.mock import AsyncMock, patch

import pytest

from src.db import save_raw_text, save_record
from src.llm.extractor import ExtractionResult, LLMKeys
from src.llm.pricing_backfill import _validate_pricing_value, backfill_one


@pytest.mark.parametrize("raw,expected", [
    ("FREE", "FREE"),
    ("free", "FREE"),
    ("  PAID  ", "PAID"),
    ("ENTERPRISE", "ENTERPRISE"),
    ("FREEMIUM", "FREEMIUM"),
    ("SUBSCRIPTION", None),
    ("probably free I think", None),
    (None, None),
    (123, None),
    ("", None),
])
def test_validate_pricing_value(raw, expected):
    assert _validate_pricing_value(raw) == expected


@pytest.fixture
def keys():
    return LLMKeys(gemini="k", groq="k", deepseek="k")


@pytest.mark.asyncio
async def test_skips_records_that_already_have_pricing(keys):
    record = {"source": {"url": "https://x.com/1"}, "content": {"startupName": "X", "pricingModel": "FREE"}}
    with patch("src.llm.pricing_backfill.extract_structured", new=AsyncMock(side_effect=Exception("should not be called"))):
        result = await backfill_one(None, record, keys)
    assert result is False


@pytest.mark.asyncio
async def test_skips_records_with_no_raw_text_available(keys):
    record = {"source": {"url": "https://x.com/nonexistent"}, "content": {"startupName": "Y", "pricingModel": None}}
    result = await backfill_one(None, record, keys)
    assert result is False


@pytest.mark.asyncio
async def test_successful_backfill_mutates_record(keys):
    save_raw_text("https://x.com/3", "This is a completely free tool for everyone")
    record = {"source": {"url": "https://x.com/3"}, "content": {"startupName": "Z", "pricingModel": None}}
    save_record("PRODUCT", dict(record))
    with patch("src.llm.pricing_backfill.extract_structured", new=AsyncMock(
        return_value=ExtractionResult(data={"pricingModel": "FREE"}, provider_used="groq", attempts=[])
    )):
        result = await backfill_one(None, record, keys)
    assert result is True
    assert record["content"]["pricingModel"] == "FREE"


@pytest.mark.asyncio
async def test_invalid_llm_value_is_rejected_not_stored(keys):
    save_raw_text("https://x.com/4", "Some ambiguous text")
    record = {"source": {"url": "https://x.com/4"}, "content": {"startupName": "W", "pricingModel": None}}
    with patch("src.llm.pricing_backfill.extract_structured", new=AsyncMock(
        return_value=ExtractionResult(data={"pricingModel": "SUBSCRIPTION_BASED"}, provider_used="groq", attempts=[])
    )):
        result = await backfill_one(None, record, keys)
    assert result is False
    assert record["content"]["pricingModel"] is None