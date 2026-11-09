"""The contract's endpoints. Request bodies are validated against the contract's JSON Schema
(rag.contract), not a second hand-written model, so there is a single source of truth."""

from collections.abc import Callable
from typing import Annotated, Any

import psycopg
from fastapi import APIRouter, Depends, Request

from api import queries
from api.db import get_conn
from api.errors import ApiException
from api.openapi import (
    DEMO_QUESTIONS,
    error_responses,
    example,
    ok,
    request_body,
    response_doc,
)
from rag import answer as rag_answer
from rag import search as rag_search
from rag.contract import contract_errors

router = APIRouter()
Conn = Annotated[psycopg.Connection, Depends(get_conn)]


def contract_body(name: str) -> Callable[[Request], Any]:
    async def dependency(request: Request) -> dict:
        try:
            body = await request.json()
        except ValueError as exc:
            raise ApiException(422, "invalid_json", f"Body is not valid JSON: {exc}") from exc
        errors = contract_errors(name, body)
        if errors:
            more = f" (+{len(errors) - 5} more)" if len(errors) > 5 else ""
            raise ApiException(422, "validation_error", "; ".join(errors[:5]) + more)
        return body

    return dependency


SEARCH_EXAMPLES = {
    "fixture": example("SearchRequest", "Hybrid search with filters (contract fixture)"),
    "bm25": {
        "summary": "Exact-name search",
        "value": {"query": "Soering", "mode": "bm25", "chunking": "recursive", "k": 5},
    },
    "vector": {
        "summary": "Search by meaning",
        "value": {
            "query": "extradition to face death row",
            "mode": "vector",
            "chunking": "recursive",
            "k": 5,
        },
    },
}

ASK_EXAMPLES = {
    "fixture": example("AnswerRequest", "Request with options (contract fixture)"),
    **{
        key: {"summary": f"Demo question: {key}", "value": {"question": question}}
        for key, question in DEMO_QUESTIONS.items()
    },
}


@router.post(
    "/search",
    response_model=None,
    summary="Search the corpus (BM25, vector, fused or reranked)",
    description="Returns ranked chunks with per-method scores and ranks (`SearchResult`).",
    openapi_extra=request_body("SearchRequest", SEARCH_EXAMPLES),
    responses={
        200: ok("Ranked hits", "SearchResult", "Hybrid hits"),
        **error_responses(422, 500, 503),
    },
)
def search(
    request: Request,
    conn: Conn,
    body: Annotated[dict, Depends(contract_body("SearchRequest"))],
) -> dict:
    try:
        return rag_search.search(
            conn,
            body,
            embedder=getattr(request.app.state, "embedder", None),
            reranker=getattr(request.app.state, "reranker", None),
        )
    finally:
        conn.commit()  # keep the cost_log rows the search wrote


@router.post(
    "/ask",
    response_model=None,
    summary="Ask a question: a cited answer, or a SQL count",
    description=(
        "Routes the question to retrieval-augmented generation (`route = rag`) or to SQL over "
        "metadata (`route = stats`), then returns the `Answer` with citations, claim "
        "verification, and per-step cost. `X-Request-ID` equals `Answer.request_id`."
    ),
    openapi_extra=request_body("AnswerRequest", ASK_EXAMPLES),
    responses={
        200: response_doc(
            "A cited answer",
            "Answer",
            {
                "rag": example("Answer", "Explanation with cited paragraphs"),
                "stats": example("Answer.stats", "Counting question answered with SQL"),
                "refused": example("Answer.refused", "Sources do not answer the question"),
            },
        ),
        **error_responses(422, 500, 503),
    },
)
def ask(
    request: Request,
    conn: Conn,
    body: Annotated[dict, Depends(contract_body("AnswerRequest"))],
) -> dict:
    try:
        result = rag_answer.answer(
            conn,
            body,
            embedder=getattr(request.app.state, "embedder", None),
            reranker=getattr(request.app.state, "reranker", None),
        )
    finally:
        conn.commit()  # keep the cost_log rows, even if a later step failed
    request.state.request_id = result.get("request_id") or request.state.request_id
    return result


@router.get(
    "/stats",
    response_model=None,
    summary="Corpus counts, last ingest run, running cost and latest eval",
    responses={
        200: ok("Corpus statistics", "CorpusStats", "Snapshot"),
        **error_responses(500, 503),
    },
)
def stats(conn: Conn) -> dict:
    return queries.corpus_stats(conn)


@router.get(
    "/case/{item_id}",
    response_model=None,
    summary="One document with all its paragraphs, in order",
    responses={
        200: ok("The case", "CaseDetail", "Miah v UK"),
        **error_responses(404, 422, 500, 503),
    },
)
def case(item_id: str, conn: Conn) -> dict:
    found = queries.get_case(conn, item_id)
    if found is None:
        raise ApiException(
            404,
            "not_found",
            f"No document with item_id '{item_id}' in the loaded corpus "
            "(GET /stats shows what is loaded).",
        )
    return found


@router.get(
    "/ingest-runs",
    response_model=None,
    summary="Ingest runs, newest first (at most 50)",
    responses={
        200: ok("Ingest runs", "IngestRunList", "One run"),
        **error_responses(500, 503),
    },
)
def ingest_runs(conn: Conn) -> dict:
    return {"runs": queries.ingest_runs(conn)}


@router.get(
    "/eval-runs",
    response_model=None,
    summary="Eval run summaries, newest first (at most 50)",
    responses={
        200: ok("Eval runs", "EvalRunList", "One run"),
        **error_responses(500, 503),
    },
)
def eval_runs(conn: Conn) -> dict:
    return {"runs": queries.eval_runs(conn)}


@router.get(
    "/eval-runs/{run_id}",
    response_model=None,
    summary="One eval run with per-item results",
    responses={
        200: ok("The eval run", "EvalRun", "Retrieval-only"),
        **error_responses(404, 422, 500, 503),
    },
)
def eval_run(run_id: str, conn: Conn) -> dict:
    found = queries.eval_run(conn, run_id)
    if found is None:
        raise ApiException(
            404, "not_found", f"No eval run with run_id '{run_id}' (GET /eval-runs lists them)."
        )
    return found


@router.get(
    "/costs",
    response_model=None,
    summary="Running model cost, from cost_log",
    responses={
        200: ok("Cost summary", "CostSummary", "Local embedding only"),
        **error_responses(500, 503),
    },
)
def costs(conn: Conn) -> dict:
    return queries.cost_summary(conn)
