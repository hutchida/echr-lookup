# ruff: noqa: E501
"""Per-claim citation check: a small model reads ONLY the cited paragraph(s) and judges the claim."""

from __future__ import annotations

import time
from concurrent.futures import ThreadPoolExecutor

from rag import config
from rag.answer import llm
from rag.answer.context import Source, one_line

MAX_WORKERS = 8
REASON_MAX_CHARS = 160
PARAGRAPH_MAX_CHARS = 4000
MAX_TOKENS = 700  # the JSON reply is short, but the model sometimes reasons first; 200 truncated it
MAX_TOKENS_RETRY = 1200

SYSTEM_PROMPT = """You check ONE claim against the paragraph(s) it cites from a European Court of \
Human Rights document. Judge only from the paragraph text shown; never use outside knowledge.

- "supported": the paragraph(s) state the claim, or it follows directly from them, in every substantive \
respect (who, what the Court decided, and any qualification or condition).
- "unsupported": the paragraph(s) do not say it, contradict it, or the claim goes beyond them (it \
overstates, names the wrong case or party, reports a different outcome, or presents an applicant's or \
the Government's argument as the Court's finding).

Reply with only JSON, and keep the reason to one short sentence (under 25 words): \
{"status": "supported" | "unsupported", "reason": "<one short sentence>"}"""

SHORT_ANSWER_RULES = """

THIS CLAIM IS A SHORT ANSWER to the user's question. It may summarise the cited paragraphs TOGETHER: \
judge it against all of them taken as a whole, and accept a plain-words statement of what the Court \
has done, or of the general position, if the paragraphs together support it. It is "unsupported" if it \
adds a fact, a case, an outcome or a qualification that none of the paragraphs support, or states a \
broader rule than they support."""


def _verify_one(
    conn, claim: dict, sources: dict[str, Source], request_id: str
) -> tuple[dict, list[llm.LLMResult]]:
    """-> (claim with status/reason filled in, the LLM results (1 or 2) for cost accounting)."""
    cited = [sources[i] for i in claim["citation_ids"] if i in sources]
    if not cited:
        reason = claim["reason"] if claim["status"] == "unsupported" else "No cited paragraph."
        return {**claim, "status": "unsupported", "reason": reason}, []
    paragraphs = "\n\n".join(
        f"[{s.id}] {s.case_name}\n{one_line(s.text, PARAGRAPH_MAX_CHARS)}" for s in cited
    )
    user = f"Claim: {claim['text']}\n\nCited paragraph(s):\n\n{paragraphs}"
    system = (
        SYSTEM_PROMPT + SHORT_ANSWER_RULES if claim.get("role") == "short_answer" else SYSTEM_PROMPT
    )
    results: list[llm.LLMResult] = []
    try:
        parsed: dict = {}
        for attempt in range(2):  # one retry if the reply is cut off or is not valid JSON
            results.append(
                llm.complete(
                    conn,
                    model=config.verify_model(),
                    system=system,
                    messages=[{"role": "user", "content": user}],
                    purpose="verify",
                    request_id=request_id,
                    max_tokens=MAX_TOKENS if attempt == 0 else MAX_TOKENS_RETRY,
                )
            )
            try:
                parsed = llm.parse_json_object(results[-1].text)
                break
            except ValueError:
                if attempt == 1:
                    raise
        status = parsed.get("status")
        if status not in ("supported", "unsupported"):
            raise ValueError(f"unexpected status {status!r}")
        reason = one_line(str(parsed.get("reason") or ""))[:REASON_MAX_CHARS]
    except Exception as exc:  # verification itself failed: keep the claim, mark it unverified
        reason = f"Verification failed ({type(exc).__name__}); claim kept unverified."
        return {**claim, "status": "unverified", "reason": reason[:REASON_MAX_CHARS]}, results
    return {**claim, "status": status, "reason": reason}, results


def verify_claims(
    conn, claims: list[dict], sources: list[Source], request_id: str
) -> tuple[list[dict], dict]:
    """Verify every claim in parallel. -> (claims with final status, the "verify" StepCost dict)."""
    by_id = {s.id: s for s in sources}
    started = time.perf_counter()
    with ThreadPoolExecutor(max_workers=min(MAX_WORKERS, max(len(claims), 1))) as pool:
        outcomes = list(pool.map(lambda c: _verify_one(conn, c, by_id, request_id), claims))
    results = [r for _, rs in outcomes for r in rs]
    step = {
        "step": "verify",
        "model": config.verify_model(),
        "tokens_in": sum(r.tokens_in for r in results),
        "tokens_out": sum(r.tokens_out for r in results),
        "tokens_cached": sum(r.tokens_cached for r in results),
        "cost_usd": sum(r.cost_usd for r in results),
        "latency_ms": (time.perf_counter() - started) * 1000,
    }
    return [c for c, _ in outcomes], step
