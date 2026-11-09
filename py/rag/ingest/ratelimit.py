"""Cross-process politeness limiter: at most one HUDOC request per `min_interval` seconds, whoever
makes it, plus a hard cap on the total number of requests.

Every process takes the same file lock, reads the timestamp of the previous request, sleeps until
`min_interval` has passed, then writes its own timestamp. The clock and sleep functions are
injectable so tests need no real waiting.
"""

from __future__ import annotations

import fcntl
import json
import time
from collections.abc import Callable
from pathlib import Path

MIN_INTERVAL = 1.05
DEFAULT_HARD_CAP = 6000


class RequestCapReached(RuntimeError):
    """The configured request cap was reached; nothing more is sent."""


class RateLimiter:
    def __init__(
        self,
        state_dir: Path,
        *,
        min_interval: float = MIN_INTERVAL,
        hard_cap: int = DEFAULT_HARD_CAP,
        run_cap: int | None = None,
        clock: Callable[[], float] = time.time,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        self.state_dir = Path(state_dir)
        self.min_interval = min_interval
        self.hard_cap = hard_cap
        self.run_cap = run_cap
        self.clock = clock
        self.sleep = sleep
        self.run_count = 0
        self._lock_path = self.state_dir / "hudoc.lock"
        self._state_path = self.state_dir / "hudoc-state.json"

    def acquire(self) -> int:
        """Block until a request may start; returns the lifetime request number."""
        if self.run_cap is not None and self.run_count >= self.run_cap:
            raise RequestCapReached(f"per-run request cap {self.run_cap} reached")
        self.state_dir.mkdir(parents=True, exist_ok=True)
        with open(self._lock_path, "w") as lock:
            fcntl.flock(lock, fcntl.LOCK_EX)
            state = self._read()
            if state["count"] >= self.hard_cap:
                raise RequestCapReached(f"lifetime request cap {self.hard_cap} reached")
            wait = state["last"] + self.min_interval - self.clock()
            if wait > 0:
                self.sleep(wait)
            state["count"] += 1
            state["last"] = self.clock()
            self._state_path.write_text(json.dumps(state))
        self.run_count += 1
        return state["count"]

    def lifetime_count(self) -> int:
        return self._read()["count"]

    def _read(self) -> dict:
        if self._state_path.exists():
            return json.loads(self._state_path.read_text())
        return {"count": 0, "last": 0.0}
