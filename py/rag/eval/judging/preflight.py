"""Step 2: cost pre-flight. Projects the judge spend from the real pool before any paid call
(chars / 4 for input tokens; 60 output tokens per paragraph, which covers the JSON and a one-line
reason) at the proxy's list price. It is an ESTIMATE, not the bill: the measured cost is what the
proxy reports per call, read back from cost_log."""

from collections.abc import Sequence

from .budget import SOFT_LIMIT_USD, estimate_call_usd
from .grader import JUDGE_MODEL, SYSTEM_PROMPT, build_user_prompt


def question_estimate(q: dict, model: str = JUDGE_MODEL) -> float:
    entries = [(f"P{i:02d}", p) for i, p in enumerate(q["paragraphs"], start=1)]
    chars = len(SYSTEM_PROMPT) + len(build_user_prompt(q["question"], entries))
    return estimate_call_usd(model, chars, len(q["paragraphs"]))


def cap_pool(pool: Sequence[dict], top_n: int | None) -> list[dict]:
    """Optional pool reduction: keep every original gold paragraph, then fill up to `top_n`
    paragraphs per question by number of configs that found it (best rank breaks ties)."""
    if top_n is None:
        return list(pool)
    out = []
    for q in pool:
        gold = [p for p in q["paragraphs"] if p["gold"]]
        rest = [p for p in q["paragraphs"] if not p["gold"]]  # already sorted by n_configs, rank
        room = max(top_n - len(gold), 0)
        keep = {p["id"] for p in gold + rest[:room]}
        out.append({**q, "paragraphs": [p for p in q["paragraphs"] if p["id"] in keep]})
    return out


def projection(pool: Sequence[dict], recheck_n: int = 15, model: str = JUDGE_MODEL) -> dict:
    """Projected USD for one call per question plus `recheck_n` re-judges of the costliest-average
    questions (re-judge cost = mean per-question cost, a fair stand-in for a random sample)."""
    per_q = [question_estimate(q, model) for q in pool]
    first = sum(per_q)
    mean = first / len(per_q) if per_q else 0.0
    recheck = recheck_n * mean
    return {
        "questions": len(per_q),
        "judge_calls_usd": first,
        "recheck_usd": recheck,
        "total_usd": first + recheck,
        "soft_limit_usd": SOFT_LIMIT_USD,
        "mean_per_question_usd": mean,
    }
