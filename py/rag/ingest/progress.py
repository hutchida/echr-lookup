"""Progress lines with a running ETA, and the final summary table.

ETA = (time elapsed / documents done) x documents left: the measured mean per-document time so
far, so skipped documents (nearly free) and new ones (embedding) both feed the estimate.
"""

from __future__ import annotations

import time
from collections.abc import Callable

Out = Callable[[str], None]


def fmt_duration(seconds: float) -> str:
    seconds = max(0, int(round(seconds)))
    h, rem = divmod(seconds, 3600)
    m, s = divmod(rem, 60)
    return f"{h}:{m:02d}:{s:02d}" if h else f"{m}:{s:02d}"


class Progress:
    def __init__(
        self,
        total: int,
        label: str = "ingest",
        *,
        out: Out = print,
        clock: Callable[[], float] = time.perf_counter,
    ) -> None:
        self.total = total
        self.label = label
        self.out = out
        self.clock = clock
        self.start = clock()
        self.done = 0

    def eta_seconds(self) -> float | None:
        if self.done == 0:
            return None
        return (self.clock() - self.start) / self.done * (self.total - self.done)

    def step(self, item_id: str, status: str, detail: str = "") -> str:
        self.done += 1
        eta = self.eta_seconds()
        width = len(str(self.total))
        line = (
            f"[{self.label} {self.done:>{width}}/{self.total}] {item_id:<16} {status:<9} "
            f"{detail:<40.40} elapsed {fmt_duration(self.clock() - self.start)} "
            f"ETA {fmt_duration(eta) if eta is not None else '?'}"
        )
        self.out(line.rstrip())
        return line


def summary_table(run: dict, wall_seconds: float, extra: list[str] | None = None) -> str:
    st, ct = run["stage_seconds"], run["counts"]
    rows = [
        ("run_id", run["run_id"]),
        ("data_source", run["data_source"]),
        ("embedder", f"{run['embedder_model']} ({run['embedding_dim']} dims)"),
        ("", ""),
        *[(f"stage: {k}", f"{v:8.2f} s") for k, v in st.items()],
        ("stage: sum", f"{sum(st.values()):8.2f} s"),
        ("wall clock", f"{wall_seconds:8.2f} s"),
        ("", ""),
        *[(f"docs: {k}", f"{v:8d}") for k, v in ct.items()],
    ]
    width = max(len(k) for k, _ in rows)
    lines = ["", "Ingest summary", "-" * (width + 30)]
    lines += [f"{k:<{width}}  {v}" if k else "" for k, v in rows]
    lines += extra or []
    return "\n".join(lines)
