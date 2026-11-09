"""Every endpoint's success response, validated against the contract's JSON Schema."""

import json

import psycopg
import pytest

from api.tests.helpers import MIAH, SOERING, extra_cost_rows
from rag import answer as rag_answer
from rag import search as rag_search
from rag.contract import contract_errors, load_fixture


def assert_contract(name: str, body) -> None:
    assert contract_errors(name, body) == [], body


# --- /search and /ask (S3 and S4 faked with the contract fixtures) --------------------------


@pytest.fixture
def fake_search(monkeypatch):
    calls = []

    def fake(conn, request, *, embedder=None, reranker=None):
        calls.append({"request": request, "embedder": embedder, "reranker": reranker})
        return load_fixture("SearchResult")

    monkeypatch.setattr(rag_search, "search", fake)
    return calls


@pytest.fixture
def fake_answer(monkeypatch):
    calls = []

    def fake(conn, request, *, embedder=None, reranker=None):
        calls.append(request)
        # Like the real answer(), spend is logged on the passed connection.
        conn.execute(
            "INSERT INTO cost_log VALUES ('cost-from-ask', now(), 'm', 'generate', 1, 1, 0, "
            "0.01, 5, 'req-g0b-fixture-rag')"
        )
        return load_fixture("Answer")

    monkeypatch.setattr(rag_answer, "answer", fake)
    return calls


def test_search_returns_search_result(client, fake_search):
    body = load_fixture("SearchRequest")
    res = client.post("/search", json=body)
    assert res.status_code == 200
    assert_contract("SearchResult", res.json())
    assert fake_search[0]["request"] == body


def test_search_accepts_every_mode_without_filters(client, fake_search):
    for mode in ("bm25", "vector", "hybrid", "hybrid_rerank"):
        res = client.post(
            "/search", json={"query": "Soering", "mode": mode, "chunking": "fixed", "k": 3}
        )
        assert res.status_code == 200, res.text


def test_search_passes_the_models_loaded_at_startup(client, fake_search):
    client.post("/search", json=load_fixture("SearchRequest"))
    assert fake_search[0]["embedder"] is client.app.state.embedder
    assert fake_search[0]["reranker"] is client.app.state.reranker


@pytest.mark.parametrize("fixture", ["Answer", "Answer.stats", "Answer.refused"])
def test_ask_returns_answer(client, monkeypatch, fixture):
    monkeypatch.setattr(rag_answer, "answer", lambda conn, request, **kw: load_fixture(fixture))
    res = client.post("/ask", json=load_fixture("AnswerRequest"))
    assert res.status_code == 200
    assert_contract("Answer", res.json())
    assert res.headers["x-request-id"] == res.json()["request_id"]


def test_ask_forwards_the_request_and_keeps_logged_costs(client, fake_answer, app_env):
    body = {"question": "Does the Convention stop the UK deporting criminals?"}
    assert client.post("/ask", json=body).status_code == 200
    assert fake_answer == [body]
    with psycopg.connect(app_env) as conn:
        rows = conn.execute("SELECT count(*) FROM cost_log WHERE id = 'cost-from-ask'").fetchone()
    assert rows[0] == 1


# --- /stats ---------------------------------------------------------------------------------


def buckets(rows):
    return {b["key"]: b["count"] for b in rows}


def test_stats_matches_contract_and_seeded_counts(client):
    res = client.get("/stats")
    assert res.status_code == 200
    body = res.json()
    assert_contract("CorpusStats", body)

    assert body["data_source"] == "snapshot"
    assert body["totals"]["documents"] == 3
    assert body["totals"]["paragraphs"] == len(load_fixture("CaseDetail")["paragraphs"]) + 2
    assert body["totals"]["chunks"] == {"fixed": 1, "recursive": 2, "by_section": 0}
    assert buckets(body["by_doc_type"]) == {"decision": 1, "judgment": 1, "legislation": 1}
    assert buckets(body["by_outcome"]) == {"inadmissible": 1, "violation": 1, "not_applicable": 1}
    assert buckets(body["by_chamber"]) == {"Chamber": 1, "Grand Chamber": 1, None: 1}
    assert [b["key"] for b in body["by_year"]] == ["1950", "1989", "2010"]
    for key in ("by_doc_type", "by_outcome", "by_chamber", "by_year"):
        assert sum(b["count"] for b in body[key]) == body["totals"]["documents"]


def test_stats_folds_article_sub_paragraphs_and_counts_documents_once(client):
    by_article = client.get("/stats").json()["by_article"]
    # Miah: 3, 7, 8. Soering: 3, 8, 8-1, 14+8, P1-3, 35-3-a.
    assert buckets(by_article) == {"3": 2, "8": 2, "7": 1, "14": 1, "35": 1, "P1-3": 1}
    counts = [b["count"] for b in by_article]
    assert counts == sorted(counts, reverse=True)


def test_stats_reports_latest_runs_and_costs(client):
    body = client.get("/stats").json()
    assert body["last_ingest_run"] == load_fixture("IngestRun")
    latest = body["latest_eval"]
    assert latest["run_id"] == load_fixture("EvalRun")["run_id"]
    assert "items" not in latest and latest["item_count"] == 2
    assert body["costs"] == client.get("/costs").json()


def test_stats_on_an_empty_database(empty_client):
    res = empty_client.get("/stats")
    assert res.status_code == 200
    body = res.json()
    assert_contract("CorpusStats", body)
    assert body["totals"] == {
        "documents": 0,
        "paragraphs": 0,
        "chunks": {"fixed": 0, "recursive": 0, "by_section": 0},
    }
    assert body["last_ingest_run"] is None and body["latest_eval"] is None
    assert body["costs"]["since"] is None and body["costs"]["total_usd"] == 0


# --- /case ----------------------------------------------------------------------------------


def test_case_returns_document_and_paragraphs_exactly_as_ingested(client):
    res = client.get(f"/case/{MIAH}")
    assert res.status_code == 200
    assert_contract("CaseDetail", res.json())
    assert res.json() == load_fixture("CaseDetail")


def test_case_paragraphs_follow_position_not_insertion_order(client):
    res = client.get(f"/case/{SOERING}")
    assert_contract("CaseDetail", res.json())
    assert [p["id"] for p in res.json()["paragraphs"]] == [f"{SOERING}§1", f"{SOERING}§2"]
    assert res.json()["document"]["case_name"] == "SOERING v. THE UNITED KINGDOM"


def test_case_for_a_document_without_paragraphs(client):
    res = client.get("/case/echr-convention")
    assert res.status_code == 200
    assert_contract("CaseDetail", res.json())
    assert res.json()["paragraphs"] == []


# --- lists ----------------------------------------------------------------------------------


def test_ingest_runs_newest_first(client):
    res = client.get("/ingest-runs")
    assert res.status_code == 200
    assert_contract("IngestRunList", res.json())
    assert [r["run_id"] for r in res.json()["runs"]] == [
        load_fixture("IngestRun")["run_id"],
        "older-ingest",
    ]


def test_eval_runs_are_summaries_newest_first(client):
    res = client.get("/eval-runs")
    assert res.status_code == 200
    assert_contract("EvalRunList", res.json())
    runs = res.json()["runs"]
    assert [r["run_id"] for r in runs] == [load_fixture("EvalRun")["run_id"], "older-run"]
    assert all("items" not in r for r in runs)


def test_eval_run_detail_has_items(client):
    run_id = load_fixture("EvalRun")["run_id"]
    res = client.get(f"/eval-runs/{run_id}")
    assert res.status_code == 200
    assert_contract("EvalRun", res.json())
    assert res.json() == load_fixture("EvalRun")


def test_lists_are_capped_at_fifty(client, app_env):
    run = load_fixture("IngestRun")
    with psycopg.connect(app_env) as conn:
        for i in range(60):
            conn.execute(
                "INSERT INTO ingest_runs VALUES (%s, now() - make_interval(secs => %s), %s)",
                (f"bulk-{i}", i, json.dumps({**run, "run_id": f"bulk-{i}"})),
            )
        conn.commit()
    res = client.get("/ingest-runs")
    assert len(res.json()["runs"]) == 50
    assert_contract("IngestRunList", res.json())


# --- /costs ---------------------------------------------------------------------------------


def test_costs_summarise_cost_log(client):
    res = client.get("/costs")
    assert res.status_code == 200
    body = res.json()
    assert_contract("CostSummary", body)

    extra = extra_cost_rows()
    assert body["total_usd"] == pytest.approx(sum(r["cost_usd"] for r in extra))
    assert body["since"] == "2026-11-03T16:34:47Z"
    purposes = {p["purpose"]: p for p in body["by_purpose"]}
    assert purposes["embed"]["calls"] == 4 and purposes["embed"]["tokens_in"] == 4433340
    assert purposes["generate"]["tokens_cached"] == 1000
    assert body["by_purpose"][0]["purpose"] == "generate"  # costliest first
    assert {m["model"] for m in body["by_model"]} == {
        "BAAI/bge-base-en-v1.5",
        "BAAI/bge-small-en-v1.5",
        "claude-sonnet-5-5",
        "claude-haiku-5-5",
    }
    timestamps = [r["timestamp"] for r in body["recent"]]
    assert timestamps == sorted(timestamps, reverse=True)
    assert body["recent"][1]["timestamp"] == "2026-11-03T18:00:00.123Z"


def test_health_is_unchanged(client):
    res = client.get("/health")
    assert res.status_code == 200
    assert_contract("Health", res.json())
