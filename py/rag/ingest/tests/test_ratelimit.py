import json

import pytest

from rag.ingest.ratelimit import RateLimiter, RequestCapReached

from .fakes import FakeClock


def limiter(tmp_path, clock, **kw):
    return RateLimiter(tmp_path, clock=clock.time, sleep=clock.sleep, **kw)


def test_requests_are_spaced_at_least_min_interval(tmp_path):
    clock = FakeClock()
    lim = limiter(tmp_path, clock, min_interval=1.05)
    starts = []
    for _ in range(6):
        lim.acquire()
        starts.append(clock.time())
    gaps = [b - a for a, b in zip(starts, starts[1:], strict=False)]
    assert all(g >= 1.05 - 1e-9 for g in gaps)
    assert max(gaps) < 1.06  # and no longer than needed


def test_no_sleep_when_enough_time_already_passed(tmp_path):
    clock = FakeClock()
    lim = limiter(tmp_path, clock)
    lim.acquire()
    clock.now += 5
    lim.acquire()
    assert clock.sleeps == []


def test_state_is_shared_between_limiter_instances(tmp_path):
    """A second 'process' (new instance, same directory) must also wait."""
    clock = FakeClock()
    limiter(tmp_path, clock).acquire()
    limiter(tmp_path, clock).acquire()
    assert clock.sleeps and clock.sleeps[0] == pytest.approx(1.05)
    assert json.loads((tmp_path / "hudoc-state.json").read_text())["count"] == 2


def test_run_cap_and_hard_cap(tmp_path):
    clock = FakeClock()
    lim = limiter(tmp_path, clock, run_cap=2)
    lim.acquire()
    lim.acquire()
    with pytest.raises(RequestCapReached):
        lim.acquire()
    hard = limiter(tmp_path, clock, hard_cap=2)  # lifetime count is already 2
    with pytest.raises(RequestCapReached):
        hard.acquire()
