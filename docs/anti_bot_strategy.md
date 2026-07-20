# Anti-Bot & Scale Strategy

## What this pipeline actually hit, and what fixed it

Rather than write this section in the abstract, here's what genuinely broke
during this project and what the fix was — these are real incidents, not
hypotheticals:

**GitHub API returned 403 with no explanation.** Cause: no `User-Agent`
header. GitHub's API (and most APIs behind any bot-detection layer) reject
requests with a missing or default-library User-Agent (`Python/3.x
aiohttp/3.x`) regardless of rate. Fix: every outbound request in this
pipeline sends a realistic desktop browser User-Agent
(`src/http_client.py`, `src/scrapers/*.py`).

**Hugging Face's Papers API returned persistent 429s even at a
throttled 1 request/second.** This looked like a rate limit but was
actually the same missing-User-Agent problem — Cloudflare-fronted services
often bot-fingerprint on headers before they even get to counting request
rate. Confirmed via a direct `curl` test with proper headers, which
returned a clean `404` (not 429) and revealed the *actual* documented rate
limit in the response headers (`RateLimit-Policy: "api";q=500;w=300`).
Lesson generalized into policy: **fix headers before assuming you need to
slow down further.** A 429 doesn't always mean "too fast" — it sometimes
means "identifiable as a script."

**A planned data source (Papers with Code) turned out to be fully
shut down** (Meta discontinued it in July 2025), returning what looked
like rate-limit errors but was actually a dead/redirected API. This is why
the fallback-chain design in Phase III and the per-source resilience
pattern in the jobs pipeline (Phase II) matter beyond their nominal
purpose: a source can disappear entirely, and the architecture should
absorb that as a one-file swap, not a rewrite.

**Job board ATS platforms were not reliably guessable per company.**
OpenAI turned out to be on Ashby, not Greenhouse (the default assumption);
Hugging Face turned out to be on a fourth platform (Workable) not
implemented here at all. Fix: `src/scrapers/jobs.py` tries each company
across an ordered list of (platform, token) candidates and uses whichever
responds — the same "resilient by design, not by guessing right the first
time" principle as the LLM fallback chain.

## General strategy for Cloudflare/Datadome-class protection

For sources that go beyond header/rate-limit checks into full
JavaScript-challenge or behavioral bot detection:

1. **Prefer a structured API over the protected page entirely.** Every
   scraper in this pipeline (Arxiv, GitHub, Hugging Face, YC, Product Hunt,
   Greenhouse/Lever/Ashby, RSS feeds) uses this path. It's not a fallback —
   it's the default, because it sidesteps anti-bot risk structurally rather
   than trying to defeat it. This is the single highest-leverage decision
   in the whole architecture.

2. **When no API exists, render with a real browser, not a raw HTTP
   client.** `src/scrapers/stealth_browser.py` implements this via
   Playwright's async Chromium: a genuine browser engine executes the
   site's JS challenge the same way a real visitor's browser would, rather
   than trying to fake the *result* of that challenge. Verified live in
   this project: `navigator.webdriver` (the single most commonly checked
   bot flag) correctly reports `undefined` instead of Playwright's default
   `true`, via a page-init script that runs before the target site's own
   JS.

3. **Behave like one continuous user, not N independent requests.**
   A fresh, cookie-less connection on every single request is itself a
   signal. `stealth_browser.py` reuses one browser context (carrying
   cookies/session state) across a run rather than spinning up an isolated
   context per URL, and randomizes inter-action delays rather than hitting
   a page on a fixed interval — a bot-detection script watching for
   "requests every exactly 500ms" is extremely common.

4. **Keep browser-based concurrency low relative to plain-HTTP
   concurrency.** This project's aiohttp-based scrapers run at up to 10
   concurrent requests; the browser-based fetcher defaults to 2. A full
   rendered browser session is both far more resource-intensive and a much
   louder signal if run in a tight loop than a plain GET request — matching
   the concurrency profile of the cheap path to the expensive path isn't a
   like-for-like trade.

5. **Residential proxy rotation and CAPTCHA-solving are documented,
   not implemented, here.** Both are real, commonly used techniques for
   sources that actively fingerprint and block at scale — but they cross
   from "presenting as a normal browser" into "defeating an explicit abuse
   control," which is a meaningfully different risk/legal posture than the
   rest of this pipeline (which deliberately routes around anti-bot systems
   via legitimate APIs wherever one exists). For a production system that
   genuinely needed this, the standard approach is a residential/mobile
   proxy pool with per-request IP rotation, paired with a third-party
   CAPTCHA-solving service triggered only when a challenge is actually
   detected in the response (not on a schedule) to avoid the cost and
   latency of solving challenges that would never have appeared.

## Why this matters for the 500k-scale story

The header/rate-limit incidents above all happened at **1,000 records**,
not 500,000. At 500x the volume, header/UA mistakes would have looked like
outright source failures rather than isolated warnings, and an unresolved
ATS-guessing mistake would have silently produced zero data from an entire
company rather than a visible 404 log line. The fixes made here — real
User-Agents everywhere, per-host throttling calibrated to each source's
actual documented limits (not a guess), and resilient multi-candidate
fallback for sources with more than one possible identity — are exactly
the differences between a pipeline that degrades gracefully at scale and
one that silently produces incomplete data at scale.