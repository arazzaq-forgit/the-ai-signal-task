"""
News pipeline: RSS feeds from 5 AI news sources, filtered to the last 24h.

Design choice: RSS gives us a real, structured pubDate for free, which is
far more reliable than scraping raw HTML and guessing at a date from page
text. Full-text content is fetched separately per-article since RSS feeds
usually only include a summary/excerpt.

Relevance filter: sources like The Verge tag general newsletter content into
their "AI" RSS feed alongside actual AI news, so being nominally listed under
an AI category isn't a strict guarantee of topic relevance. We check title +
summary against an AI-keyword list (word-boundary matched, so "ai" doesn't
false-positive on "again" or "chair") before doing the more expensive
full-text fetch, and drop anything that doesn't mention AI at all.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import Optional

import aiohttp
import feedparser
import trafilatura

from src.db import is_seen, mark_seen, save_record
from src.freshness import is_within_freshness_window, normalize_date
from src.http_client import fetch_text

logger = logging.getLogger("scrapers.news")

# 5 distinct AI news sources via their RSS feeds.
NEWS_FEEDS = {
    "TechCrunch AI": "https://techcrunch.com/category/artificial-intelligence/feed/",
    "VentureBeat AI": "https://venturebeat.com/category/ai/feed/",
    "The Verge AI": "https://www.theverge.com/rss/ai-artificial-intelligence/index.xml",
    "MIT Technology Review AI": "https://www.technologyreview.com/topic/artificial-intelligence/feed",
    "Ars Technica AI": "https://arstechnica.com/tag/ai/feed/",
}

_USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36"

_AI_KEYWORDS = [
    r"\bai\b", r"artificial intelligence", r"machine learning", r"\bllm\b", r"\bllms\b",
    r"large language model", r"neural network", r"generative ai", r"\bgenai\b",
    r"chatbot", r"\bgpt\b", r"openai", r"anthropic", r"\bclaude\b", r"\bgemini\b",
    r"deepmind", r"\bagi\b", r"machine\-learning", r"\bml model", r"foundation model",
    r"\bslm\b", r"transformer model", r"diffusion model",
]
_AI_RELEVANCE_PATTERN = re.compile("|".join(_AI_KEYWORDS), re.IGNORECASE)


def _is_ai_relevant(title: str, summary: str) -> bool:
    return bool(_AI_RELEVANCE_PATTERN.search(f"{title or ''} {summary or ''}"))


async def _fetch_full_text(session: aiohttp.ClientSession, url: str) -> Optional[str]:
    """Best-effort full-text extraction. Returns None (not an error) if the
    article can't be fetched or extracted — we still keep the record with a
    null body rather than dropping it, since title/date/url are still valid
    signal on their own."""
    try:
        html = await fetch_text(session, url, headers={"User-Agent": _USER_AGENT})
    except Exception as e:
        logger.info(f"Could not fetch article body for {url}: {e}")
        return None
    try:
        return trafilatura.extract(html)
    except Exception as e:
        logger.info(f"Could not extract text for {url}: {e}")
        return None


def _entry_published_raw(entry) -> Optional[str]:
    """feedparser normalizes most dates into entry.published, but field
    names vary by feed (updated, published, pubDate already mapped)."""
    return getattr(entry, "published", None) or getattr(entry, "updated", None)


async def process_entry(session: aiohttp.ClientSession, source_name: str, entry, now: datetime) -> Optional[dict]:
    url = getattr(entry, "link", None)
    if not url:
        return None
    if is_seen(url):
        return None

    title = getattr(entry, "title", None)
    summary = getattr(entry, "summary", None)
    if not _is_ai_relevant(title, summary):
        mark_seen(url, "NEWS")  # don't re-check this known-irrelevant url every run
        return None

    raw_date = _entry_published_raw(entry)
    published_dt = normalize_date(raw_date, now=now)

    if published_dt is not None:
        # We have a real date — enforce the 24h freshness requirement strictly.
        if not is_within_freshness_window(published_dt, now=now):
            mark_seen(url, "NEWS")  # still mark seen so we don't re-check a known-stale url forever
            return None
    else:
        # Intelligent heuristic for missing dates: since this is the first
        # time we've seen this URL (checked above via is_seen), treat it as
        # new. A second run of the pipeline will correctly skip it via dedup
        # rather than re-treating it as fresh forever.
        logger.info(f"No parseable date for {url}, using first-seen heuristic")

    full_text = await _fetch_full_text(session, url)

    record = {
        "schemaVersion": "1.0",
        "recordType": "NEWS",
        "source": {"name": source_name, "url": url},
        "content": {
            "title": title,
            "publishedDate": published_dt.isoformat() if published_dt else None,
            "fullText": full_text,
        },
        "collectedAt": datetime.now(timezone.utc).isoformat(),
    }
    mark_seen(url, "NEWS")
    save_record("NEWS", record)
    return record


async def run_news_pipeline() -> int:
    """Entry point. Returns the number of new fresh records saved.
    Note: unlike papers/startups/products, there's no target_count here —
    Phase II asks for 'all 24-hr fresh news found', so we take everything
    that clears the freshness bar rather than capping at a fixed number.
    """
    now = datetime.now(timezone.utc)
    saved = 0

    async with aiohttp.ClientSession() as session:
        for source_name, feed_url in NEWS_FEEDS.items():
            try:
                raw_feed = await fetch_text(session, feed_url, headers={"User-Agent": _USER_AGENT})
            except Exception as e:
                logger.warning(f"Could not fetch feed for {source_name}: {e}")
                continue

            parsed = feedparser.parse(raw_feed)
            logger.info(f"{source_name}: {len(parsed.entries)} entries in feed")

            for entry in parsed.entries:
                record = await process_entry(session, source_name, entry, now)
                if record is not None:
                    saved += 1

    return saved