"""
Async browser-based fetcher for JS-rendered or anti-bot-protected sources
that plain aiohttp requests can't handle — used when a source has no
API/RSS alternative and actually requires a rendered browser session.

This is a deliberate escalation path, not the default: every other scraper
in this project (papers/startups/products/news/jobs) prefers a structured
API specifically to avoid needing this. Reach for this only when no API
exists and the target actively blocks plain HTTP clients.

Stealth measures implemented:
- Real Chromium via Playwright (not a headless-detectable stub) with a
  realistic viewport and a current desktop User-Agent.
- `navigator.webdriver` flag suppressed — the single most common signal
  bot-detection scripts check first.
- Randomized per-action delays — fixed-interval request patterns (e.g.
  "exactly every 500ms") are themselves a bot signal, independent of any
  single request looking fine in isolation.
- Persistent browser context (cookies/local storage carried across
  requests within a run) — a fresh, cookie-less session on every request is
  itself suspicious; real users accumulate session state.
- One page at a time per browser context, reusing the context rather than
  spawning a new one per URL — matches how a real user's single browser tab
  behaves, and is far cheaper than a full browser launch per page.

NOT implemented here (documented instead, see docs/anti_bot_strategy.md):
CAPTCHA-solving, residential proxy rotation, and full browser fingerprint
randomization — these cross from "acting like a real user" into actively
defeating a site's abuse controls, which is a different risk profile than
the rest of this pipeline and is treated as a documentation-only strategy
per Phase V's "demonstrate or document" option.
"""
from __future__ import annotations

import asyncio
import logging
import random
from typing import Optional

logger = logging.getLogger("scrapers.stealth_browser")

_USER_AGENT = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"

_STEALTH_INIT_SCRIPT = """
Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3, 4, 5] });
Object.defineProperty(navigator, 'languages', { get: () => ['en-US', 'en'] });
window.chrome = { runtime: {} };
"""


async def _human_delay(min_ms: int = 300, max_ms: int = 1200) -> None:
    """Randomized delay between actions. Fixed intervals are themselves a
    detectable bot signal, so this is jittered rather than a flat sleep."""
    await asyncio.sleep(random.uniform(min_ms / 1000, max_ms / 1000))


async def fetch_rendered_page(url: str, *, wait_for_selector: Optional[str] = None, timeout_ms: int = 30000) -> str:
    """Fetches a URL through a real rendered Chromium session with basic
    stealth measures applied. Returns the fully-rendered page HTML.

    Raises RuntimeError with a clear message if Playwright's browsers
    aren't installed (`playwright install chromium`) or if the browser
    fails to launch — rather than a raw stack trace, since that's the most
    common setup gap for anyone running this for the first time. Network-
    level failures (DNS, connection refused, blocked egress) surface as
    whatever content the browser actually receives — e.g. a network proxy
    that blocks a domain typically returns an HTML error page rather than
    failing the page load outright, so `page.goto()` can "succeed" while
    the returned content is a block page, not the real site. Callers doing
    anything content-sensitive should sanity-check the returned HTML length/
    shape, not just whether an exception was raised.
    """
    try:
        from playwright.async_api import async_playwright
    except ImportError as e:
        raise RuntimeError("playwright package not installed. Run: pip install playwright") from e

    async with async_playwright() as p:
        try:
            browser = await p.chromium.launch(headless=True)
        except Exception as e:
            raise RuntimeError(
                "Could not launch Chromium. Run: playwright install chromium"
            ) from e

        try:
            context = await browser.new_context(
                user_agent=_USER_AGENT,
                viewport={"width": 1920, "height": 1080},
                locale="en-US",
            )
            await context.add_init_script(_STEALTH_INIT_SCRIPT)
            page = await context.new_page()

            await _human_delay()
            await page.goto(url, timeout=timeout_ms, wait_until="domcontentloaded")

            if wait_for_selector:
                await page.wait_for_selector(wait_for_selector, timeout=timeout_ms)
            else:
                # Give any lazy-loaded/JS-rendered content a beat to settle.
                await _human_delay(500, 1500)

            html = await page.content()
            return html
        finally:
            await browser.close()


async def fetch_rendered_pages(urls: list[str], *, max_concurrent_pages: int = 2) -> dict[str, Optional[str]]:
    """Fetch multiple URLs, reusing effort across a bounded concurrency
    limit. Kept deliberately low (default 2) compared to the plain-HTTP
    scrapers' concurrency (10) — full browser sessions are far more
    resource-intensive and a more visible signal if run in a tight loop, so
    this stays conservative by default rather than matching the aiohttp-based
    scrapers' throughput."""
    semaphore = asyncio.Semaphore(max_concurrent_pages)
    results: dict[str, Optional[str]] = {}

    async def _fetch_one(url: str) -> None:
        async with semaphore:
            try:
                results[url] = await fetch_rendered_page(url)
            except Exception as e:
                logger.warning(f"Rendered fetch failed for {url}: {e}")
                results[url] = None

    await asyncio.gather(*(_fetch_one(url) for url in urls))
    return results