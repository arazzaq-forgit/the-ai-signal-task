from datetime import datetime, timedelta, timezone

from src.freshness import is_within_freshness_window, normalize_date

NOW = datetime(2026, 7, 19, 12, 0, 0, tzinfo=timezone.utc)


def test_relative_hours_ago():
    assert normalize_date("2 hours ago", now=NOW) == NOW - timedelta(hours=2)


def test_relative_days_ago():
    assert normalize_date("3 days ago", now=NOW) == NOW - timedelta(days=3)


def test_relative_yesterday():
    assert normalize_date("yesterday", now=NOW) == NOW - timedelta(days=1)


def test_relative_just_now():
    assert normalize_date("just now", now=NOW) == NOW


def test_rfc822_format():
    assert normalize_date("Sun, 19 Jul 2026 10:00:00 GMT", now=NOW) == datetime(2026, 7, 19, 10, 0, 0, tzinfo=timezone.utc)


def test_iso8601_format():
    assert normalize_date("2026-07-19T09:30:00Z", now=NOW) == datetime(2026, 7, 19, 9, 30, 0, tzinfo=timezone.utc)


def test_empty_and_none_return_none():
    assert normalize_date("") is None
    assert normalize_date(None) is None


def test_unparseable_text_returns_none():
    assert normalize_date("not a date at all") is None


def test_freshness_window_boundary():
    assert is_within_freshness_window(NOW - timedelta(hours=23, minutes=59), now=NOW) is True
    assert is_within_freshness_window(NOW - timedelta(hours=25), now=NOW) is False


def test_freshness_window_none_is_not_fresh():
    assert is_within_freshness_window(None, now=NOW) is False
