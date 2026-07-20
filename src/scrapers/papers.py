"""
Research paper pipeline: Arxiv (metadata) -> GitHub (stars, if a repo is linked).

Design choice: we use Arxiv's own API (no scraping needed, no anti-bot risk)
for title/authors/date/url — genuinely legit, structured source data.

Papers with Code (the original plan for GitHub linkage) was shut down by Meta
in July 2025 and its domain now redirects elsewhere — its API is dead, not
just rate-limited, so we don't use it. Hugging Face's Papers API
(huggingface.co/api/papers/{arxiv_id}) is the closest live successor and
explicitly surfaces linked GitHub repos, so we use that instead. We parse it
defensively (regex-scan the raw response for any github.com URL) rather than
betting on one exact field name, since the endpoint isn't officially
documented and its schema could shift.
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
from typing import Optional

import aiohttp
import arxiv

from src.db import is_seen, mark_seen, save_record
from src.http_client import fetch_json
from src.schemas import ResearchPaperContent, ResearchPaperEntity, Source

logger = logging.getLogger("scrapers.papers")

GITHUB_API = "https://api.github.com"
HF_PAPERS_API = "https://huggingface.co/api/papers/"


def _extract_github_url_from_text(text: str) -> Optional[str]:
    """Cheap heuristic fallback: look for a github.com link in raw text
    (an abstract, comments field, or an API response blob)."""
    match = re.search(r"https?://github\.com/[\w\-]+/[\w\-.]+", text or "")
    return match.group(0).rstrip(".,)\"'") if match else None


def _parse_owner_repo(github_url: str) -> Optional[tuple[str, str]]:
    match = re.search(r"github\.com/([\w\-]+)/([\w\-.]+)", github_url)
    if not match:
        return None
    owner, repo = match.groups()
    return owner, repo.removesuffix(".git")


def _arxiv_short_id(entry_id: str) -> str:
    """'http://arxiv.org/abs/2607.14585v1' -> '2607.14585' (versionless id,
    what most external indexes key on)."""
    tail = entry_id.rstrip("/").rsplit("/", 1)[-1]
    return re.sub(r"v\d+$", "", tail)


async def _fetch_hf_github_url(session: aiohttp.ClientSession, entry_id: str) -> Optional[str]:
    """Look up the paper on Hugging Face by Arxiv id. Returns None (not an
    error) if the paper simply isn't indexed there — HF only indexes a
    fraction of all Arxiv papers (submitted/trending ones), so plenty of
    misses are expected, not a bug."""
    arxiv_id = _arxiv_short_id(entry_id)
    headers = {
        "Accept": "application/json",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
    }
    try:
        data = await fetch_json(session, f"{HF_PAPERS_API}{arxiv_id}", headers=headers)
    except Exception as e:
        logger.info(f"HF papers lookup failed for {arxiv_id}: {e}")
        return None

    # Scan the whole payload for a github.com link rather than trusting one
    # specific field name — robust against undocumented/shifting schema.
    return _extract_github_url_from_text(json.dumps(data))


async def _get_github_stars(session: aiohttp.ClientSession, github_url: str, github_token: Optional[str]) -> Optional[int]:
    parsed = _parse_owner_repo(github_url)
    if not parsed:
        return None
    owner, repo = parsed
    headers = {"Accept": "application/vnd.github+json", "User-Agent": "ai-signal-trial-pipeline"}
    if github_token:
        headers["Authorization"] = f"Bearer {github_token}"
    try:
        data = await fetch_json(session, f"{GITHUB_API}/repos/{owner}/{repo}", headers=headers)
        return data.get("stargazers_count")
    except Exception as e:
        logger.info(f"Could not fetch stars for {owner}/{repo}: {e}")
        return None


async def fetch_arxiv_papers(query: str, max_results: int) -> list[arxiv.Result]:
    """Arxiv's client is sync under the hood; run it in a thread so it doesn't
    block the asyncio event loop."""
    def _search():
        client = arxiv.Client(page_size=100, delay_seconds=3, num_retries=3)
        search = arxiv.Search(
            query=query,
            max_results=max_results,
            sort_by=arxiv.SortCriterion.SubmittedDate,
        )
        return list(client.results(search))

    return await asyncio.to_thread(_search)


async def process_paper(
    session: aiohttp.ClientSession,
    result: arxiv.Result,
    github_token: Optional[str],
) -> Optional[ResearchPaperEntity]:
    paper_url = result.entry_id
    if is_seen(paper_url):
        return None

    github_url = await _fetch_hf_github_url(session, paper_url)
    if not github_url:
        # Not indexed on HF — fall back to scanning the abstract/comments
        # text before giving up entirely.
        github_url = _extract_github_url_from_text(result.comment or "") or _extract_github_url_from_text(result.summary or "")

    stars = None
    if github_url:
        stars = await _get_github_stars(session, github_url, github_token)

    entity = ResearchPaperEntity(
        source=Source(name="Arxiv", url=paper_url),
        content=ResearchPaperContent(
            title=result.title.strip(),
            authors=[a.name for a in result.authors],
            paper_url=paper_url,
            github_url=github_url,
            github_stars=stars,
            published_date=result.published.isoformat() if result.published else None,
        ),
    )
    mark_seen(paper_url, "RESEARCH_PAPER")
    save_record("RESEARCH_PAPER", entity.model_dump(mode="json"))
    return entity


async def run_papers_pipeline(
    query: str = "cat:cs.AI",
    target_count: int = 1000,
    github_token: Optional[str] = None,
) -> int:
    """Entry point. Returns the number of new records saved.
    To scale toward 500k: raise target_count and/or shard `query` across
    multiple arxiv categories run as separate worker processes — no code
    change needed beyond the query string per worker.
    """
    results = await fetch_arxiv_papers(query, target_count)
    logger.info(f"Fetched {len(results)} candidate papers from Arxiv for query={query!r}")

    saved = 0
    async with aiohttp.ClientSession() as session:
        tasks = [process_paper(session, r, github_token) for r in results]
        for coro in asyncio.as_completed(tasks):
            entity = await coro
            if entity is not None:
                saved += 1
    return saved