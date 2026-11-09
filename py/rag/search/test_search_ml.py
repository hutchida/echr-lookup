"""Real embedder + real reranker. Skipped unless the `ml` group is installed.

Mini corpus (in the test DB): real Soering text from the contract fixtures next to unrelated
synthetic cases, so these run anywhere. `test_real_snapshot_*` additionally run when DATABASE_URL's
database holds the loaded snapshot (scripts/s3/load_snapshot_dev.py or the real ingest)."""

import psycopg
import pytest

from rag.config import database_url
from rag.contract import contract_errors
from rag.index import get_embedder
from rag.index.testing import SYNTHETIC, load_doc
from rag.search import get_reranker, search

pytestmark = pytest.mark.ml

SOERING_ID = "001-57619"


def run(conn, query, mode, **over):
    request = {"query": query, "mode": mode, "chunking": "recursive", "k": 5, **over}
    result = search(
        conn,
        request,
        embedder=get_embedder("BAAI/bge-small-en-v1.5"),
        reranker=get_reranker("BAAI/bge-reranker-base"),
    )
    assert contract_errors("SearchResult", result) == []
    return result


@pytest.fixture
def mini(empty_db):
    emb = get_embedder("BAAI/bge-small-en-v1.5")
    for doc, texts in SYNTHETIC:
        load_doc(empty_db, emb, doc, texts)
    empty_db.execute("ANALYZE")
    empty_db.commit()
    return empty_db


def test_bm25_soering_puts_soering_first(mini):
    # the contract fixtures' Soering chunks say "Mr Soering" in only some chunks
    result = run(mini, "Soering", "bm25")
    assert result["hits"][0]["chunk"]["doc_id"] == SOERING_ID


def test_vector_finds_soering_without_the_word(mini):
    result = run(mini, "extradition to face death row", "vector")
    assert SOERING_ID in {h["chunk"]["doc_id"] for h in result["hits"]}
    assert result["hits"][0]["chunk"]["doc_id"] == SOERING_ID
    assert "soering" not in "extradition to face death row".lower()


def test_hybrid_rerank_returns_reranked_scores(mini):
    result = run(mini, "extradition to face death row", "hybrid_rerank")
    values = [h["scores"]["rerank_score"] for h in result["hits"]]
    assert all(v is not None for v in values)
    assert values == sorted(values, reverse=True)
    assert result["hits"][0]["chunk"]["doc_id"] == SOERING_ID


@pytest.fixture
def snapshot_conn():
    try:
        conn = psycopg.connect(database_url())
        n = conn.execute(
            "SELECT count(*) FROM documents WHERE item_id = %s", (SOERING_ID,)
        ).fetchone()[0]
        has_chunks = conn.execute("SELECT count(*) FROM chunks").fetchone()[0] > 1000
    except psycopg.Error:
        pytest.skip("DATABASE_URL has no loaded snapshot")
    if not n or not has_chunks:
        pytest.skip("snapshot not loaded into DATABASE_URL (scripts/s3/load_snapshot_dev.py)")
    yield conn
    conn.close()


def test_real_snapshot_bm25_soering_first(snapshot_conn):
    assert run(snapshot_conn, "Soering", "bm25")["hits"][0]["chunk"]["doc_id"] == SOERING_ID


def test_real_snapshot_vector_extradition_death_row(snapshot_conn):
    result = run(snapshot_conn, "extradition to face death row", "vector")
    assert SOERING_ID in {h["chunk"]["doc_id"] for h in result["hits"]}


def test_real_snapshot_rerank_scores(snapshot_conn):
    result = run(snapshot_conn, "extradition to face death row", "hybrid_rerank")
    assert all(h["scores"]["rerank_score"] is not None for h in result["hits"])
