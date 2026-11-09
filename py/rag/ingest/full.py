"""Full mode, step 1: list the UK English corpus on HUDOC, download the HTML bodies, write
data/full/manifest.json. Step 2 (parse -> index) is the shared pipeline.

Resumable: the listing is cached page by page and files already on disk are never fetched again.
"""

from __future__ import annotations

import json
import math
import os
import shutil
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

import httpx

from .hudoc import (
    COMMISSION_REPORTS_QUERY,
    LISTING_QUERIES,
    DocumentUnavailable,
    HudocBlocked,
    HudocClient,
    entry_from_row,
)
from .pipeline import sha256_hex
from .progress import Out, Progress
from .ratelimit import RequestCapReached

USER_AGENT = "echr-lookup/0.1 (+https://github.com/hutchida/echr-lookup)"
PAGE_LENGTH = 500
LISTING_MAX_AGE = 24 * 3600
MAX_CONSECUTIVE_FAILURES = 5
HRA_URL = "https://www.legislation.gov.uk/ukpga/1998/42/data.xml"


class ListingLoopError(RuntimeError):
    """The listing pager hit its request cap without finishing: stop instead of looping."""


def utc_iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def http_get(url: str) -> bytes:
    """Plain HTTP for non-HUDOC sources (legislation.gov.uk, echr.coe.int)."""
    resp = httpx.get(url, headers={"User-Agent": USER_AGENT}, follow_redirects=True, timeout=60)
    resp.raise_for_status()
    return resp.content


@dataclass
class FullResult:
    entries: list[dict] = field(default_factory=list)  # what this run ingests
    manifest: list[dict] = field(default_factory=list)  # everything on disk
    blocked: str | None = None
    cap_reached: bool = False
    skipped_commission_reports: int | None = None
    download_seconds: float = 0.0
    downloaded: int = 0
    already_on_disk: int = 0
    download_failures: list[tuple[str, str]] = field(default_factory=list)


def _write_atomic(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".part")
    tmp.write_bytes(data)
    os.replace(tmp, path)


class FullDownloader:
    def __init__(
        self,
        root: Path,
        client: HudocClient,
        *,
        get: Callable[[str], bytes] = http_get,
        snapshot_root: Path | None = None,
        limit: int | None = None,
        out: Out = print,
        now: Callable[[], float] = time.time,
    ) -> None:
        self.root = Path(root)
        self.client = client
        self.get = get
        self.snapshot_root = snapshot_root
        self.limit = limit
        self.out = out
        self.now = now
        self.listing_path = self.root / "listing.json"
        self.state_path = self.root / "state.json"

    # --- listing ------------------------------------------------------------------------------

    def _load_listing(self) -> dict:
        if self.listing_path.exists():
            return json.loads(self.listing_path.read_text())
        return {}

    def _save_listing(self, listing: dict) -> None:
        _write_atomic(self.listing_path, json.dumps(listing).encode())

    def list_rows(self) -> list[dict]:
        """Listing rows in query order, enough to cover `limit` (all of them when no limit)."""
        listing = self._load_listing()
        rows: list[dict] = []
        for name, query in LISTING_QUERIES:
            cached = listing.get(name)
            if (
                cached
                and cached.get("complete")
                and self.now() - cached["fetched_at"] > (LISTING_MAX_AGE)
            ):
                cached = None
            cached = cached or {"rows": [], "total": None, "complete": False}
            seen = {r["itemid"] for r in cached["rows"]}
            # HUDOC pages by position in ITS list, which contains duplicates. Old caches have no
            # `next_start`; the unique-row count is the best guess for them.
            next_start = cached.get("next_start", len(cached["rows"]))
            requests_made = 0
            pages_without_new = 0
            while not cached["complete"]:
                want = None if self.limit is None else self.limit - len(rows) - len(cached["rows"])
                if want is not None and want <= 0:
                    break
                max_requests = math.ceil((cached["total"] or 0) / PAGE_LENGTH) + 3
                if cached["total"] is not None and requests_made >= max_requests:
                    raise ListingLoopError(
                        f"[listing {name}] stopped after {requests_made} requests for "
                        f"{cached['total']} listed rows ({len(cached['rows'])} unique, next start "
                        f"{next_start}): HUDOC is not paging as expected. Nothing was lost; the "
                        "cached rows are kept."
                    )
                length = PAGE_LENGTH if want is None else min(PAGE_LENGTH, want)
                data = self.client.search(query, start=next_start, length=length)
                requests_made += 1
                page = [r["columns"] for r in data.get("results", [])]
                cached["total"] = data.get("resultcount", cached["total"])
                new = []
                for r in page:
                    if r["itemid"] not in seen:
                        seen.add(r["itemid"])
                        new.append(r)
                cached["rows"].extend(new)
                next_start += len(page)
                cached["next_start"] = next_start
                cached["fetched_at"] = self.now()
                pages_without_new = 0 if new else pages_without_new + 1
                total = cached["total"] or 0
                cached["complete"] = (
                    not page
                    or next_start >= total
                    or len(cached["rows"]) >= total
                    or pages_without_new >= 2
                )
                listing[name] = cached
                self._save_listing(listing)
                self.out(f"[listing {name}] {len(cached['rows'])}/{cached['total']}")
                if cached["complete"] and len(cached["rows"]) < total:
                    self.out(
                        f"[listing {name}] WARNING: {len(cached['rows'])} unique of {total} listed "
                        f"({total - len(cached['rows'])} duplicates)"
                    )
            listing[name] = cached
            rows.extend(cached["rows"])
            if self.limit is not None and len(rows) >= self.limit:
                break
        return rows if self.limit is None else rows[: self.limit]

    def count_commission_reports(self) -> int:
        """How many Commission reports HUDOC lists (we skip them): one cheap request, cached."""
        listing = self._load_listing()
        cached = listing.get("_commission_reports_count")
        if cached and self.now() - cached["fetched_at"] <= LISTING_MAX_AGE:
            return cached["count"]
        data = self.client.search(COMMISSION_REPORTS_QUERY, start=0, length=1, tag="count")
        count = int(data.get("resultcount", 0))
        listing["_commission_reports_count"] = {"count": count, "fetched_at": self.now()}
        self._save_listing(listing)
        return count

    # --- download -----------------------------------------------------------------------------

    def _cached_rows(self) -> list[dict]:
        listing = self._load_listing()
        return [r for name, _ in LISTING_QUERIES for r in listing.get(name, {}).get("rows", [])]

    def run(self) -> FullResult:
        t0 = time.perf_counter()
        result = FullResult()
        try:
            selected = self.list_rows()
            self._download(selected, result)
            result.skipped_commission_reports = self.count_commission_reports()
        except HudocBlocked as exc:
            result.blocked = str(exc)
        except RequestCapReached as exc:
            result.blocked = str(exc)
            result.cap_reached = True
        cached = self._cached_rows()
        selected_ids = {r["itemid"] for r in cached[: self.limit]}
        everything = self._build_manifest(cached)
        legislation = self._legislation()
        result.manifest = everything + legislation
        result.entries = [e for e in everything if e["item_id"] in selected_ids] + legislation
        result.download_seconds = time.perf_counter() - t0
        self._save_state(result)
        return result

    def _download(self, rows: list[dict], result: FullResult) -> None:
        progress = Progress(len(rows), "download", out=self.out)
        consecutive = 0
        for row in rows:
            item_id = row["itemid"]
            path = self.root / "hudoc" / f"{item_id}.html"
            if path.exists() and path.stat().st_size > 1000:
                result.already_on_disk += 1
                progress.step(item_id, "on disk")
                continue
            try:
                body = self.client.body(item_id)
            except DocumentUnavailable as exc:
                consecutive += 1
                result.download_failures.append((item_id, str(exc)))
                progress.step(item_id, "FAILED", str(exc))
                if consecutive >= MAX_CONSECUTIVE_FAILURES:
                    raise HudocBlocked(f"{consecutive} downloads in a row failed") from exc
                continue
            consecutive = 0
            _write_atomic(path, body)
            result.downloaded += 1
            progress.step(item_id, "got", f"{len(body) // 1024} KB")

    def _build_manifest(self, rows: list[dict]) -> list[dict]:
        entries: list[dict] = []
        for row in rows:
            path = self.root / "hudoc" / f"{row['itemid']}.html"
            if not path.exists():
                continue
            try:
                entries.append(
                    entry_from_row(
                        row,
                        sha256=sha256_hex(path.read_bytes()),
                        retrieved_at=utc_iso(path.stat().st_mtime),
                    )
                )
            except (ValueError, KeyError) as exc:
                self.out(f"[manifest] skipping {row.get('itemid')}: {exc}")
        return entries

    # --- legislation (not HUDOC: plain httpx) --------------------------------------------------

    def _legislation(self) -> list[dict]:
        leg = self.root / "legislation"
        entries: list[dict] = []
        base = {
            "application_numbers": [],
            "ecli": None,
            "doc_type": "legislation",
            "chamber": None,
            "articles": [],
            "outcome_raw": None,
            "outcome": "not_applicable",
            "inadmissibility_grounds": None,
            "inadmissibility_grounds_source": None,
            "importance": None,
            "language": "en",
            "data_source": "full",
        }
        hra = leg / "ukpga-1998-42.xml"
        try:
            if not hra.exists():
                _write_atomic(hra, self.get(HRA_URL))
        except httpx.HTTPError as exc:
            self.out(f"[legislation] Human Rights Act not fetched: {exc}")
        if hra.exists():
            entries.append(
                {
                    **base,
                    "item_id": "ukpga-1998-42",
                    "case_name": "Human Rights Act 1998",
                    "date": "1998-11-09",
                    "source_url": "https://www.legislation.gov.uk/ukpga/1998/42",
                    "sha256": sha256_hex(hra.read_bytes()),
                    "retrieved_at": utc_iso(hra.stat().st_mtime),
                    "format": "xml",
                    "path": "legislation/ukpga-1998-42.xml",
                }
            )
        # The Convention is published as a PDF on echr.coe.int; turning it into clean text needs a
        # PDF library that is not a project dependency, so the already-cleaned text is reused.
        conv = leg / "echr-convention.txt"
        src = (
            self.snapshot_root / "legislation" / "echr-convention.txt"
            if self.snapshot_root
            else None
        )
        if not conv.exists() and src and src.exists():
            conv.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(src, conv)
        if conv.exists():
            entries.append(
                {
                    **base,
                    "item_id": "echr-convention",
                    "case_name": (
                        "European Convention on Human Rights (as amended by Protocols 11, 14 and "
                        "15, with Protocols 1, 4, 6, 7, 12, 13, 16)"
                    ),
                    "date": "1950-11-04",
                    "source_url": "https://www.echr.coe.int/documents/d/echr/convention_eng",
                    "sha256": sha256_hex(conv.read_bytes()),
                    "retrieved_at": utc_iso(conv.stat().st_mtime),
                    "format": "txt",
                    "path": "legislation/echr-convention.txt",
                }
            )
        return entries

    # --- state --------------------------------------------------------------------------------

    def _save_state(self, result: FullResult) -> None:
        manifest = sorted(result.manifest, key=lambda e: (e["doc_type"], e["date"], e["item_id"]))
        _write_atomic(
            self.root / "manifest.json",
            (json.dumps(manifest, indent=1, ensure_ascii=False) + "\n").encode(),
        )
        state = {
            "status": "blocked" if result.blocked else "ok",
            "reason": result.blocked,
            "skipped_commission_reports": result.skipped_commission_reports,
            "at": utc_iso(self.now()),
            "downloaded_this_run": result.downloaded,
            "failures": result.download_failures,
            "requests_lifetime": self.client.limiter.lifetime_count(),
        }
        _write_atomic(self.state_path, json.dumps(state, indent=1).encode())
