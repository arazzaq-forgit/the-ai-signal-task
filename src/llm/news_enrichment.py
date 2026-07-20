"""
Applies the multi-tier LLM extraction engine to the news pipeline's raw
full-text — this is the genuine "raw HTML/text must be structured into JSON
using LLMs" use case Phase III describes. (Startups/products/papers/jobs
were deliberately sourced from clean structured APIs instead of raw HTML,
so they don't need this step — news is the one vertical in this pipeline
where we're holding unstructured prose that benefits from LLM structuring.)

Each result also records which provider actually produced it and the full
attempt log, so the fallback chain's behavior is auditable, not a black box.
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone

import aiohttp

from src.db import fetch_records, save_record
from src.llm.extractor import LLMKeys, extract_structured

logger = logging.getLogger("llm.news_enrichment")

NEWS_SCHEMA_DESCRIPTION = """{
  "summary": "string, 1-2 sentence neutral summary of the article",
  "key_entities": ["array of strings: companies, products, or people named"],
  "sentiment": "one of: positive, negative, neutral, mixed"
}"""


async def enrich_one(session: aiohttp.ClientSession, news_record: dict, keys: LLMKeys) -> dict:
    full_text = news_record.get("content", {}).get("fullText")
    source_url = news_record.get("source", {}).get("url")

    if not full_text:
        return {
            "sourceUrl": source_url,
            "extraction": None,
            "providerUsed": None,
            "attempts": ["skipped: no full text available for this record"],
        }

    result = await extract_structured(session, full_text, NEWS_SCHEMA_DESCRIPTION, keys)
    return {
        "sourceUrl": source_url,
        "extraction": result.data,
        "providerUsed": result.provider_used,
        "attempts": result.attempts,
        "enrichedAt": datetime.now(timezone.utc).isoformat(),
    }


async def run_news_enrichment_pipeline(keys: LLMKeys) -> int:
    """Entry point. Returns the number of records successfully enriched
    (i.e. at least one provider in the chain returned valid, parseable
    JSON). Records where every provider failed still get saved — with
    extraction=None and a full attempts log — so failures are visible in
    the output, not silently dropped."""
    news_records = fetch_records("NEWS")
    if not news_records:
        logger.warning("No NEWS records found — run 'python main.py news' first")
        return 0

    succeeded = 0
    async with aiohttp.ClientSession() as session:
        for record in news_records:
            enriched = await enrich_one(session, record, keys)
            save_record("NEWS_ENRICHED", enriched)
            if enriched["extraction"] is not None:
                succeeded += 1
            logger.info(f"{enriched['sourceUrl']}: provider={enriched['providerUsed']}")

    return succeeded