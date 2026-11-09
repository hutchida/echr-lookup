# ruff: noqa: E501
"""Decide whether a question is answered by reading sources ("rag") or by counting rows ("stats").

Cheap first: counting words settle the obvious cases with no model call. Only questions with a weak
statistical hint ("how often", "trend", "which cases ...") are sent to the small router model.
Everything else is an explanation question and goes down the RAG path.
"""

from __future__ import annotations

import re
import time

from rag import config
from rag.answer import llm

STRONG_STATS = re.compile(
    r"\b(how many|number of|count of|count the|total number|most common(?:ly)?|"
    r"most frequent(?:ly)?|percentage|percent|proportion|what share|what fraction)\b",
    re.IGNORECASE,
)
WEAK_STATS = re.compile(
    r"\b(how often|how frequent(?:ly)?|statistic(?:s|al)?|trend|per year|over time|"
    r"list (?:all|the|every)|which cases|every case|all (?:the )?cases|majority of|most of)\b",
    re.IGNORECASE,
)

ROUTER_SYSTEM = """You route questions about European Court of Human Rights case law (UK cases).
Answer "stats" if the question asks to COUNT, TABULATE or RANK cases (how many, what share, most common
reason, which year had the most ...). Answer "rag" if it asks what the Court said, held or reasoned,
how a right was applied, or anything needing the text of judgments explained.
Reply with only JSON: {"route": "rag"} or {"route": "stats"}."""


def route_with_step(conn, question: str, request_id: str) -> tuple[str, dict]:
    """-> (route, StepCost-shaped dict for the "route" step)."""
    started = time.perf_counter()
    if STRONG_STATS.search(question):
        return "stats", _step(None, started)
    if not WEAK_STATS.search(question):
        return "rag", _step(None, started)
    result = None
    try:
        result = llm.complete(
            conn,
            model=config.router_model(),
            system=ROUTER_SYSTEM,
            messages=[{"role": "user", "content": f"Question: {question}"}],
            purpose="route",
            request_id=request_id,
            max_tokens=20,
        )
        choice = llm.parse_json_object(result.text).get("route")
    except Exception:  # a failed router call must never break the answer: read the sources
        return "rag", _step(result, started)
    return ("stats" if choice == "stats" else "rag"), _step(result, started)


def route(conn, question: str, request_id: str) -> str:
    return route_with_step(conn, question, request_id)[0]


def _step(result: llm.LLMResult | None, started: float) -> dict:
    return {
        "step": "route",
        "model": result.model if result else None,
        "tokens_in": result.tokens_in if result else 0,
        "tokens_out": result.tokens_out if result else 0,
        "tokens_cached": result.tokens_cached if result else 0,
        "cost_usd": result.cost_usd if result else 0.0,
        "latency_ms": (time.perf_counter() - started) * 1000,
    }
