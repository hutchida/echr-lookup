"""The per-document pipeline shared by snapshot and full mode:
read + verify -> skip if unchanged -> parse -> chunk x3 -> embed -> index.

Seams to other tasks (rag.parse, rag.index) are collected in `Deps`, so tests can swap in fakes.
"""

from __future__ import annotations

import functools
import hashlib
import logging
import time
from collections.abc import Callable, Iterable
from concurrent.futures import Future, ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any

from .progress import Out, Progress

log = logging.getLogger("rag.ingest")

EMBED_BATCH = 32
STAGES = ("download", "parse", "chunk", "embed", "index")


@dataclass
class Deps:
    parse_document: Callable[..., dict]
    chunk_paragraphs: Callable[..., list[dict]]
    strategies: tuple[str, ...]
    embedder: Any
    upsert_document: Callable[..., None]
    replace_chunks: Callable[..., None]
    stored_hashes: Callable[[Any], dict[str, str]]
    record_ingest_run: Callable[[Any, dict], None]
    reset: Callable[[Any], None]
    migrate: Callable[[Any], None]
    discard_document: Callable[[Any, str], None] = lambda conn, item_id: None


def default_deps() -> Deps:
    from rag import index, parse

    return Deps(
        parse_document=parse.parse_document,
        chunk_paragraphs=parse.chunk_paragraphs,
        strategies=tuple(parse.STRATEGIES),
        embedder=index.get_embedder(),
        upsert_document=index.upsert_document,
        replace_chunks=index.replace_chunks,
        stored_hashes=index.stored_hashes,
        record_ingest_run=index.record_ingest_run,
        reset=index.reset,
        migrate=index.migrate,
        discard_document=discard_document,
    )


def discard_document(conn: Any, item_id: str) -> None:
    """Remove a half-ingested document (rows cascade) so its stored hash cannot make the next
    run skip it: documents.sha256 is what stored_hashes() reports."""
    conn.rollback()
    conn.execute("DELETE FROM documents WHERE item_id = %s", (item_id,))
    conn.commit()


@dataclass
class Item:
    """One document to consider: its ManifestEntry and a function that returns its stored bytes."""

    entry: dict
    read: Callable[[], bytes]


@dataclass
class Tally:
    stage_seconds: dict[str, float] = field(default_factory=lambda: dict.fromkeys(STAGES, 0.0))
    counts: dict[str, int] = field(
        default_factory=lambda: {
            "seen": 0,
            "new": 0,
            "changed": 0,
            "unchanged_skipped": 0,
            "failed": 0,
        }
    )
    failures: list[tuple[str, str]] = field(default_factory=list)


def sha256_hex(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def embed_all(embedder: Any, texts: list[str]) -> list[list[float]]:
    """Embed in batches of 32. Texts are batched longest-with-longest so a batch wastes little
    time padding short chunks up to a long one; vectors come back in the original order."""
    order = sorted(range(len(texts)), key=lambda i: len(texts[i]))
    vectors: list[list[float] | None] = [None] * len(texts)
    for start in range(0, len(order), EMBED_BATCH):
        idx = order[start : start + EMBED_BATCH]
        for i, vec in zip(idx, embedder.embed([texts[i] for i in idx]), strict=True):
            vectors[i] = vec
    return vectors  # type: ignore[return-value]


@dataclass
class Prepared:
    """A document that is parsed and chunked and waits for its vectors."""

    item: Item
    status: str  # 'new' | 'changed'
    document: dict
    paragraphs: list[dict]
    chunks_by_strategy: dict[str, list[dict]]

    @property
    def texts(self) -> list[str]:
        return [c["text"] for chunks in self.chunks_by_strategy.values() for c in chunks]


def prepare(item: Item, stored: dict[str, str], deps: Deps, tally: Tally) -> Prepared | None:
    """Read + verify + parse + chunk. Returns None when the document is unchanged (skipped)."""
    entry = item.entry
    item_id = entry["item_id"]
    perf = time.perf_counter

    t = perf()
    raw = item.read()
    actual = sha256_hex(raw)
    tally.stage_seconds["download"] += perf() - t
    if actual != entry["sha256"]:
        raise ValueError(f"sha256 mismatch: manifest {entry['sha256'][:12]}…, file {actual[:12]}…")
    if stored.get(item_id) == actual:
        return None
    status = "changed" if item_id in stored else "new"

    t = perf()
    parsed = deps.parse_document(entry, raw)
    document, paragraphs = parsed["document"], parsed["paragraphs"]
    tally.stage_seconds["parse"] += perf() - t
    if not paragraphs:
        raise ValueError("parser returned no paragraphs")

    t = perf()
    # one cache per document: the 3 strategies tokenise mostly the same paragraph texts
    count_tokens = functools.lru_cache(maxsize=None)(deps.embedder.count_tokens)
    chunks_by_strategy = {
        strategy: deps.chunk_paragraphs(paragraphs, strategy, count_tokens=count_tokens)
        for strategy in deps.strategies
    }
    tally.stage_seconds["chunk"] += perf() - t
    return Prepared(item, status, document, paragraphs, chunks_by_strategy)


def timed_embed(embedder: Any, texts: list[str]) -> tuple[list[list[float]], float]:
    t = time.perf_counter()
    vectors = embed_all(embedder, texts)
    return vectors, time.perf_counter() - t


def finish(conn: Any, prep: Prepared, vectors: list[list[float]], deps: Deps, tally: Tally) -> None:
    """Write the document, its paragraphs and its chunks + vectors; commit."""
    t = time.perf_counter()
    item_id = prep.document["item_id"]
    try:
        deps.upsert_document(conn, prep.document, prep.paragraphs)
        offset = 0
        for strategy, chunks in prep.chunks_by_strategy.items():
            deps.replace_chunks(
                conn,
                item_id,
                strategy,
                chunks,
                vectors[offset : offset + len(chunks)],
                deps.embedder.model_name,
            )
            offset += len(chunks)
        conn.commit()
    except Exception:
        deps.discard_document(conn, item_id)
        raise
    tally.stage_seconds["index"] += time.perf_counter() - t


def process_item(conn: Any, item: Item, stored: dict[str, str], deps: Deps, tally: Tally) -> str:
    """Ingest one document, one stage after the other. Returns 'new' | 'changed' | 'skipped';
    raises on any failure."""
    prep = prepare(item, stored, deps, tally)
    if prep is None:
        return "skipped"
    vectors, secs = timed_embed(deps.embedder, prep.texts)
    tally.stage_seconds["embed"] += secs
    finish(conn, prep, vectors, deps, tally)
    return prep.status


def process_items(
    conn: Any,
    items: Iterable[Item],
    total: int,
    deps: Deps,
    tally: Tally,
    *,
    out: Out = print,
    clock: Callable[[], float] = time.perf_counter,
) -> None:
    """Run every item through the pipeline.

    Embedding is the slow, CPU-bound stage, so it runs in one worker thread: while document N is
    being embedded, the main thread writes document N-1 to the database and reads, parses and
    chunks document N+1. Stage seconds are the time spent in each stage (they can add up to more
    than the wall clock because of this overlap). Database access stays on the main thread.
    """
    stored = deps.stored_hashes(conn)
    progress = Progress(total, "ingest", out=out, clock=clock)
    pending: tuple[Prepared, Future] | None = None

    def fail(item_id: str, exc: Exception) -> None:
        conn.rollback()
        tally.counts["failed"] += 1
        tally.failures.append((item_id, f"{type(exc).__name__}: {exc}"))
        log.warning("failed %s: %s", item_id, exc)
        progress.step(item_id, "FAILED", f"{type(exc).__name__}: {exc}")

    def complete(prep: Prepared, future: Future) -> None:
        item_id = prep.item.entry["item_id"]
        try:
            vectors, secs = future.result()
            tally.stage_seconds["embed"] += secs
            finish(conn, prep, vectors, deps, tally)
        except Exception as exc:  # one bad document must not stop the run
            fail(item_id, exc)
            return
        tally.counts[prep.status] += 1
        progress.step(item_id, prep.status, prep.item.entry["case_name"])

    with ThreadPoolExecutor(max_workers=1, thread_name_prefix="embed") as pool:
        for item in items:
            entry = item.entry
            tally.counts["seen"] += 1
            try:
                prep = prepare(item, stored, deps, tally)
            except Exception as exc:
                fail(entry["item_id"], exc)
                continue
            if prep is None:
                tally.counts["unchanged_skipped"] += 1
                progress.step(entry["item_id"], "skipped", entry["case_name"])
                continue
            future = pool.submit(timed_embed, deps.embedder, prep.texts)
            if pending:
                complete(*pending)
            pending = (prep, future)
        if pending:
            complete(*pending)
