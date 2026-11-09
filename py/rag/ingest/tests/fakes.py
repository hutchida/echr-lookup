"""Offline fakes for the ingest tests: in-memory "database", fake parser/chunker/embedder, a fake
HUDOC transport and a fake clock. Real rag.parse / rag.index are used only in the integration test.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from rag.ingest.hudoc import RawResponse
from rag.ingest.pipeline import Deps


class FakeClock:
    def __init__(self, start: float = 1000.0) -> None:
        self.now = start
        self.sleeps: list[float] = []

    def time(self) -> float:
        return self.now

    def sleep(self, seconds: float) -> None:
        self.sleeps.append(seconds)
        self.now += seconds


class FakeConn:
    def __init__(self) -> None:
        self.commits = 0
        self.rollbacks = 0

    def commit(self) -> None:
        self.commits += 1

    def rollback(self) -> None:
        self.rollbacks += 1


class FakeEmbedder:
    model_name = "fake-embedder"
    dim = 384

    def __init__(self) -> None:
        self.batches: list[int] = []

    def embed(self, texts: list[str]) -> list[list[float]]:
        self.batches.append(len(texts))
        return [[0.0] * self.dim for _ in texts]

    def count_tokens(self, text: str) -> int:
        return len(text.split())


class FakeDb:
    """Implements the rag.index functions run_ingest uses, in memory."""

    def __init__(self) -> None:
        self.hashes: dict[str, str] = {}
        self.chunks: dict[tuple[str, str], int] = {}
        self.runs: list[dict] = []
        self.resets = 0
        self.migrations = 0

    def deps(self, *, fail_on: set[str] | None = None) -> Deps:
        fail_on = fail_on or set()
        embedder = FakeEmbedder()

        def parse_document(entry: dict, raw: bytes) -> dict:
            if entry["item_id"] in fail_on:
                raise RuntimeError("parser exploded")
            document = {k: entry[k] for k in entry if k not in ("retrieved_at", "format", "path")}
            paras = [
                {
                    "id": f"{entry['item_id']}§{i}",
                    "doc_id": entry["item_id"],
                    "position": i,
                    "number": i,
                    "section": "The Law",
                    "text": f"paragraph {i} " * 5,
                }
                for i in range(1, 4)
            ]
            return {"document": document, "paragraphs": paras}

        def chunk_paragraphs(paras, strategy, *, count_tokens=None, max_tokens=256):
            return [
                {
                    "id": f"{p['doc_id']}:{strategy}:{i}",
                    "doc_id": p["doc_id"],
                    "strategy": strategy,
                    "position": i,
                    "text": p["text"],
                    "paragraph_ids": [p["id"]],
                    "token_count": count_tokens(p["text"]) if count_tokens else 1,
                }
                for i, p in enumerate(paras)
            ]

        def upsert_document(conn, document, paragraphs) -> None:
            self.hashes[document["item_id"]] = document["sha256"]

        def replace_chunks(conn, doc_id, strategy, chunks, vectors, embedder_model) -> None:
            assert len(chunks) == len(vectors)
            self.chunks[(doc_id, strategy)] = len(chunks)

        def reset(conn) -> None:
            self.resets += 1
            self.hashes.clear()
            self.chunks.clear()

        def migrate(conn) -> None:
            self.migrations += 1

        return Deps(
            parse_document=parse_document,
            chunk_paragraphs=chunk_paragraphs,
            strategies=("fixed", "recursive", "by_section"),
            embedder=embedder,
            upsert_document=upsert_document,
            replace_chunks=replace_chunks,
            stored_hashes=lambda conn: dict(self.hashes),
            record_ingest_run=lambda conn, run: self.runs.append(run),
            reset=reset,
            migrate=migrate,
        )


def make_snapshot(root: Path, n: int = 4) -> list[dict]:
    """A tiny snapshot directory (manifest.json + files) with correct hashes."""
    (root / "hudoc").mkdir(parents=True, exist_ok=True)
    entries = []
    for i in range(n):
        item_id = f"001-{1000 + i}"
        body = f"<p>1. Body of document {i}.</p>".encode() * 40
        (root / "hudoc" / f"{item_id}.html").write_bytes(body)
        entries.append(
            {
                "item_id": item_id,
                "case_name": f"CASE {i} v. THE UNITED KINGDOM",
                "application_numbers": [f"{i}/99"],
                "ecli": None,
                "doc_type": "judgment",
                "chamber": "Chamber",
                "date": "2000-01-01",
                "articles": ["8"],
                "outcome_raw": "No violation of Article 8",
                "outcome": "no_violation",
                "inadmissibility_grounds": None,
                "inadmissibility_grounds_source": None,
                "importance": 2,
                "language": "en",
                "source_url": f"https://hudoc.echr.coe.int/eng?i={item_id}",
                "sha256": hashlib.sha256(body).hexdigest(),
                "data_source": "snapshot",
                "retrieved_at": "2026-11-03T10:00:00Z",
                "format": "html",
                "path": f"hudoc/{item_id}.html",
            }
        )
    (root / "manifest.json").write_text(json.dumps(entries))
    return entries


def hudoc_row(i: int, doctype: str = "HEJUD") -> dict:
    return {
        "itemid": f"001-{5000 + i}",
        "docname": f"CASE OF TEST {i} v. THE UNITED KINGDOM",
        "appno": f"{i}/01;{i}/02",
        "doctype": doctype,
        "doctypebranch": "CHAMBER",
        "languageisocode": "ENG",
        "kpdate": "2010-05-04T00:00:00",
        "respondent": "GBR",
        "article": "3;8-1",
        "conclusion": "Violation of Article 3",
        "importance": "2",
        "ecli": f"ECLI:CE:ECHR:2010:{i}",
    }


class FakeHudoc:
    """Stands in for the Orca browser tab: serves listing JSON and HTML bodies, or a challenge."""

    def __init__(
        self,
        rows_by_doctype: dict[str, list[dict]],
        *,
        block_after: int | None = None,
        resultcount: dict[str, int] | None = None,
        max_page: int | None = None,
        repeat_tail: int = 0,
    ):
        """`resultcount` overrides the advertised count per doctype; `max_page` caps the rows per
        answer; `repeat_tail=n` makes every start past the end answer with the last n rows again
        (HUDOC listing rows that are duplicates of earlier ones)."""
        self.rows_by_doctype = rows_by_doctype
        self.resultcount = resultcount or {}
        self.max_page = max_page
        self.repeat_tail = repeat_tail
        self.block_after = block_after
        self.urls: list[str] = []

    def fetch(self, url: str) -> RawResponse:
        if self.block_after is not None and len(self.urls) >= self.block_after:
            self.urls.append(url)
            return RawResponse(
                403, b"<title>Just a moment...</title>", "text/html", cf_mitigated="challenge"
            )
        self.urls.append(url)
        parsed = urlparse(url)
        q = parse_qs(parsed.query)
        if parsed.path == "/app/query/results":
            doctype = next((d for d in self.rows_by_doctype if f'"{d}"' in q["query"][0]), None)
            rows = self.rows_by_doctype.get(doctype, [])
            start, length = int(q["start"][0]), int(q["length"][0])
            if self.max_page:
                length = min(length, self.max_page)
            page = rows[start : start + length]
            if not page and self.repeat_tail and rows:
                page = rows[-self.repeat_tail :]
            payload = {
                "resultcount": self.resultcount.get(doctype, len(rows)),
                "results": [{"columns": r} for r in page],
            }
            return RawResponse(200, json.dumps(payload).encode(), "application/json")
        item_id = q["id"][0]
        return RawResponse(200, f"<p>1. Body of {item_id}.</p>".encode() * 60, "text/html")
