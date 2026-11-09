import json

import pytest

from rag.config import REPO_ROOT
from rag.contract import contract_errors, load_fixture
from rag.index import (
    get_embedder,
    log_cost,
    migrate,
    price_usd,
    record_ingest_run,
    replace_chunks,
    reset,
    stored_hashes,
    upsert_document,
)
from rag.index.db import migration_files
from rag.index.testing import make_chunks, make_doc, make_paragraphs

TABLES = {
    "documents",
    "paragraphs",
    "chunks",
    "ingest_runs",
    "cost_log",
    "eval_runs",
    "schema_migrations",
}


def _tables(conn) -> set[str]:
    rows = conn.execute("SELECT tablename FROM pg_tables WHERE schemaname = 'public'").fetchall()
    return {r[0] for r in rows}


def test_migrate_is_idempotent(empty_db):
    conn = empty_db
    before = conn.execute("SELECT version, applied_at FROM schema_migrations").fetchall()
    migrate(conn)
    migrate(conn)
    after = conn.execute("SELECT version, applied_at FROM schema_migrations").fetchall()
    assert before == after
    assert {r[0] for r in after} == {p.name for p in migration_files()}
    assert _tables(conn) >= TABLES


def test_chunk_indexes_exist(empty_db):
    defs = " ".join(
        r[0] for r in empty_db.execute("SELECT indexdef FROM pg_indexes WHERE tablename = 'chunks'")
    )
    assert "USING bm25" in defs
    assert "USING hnsw (embedding vector_cosine_ops)" in defs


def test_reset_empties_the_app_tables(empty_db):
    conn = empty_db
    upsert_document(conn, make_doc("001-1", "A v. THE UNITED KINGDOM"), [])
    log_cost(
        conn,
        model="fake",
        purpose="embed",
        tokens_in=1,
        tokens_out=0,
        tokens_cached=0,
        latency_ms=1,
        request_id="r",
    )
    assert conn.execute("SELECT count(*) FROM documents").fetchone()[0] == 1
    reset(conn)
    assert conn.execute("SELECT count(*) FROM documents").fetchone()[0] == 0
    assert conn.execute("SELECT count(*) FROM cost_log").fetchone()[0] == 0
    assert _tables(conn) >= TABLES


def test_upsert_replaces_paragraphs_and_stored_hashes(empty_db):
    conn = empty_db
    doc = make_doc("001-1", "A v. THE UNITED KINGDOM", sha256="a" * 64)
    upsert_document(conn, doc, make_paragraphs("001-1", ["one", "two", "three"]))
    assert stored_hashes(conn) == {"001-1": "a" * 64}
    upsert_document(conn, {**doc, "sha256": "b" * 64}, make_paragraphs("001-1", ["only"]))
    assert stored_hashes(conn) == {"001-1": "b" * 64}
    rows = conn.execute("SELECT id, position, text FROM paragraphs").fetchall()
    assert rows == [("001-1§1", 0, "only")]


def test_replace_chunks_replaces_only_that_strategy(empty_db):
    conn = empty_db
    emb = get_embedder("fake")
    upsert_document(conn, make_doc("001-1", "A v. THE UNITED KINGDOM"), [])
    for strategy, texts in (("recursive", ["a b", "c d", "e f"]), ("fixed", ["g h"])):
        chunks = make_chunks("001-1", strategy, texts)
        replace_chunks(conn, "001-1", strategy, chunks, emb.embed(texts), emb.model_name)
    chunks = make_chunks("001-1", "recursive", ["x y"])
    replace_chunks(conn, "001-1", "recursive", chunks, emb.embed(["x y"]), "fake")
    rows = conn.execute("SELECT strategy, count(*) FROM chunks GROUP BY 1 ORDER BY 1").fetchall()
    assert rows == [("fixed", 1), ("recursive", 1)]
    with pytest.raises(ValueError):
        replace_chunks(conn, "001-1", "fixed", chunks, [], "fake")


def test_record_ingest_run_roundtrip(empty_db):
    run = load_fixture("IngestRun")
    record_ingest_run(empty_db, run)
    record_ingest_run(empty_db, run)  # idempotent
    rows = empty_db.execute("SELECT run_id, payload FROM ingest_runs").fetchall()
    assert len(rows) == 1
    assert contract_errors("IngestRun", rows[0][1]) == []


def test_price_usd_tiers_and_local_models():
    # Haiku 5.5: standard tier up to 100K prompt tokens, long-context tier above (per request)
    assert price_usd("claude-haiku-5-5", 50_000, 1_000, 0) == pytest.approx(0.0055)
    assert price_usd("claude-haiku-5-5", 150_000, 1_000, 0) == pytest.approx(0.0775)
    assert price_usd("claude-haiku-5-5", 60_000, 0, 60_000) == pytest.approx(
        120_000 * 0 + 60_000 * 0.5 / 1e6 + 60_000 * 0.05 / 1e6
    )
    # Sonnet: 1000*$2 + 500*$10 + 2000 cached*$0.1 per MTok
    assert price_usd("claude-sonnet-5-5", 1_000, 500, 2_000) == pytest.approx(0.0072)
    assert price_usd("BAAI/bge-small-en-v1.5", 10_000, 0, 0) == 0.0
    assert price_usd("BAAI/bge-reranker-base", 10_000, 0, 0) == 0.0
    assert price_usd("fake", 10, 0, 0) == 0.0
    with pytest.raises(KeyError):
        price_usd("claude-unknown-9", 1, 1, 1)


def test_prices_file_has_the_models_we_price():
    models = json.loads((REPO_ROOT / "config" / "model-prices.json").read_text())["models"]
    assert "long_context" in models["claude-haiku-5-5"]


def test_log_cost_returns_a_valid_entry_and_stores_it(empty_db):
    entry = log_cost(
        empty_db,
        model="BAAI/bge-small-en-v1.5",
        purpose="embed",
        tokens_in=12,
        tokens_out=0,
        tokens_cached=0,
        latency_ms=3.5,
        request_id="req-1",
    )
    assert contract_errors("CostLogEntry", entry) == []
    assert entry["cost_usd"] == 0.0
    row = empty_db.execute("SELECT model, purpose, tokens_in, cost_usd FROM cost_log").fetchone()
    assert row[:3] == ("BAAI/bge-small-en-v1.5", "embed", 12)


def test_fake_embedder_is_deterministic_normalised_384d():
    e = get_embedder("fake")
    a, b = e.embed(["death row phenomenon", "death row phenomenon"])
    assert a == b and len(a) == e.dim == 384
    assert sum(x * x for x in a) == pytest.approx(1.0)
    near, far = e.embed(["death row extradition", "freedom of the press"])
    cos = lambda u, v: sum(x * y for x, y in zip(u, v, strict=True))  # noqa: E731
    assert cos(a, near) > cos(a, far)
    assert e.count_tokens("Death row, extradition!") == 3
    assert get_embedder("fake") is get_embedder("fake")


@pytest.mark.ml
def test_real_embedder_shape_and_norm():
    e = get_embedder("BAAI/bge-small-en-v1.5")
    (v,) = e.embed(["extradition to face death row"])
    assert len(v) == e.dim == 384
    assert sum(x * x for x in v) == pytest.approx(1.0, abs=1e-4)
    assert e.count_tokens("extradition to face death row") > 3
