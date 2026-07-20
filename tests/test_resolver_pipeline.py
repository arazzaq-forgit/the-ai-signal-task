from src.db import get_conn, save_record
from src.resolver.pipeline import run_entity_resolution


def test_resolution_pipeline_processes_startups_and_products():
    save_record("STARTUP", {"content": {"entityName": "OpenAI"}})
    save_record("STARTUP", {"content": {"entityName": "OpenAI, Inc."}})
    save_record("STARTUP", {"content": {"entityName": "Some Random Startup Inc"}})
    save_record("PRODUCT", {"content": {"startupName": "Scale.ai"}})

    counts = run_entity_resolution()

    assert counts["exact_canonical"] + counts["exact_alias"] >= 2  # both OpenAI variants + Scale.ai
    assert counts["no_match"] >= 1  # the random startup

    with get_conn() as conn:
        rows = conn.execute("SELECT raw_name, canonical_name FROM entity_mapping_log").fetchall()
    mapped = dict(rows)
    assert mapped["OpenAI"] == "OpenAI"
    assert mapped["OpenAI, Inc."] == "OpenAI"
    assert mapped["Scale.ai"] == "Scale AI"


def test_resolution_pipeline_skips_records_with_no_name():
    save_record("STARTUP", {"content": {}})  # no entityName at all
    counts = run_entity_resolution()
    assert sum(counts.values()) == 0
