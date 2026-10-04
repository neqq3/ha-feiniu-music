"""Header-driven cooldown and cancellation, without real server sleep intervals."""

import asyncio
from datetime import UTC, datetime, timedelta
from email.utils import format_datetime
from unittest.mock import AsyncMock

import pytest

from custom_components.feiniu_music.client import RateLimitError, retry_after

from .test_client import Response, client_with


@pytest.mark.parametrize(
    "header,expected",
    [
        (None, 60),
        ("bad", 60),
        ("nan", 60),
        ("inf", 60),
        ("-1", 60),
        ("0", 1),
        ("1.5", 2),
        ("9000", 120),
    ],
)
def test_retry_after_is_finite_and_bounded(header, expected):
    assert retry_after(header) == expected


def test_retry_after_http_date():
    assert 58 <= retry_after(format_datetime(datetime.now(UTC) + timedelta(seconds=60))) <= 60


async def test_rate_limit_closes_response_and_close_interrupts_following_wait():
    response = Response(b"test", 429, {"Retry-After": "120"})
    client = client_with(response)
    client._session.close = AsyncMock()
    with pytest.raises(RateLimitError) as error:
        await client.current_user()
    assert error.value.backoff_time == 120
    waiting = asyncio.create_task(client.current_user())
    await asyncio.sleep(0)
    assert not waiting.done()
    await client.__aexit__(None, None, None)
    with pytest.raises(asyncio.CancelledError):
        await waiting
    assert not client._operations and client._session is None


async def test_close_interrupts_wait_for_native_request_slot():
    client = client_with()
    client._session.close = AsyncMock()
    for _ in range(4):
        await client._slots["interactive"].acquire()
    request = asyncio.create_task(client.current_user())
    await asyncio.sleep(0)
    assert not request.done()
    await client.__aexit__(None, None, None)
    with pytest.raises(asyncio.CancelledError):
        await request
    assert not client._operations
