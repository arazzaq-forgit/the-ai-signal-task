from src.db import (
    count_records, fetch_records, is_seen, mark_seen, save_mapping, save_record,
)


def test_url_not_seen_initially():
    assert is_seen("https://example.com/never-seen") is False


def test_mark_seen_makes_url_seen():
    url = "https://example.com/article"
    assert is_seen(url) is False
    mark_seen(url, "NEWS")
    assert is_seen(url) is True


def test_mark_seen_is_idempotent():
    url = "https://example.com/article"
    mark_seen(url, "NEWS")
    mark_seen(url, "NEWS")  # should not raise or duplicate
    assert is_seen(url) is True


def test_save_and_fetch_records():
    save_record("STARTUP", {"content": {"entityName": "OpenAI"}})
    save_record("STARTUP", {"content": {"entityName": "Anthropic"}})
    records = fetch_records("STARTUP")
    assert len(records) == 2
    names = {r["content"]["entityName"] for r in records}
    assert names == {"OpenAI", "Anthropic"}


def test_fetch_records_filters_by_type():
    save_record("STARTUP", {"content": {"entityName": "X"}})
    save_record("PRODUCT", {"content": {"startupName": "Y"}})
    assert len(fetch_records("STARTUP")) == 1
    assert len(fetch_records("PRODUCT")) == 1


def test_count_records():
    assert count_records("STARTUP") == 0
    save_record("STARTUP", {"content": {"entityName": "X"}})
    assert count_records("STARTUP") == 1


def test_save_mapping_logs_entity_resolution():
    save_mapping("OpenAI, Inc.", "OpenAI", 1.0)
    save_mapping("Random Co", "Random Co", 0.0)
    # save_mapping doesn't have a dedicated fetch helper in db.py, so we
    # verify indirectly via the resolver pipeline tests instead — this test
    # just confirms it doesn't raise for both matched and unmatched cases.
