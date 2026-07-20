import pytest

from src.scrapers.startups import _prominence_sort_key, process_company


def test_top_companies_sort_before_non_top():
    companies = [
        {"name": "Obscure Co", "top_company": False, "team_size": 500},
        {"name": "Famous Co", "top_company": True, "team_size": 5},
    ]
    result = sorted(companies, key=_prominence_sort_key)
    assert result[0]["name"] == "Famous Co"  # top_company wins even with a tiny team


def test_within_same_tier_sorts_by_team_size_descending():
    companies = [
        {"name": "Small", "top_company": True, "team_size": 5},
        {"name": "Big", "top_company": True, "team_size": 500},
    ]
    result = sorted(companies, key=_prominence_sort_key)
    assert result[0]["name"] == "Big"


def test_missing_fields_do_not_crash_sort():
    companies = [{"name": "No Fields At All"}, {"name": "Has Fields", "top_company": True, "team_size": 10}]
    result = sorted(companies, key=_prominence_sort_key)
    assert result[0]["name"] == "Has Fields"


@pytest.mark.asyncio
async def test_process_company_maps_fields_correctly():
    company = {"name": "OpenAI", "slug": "openai", "team_size": 500}
    entity = await process_company(company)
    assert entity.content.entityName == "OpenAI"
    assert entity.content.data.employeeCount == 500
    assert str(entity.source.url) == "https://www.ycombinator.com/companies/openai"


@pytest.mark.asyncio
async def test_process_company_skips_missing_name():
    company = {"slug": "no-name-co"}
    entity = await process_company(company)
    assert entity is None