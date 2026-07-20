"""
Jobs pipeline: 5 AI-company job boards via Greenhouse/Lever/Ashby's public
JSON APIs rather than scraping HTML.

Design choice: most companies host job listings on one of these three ATS
platforms, all of which expose clean, unauthenticated, structured JSON —
including real timestamps, sidestepping the "extract and normalize relative
dates" problem entirely for these particular sources.

Resilience choice: we don't hardcode which single platform each company
uses, because that's genuinely easy to get wrong (companies migrate ATS
platforms, e.g. OpenAI uses Ashby, not Greenhouse, despite Greenhouse being
the most common default guess). Instead, each company has a ranked list of
(platform, token) candidates and we try them in order, using whichever
responds first. This is also just a more resilient production pattern in
general — the same shape you'd want when a source could change out from
under you between runs.
"""
from __future__ import annotations

import logging
import re
from datetime import datetime, timezone
from typing import Optional

import aiohttp

from src.db import is_seen, mark_seen, save_record
from src.freshness import is_within_freshness_window, normalize_date
from src.http_client import ClientHTTPError, fetch_json
from src.schemas import JobContent, JobEntity, Source

logger = logging.getLogger("scrapers.jobs")

# Each company maps to an ORDERED list of (platform, token) candidates.
# We try each in turn and use the first one that responds successfully.
COMPANY_CANDIDATES: dict[str, list[tuple[str, str]]] = {
    "OpenAI": [("ashby", "openai"), ("greenhouse", "openai")],
    "ElevenLabs": [("ashby", "elevenlabs"), ("greenhouse", "elevenlabs"), ("lever", "elevenlabs")],
    "Anthropic": [("greenhouse", "anthropic")],  # confirmed working
    "Scale AI": [("greenhouse", "scaleai"), ("lever", "scaleai"), ("greenhouse", "scale-ai"), ("lever", "scale-ai")],
    "Cohere": [("lever", "cohere"), ("greenhouse", "cohere"), ("ashby", "cohere")],
}
# Note: Hugging Face was considered but actually hosts its careers page on
# Workable (apply.workable.com/huggingface), a 4th ATS not implemented here
# — confirmed via web search after all 3 supported platforms 404'd for it.
# Swapped for ElevenLabs (confirmed on Ashby) rather than adding a fourth ATS
# integration for a single company.

_HEADERS = {
    "Accept": "application/json",
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
}

_REMOTE_PATTERN = re.compile(r"\bremote\b", re.IGNORECASE)


def _infer_role_family(title: str) -> Optional[str]:
    title_lower = (title or "").lower()
    mapping = [
        (("engineer", "developer", "swe"), "Engineering"),
        (("research", "scientist"), "Research"),
        (("product manager", "pm "), "Product"),
        (("sales", "account executive"), "Sales"),
        (("marketing", "growth"), "Marketing"),
        (("design",), "Design"),
        (("recruit", "people", "hr "), "People"),
        (("legal", "counsel"), "Legal"),
        (("finance", "accounting"), "Finance"),
    ]
    for keywords, family in mapping:
        if any(k in title_lower for k in keywords):
            return family
    return None


def _make_entity(company: str, platform: str, job_url: str, published_dt, title: str, location_name: str) -> JobEntity:
    return JobEntity(
        source=Source(name=f"{company} ({platform.title()})", url=job_url),
        content=JobContent(
            company=company,
            date=published_dt.isoformat(),
            is_remote=bool(_REMOTE_PATTERN.search(location_name)) if location_name else None,
            role_family=_infer_role_family(title),
        ),
    )


async def _process_greenhouse_job(company: str, job: dict, now: datetime) -> Optional[JobEntity]:
    job_url = job.get("absolute_url")
    if not job_url or is_seen(job_url):
        return None
    published_dt = normalize_date(job.get("updated_at"), now=now)
    if published_dt is None or not is_within_freshness_window(published_dt, now=now):
        mark_seen(job_url, "JOB")
        return None
    location_name = (job.get("location") or {}).get("name", "")
    entity = _make_entity(company, "greenhouse", job_url, published_dt, job.get("title", ""), location_name)
    mark_seen(job_url, "JOB")
    save_record("JOB", entity.model_dump(mode="json"))
    return entity


async def _process_lever_job(company: str, job: dict, now: datetime) -> Optional[JobEntity]:
    job_url = job.get("hostedUrl")
    if not job_url or is_seen(job_url):
        return None
    created_at_ms = job.get("createdAt")
    published_dt = datetime.fromtimestamp(created_at_ms / 1000, tz=timezone.utc) if created_at_ms else None
    if published_dt is None or not is_within_freshness_window(published_dt, now=now):
        mark_seen(job_url, "JOB")
        return None
    categories = job.get("categories", {}) or {}
    location_name = categories.get("location", "") or ""
    entity = _make_entity(company, "lever", job_url, published_dt, job.get("text", ""), location_name)
    mark_seen(job_url, "JOB")
    save_record("JOB", entity.model_dump(mode="json"))
    return entity


async def _process_ashby_job(company: str, job: dict, now: datetime) -> Optional[JobEntity]:
    job_url = job.get("jobUrl") or job.get("applyUrl")
    if not job_url or is_seen(job_url):
        return None
    published_dt = normalize_date(job.get("publishedAt"), now=now)
    if published_dt is None or not is_within_freshness_window(published_dt, now=now):
        mark_seen(job_url, "JOB")
        return None
    location_name = job.get("location", "") or ""
    is_remote_flag = job.get("isRemote")
    entity = JobEntity(
        source=Source(name=f"{company} (Ashby)", url=job_url),
        content=JobContent(
            company=company,
            date=published_dt.isoformat(),
            is_remote=bool(is_remote_flag) if is_remote_flag is not None else (bool(_REMOTE_PATTERN.search(location_name)) if location_name else None),
            role_family=_infer_role_family(job.get("title", "")),
        ),
    )
    mark_seen(job_url, "JOB")
    save_record("JOB", entity.model_dump(mode="json"))
    return entity


async def _try_fetch_board(session: aiohttp.ClientSession, platform: str, token: str) -> Optional[list[dict]]:
    """Returns the raw job list for one (platform, token) candidate, or None
    if that candidate doesn't exist (404) — a 404 here means 'wrong slug',
    not a failure, so callers move on to the next candidate silently."""
    try:
        if platform == "greenhouse":
            data = await fetch_json(session, f"https://boards-api.greenhouse.io/v1/boards/{token}/jobs", headers=_HEADERS)
            return data.get("jobs", [])
        elif platform == "lever":
            data = await fetch_json(session, f"https://api.lever.co/v0/postings/{token}?mode=json", headers=_HEADERS)
            return data if isinstance(data, list) else None
        elif platform == "ashby":
            data = await fetch_json(session, f"https://api.ashbyhq.com/posting-api/job-board/{token}", headers=_HEADERS)
            return data.get("jobs", [])
    except ClientHTTPError as e:
        logger.info(f"{platform}:{token} not found ({e}) — trying next candidate")
        return None
    except Exception as e:
        logger.warning(f"{platform}:{token} failed unexpectedly: {e}")
        return None
    return None


_PROCESSORS = {
    "greenhouse": _process_greenhouse_job,
    "lever": _process_lever_job,
    "ashby": _process_ashby_job,
}


async def run_jobs_pipeline() -> int:
    """Entry point. Returns the number of new fresh records saved.
    Like news, there's no target_count — Phase II asks for 'all 24-hr fresh
    jobs found', so most runs will legitimately save very few or zero
    records (established companies don't post new roles every day). A near-
    empty Jobs tab is an honest, correct result, not a bug.
    """
    now = datetime.now(timezone.utc)
    saved = 0

    async with aiohttp.ClientSession() as session:
        for company, candidates in COMPANY_CANDIDATES.items():
            jobs = None
            matched_platform = None
            for platform, token in candidates:
                jobs = await _try_fetch_board(session, platform, token)
                if jobs is not None:
                    matched_platform = platform
                    break

            if jobs is None:
                logger.warning(f"No working board found for {company} after trying {len(candidates)} candidate(s)")
                continue

            logger.info(f"{company} ({matched_platform}): {len(jobs)} total listings")
            processor = _PROCESSORS[matched_platform]
            for job in jobs:
                entity = await processor(company, job, now)
                if entity is not None:
                    saved += 1

    return saved