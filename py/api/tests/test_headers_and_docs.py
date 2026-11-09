"""Headers on every response, CORS, the model lifecycle, and the OpenAPI docs."""

import re

import pytest

from api.main import app
from api.openapi import DEMO_QUESTIONS
from rag import index
from rag import search as rag_search
from rag.contract import contract_errors, load_fixture

ENDPOINTS = ["/health", "/stats", "/costs", "/ingest-runs", "/eval-runs", "/case/001-98645"]


@pytest.mark.parametrize("path", [*ENDPOINTS, "/nope", "/case/missing"])
def test_every_response_has_request_id_and_timing(client, path):
    res = client.get(path)
    assert re.fullmatch(r"req-[0-9a-f]{16}", res.headers["x-request-id"])
    assert re.fullmatch(r"app;dur=\d+\.\d", res.headers["server-timing"])


def test_request_ids_are_unique(client):
    ids = {client.get("/costs").headers["x-request-id"] for _ in range(5)}
    assert len(ids) == 5


def test_unsafe_incoming_request_id_is_replaced(client):
    res = client.get("/costs", headers={"X-Request-ID": "bad id\twith spaces" + "x" * 100})
    assert re.fullmatch(r"req-[0-9a-f]{16}", res.headers["x-request-id"])


@pytest.mark.parametrize("origin", ["http://localhost:3000", "http://localhost:3100"])
def test_cors_allows_the_web_app(client, origin):
    res = client.options(
        "/ask",
        headers={
            "Origin": origin,
            "Access-Control-Request-Method": "POST",
            "Access-Control-Request-Headers": "content-type",
        },
    )
    assert res.status_code == 200
    assert res.headers["access-control-allow-origin"] == origin

    simple = client.get("/stats", headers={"Origin": origin})
    assert simple.headers["access-control-allow-origin"] == origin
    exposed = simple.headers["access-control-expose-headers"].lower()
    assert "x-request-id" in exposed and "server-timing" in exposed


def test_cors_rejects_other_origins(client):
    res = client.get("/stats", headers={"Origin": "http://evil.example"})
    assert "access-control-allow-origin" not in res.headers


def test_error_responses_carry_cors_headers(client):
    res = client.get("/case/nope", headers={"Origin": "http://localhost:3100"})
    assert res.status_code == 404
    assert res.headers["access-control-allow-origin"] == "http://localhost:3100"


def test_models_load_once_at_startup_not_per_request(app_env, monkeypatch):
    from fastapi.testclient import TestClient

    loaded = {"embedder": 0, "reranker": 0}

    def get_embedder(name=None):
        loaded["embedder"] += 1
        return "embedder"

    def get_reranker(name=None):
        loaded["reranker"] += 1
        return "reranker"

    monkeypatch.setattr(index, "get_embedder", get_embedder)
    monkeypatch.setattr(rag_search, "get_reranker", get_reranker)
    monkeypatch.setattr(rag_search, "search", lambda conn, r, **kw: load_fixture("SearchResult"))
    monkeypatch.setenv("RERANK_ENABLED", "1")

    with TestClient(app) as client:
        assert loaded == {"embedder": 1, "reranker": 1}
        for _ in range(3):
            assert client.post("/search", json=load_fixture("SearchRequest")).status_code == 200
        assert client.app.state.embedder == "embedder"
        assert client.app.state.reranker == "reranker"
    assert loaded == {"embedder": 1, "reranker": 1}


def test_reranker_is_skipped_when_rerank_is_disabled(app_env, monkeypatch):
    from fastapi.testclient import TestClient

    monkeypatch.setattr(rag_search, "get_reranker", lambda name=None: pytest.fail("loaded"))
    monkeypatch.setenv("RERANK_ENABLED", "0")
    with TestClient(app) as client:
        assert client.app.state.reranker is None


# --- OpenAPI --------------------------------------------------------------------------------


@pytest.fixture
def spec(client):
    return client.get("/openapi.json").json()


def walk(node):
    if isinstance(node, dict):
        yield node
        for v in node.values():
            yield from walk(v)
    elif isinstance(node, list):
        for v in node:
            yield from walk(v)


def test_docs_page_loads(client):
    res = client.get("/docs")
    assert res.status_code == 200 and "swagger" in res.text.lower()


def test_every_ref_in_the_spec_resolves(spec):
    schemas = spec["components"]["schemas"]
    refs = {n["$ref"] for n in walk(spec) if "$ref" in n}
    assert refs
    for ref in refs:
        assert ref.startswith("#/components/schemas/"), ref
        assert ref.rsplit("/", 1)[1] in schemas, ref
    assert "HTTPValidationError" not in schemas


def test_every_operation_has_a_summary_and_documented_errors(spec):
    for path, ops in spec["paths"].items():
        for method, op in ops.items():
            assert op.get("summary"), (method, path)
            if path != "/health":
                assert "500" in op["responses"], (method, path)


@pytest.mark.parametrize(
    ("path", "method", "schema"),
    [
        ("/search", "post", "SearchResult"),
        ("/ask", "post", "Answer"),
        ("/stats", "get", "CorpusStats"),
        ("/case/{item_id}", "get", "CaseDetail"),
        ("/ingest-runs", "get", "IngestRunList"),
        ("/eval-runs", "get", "EvalRunList"),
        ("/eval-runs/{run_id}", "get", "EvalRun"),
        ("/costs", "get", "CostSummary"),
        ("/health", "get", "Health"),
    ],
)
def test_documented_response_examples_match_the_contract(spec, path, method, schema):
    content = spec["paths"][path][method]["responses"]["200"]["content"]["application/json"]
    assert content["schema"] == {"$ref": f"#/components/schemas/{schema}"}
    for name, example in content["examples"].items():
        assert contract_errors(schema, example["value"]) == [], name


@pytest.mark.parametrize(
    ("path", "schema"), [("/search", "SearchRequest"), ("/ask", "AnswerRequest")]
)
def test_request_examples_are_valid_and_come_from_the_contract(spec, path, schema):
    body = spec["paths"][path]["post"]["requestBody"]["content"]["application/json"]
    assert body["schema"] == {"$ref": f"#/components/schemas/{schema}"}
    assert spec["paths"][path]["post"]["requestBody"]["required"] is True
    assert "fixture" in body["examples"]
    for name, example in body["examples"].items():
        assert contract_errors(schema, example["value"]) == [], name
    assert body["examples"]["fixture"]["value"] == load_fixture(schema)


def test_demo_questions_are_in_the_ask_examples(spec):
    examples = spec["paths"]["/ask"]["post"]["requestBody"]["content"]["application/json"][
        "examples"
    ]
    questions = {e["value"]["question"] for e in examples.values()}
    assert set(DEMO_QUESTIONS.values()) <= questions
