import time

import aiohttp
import pytest

from src.http_client import (
    ClientHTTPError, MIN_INTERVAL_SECONDS, RateLimitError, TransientHTTPError,
    _throttle, fetch_json,
)


@pytest.mark.asyncio
async def test_throttle_spaces_requests_to_configured_host():
    host = "huggingface.co"
    interval = MIN_INTERVAL_SECONDS[host]
    start = time.monotonic()
    for _ in range(3):
        await _throttle(f"https://{host}/api/papers/1")
    elapsed = time.monotonic() - start
    # 3 calls means 2 gaps enforced
    assert elapsed >= interval * 2 * 0.9  # small tolerance for scheduling jitter


@pytest.mark.asyncio
async def test_throttle_does_not_delay_unconfigured_host():
    start = time.monotonic()
    for _ in range(5):
        await _throttle("https://totally-unconfigured-host.example/x")
    elapsed = time.monotonic() - start
    assert elapsed < 0.05


class _FakeResponse:
    def __init__(self, status, json_data=None):
        self.status = status
        self._json_data = json_data or {}

    async def json(self):
        return self._json_data

    def raise_for_status(self):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, *a):
        return False


class _FakeSession:
    def __init__(self, status):
        self.status = status

    def get(self, *a, **kw):
        return _FakeResponse(self.status, {"ok": True})


@pytest.mark.asyncio
async def test_fetch_json_raises_rate_limit_error_on_429():
    session = _FakeSession(429)
    with pytest.raises(RateLimitError):
        await fetch_json(session, "https://unconfigured-host.example/x")


@pytest.mark.asyncio
async def test_fetch_json_raises_client_http_error_on_404_without_retry():
    session = _FakeSession(404)
    start = time.monotonic()
    with pytest.raises(ClientHTTPError):
        await fetch_json(session, "https://unconfigured-host.example/x")
    elapsed = time.monotonic() - start
    # A 404 must NOT trigger the retry/backoff loop — this was a real bug
    # that made pipeline runs appear to hang. Should fail near-instantly.
    assert elapsed < 0.5


@pytest.mark.asyncio
async def test_fetch_json_succeeds_on_200():
    session = _FakeSession(200)
    result = await fetch_json(session, "https://unconfigured-host.example/x")
    assert result == {"ok": True}
