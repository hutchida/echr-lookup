"""End-to-end through the real modules on a tiny corpus (fake embedder, fake LLM)."""

import psycopg
import pytest
from fastapi.testclient import TestClient

from api.main import app
from api.tests.helpers import MIAH
from rag import index
from rag.contract import contract_errors, load_fixture


@pytest.fixture
def real_client(test_database_url, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", test_database_url)
    monkeypatch.setenv("RERANKER", "fake")
    monkeypatch.setenv("RERANK_ENABLED", "1")
    detail = load_fixture("CaseDetail")
    embedder = index.get_embedder("fake")
    with psycopg.connect(test_database_url) as conn:
        index.reset(conn)
        index.upsert_document(conn, detail["document"], detail["paragraphs"])
        for strategy in ("fixed", "recursive", "by_section"):
            chunks = [
                {
                    "id": f"{MIAH}:{strategy}:{i}",
                    "doc_id": MIAH,
                    "strategy": strategy,
                    "text": p["text"],
                    "paragraph_ids": [p["id"]],
                    "token_count": embedder.count_tokens(p["text"]),
                }
                for i, p in enumerate(detail["paragraphs"])
            ]
            vectors = embedder.embed([c["text"] for c in chunks])
            index.replace_chunks(conn, MIAH, strategy, chunks, vectors, embedder.model_name)
        conn.commit()
    with TestClient(app, raise_server_exceptions=False) as client:
        yield client


@pytest.mark.parametrize("mode", ["bm25", "vector", "hybrid", "hybrid_rerank"])
def test_search_through_the_real_pipeline(real_client, mode):
    res = real_client.post(
        "/search",
        json={"query": "Bangladesh deportation", "mode": mode, "chunking": "recursive", "k": 3},
    )
    assert res.status_code == 200, res.text
    assert contract_errors("SearchResult", res.json()) == []
    hits = res.json()["hits"]
    assert hits
    assert (hits[0]["scores"]["rerank_score"] is not None) == (mode == "hybrid_rerank")


@pytest.mark.parametrize("route", ["rag", "stats"])
def test_ask_forced_routes_return_contract_valid_answers(real_client, route):
    res = real_client.post(
        "/ask",
        json={
            "question": "How many decisions were declared inadmissible?",
            "options": {"route": route},
        },
    )
    assert res.status_code == 200, res.text
    assert contract_errors("Answer", res.json()) == []
    assert res.json()["route"] == route


def test_ask_through_the_real_pipeline_with_a_fake_llm(real_client):
    res = real_client.post("/ask", json={"question": "Why was the application inadmissible?"})
    assert res.status_code == 200, res.text
    assert contract_errors("Answer", res.json()) == []
    assert res.headers["x-request-id"] == res.json()["request_id"]


def test_stats_and_case_read_what_ingest_wrote(real_client):
    stats = real_client.get("/stats")
    assert contract_errors("CorpusStats", stats.json()) == []
    assert stats.json()["totals"]["documents"] == 1
    case = real_client.get(f"/case/{MIAH}")
    assert case.json() == load_fixture("CaseDetail")
    # search/ask logged embedding/LLM cost rows through log_cost; /costs must still validate
    assert contract_errors("CostSummary", real_client.get("/costs").json()) == []
