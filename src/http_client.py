"""
Shared async HTTP layer. Every scraper and LLM call routes through here so
retry/backoff/concurrency behavior is defined once, not copy-pasted.
"""
from __future__ import annotations

import asyncio
import logging
import time
from collections import defaultdict
from typing import Any, Optional
from urllib.parse import urlparse

import aiohttp
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential_jitter,
)

logger = logging.getLogger("http_client")


class RateLimitError(Exception):
    """Raised on HTTP 429 so tenacity knows to back off and retry."""


class PayloadTooLargeError(Exception):
    """Raised on HTTP 413 so callers can shrink the payload and retry."""


class TransientHTTPError(Exception):
    """Raised on 5xx so tenacity retries; not raised for 4xx (client's fault)."""


class ClientHTTPError(Exception):
    """Raised on any other 4xx (404, 403, etc). Deliberately NOT retried —
    a repo/paper that doesn't exist won't exist on retry #2 either. Retrying
    these was the actual cause of runs appearing to hang: each 404 was
    silently costing up to ~70s across 5 retries with exponential backoff."""


# Global concurrency cap — this is the one knob you turn to "scale to 500k":
# raise MAX_CONCURRENCY (and run more worker processes/nodes) without touching
# any scraper logic.
MAX_CONCURRENCY = 10
_semaphore = asyncio.Semaphore(MAX_CONCURRENCY)

# Per-host minimum spacing between requests, in seconds. Concurrency alone
# isn't enough — a source can tolerate 10 concurrent connections but still
# reject you if you fire 10 requests in the same 100ms. Retrying after a 429
# is a safety net; this is what actually avoids triggering them in the first
# place. Unlisted hosts get no throttling (0.0).
MIN_INTERVAL_SECONDS: dict[str, float] = {
    "huggingface.co": 1.0,
    "api.github.com": 0.05,
    "boards-api.greenhouse.io": 0.2,
    "job-boards.greenhouse.io": 0.2,
    "api.lever.co": 0.2,
    "api.ashbyhq.com": 0.2,
    "techcrunch.com": 0.5,
    "venturebeat.com": 0.5,
    "www.theverge.com": 0.5,
    "www.technologyreview.com": 0.5,
    "arstechnica.com": 0.5,
    "generativelanguage.googleapis.com": 0.3,
    "api.groq.com": 0.1,
    "api.deepseek.com": 0.2,
    "api.producthunt.com": 0.3,
}

_host_locks: dict[str, asyncio.Lock] = defaultdict(asyncio.Lock)
_host_last_call: dict[str, float] = {}

# Only these are worth retrying: rate limits, server-side 5xx, and genuine
# network-level failures (dropped connections, timeouts). A 404/403/other
# 4xx means the request reached the server and got a definitive answer —
# retrying it wastes time for no benefit.
_RETRYABLE = (RateLimitError, TransientHTTPError, aiohttp.ClientConnectionError, asyncio.TimeoutError)


async def _throttle(url: str) -> None:
    host = urlparse(url).netloc
    interval = MIN_INTERVAL_SECONDS.get(host, 0.0)
    if interval <= 0:
        return
    async with _host_locks[host]:
        now = time.monotonic()
        elapsed = now - _host_last_call.get(host, 0.0)
        wait = interval - elapsed
        if wait > 0:
            await asyncio.sleep(wait)
        _host_last_call[host] = time.monotonic()


@retry(
    reraise=True,
    stop=stop_after_attempt(5),
    wait=wait_exponential_jitter(initial=1, max=30),
    retry=retry_if_exception_type(_RETRYABLE),
)
async def fetch_json(
    session: aiohttp.ClientSession,
    url: str,
    *,
    headers: Optional[dict] = None,
    params: Optional[dict] = None,
) -> Any:
    await _throttle(url)
    async with _semaphore:
        async with session.get(url, headers=headers, params=params, timeout=aiohttp.ClientTimeout(total=30)) as resp:
            if resp.status == 429:
                logger.warning(f"429 rate limited: {url}")
                raise RateLimitError(url)
            if resp.status == 413:
                logger.warning(f"413 payload too large: {url}")
                raise PayloadTooLargeError(url)
            if 500 <= resp.status < 600:
                raise TransientHTTPError(f"{resp.status} on {url}")
            if 400 <= resp.status < 500:
                raise ClientHTTPError(f"{resp.status} on {url}")
            resp.raise_for_status()
            return await resp.json()


@retry(
    reraise=True,
    stop=stop_after_attempt(5),
    wait=wait_exponential_jitter(initial=1, max=30),
    retry=retry_if_exception_type(_RETRYABLE),
)
async def fetch_text(
    session: aiohttp.ClientSession,
    url: str,
    *,
    headers: Optional[dict] = None,
) -> str:
    await _throttle(url)
    async with _semaphore:
        async with session.get(url, headers=headers, timeout=aiohttp.ClientTimeout(total=30)) as resp:
            if resp.status == 429:
                raise RateLimitError(url)
            if 500 <= resp.status < 600:
                raise TransientHTTPError(f"{resp.status} on {url}")
            if 400 <= resp.status < 500:
                raise ClientHTTPError(f"{resp.status} on {url}")
            resp.raise_for_status()
            return await resp.text()


@retry(
    reraise=True,
    stop=stop_after_attempt(5),
    wait=wait_exponential_jitter(initial=1, max=30),
    retry=retry_if_exception_type(_RETRYABLE),
)
async def post_json(
    session: aiohttp.ClientSession,
    url: str,
    *,
    json_body: Optional[dict] = None,
    headers: Optional[dict] = None,
    timeout: int = 30,
) -> Any:
    """POST counterpart to fetch_json — same retry/backoff/throttle policy.
    Added after a real bug: Product Hunt's GraphQL endpoint (POST-only) was
    originally called with a raw aiohttp POST that bypassed all retry
    protection, so its first live 429 crashed the whole pipeline instead of
    backing off. Every outbound request in this project, GET or POST, now
    routes through one of these two functions — no more parallel
    hand-rolled request paths with inconsistent error handling."""
    await _throttle(url)
    async with _semaphore:
        async with session.post(url, json=json_body, headers=headers, timeout=aiohttp.ClientTimeout(total=timeout)) as resp:
            if resp.status == 429:
                logger.warning(f"429 rate limited: {url}")
                raise RateLimitError(url)
            if resp.status == 413:
                raise PayloadTooLargeError(url)
            if 500 <= resp.status < 600:
                raise TransientHTTPError(f"{resp.status} on {url}")
            if 400 <= resp.status < 500:
                body_text = await resp.text()
                raise ClientHTTPError(f"{resp.status} on {url}: {body_text[:300]}")
            resp.raise_for_status()
            return await resp.json()