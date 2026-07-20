"""
Exports all collected data to a Google Sheet with the 6 required tabs:
Startups, Products, Research Papers, Jobs, News, Entity Mapping Log.

Auth: uses a Google Cloud service account (not OAuth user login) — simplest
path for a script with no interactive browser step. See README for setup.

Each record type gets flattened from its nested JSON shape into flat
spreadsheet rows with a fixed column order matching (as closely as a flat
sheet can) the schema field tables in the assignment doc.
"""
from __future__ import annotations

import logging
from typing import Any, Optional

from src.db import fetch_records, get_conn

logger = logging.getLogger("export.sheets")


def _get(d: dict, path: str, default: Any = "") -> Any:
    """Dotted-path getter for nested dicts, e.g. _get(record, 'content.entityName')."""
    cur: Any = d
    for part in path.split("."):
        if not isinstance(cur, dict):
            return default
        cur = cur.get(part)
        if cur is None:
            return default
    return cur if cur is not None else default


# Each tab: (header row, function that takes a record dict and returns a row list)

def _startup_row(r: dict) -> list:
    return [
        _get(r, "schemaVersion"), _get(r, "recordType"),
        _get(r, "source.name"), _get(r, "source.url"),
        _get(r, "content.entityName"), _get(r, "content.data.employeeCount"),
        _get(r, "collectedAt"),
    ]


def _product_row(r: dict) -> list:
    return [
        _get(r, "schemaVersion"), _get(r, "recordType"),
        _get(r, "source.name"), _get(r, "source.url"),
        _get(r, "content.startupName"), _get(r, "content.pricingModel"),
        _get(r, "collectedAt"),
    ]


def _paper_row(r: dict) -> list:
    authors = _get(r, "content.authors", [])
    return [
        _get(r, "schemaVersion"), _get(r, "recordType"),
        _get(r, "source.name"), _get(r, "source.url"),
        _get(r, "content.title"),
        ", ".join(authors) if isinstance(authors, list) else authors,
        _get(r, "content.paper_url"), _get(r, "content.github_url"),
        _get(r, "content.github_stars"), _get(r, "content.published_date"),
        _get(r, "collectedAt"),
    ]


def _job_row(r: dict) -> list:
    return [
        _get(r, "schemaVersion"), _get(r, "recordType"),
        _get(r, "source.name"), _get(r, "source.url"),
        _get(r, "content.company"), _get(r, "content.date"),
        _get(r, "content.is_remote"), _get(r, "content.role_family"),
        _get(r, "collectedAt"),
    ]


def _news_row(r: dict) -> list:
    full_text = _get(r, "content.fullText", "") or ""
    # Sheets cells have a practical size limit; truncate very long article
    # bodies rather than risk a write failure on a single oversized cell.
    truncated = full_text[:5000] + ("... [truncated]" if len(full_text) > 5000 else "")
    return [
        _get(r, "schemaVersion"), _get(r, "recordType"),
        _get(r, "source.name"), _get(r, "source.url"),
        _get(r, "content.title"), _get(r, "content.publishedDate"),
        truncated, _get(r, "collectedAt"),
    ]


TAB_CONFIG = {
    "Startups": (
        ["schemaVersion", "recordType", "source.name", "source.url", "entityName", "employeeCount", "collectedAt"],
        "STARTUP", _startup_row,
    ),
    "Products": (
        ["schemaVersion", "recordType", "source.name", "source.url", "startupName", "pricingModel", "collectedAt"],
        "PRODUCT", _product_row,
    ),
    "Research Papers": (
        ["schemaVersion", "recordType", "source.name", "source.url", "title", "authors", "paper_url", "github_url", "github_stars", "published_date", "collectedAt"],
        "RESEARCH_PAPER", _paper_row,
    ),
    "Jobs": (
        ["schemaVersion", "recordType", "source.name", "source.url", "company", "date", "is_remote", "role_family", "collectedAt"],
        "JOB", _job_row,
    ),
    "News": (
        ["schemaVersion", "recordType", "source.name", "source.url", "title", "publishedDate", "fullText", "collectedAt"],
        "NEWS", _news_row,
    ),
}

ENTITY_LOG_HEADER = ["raw_name", "canonical_name", "confidence"]


def _fetch_entity_mapping_rows() -> list[list]:
    with get_conn() as conn:
        rows = conn.execute("SELECT raw_name, canonical_name, confidence FROM entity_mapping_log").fetchall()
    return [list(row) for row in rows]


def export_to_sheet(creds_path: str, sheet_key: Optional[str] = None, sheet_title: str = "AI Signal Trial Output") -> str:
    """Writes all 6 tabs to a Google Sheet. If sheet_key is given, opens that
    existing sheet (must already be shared with the service account's
    email — see README); otherwise creates a new sheet titled sheet_title.
    Returns the sheet's URL.
    """
    import gspread

    gc = gspread.service_account(filename=creds_path)

    if sheet_key:
        sh = gc.open_by_key(sheet_key)
        logger.info(f"Opened existing sheet: {sh.title}")
    else:
        sh = gc.create(sheet_title)
        logger.info(f"Created new sheet: {sh.title}")

    for tab_name, (header, record_type, row_fn) in TAB_CONFIG.items():
        records = fetch_records(record_type)
        rows = [row_fn(r) for r in records]
        _write_tab(sh, tab_name, header, rows)
        logger.info(f"{tab_name}: wrote {len(rows)} rows")

    mapping_rows = _fetch_entity_mapping_rows()
    _write_tab(sh, "Entity Mapping Log", ENTITY_LOG_HEADER, mapping_rows)
    logger.info(f"Entity Mapping Log: wrote {len(mapping_rows)} rows")

    return sh.url


def _write_tab(sh, tab_name: str, header: list, rows: list[list]) -> None:
    try:
        ws = sh.worksheet(tab_name)
        ws.clear()
    except Exception:
        ws = sh.add_worksheet(title=tab_name, rows=max(len(rows) + 10, 100), cols=max(len(header) + 2, 10))

    if rows:
        ws.update([header] + rows, value_input_option="RAW")
    else:
        ws.update([header], value_input_option="RAW")