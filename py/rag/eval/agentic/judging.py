# ruff: noqa: E501
"""Judge calls for the comparison. `judge_support` is the existing judge, unchanged; this module
wraps it to also keep each claim's verdict, and adds one extra call for the owner-review `judge` checks."""

from collections.abc import Callable
from typing import Any

from rag.eval import judge as judge_mod

from .common import EST_JUDGE_COST, Budget, usd

CHECKS_SYSTEM = """You are checking an answer about European Court of Human Rights case law against \
a list of requirements. For each numbered requirement decide whether the answer meets it. Judge only \
what the answer text says, not whether it is legally right.

Reply with JSON only, no prose:
{"checks": [{"n": 1, "pass": true}]}"""


def budgeted(llm: judge_mod.LLMCall, budget: Budget | None) -> judge_mod.LLMCall:
    """Wrap a judge LLM call so it is refused before it would cross --max-cost and charged after."""

    def call(system: str, user: str, purpose: str, request_id: str) -> Any:
        if budget is not None:
            budget.require(EST_JUDGE_COST, "judge call")
        result = llm(system, user, purpose, request_id)
        if budget is not None:
            budget.charge(
                usd(
                    result.model,
                    result.tokens_in,
                    result.tokens_out,
                    getattr(result, "tokens_cached", 0),
                )
            )
        return result

    return call


def judge_claims(
    llm: judge_mod.LLMCall,
    claims: list[dict],
    paragraph_text: Callable[[str], str | None],
    request_id: str,
) -> dict:
    """Score claims with `judge_support` (unchanged) and read each claim's verdict from the same reply.

    Claim-level = every claim scored on all its citations together (mean verdict, 1 / 0.5 / 0);
    per-citation = share of (claim, citation) pairs the judge says support the claim on their own.
    Claims that cite nothing are not sent (judge_support would score them 0): they are counted in
    `uncited_claims`. -> {...} with None values where there was nothing to judge."""
    cited = [c for c in claims if c["citation_ids"]]
    out: dict = {
        "n_claims": len(claims),
        "uncited_claims": len(claims) - len(cited),
        "claim_verdicts": [],
        "claim_accuracy": None,
        "fully_supported": None,
        "per_citation_accuracy": None,
        "judge_cost_usd": 0.0,
    }
    if not cited:
        return out
    last: dict[str, str] = {}

    def capture(system: str, user: str, purpose: str, rid: str) -> Any:
        result = llm(system, user, purpose, rid)
        last["text"] = result.text
        return result

    usage = judge_mod.JudgeUsage()
    claim_acc, per_cite = judge_mod.judge_support(
        capture, {"claims": cited}, paragraph_text, request_id, usage
    )
    out["judge_cost_usd"] = usage.cost_usd
    data = judge_mod.parse_json(last.get("text", ""))
    if claim_acc is None or data is None:
        return out
    by_id = {str(c.get("id")): c for c in data.get("claims", []) if isinstance(c, dict)}
    verdicts = []
    for claim in cited:
        v = by_id.get(str(claim["id"]), {}).get("verdict", 0)
        verdicts.append(min(max(float(v), 0.0), 1.0) if isinstance(v, int | float) else 0.0)
    out["claim_verdicts"] = [
        {"id": c["id"], "verdict": v} for c, v in zip(cited, verdicts, strict=True)
    ]
    out["claim_accuracy"] = claim_acc
    out["fully_supported"] = sum(v == 1.0 for v in verdicts) / len(verdicts)
    out["per_citation_accuracy"] = per_cite
    return out


def judge_requirements(
    llm: judge_mod.LLMCall,
    question: str,
    answer_text: str,
    requirements: list[str],
    request_id: str,
) -> tuple[list[bool | None], float]:
    """One judge call for all of an answer's prose requirements. -> (pass/fail each, cost USD)."""
    listing = "\n".join(f"{i}. {r}" for i, r in enumerate(requirements, start=1))
    user = f"Question: {question}\n\nAnswer:\n{answer_text}\n\nRequirements:\n{listing}"
    usage = judge_mod.JudgeUsage()
    result = judge_mod._call(llm, CHECKS_SYSTEM, user, "judge", request_id, usage)
    data = judge_mod.parse_json(result.text)
    verdicts: dict[int, bool] = {}
    if data and isinstance(data.get("checks"), list):
        for item in data["checks"]:
            if isinstance(item, dict) and isinstance(item.get("pass"), bool):
                try:
                    verdicts[int(item["n"])] = item["pass"]
                except (KeyError, TypeError, ValueError):
                    continue
    return [verdicts.get(i) for i in range(1, len(requirements) + 1)], usage.cost_usd
