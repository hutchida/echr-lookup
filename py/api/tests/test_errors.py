"""Every error (404, 405, 422, 500, 503) is an `ApiError` with a request_id and headers."""

import pytest

from api.tests.helpers import MIAH
from rag import answer as rag_answer
from rag import search as rag_search
from rag.contract import contract_errors, load_fixture


def assert_api_error(res, status: int, error: str) -> dict:
    assert res.status_code == status, res.text
    body = res.json()
    assert contract_errors("ApiError", body) == [], body
    assert body["error"] == error
    assert body["request_id"] and body["request_id"] == res.headers["x-request-id"]
    assert "server-timing" in res.headers
    return body


def test_unknown_case_is_not_found(client):
    body = assert_api_error(client.get("/case/001-99999"), 404, "not_found")
    assert body["detail"] == load_fixture("ApiError")["detail"]


def test_unknown_eval_run_is_not_found(client):
    assert_api_error(client.get("/eval-runs/nope"), 404, "not_found")


def test_unknown_route_is_not_found(client):
    body = assert_api_error(client.get("/nope"), 404, "not_found")
    assert "/nope" in body["detail"]


def test_wrong_method_is_405(client):
    assert_api_error(client.get("/search"), 405, "method_not_allowed")
    assert_api_error(client.post("/stats", json={}), 405, "method_not_allowed")


@pytest.mark.parametrize(
    ("path", "body"),
    [
        ("/search", {"query": "x", "mode": "fuzzy", "chunking": "fixed", "k": 5}),
        ("/search", {"query": "", "mode": "bm25", "chunking": "fixed", "k": 5}),
        ("/search", {"query": "x", "mode": "bm25", "chunking": "fixed", "k": 51}),
        ("/search", {"query": "x", "mode": "bm25", "chunking": "fixed"}),
        ("/search", {"query": "x", "mode": "bm25", "chunking": "fixed", "k": 5, "extra": 1}),
        ("/search", ["not", "an", "object"]),
        ("/ask", {}),
        ("/ask", {"question": "x" * 501}),
        ("/ask", {"question": "ok", "options": {"route": "sometimes"}}),
    ],
)
def test_invalid_bodies_are_422_api_errors(client, path, body):
    res = client.post(path, json=body)
    detail = assert_api_error(res, 422, "validation_error")["detail"]
    assert detail


def test_invalid_body_never_reaches_the_pipeline(client, monkeypatch):
    def boom(*args, **kwargs):
        raise AssertionError("should not be called")

    monkeypatch.setattr(rag_search, "search", boom)
    monkeypatch.setattr(rag_answer, "answer", boom)
    assert client.post("/search", json={"query": "x"}).status_code == 422
    assert client.post("/ask", json={"q": "x"}).status_code == 422


def test_non_json_body_is_422(client):
    res = client.post("/ask", content=b"not json", headers={"content-type": "application/json"})
    assert_api_error(res, 422, "invalid_json")
    assert_api_error(client.post("/search"), 422, "invalid_json")


def test_long_validation_details_stay_within_the_contract(client):
    res = client.post("/search", json={f"bad{i}": "x" * 400 for i in range(10)})
    assert_api_error(res, 422, "validation_error")
    assert len(res.json()["detail"]) <= 500


def test_bug_in_the_pipeline_is_a_500_api_error(client, monkeypatch):
    def boom(conn, request, **kwargs):
        raise RuntimeError("secret internal detail")

    monkeypatch.setattr(rag_search, "search", boom)
    res = client.post("/search", json=load_fixture("SearchRequest"))
    body = assert_api_error(res, 500, "internal_error")
    assert "secret internal detail" not in res.text
    assert body["detail"]


def test_ask_failure_keeps_the_cost_rows_it_logged(client, monkeypatch, app_env):
    import psycopg

    def half_done(conn, request, **kwargs):
        conn.execute(
            "INSERT INTO cost_log VALUES ('spent', now(), 'm', 'route', 1, 1, 0, 0.5, 5, 'r')"
        )
        raise RuntimeError("generation failed")

    monkeypatch.setattr(rag_answer, "answer", half_done)
    assert_api_error(client.post("/ask", json={"question": "q"}), 500, "internal_error")
    with psycopg.connect(app_env) as conn:
        assert conn.execute("SELECT count(*) FROM cost_log WHERE id = 'spent'").fetchone()[0] == 1


def test_database_down_is_503(client, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", "postgresql://x:y@127.0.0.1:1/none")
    assert_api_error(client.get("/stats"), 503, "database_unavailable")
    assert_api_error(client.get(f"/case/{MIAH}"), 503, "database_unavailable")


def test_error_request_id_comes_from_the_caller_when_valid(client):
    res = client.get("/case/001-99999", headers={"X-Request-ID": "web-abc_123"})
    assert res.headers["x-request-id"] == "web-abc_123"
    assert res.json()["request_id"] == "web-abc_123"


def test_database_without_tables_is_503_with_a_hint(app_env, client):
    import psycopg

    with psycopg.connect(app_env) as conn:
        conn.execute("ALTER TABLE documents RENAME TO documents_away")
        conn.commit()
    try:
        body = assert_api_error(client.get("/stats"), 503, "database_not_ready")
        assert "ingest" in body["detail"]
    finally:
        with psycopg.connect(app_env) as conn:
            conn.execute("ALTER TABLE documents_away RENAME TO documents")
            conn.commit()
