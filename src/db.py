"""
Lightweight state store. Two jobs:
1. Dedup — never process the same source URL twice (across runs or nodes,
   if you swap this for Postgres/Redis later; the interface stays the same).
2. Output — append validated records so a crash mid-run doesn't lose work.
"""
from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Optional


DB_PATH = Path(__file__).resolve().parent.parent / "data" / "state.db"


SCHEMA = """
CREATE TABLE IF NOT EXISTS seen_urls (
    url TEXT PRIMARY KEY,
    record_type TEXT NOT NULL,
    first_seen_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS records (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    record_type TEXT NOT NULL,
    payload TEXT NOT NULL,
    inserted_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS entity_mapping_log (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    raw_name TEXT NOT NULL,
    canonical_name TEXT NOT NULL,
    confidence REAL,
    inserted_at TEXT NOT NULL DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS raw_text_cache (
    url TEXT PRIMARY KEY,
    raw_text TEXT NOT NULL,
    inserted_at TEXT NOT NULL DEFAULT (datetime('now'))
);
"""


@contextmanager
def get_conn():
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db() -> None:
    with get_conn() as conn:
        conn.executescript(SCHEMA)


def is_seen(url: str) -> bool:
    with get_conn() as conn:
        row = conn.execute("SELECT 1 FROM seen_urls WHERE url = ?", (url,)).fetchone()
        return row is not None


def mark_seen(url: str, record_type: str) -> None:
    with get_conn() as conn:
        conn.execute(
            "INSERT OR IGNORE INTO seen_urls (url, record_type, first_seen_at) "
            "VALUES (?, ?, datetime('now'))",
            (url, record_type),
        )


def save_record(record_type: str, payload: dict) -> None:
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO records (record_type, payload) VALUES (?, ?)",
            (record_type, json.dumps(payload)),
        )


def save_mapping(raw_name: str, canonical_name: str, confidence: float) -> None:
    with get_conn() as conn:
        conn.execute(
            "INSERT INTO entity_mapping_log (raw_name, canonical_name, confidence) "
            "VALUES (?, ?, ?)",
            (raw_name, canonical_name, confidence),
        )


def fetch_records(record_type: str) -> list[dict]:
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT payload FROM records WHERE record_type = ?", (record_type,)
        ).fetchall()
        return [json.loads(r[0]) for r in rows]


def count_records(record_type: str) -> int:
    with get_conn() as conn:
        row = conn.execute(
            "SELECT COUNT(*) FROM records WHERE record_type = ?", (record_type,)
        ).fetchone()
        return row[0]


def save_raw_text(url: str, raw_text: str) -> None:
    """Stashes the raw source text behind a record's URL. Used by
    src/llm/pricing_backfill.py so a later pass can run LLM extraction
    against the original text without needing it to be part of the
    official schema payload — the raw text isn't a graded field, just
    working material for the backfill step."""
    with get_conn() as conn:
        conn.execute(
            "INSERT OR REPLACE INTO raw_text_cache (url, raw_text) VALUES (?, ?)",
            (url, raw_text),
        )


def get_raw_text(url: str) -> Optional[str]:
    with get_conn() as conn:
        row = conn.execute("SELECT raw_text FROM raw_text_cache WHERE url = ?", (url,)).fetchone()
        return row[0] if row else None


def update_record_by_source_url(record_type: str, source_url: str, updated_payload: dict) -> bool:
    """Overwrites the stored payload for the record matching record_type +
    source.url. Returns True if a matching record was found and updated.
    Used sparingly — most of this pipeline is insert-only by design (see
    module docstring), but a backfill pass genuinely needs to update a
    field on an already-saved record rather than create a duplicate."""
    with get_conn() as conn:
        rows = conn.execute(
            "SELECT id, payload FROM records WHERE record_type = ?", (record_type,)
        ).fetchall()
        for row_id, payload_json in rows:
            payload = json.loads(payload_json)
            if payload.get("source", {}).get("url") == source_url:
                conn.execute(
                    "UPDATE records SET payload = ? WHERE id = ?",
                    (json.dumps(updated_payload), row_id),
                )
                return True
    return False