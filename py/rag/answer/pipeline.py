# ruff: noqa: E501
"""`answer()`: question in, neutral cited Answer out (route -> retrieve -> generate -> verify | stats)."""

from __future__ import annotations

import json
import logging
import time
from concurrent.futures import ThreadPoolExecutor

import psycopg
from psycopg.pq import TransactionStatus

from rag.answer import citations as cit
from rag.answer import context, generate, llm, plan, router, stats, verify
from rag.answer.context import Source

log = logging.getLogger(__name__)

ANSWER_MAX_BYTES = 49_000  # contract limit is 50_000
ANSWER_TEXT_MAX_CHARS = 3000
CITATIONS_MAX = 10
NO_VERIFIED_CLAIMS = (
    "No claim could be verified against the cited paragraphs, so no answer is shown."
)
STATS_FAILED = "The statistics query could not be built for this question."


def route(conn, question: str, request_id: str) -> str:
    return router.route(conn, question, request_id)


def run_stats(conn, question: str, request_id: str) -> dict:
    return stats.run_stats(conn, question, request_id)


def _sentence(text: str, ids: list[str], names: dict[str, str]) -> str:
    """Claim text + inline markers, one bracket per case: [Ndidi v UK §21, §74] [Soering v UK §88]."""
    by_doc: dict[str, list[str]] = {}
    for i in ids:
        if i in names:
            by_doc.setdefault(cit.split_paragraph_id(i)[0], []).append(i)
    markers = " ".join(
        f"[{cit.short_case_name(names[group[0]])} "
        + ", ".join(f"§{cit.split_paragraph_id(i)[1]}" for i in group)
        + "]"
        for group in by_doc.values()
    )
    body = text.rstrip().rstrip(".")
    return f"{body} {markers}." if markers else f"{body}."


def assemble_rag(
    claims: list[dict], sources: list[Source], message: str
) -> tuple[str, list[dict], list[dict], bool]:
    """Verified claims -> (answer_text, claims kept, citations, refused).

    Unsupported claims stay in `claims` (with their status) but are left out of answer_text and
    citations. Caps from the contract (3000 chars of text, 10 citations) are enforced here.
    """
    by_id = {s.id: s for s in sources}
    names = {s.id: s.case_name for s in sources}
    placed: list[
        tuple[dict, str]
    ] = []  # (claim, its sentence with citation markers) in answer_text
    cited: dict[str, str] = {}  # paragraph id -> the claim text that cites it first
    kept: list[dict] = []
    length = len(message) + 1 if message else 0
    previous_group: str | None = None
    for claim in claims:
        if claim["status"] == "unsupported":
            kept.append(claim)
            continue
        new_ids = [i for i in claim["citation_ids"] if i not in cited]
        sentence = _sentence(claim["text"], claim["citation_ids"], names)
        heading = claim.get("group")
        cost = len(sentence) + (2 if claim.get("role") else 1)  # a space, or a paragraph break
        if heading and heading != previous_group:
            cost += len(heading) + 3
        over_cap = len(cited) + len(new_ids) > CITATIONS_MAX
        if over_cap and claim.get("role"):
            continue  # over the citation cap: this claim is dropped, later ones may still fit
        if over_cap or length + cost > ANSWER_TEXT_MAX_CHARS:
            break  # out of room: later claims are dropped entirely
        placed.append((claim, sentence))
        length += cost
        if claim.get("role") != "short_answer":
            previous_group = heading
        for i in new_ids:
            cited[i] = claim["text"]
        kept.append(claim)
    citations = [
        {
            "paragraph_id": pid,
            "doc_id": by_id[pid].doc_id,
            "case_name": by_id[pid].case_name[:120],
            "doc_type": by_id[pid].doc_type,
            "quote": cit.best_quote(by_id[pid].text, claim_text),
            "link_target": cit.link_target(pid),
        }
        for pid, claim_text in cited.items()
        if pid in by_id
    ]
    if not placed:
        return NO_VERIFIED_CLAIMS, kept, [], True
    return compose_text(message, placed), kept, citations, False


def compose_text(message: str, placed: list[tuple[dict, str]]) -> str:
    """The answer as plain text: short answer first, then each group's heading and its points.

    Claims without a role (value questions, older answers) are joined by single spaces as before."""
    blocks: list[str] = [message] if message else []
    previous: tuple[str, str | None] | None = None  # (kind, group heading)
    for claim, sentence in placed:
        role, group = claim.get("role"), claim.get("group")
        if role == "short_answer":
            blocks.append(sentence)
            previous = ("short", None)
        elif role is None:
            if blocks:
                blocks[-1] += f" {sentence}"
            else:
                blocks.append(sentence)
        elif previous == ("point", group) and blocks:
            blocks[-1] += f" {sentence}"
        else:
            blocks.append(f"{group}:\n{sentence}" if group else sentence)
            previous = ("point", group)
    return "\n\n".join(blocks)


def _finish(
    question,
    request_id,
    route_name,
    steps,
    started,
    *,
    answer_text,
    claims,
    citations,
    stats_result,
    refused,
) -> dict:
    models: list[str] = []
    for s in steps:
        if s["model"] and s["step"] not in ("rerank", "retrieve") and s["model"] not in models:
            models.append(s["model"])
    result = {
        "request_id": request_id,
        "question": question,
        "route": route_name,
        "answer_text": answer_text,
        "claims": claims,
        "citations": citations,
        "stats": stats_result,
        "refused_or_not_in_sources": refused,
        "steps": steps,
        "total_cost_usd": sum(s["cost_usd"] for s in steps),
        "total_latency_ms": (time.perf_counter() - started) * 1000,
        "models_used": models,
    }
    return enforce_size(result)


def enforce_size(answer: dict, max_bytes: int = ANSWER_MAX_BYTES) -> dict:
    """Keep the payload under the contract's 50 KB by trimming quotes, then rows, then claims."""

    def size() -> int:
        return len(json.dumps(answer, ensure_ascii=False).encode())

    for limit in (200, 120, 60):
        if size() <= max_bytes:
            return answer
        for c in answer["citations"]:
            c["quote"] = c["quote"][:limit]
        if answer["stats"]:
            for c in answer["stats"]["matching_cases"]:
                c["quote"] = c["quote"][:limit]
    while size() > max_bytes and answer["stats"] and answer["stats"]["rows"]:
        answer["stats"]["rows"].pop()
    while size() > max_bytes and len(answer["claims"]) > 1:
        answer["claims"].pop()
    return answer


def _add_to_route_step(steps: list[dict], extra: dict) -> None:
    """Fold the query-planning call into the "route" step (the contract has no separate step)."""
    for s in steps:
        if s["step"] == "route":
            for key in ("tokens_in", "tokens_out", "tokens_cached", "cost_usd", "latency_ms"):
                s[key] += extra[key]
            s["model"] = s["model"] or extra["model"]
            return
    steps.insert(0, extra)


def _add_to_step(steps: list[dict], name: str, extra: dict) -> None:
    for s in steps:
        if s["step"] == name:
            for key in ("tokens_in", "tokens_out", "tokens_cached", "cost_usd", "latency_ms"):
                s[key] += extra[key]
            return


REWRITE_ATTEMPTS = 2
REWRITE_RETRY_BEFORE_S = (
    9.5  # a second rewrite only if the answer is still well inside its time budget
)


def _repair_short_answer(conn, question, claims, sources, request_id, steps, started) -> list[dict]:
    """A short answer the verifier rejected is rewritten from the points that passed (the rewrite
    is verified the same way, and tried again once if there is time). If every rewrite fails, the
    original stays, flagged."""
    if (
        not claims
        or claims[0].get("role") != "short_answer"
        or claims[0]["status"] != "unsupported"
    ):
        return claims
    failed = claims[0]
    for attempt in range(REWRITE_ATTEMPTS):
        if attempt and time.perf_counter() - started > REWRITE_RETRY_BEFORE_S:
            break
        step_started = time.perf_counter()
        try:
            new, result = generate.rewrite_short_answer(
                conn, question, claims[1:], failed, request_id
            )
        except Exception as exc:  # best-effort: the flagged original stays
            log.warning("short-answer rewrite failed (%s: %s)", type(exc).__name__, exc)
            break
        if result is not None:
            _add_to_step(steps, "generate", {
                "tokens_in": result.tokens_in, "tokens_out": result.tokens_out,
                "tokens_cached": result.tokens_cached, "cost_usd": result.cost_usd,
                "latency_ms": (time.perf_counter() - step_started) * 1000,
            })  # fmt: skip
        if new is None:
            log.info("short answer rewrite: no usable rewrite")
            break
        step_started = time.perf_counter()
        (checked,), recheck = verify.verify_claims(conn, [new], sources, request_id)
        elapsed = {"latency_ms": (time.perf_counter() - step_started) * 1000}
        _add_to_step(steps, "verify", recheck | elapsed)
        log.info("short answer rewrite: %s (%s)", checked["status"], checked["reason"])
        if checked["status"] != "unsupported":
            return [checked, *claims[1:]]
        failed = checked  # the next rewrite learns from this rejection
    return claims


def _rag_answer(conn, question, request_id, options, steps, started, embedder, reranker) -> dict:
    value_question = plan.is_value_question(question)
    # Planning (a small-model call) runs while the question itself is searched; its queries are
    # searched as soon as the first search is done.
    with ThreadPoolExecutor(max_workers=1) as pool:
        planned = pool.submit(plan.plan_queries, conn, question, request_id, value=value_question)
        sources, retrieve_steps = context.retrieve(
            conn,
            question,
            options,
            embedder=embedder,
            reranker=reranker,
            extra_queries=lambda: planned.result()[0],
            value_question=value_question,
        )
        _add_to_route_step(steps, planned.result()[1])
    steps.extend(retrieve_steps)
    claims, not_in_sources, message, gen_step = generate.generate(
        conn, question, sources, request_id, value_question=value_question, answer_first=True
    )
    if gen_step:
        steps.append(gen_step)
    if not_in_sources:
        return _finish(
            question, request_id, "rag", steps, started,
            answer_text=message, claims=[], citations=[], stats_result=None, refused=True,
        )  # fmt: skip
    claims, verify_step = verify.verify_claims(conn, claims, sources, request_id)
    steps.append(verify_step)
    claims = _repair_short_answer(conn, question, claims, sources, request_id, steps, started)
    text, claims, citations, refused = assemble_rag(claims, sources, message)
    return _finish(
        question, request_id, "rag", steps, started,
        answer_text=text, claims=claims, citations=citations, stats_result=None, refused=refused,
    )  # fmt: skip


def stats_citations(result: dict) -> list[dict]:
    """The quoted example paragraphs of a stats answer, as citations (cases listed without a quote have none)."""
    keys = ("paragraph_id", "doc_id", "case_name", "doc_type", "quote", "link_target")
    return [{k: c[k] for k in keys} for c in result["matching_cases"] if c["paragraph_id"]]


def _stats_answer(conn, question, request_id, steps, started) -> dict:
    run = stats.run_stats_full(conn, question, request_id)
    steps.extend(run.steps)
    return _finish(
        question, request_id, "stats", steps, started,
        answer_text=run.answer_text, claims=run.claims, citations=stats_citations(run.result),
        stats_result=run.result, refused=False,
    )  # fmt: skip


def answer(conn, request: dict, *, embedder=None, reranker=None) -> dict:
    """AnswerRequest dict -> Answer dict. `embedder` / `reranker` let the API reuse loaded models."""
    started = time.perf_counter()
    request_id = llm.new_request_id()
    question = request["question"]
    options = request.get("options") or {}
    forced = options.get("route") or "auto"
    steps: list[dict] = []
    if forced in ("rag", "stats"):
        chosen = forced
    else:
        chosen, route_step = router.route_with_step(conn, question, request_id)
        steps.append(route_step)

    result = None
    if chosen == "stats":
        try:
            result = _stats_answer(conn, question, request_id, steps, started)
        except (stats.StatsError, psycopg.Error, ValueError) as exc:
            log.warning("stats path failed (%s: %s)", type(exc).__name__, exc)
            if conn.info.transaction_status == TransactionStatus.INERROR:
                conn.rollback()
            if forced == "stats":
                result = _finish(
                    question, request_id, "stats", steps, started,
                    answer_text=STATS_FAILED, claims=[], citations=[], stats_result=None,
                    refused=True,
                )  # fmt: skip
    if result is None:  # route "rag", or an "auto" question whose stats query could not be built
        result = _rag_answer(
            conn, question, request_id, options, steps, started, embedder, reranker
        )
    if not conn.autocommit:
        conn.commit()  # persist the cost_log rows written during this call
    return result
