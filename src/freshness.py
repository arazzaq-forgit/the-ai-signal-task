"""
Date normalization for the freshness pipeline. Handles three cases:
1. Standard formats (RFC 822 from RSS, ISO-8601 from JSON APIs) via dateutil.
2. Relative phrases ("2 hours ago", "yesterday") via regex.
3. No date at all — the "intelligent heuristic" fallback: treat first-seen-
   this-run as new, tracked via the same SQLite seen_urls table used for
   dedup elsewhere. That's implemented by the callers (news.py/jobs.py)
   checking is_seen() before deciding to keep a dateless item.
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Optional

from dateutil import parser as dateutil_parser

FRESHNESS_WINDOW = timedelta(hours=24)

_RELATIVE_PATTERN = re.compile(
    r"(?P<amount>\d+)\s*(?P<unit>second|minute|hour|day|week|month)s?\s*ago",
    re.IGNORECASE,
)

_UNIT_TO_KWARG = {
    "second": "seconds",
    "minute": "minutes",
    "hour": "hours",
    "day": "days",
    "week": "weeks",
    # "month" handled specially below (timedelta has no month unit)
}


def _parse_relative(text: str, now: datetime) -> Optional[datetime]:
    text = text.strip().lower()
    if text in ("just now", "now", "moments ago"):
        return now
    if text == "yesterday":
        return now - timedelta(days=1)

    match = _RELATIVE_PATTERN.search(text)
    if not match:
        return None
    amount = int(match.group("amount"))
    unit = match.group("unit").lower()
    if unit == "month":
        return now - timedelta(days=30 * amount)
    kwarg = _UNIT_TO_KWARG[unit]
    return now - timedelta(**{kwarg: amount})


def normalize_date(raw: Optional[str], *, now: Optional[datetime] = None) -> Optional[datetime]:
    """Best-effort normalization to a timezone-aware UTC datetime.
    Returns None if the input is empty or unparseable by any strategy —
    callers should treat None as 'unknown', not 'now', to avoid falsely
    marking stale content as fresh."""
    if not raw or not raw.strip():
        return None
    now = now or datetime.now(timezone.utc)

    relative = _parse_relative(raw, now)
    if relative is not None:
        return relative

    try:
        parsed = dateutil_parser.parse(raw)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except (ValueError, OverflowError):
        return None


def is_within_freshness_window(dt: Optional[datetime], *, now: Optional[datetime] = None) -> bool:
    """True only if dt is known AND within the last 24h. Unknown dates
    (None) are NOT treated as fresh by default — callers implementing the
    'no date at all' heuristic should use is_seen()/mark_seen() instead of
    calling this with None."""
    if dt is None:
        return False
    now = now or datetime.now(timezone.utc)
    return now - dt <= FRESHNESS_WINDOW