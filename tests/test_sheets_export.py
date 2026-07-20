from src.export.sheets_export import _get, _job_row, _news_row, _paper_row, _product_row, _startup_row


def test_get_helper_handles_nested_and_missing_paths():
    d = {"content": {"entityName": "OpenAI", "data": {"employeeCount": 500}}}
    assert _get(d, "content.entityName") == "OpenAI"
    assert _get(d, "content.data.employeeCount") == 500
    assert _get(d, "content.data.missing", "N/A") == "N/A"
    assert _get(d, "nonexistent", "DEFAULT") == "DEFAULT"


def test_startup_row_shape():
    record = {
        "schemaVersion": "1.0", "recordType": "STARTUP",
        "source": {"name": "YC", "url": "https://yc.com/x"},
        "content": {"entityName": "OpenAI", "data": {"employeeCount": 500}},
        "collectedAt": "2026-01-01",
    }
    row = _startup_row(record)
    assert row == ["1.0", "STARTUP", "YC", "https://yc.com/x", "OpenAI", 500, "2026-01-01"]


def test_product_row_shape():
    record = {
        "schemaVersion": "1.0", "recordType": "PRODUCT",
        "source": {"name": "PH", "url": "https://ph.com/x"},
        "content": {"startupName": "Jane", "pricingModel": "FREE"},
        "collectedAt": "2026-01-01",
    }
    row = _product_row(record)
    assert row == ["1.0", "PRODUCT", "PH", "https://ph.com/x", "Jane", "FREE", "2026-01-01"]


def test_paper_row_joins_authors_and_handles_null_github_fields():
    record = {
        "schemaVersion": "1.0", "recordType": "RESEARCH_PAPER",
        "source": {"name": "Arxiv", "url": "https://arxiv.org/x"},
        "content": {
            "title": "Test Paper", "authors": ["Alice", "Bob"],
            "paper_url": "https://arxiv.org/x", "github_url": None,
            "github_stars": None, "published_date": "2026-01-01",
        },
        "collectedAt": "2026-01-01",
    }
    row = _paper_row(record)
    assert row[5] == "Alice, Bob"  # authors joined
    assert row[7] == ""  # None github_url becomes empty string, not "None"
    assert row[8] == ""  # None github_stars becomes empty string


def test_job_row_shape():
    record = {
        "schemaVersion": "1.0", "recordType": "JOB",
        "source": {"name": "OpenAI", "url": "https://x.com"},
        "content": {"company": "OpenAI", "date": "2026-01-01", "is_remote": True, "role_family": "Engineering"},
        "collectedAt": "2026-01-01",
    }
    row = _job_row(record)
    assert row == ["1.0", "JOB", "OpenAI", "https://x.com", "OpenAI", "2026-01-01", True, "Engineering", "2026-01-01"]


def test_news_row_truncates_long_full_text():
    record = {
        "schemaVersion": "1.0", "recordType": "NEWS",
        "source": {"name": "TC", "url": "https://tc.com/x"},
        "content": {"title": "AI News", "publishedDate": "2026-01-01", "fullText": "A" * 6000},
        "collectedAt": "2026-01-01",
    }
    row = _news_row(record)
    full_text_col = row[6]
    assert len(full_text_col) < 6000
    assert full_text_col.endswith("[truncated]")


def test_news_row_short_text_not_truncated():
    record = {
        "schemaVersion": "1.0", "recordType": "NEWS",
        "source": {"name": "TC", "url": "https://tc.com/x"},
        "content": {"title": "AI News", "publishedDate": "2026-01-01", "fullText": "Short text."},
        "collectedAt": "2026-01-01",
    }
    row = _news_row(record)
    assert row[6] == "Short text."
