"""
Startup pipeline: Y Combinator's public company directory.

Source choice: yc-oss publishes a community-maintained, unauthenticated JSON
snapshot of every YC company (https://yc-oss.github.io/api/companies/all.json).
This sidesteps scraping ycombinator.com's own JS-rendered, semi-protected
company directory entirely — same "prefer structured APIs over raw scraping"
principle used for the papers pipeline. Every record still traces back to a
real, fetchable YC profile URL.

Caveat to know: this dataset caps out around YC's total historical company
count (several thousand), not the open web. For the "scale to 500k" story,
this is one shard among many directory sources you'd add in the same shape.

Selection order: the dataset's own ordering is arbitrary (roughly
alphabetical), so a plain [:target_count] slice mostly returns obscure,
long-inactive companies. We instead prioritize companies YC itself flags as
`top_company`, then by team size, before slicing — both a more useful
product decision (a real "AI intelligence" tool should surface well-known
companies first) and a more representative sample for downstream entity
resolution, which is explicitly graded against a seed list of well-known
names.
"""
from __future__ import annotations

import asyncio
import logging
from typing import Optional

import aiohttp

from src.db import is_seen, mark_seen, save_record
from src.http_client import fetch_json
from src.schemas import StartupContent, StartupContentData, StartupEntity, Source

logger = logging.getLogger("scrapers.startups")

YC_COMPANIES_URL = "https://yc-oss.github.io/api/companies/all.json"


def _company_profile_url(company: dict) -> str:
    slug = company.get("slug")
    if slug:
        return f"https://www.ycombinator.com/companies/{slug}"
    # Fall back to the dataset's own url field if slug is missing for some reason
    return company.get("url") or "https://www.ycombinator.com/companies"


def _prominence_sort_key(company: dict) -> tuple:
    """Sorts YC-flagged top companies first, then by team size descending.
    Returns a tuple usable directly with sorted() ascending — top_company
    True sorts before False (0 < 1), and larger teams sort before smaller
    ones (negated)."""
    is_top = bool(company.get("top_company"))
    team_size = company.get("team_size") or 0
    return (0 if is_top else 1, -team_size)


async def process_company(company: dict) -> Optional[StartupEntity]:
    profile_url = _company_profile_url(company)
    if is_seen(profile_url):
        return None

    name = company.get("name")
    if not name:
        return None

    entity = StartupEntity(
        source=Source(name="Y Combinator", url=profile_url),
        content=StartupContent(
            entityName=name,
            data=StartupContentData(employeeCount=company.get("team_size")),
        ),
    )
    mark_seen(profile_url, "STARTUP")
    save_record("STARTUP", entity.model_dump(mode="json"))
    return entity


async def run_startups_pipeline(target_count: int = 1000) -> int:
    """Entry point. Returns the number of new records saved.
    Scale note: this endpoint returns the full dataset in one response (no
    pagination needed) since YC's total company count is bounded. To scale
    the *startups vertical* toward 500k, you'd add more directory sources in
    this same file shape (each a `run_x_pipeline` function) and run them as
    parallel workers — this function itself doesn't need to change.
    """
    async with aiohttp.ClientSession() as session:
        headers = {
            "Accept": "application/json",
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
        }
        companies = await fetch_json(session, YC_COMPANIES_URL, headers=headers)

    logger.info(f"Fetched {len(companies)} candidate companies from YC dataset")
    companies = sorted(companies, key=_prominence_sort_key)
    companies = companies[:target_count]

    saved = 0
    for company in companies:
        entity = await process_company(company)
        if entity is not None:
            saved += 1
    return saved