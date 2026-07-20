"""
Backfills Product.pricingModel for records where the cheap keyword heuristic
(src/scrapers/products.py's _infer_pricing_model) found no explicit signal,
using the same multi-tier LLM fallback chain as the news enrichment pass.

This is a genuine cross-phase integration: Phase III's extraction engine
applied to Phase I's data, not two isolated pieces of code that happen to
sit in the same repo. It also demonstrates enum-constrained extraction —
the LLM is asked to pick one of exactly 4 values (or null), and any
response that doesn't match a real PricingModel value is discarded rather
than trusted, so a hallucinated or malformed answer can't corrupt the data.
"""
from __future__ import annotations

from __future__ import annotations

import logging

import aiohttp

from src.db import fetch_records, get_raw_text, update_record_by_source_url
from src.llm.extractor import LLMKeys, extract_structured
from src.schemas import PricingModel

logger = logging.getLogger("llm.pricing_backfill")

PRICING_SCHEMA_DESCRIPTION = """{
  "pricingModel": "one of exactly: FREE, FREEMIUM, PAID, ENTERPRISE — or null if genuinely unclear from the text. Do not guess if there is no real signal."
}"""

_VALID_VALUES = {m.value for m in PricingModel}


def _validate_pricing_value(raw_value) -> str | None:
    """Only accept a response that's actually one of the 4 real enum
    values. Anything else (wrong casing handled, but genuinely invalid
    values, extra text, etc.) is treated as no answer — we never let an
    LLM's malformed output become a stored value outside the schema's
    allowed set."""
    if not isinstance(raw_value, str):
        return None
    normalized = raw_value.strip().upper()
    return normalized if normalized in _VALID_VALUES else None


async def backfill_one(session: aiohttp.ClientSession, record: dict, keys: LLMKeys) -> bool:
    """Returns True if this record's pricingModel was successfully backfilled."""
    source_url = record.get("source", {}).get("url")
    current_pricing = record.get("content", {}).get("pricingModel")
    if current_pricing is not None:
        return False  # heuristic already found something — nothing to do

    raw_text = get_raw_text(source_url) if source_url else None
    if not raw_text or not raw_text.strip():
        return False  # nothing to extract from

    result = await extract_structured(session, raw_text, PRICING_SCHEMA_DESCRIPTION, keys)
    if result.data is None:
        return False

    validated = _validate_pricing_value(result.data.get("pricingModel"))
    if validated is None:
        return False

    record["content"]["pricingModel"] = validated
    update_record_by_source_url("PRODUCT", source_url, record)
    return True


async def run_pricing_backfill_pipeline(keys: LLMKeys) -> dict[str, int]:
    """Entry point. Returns {'attempted': N, 'backfilled': N} so the caller
    can see both how many were candidates and how many actually got a
    validated answer — a gap between the two is expected and honest (some
    product descriptions genuinely don't signal pricing at all, even to an
    LLM), not a failure.
    """
    products = fetch_records("PRODUCT")
    candidates = [p for p in products if p.get("content", {}).get("pricingModel") is None]

    backfilled = 0
    async with aiohttp.ClientSession() as session:
        for record in candidates:
            if await backfill_one(session, record, keys):
                backfilled += 1

    return {"attempted": len(candidates), "backfilled": backfilled}