from datetime import datetime, timedelta, timezone

import pytest

from src.scrapers.jobs import _infer_role_family, _process_ashby_job, _process_greenhouse_job, _process_lever_job

NOW = datetime(2026, 7, 19, 12, 0, 0, tzinfo=timezone.utc)


@pytest.mark.asyncio
async def test_fresh_greenhouse_job_kept():
    fresh_time = (NOW - timedelta(hours=5)).strftime("%Y-%m-%dT%H:%M:%SZ")
    job = {"absolute_url": "https://example.com/jobs/123", "updated_at": fresh_time, "title": "Senior Software Engineer", "location": {"name": "Remote"}}
    entity = await _process_greenhouse_job("TestCo", job, NOW)
    assert entity is not None
    assert entity.content.is_remote is True
    assert entity.content.role_family == "Engineering"


@pytest.mark.asyncio
async def test_stale_greenhouse_job_dropped():
    stale_time = (NOW - timedelta(days=5)).strftime("%Y-%m-%dT%H:%M:%SZ")
    job = {"absolute_url": "https://example.com/jobs/456", "updated_at": stale_time, "title": "Old Job"}
    entity = await _process_greenhouse_job("TestCo", job, NOW)
    assert entity is None


@pytest.mark.asyncio
async def test_fresh_lever_job_with_epoch_millis_kept():
    fresh_ms = int((NOW - timedelta(hours=3)).timestamp() * 1000)
    job = {"hostedUrl": "https://jobs.lever.co/test/abc", "createdAt": fresh_ms, "text": "AI Research Scientist", "categories": {"location": "San Francisco (Remote)"}}
    entity = await _process_lever_job("TestCo", job, NOW)
    assert entity is not None
    assert entity.content.role_family == "Research"


@pytest.mark.asyncio
async def test_fresh_ashby_job_kept():
    job = {"jobUrl": "https://jobs.ashbyhq.com/openai/abc", "publishedAt": (NOW - timedelta(hours=4)).isoformat(), "title": "Research Engineer", "isRemote": True}
    entity = await _process_ashby_job("OpenAI", job, NOW)
    assert entity is not None
    assert entity.content.is_remote is True


@pytest.mark.parametrize("title,expected", [
    ("Senior Software Engineer", "Engineering"),
    ("AI Research Scientist", "Research"),
    ("Head of Sales", "Sales"),
    ("Something Unusual Nobody Would Guess", None),
])
def test_role_family_inference(title, expected):
    assert _infer_role_family(title) == expected
