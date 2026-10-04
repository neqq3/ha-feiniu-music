"""Fake-backend timings: complete enumeration versus one useful page, never live NAS."""

import asyncio
import json
import tracemalloc
from pathlib import Path
from time import perf_counter

import pytest
from homeassistant.const import __version__

from .conftest import track


@pytest.mark.parametrize("total", [100, 1000, 5000])
@pytest.mark.parametrize("delay", [0, 0.3])
async def test_first_useful_page_cost(runtime, client, total, delay):
    calls = active = peak = 0

    async def fetch(kind, number, size=100):
        nonlocal calls, active, peak
        calls += 1
        active += 1
        peak = max(peak, active)
        try:
            await asyncio.sleep(delay)
            return {
                "list": [
                    track(f"test-{i}")
                    for i in range((number - 1) * size, min(number * size, total))
                ],
                "total": total,
            }
        finally:
            active -= 1

    client.page.side_effect = fetch
    started = perf_counter()
    rows = await runtime.collection("track")
    full_ms = (perf_counter() - started) * 1000
    assert len(rows) == total and calls == total // 100
    full_calls = calls
    del rows
    runtime._invalidate_metadata()
    calls = peak = 0
    tracemalloc.start()
    started = perf_counter()
    page = await runtime.browse_page("track")
    first_ms = (perf_counter() - started) * 1000
    _, memory_peak = tracemalloc.get_traced_memory()
    tracemalloc.stop()
    assert len(page.rows) == 100 and page.total == total and calls == peak == 1
    started = perf_counter()
    await runtime.browse_page("track")
    warm_ms = (perf_counter() - started) * 1000
    assert calls == 1 and runtime.browse_diagnostics()["hit"] == 1
    assert not runtime._browse_waiters and not runtime._browse_flights
    observation = {
        "ha": __version__,
        "rows": total,
        "fake_delay_ms": delay * 1000,
        "full_enumeration_ms": round(full_ms, 2),
        "full_requests": full_calls,
        "first_page_ms": round(first_ms, 2),
        "first_page_requests": calls,
        "warm_page_ms": round(warm_ms, 2),
        "warm_requests": 0,
        "peak_requests": peak,
        "cache_hits": 1,
        "first_page_python_peak_bytes": memory_peak,
        "remaining_flights": 0,
    }

    # Executor file I/O, not an HA event-loop operation. This artifact contains only
    # synthetic size/timing counters, and is uploaded by the test workflow.
    def save():
        path = Path("artifacts") / f"browse-{total}-{int(delay * 1000)}.json"
        path.parent.mkdir(exist_ok=True)
        path.write_text(json.dumps(observation, indent=2), encoding="utf-8")

    await asyncio.to_thread(save)
