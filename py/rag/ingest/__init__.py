"""Ingest: documents -> parse -> chunk (3 strategies) -> embed -> index. Owner: S1.

`run_ingest` loads documents into the database. It is *incremental* (a document whose sha256 is
already stored is skipped), *resumable* (full mode keeps its listing and downloaded files on disk)
and records an `IngestRun` with per-stage timings. See docs/learn/S1.md.
"""

from __future__ import annotations

import logging
import time
import uuid
from collections.abc import Callable
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from rag.config import REPO_ROOT

from .hudoc import HudocBlocked, HudocClient, HudocUnavailable
from .pipeline import Deps, Tally, default_deps, process_items
from .progress import Out, summary_table
from .ratelimit import RequestCapReached
from .snapshot import items_from_manifest, load_manifest

__all__ = ["HudocBlocked", "HudocUnavailable", "RequestCapReached", "run_ingest"]

SNAPSHOT_ROOT = REPO_ROOT / "data" / "snapshot"
FULL_ROOT = REPO_ROOT / "data" / "full"


def _iso(ts: datetime) -> str:
    return ts.strftime("%Y-%m-%dT%H:%M:%SZ")


def run_ingest(
    conn: Any,
    source: str,
    *,
    limit: int | None = None,
    reset: bool = False,
    deps: Deps | None = None,
    out: Out = print,
    snapshot_root: Path = SNAPSHOT_ROOT,
    full_root: Path = FULL_ROOT,
    client: HudocClient | None = None,
    http_get: Callable[[str], bytes] | None = None,
) -> dict:
    """Ingest `source` ('snapshot' | 'full') and return the recorded IngestRun dict.

    Raises HudocBlocked (full mode only) when HUDOC shows a challenge or refuses us; downloads
    done so far are kept and the next run resumes.
    """
    if source not in ("snapshot", "full"):
        raise ValueError(f"source must be 'snapshot' or 'full', got {source!r}")
    deps = deps or default_deps()
    started = datetime.now(UTC)
    wall0 = time.perf_counter()
    tally = Tally()
    skipped_reports: int | None = None

    if reset:
        out("Resetting database to empty (--reset)")
        deps.reset(conn)
    else:
        deps.migrate(conn)

    if source == "snapshot":
        t = time.perf_counter()
        entries = load_manifest(snapshot_root)
        if limit is not None:
            entries = entries[:limit]
        items = items_from_manifest(snapshot_root, entries)
        tally.stage_seconds["download"] += time.perf_counter() - t
    else:
        from .full import FullDownloader
        from .full import http_get as default_get

        if client is None:
            raise ValueError("full mode needs a HudocClient (the CLI builds one)")
        downloader = FullDownloader(
            full_root,
            client,
            get=http_get or default_get,
            snapshot_root=snapshot_root,
            limit=limit,
            out=out,
        )
        result = downloader.run()
        tally.stage_seconds["download"] += result.download_seconds
        stats = client.stats()
        out(
            f"HUDOC requests this run: {stats['requests']}, "
            f"min gap {stats['min_gap_seconds']} s, mean rate {stats['mean_rate_per_second']}/s"
        )
        skipped_reports = result.skipped_commission_reports
        if result.cap_reached:
            raise RequestCapReached(result.blocked)
        if result.blocked:
            raise HudocBlocked(result.blocked)
        entries = result.entries
        items = items_from_manifest(full_root, entries)
        tally.counts["failed"] += len(result.download_failures)
        tally.failures += result.download_failures

    process_items(conn, items, len(items), deps, tally, out=out)

    finished = datetime.now(UTC)
    run = {
        "run_id": f"{source}-{started:%Y%m%dT%H%M%S}-{uuid.uuid4().hex[:6]}",
        "data_source": source,
        "started_at": _iso(started),
        "finished_at": _iso(finished),
        "stage_seconds": {k: round(v, 3) for k, v in tally.stage_seconds.items()},
        "counts": dict(tally.counts),
        "embedder_model": deps.embedder.model_name,
        "embedding_dim": deps.embedder.dim,
    }
    deps.record_ingest_run(conn, run)
    conn.commit()
    extra = []
    if source == "full":
        shown = "unknown" if skipped_reports is None else skipped_reports
        extra.append(f"skipped_commission_reports={shown}")
        logging.getLogger("rag.ingest").info("skipped_commission_reports=%s", shown)
    out(summary_table(run, time.perf_counter() - wall0, extra))
    for item_id, why in tally.failures:
        out(f"  FAILED {item_id}: {why}")
    return run
