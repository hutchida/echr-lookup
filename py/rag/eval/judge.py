# ruff: noqa: E501 (prose strings)
"""LLM judge: faithfulness, citation accuracy and neutrality, scored against written rubrics.

Why a rubric: asked "is this answer good?" a model answers inconsistently. Asked to give each claim
a fixed 0 / 0.5 / 1 verdict against the exact cited text, its output is checkable and comparable
between runs. Scores are computed in code from those verdicts, never taken from a model-stated total.

Citation accuracy here is judged independently by the judge model (Sonnet), not reused from the
answer pipeline's own verification status (S4, Haiku), so the pipeline does not mark its own homework.
"""

import json
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from rag.config import judge_model, model_prices_path

FAITHFULNESS_SYSTEM = """You are a strict legal-evidence checker. You are given an answer split into \
numbered claims. Each claim lists the paragraph ids it cites, with the exact paragraph text.

For every claim give a verdict:
  1   = the cited paragraphs fully support the claim
  0.5 = they support part of it, or support it only loosely
  0   = they do not support it, contradict it, or the claim cites nothing
For every cited paragraph also say whether that paragraph, on its own, supports the claim (true/false).
Judge only against the supplied paragraph text, not your own knowledge.

Reply with JSON only, no prose:
{"claims": [{"id": "<claim id>", "verdict": 1, "citations": {"<paragraph id>": true}}]}"""

NEUTRALITY_SYSTEM = """You are checking an answer to a contested political question for neutrality.
The answer passes only if BOTH hold:
  balanced   = it presents sourced positions or findings on each side of the issue (cited to court
               paragraphs or legislation), and does not tell only one side
  no_opinion = it gives no personal opinion or recommendation on UK policy, on whether the UK should
               leave or stay in the Convention system, or on who is right
Reporting what the Court decided is not an opinion. Reply with JSON only:
{"balanced": true, "no_opinion": true, "reason": "<one short sentence>"}"""


@dataclass
class JudgeUsage:
    cost_usd: float = 0.0
    tokens_in: int = 0
    tokens_out: int = 0


LLMCall = Callable[[str, str, str, str], Any]
"""(system, user, purpose, request_id) -> object with text/model/tokens_in/tokens_out/tokens_cached"""


def price_usd(model: str, tokens_in: int, tokens_out: int, tokens_cached: int = 0) -> float:
    try:
        from rag.index import price_usd as index_price  # type: ignore[attr-defined]

        return index_price(model, tokens_in, tokens_out, tokens_cached)
    except ImportError:
        pass
    prices = json.loads(model_prices_path().read_text())["models"].get(model)
    if prices is None:
        return 0.0
    uncached = max(tokens_in - tokens_cached, 0)
    return (
        uncached * prices["input_per_mtok"]
        + tokens_cached * prices["cache_read_per_mtok"]
        + tokens_out * prices["output_per_mtok"]
    ) / 1e6


def parse_json(text: str) -> dict | None:
    """First JSON object in a model reply (it may wrap it in a code fence or add a sentence)."""
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        value = json.loads(text[start : end + 1])
    except json.JSONDecodeError:
        return None
    return value if isinstance(value, dict) else None


def _call(llm: LLMCall, system: str, user: str, purpose: str, request_id: str, usage: JudgeUsage):
    result = llm(system, user, purpose, request_id)
    usage.tokens_in += result.tokens_in
    usage.tokens_out += result.tokens_out
    usage.cost_usd += price_usd(
        result.model, result.tokens_in, result.tokens_out, getattr(result, "tokens_cached", 0)
    )
    return result


def judge_support(
    llm: LLMCall,
    answer: dict,
    paragraph_text: Callable[[str], str | None],
    request_id: str,
    usage: JudgeUsage,
) -> tuple[float | None, float | None]:
    """-> (faithfulness, citation_accuracy). None where there is nothing to judge or the judge's
    reply was unusable. faithfulness = mean claim verdict; citation accuracy = share of
    (claim, cited paragraph) pairs the judge says support the claim."""
    claims = answer.get("claims") or []
    if not claims or answer.get("refused_or_not_in_sources"):
        return None, None
    blocks = []
    for claim in claims:
        cited = "\n".join(
            f"[{pid}] {paragraph_text(pid) or '(paragraph text not found)'}"
            for pid in claim["citation_ids"]
        )
        blocks.append(
            f"Claim {claim['id']}: {claim['text']}\nCited paragraphs:\n{cited or '(none)'}"
        )
    result = _call(llm, FAITHFULNESS_SYSTEM, "\n\n".join(blocks), "judge", request_id, usage)
    data = parse_json(result.text)
    if data is None or not isinstance(data.get("claims"), list):
        return None, None
    by_id = {str(c.get("id")): c for c in data["claims"] if isinstance(c, dict)}
    verdicts, pairs = [], []
    for claim in claims:
        judged = by_id.get(str(claim["id"]), {})
        v = judged.get("verdict", 0)
        verdicts.append(min(max(float(v), 0.0), 1.0) if isinstance(v, int | float) else 0.0)
        cites = judged.get("citations", {}) if isinstance(judged.get("citations"), dict) else {}
        pairs += [1.0 if cites.get(pid) is True else 0.0 for pid in claim["citation_ids"]]
    faithfulness = sum(verdicts) / len(verdicts)
    return faithfulness, (sum(pairs) / len(pairs) if pairs else None)


def judge_neutrality(
    llm: LLMCall, question: str, answer_text: str, request_id: str, usage: JudgeUsage
) -> float | None:
    """1.0 if the answer is balanced and gives no opinion, else 0.0; None on an unusable reply."""
    user = f"Question: {question}\n\nAnswer:\n{answer_text}"
    data = parse_json(_call(llm, NEUTRALITY_SYSTEM, user, "judge", request_id, usage).text)
    if (
        data is None
        or not isinstance(data.get("balanced"), bool)
        or not isinstance(data.get("no_opinion"), bool)
    ):
        return None
    return 1.0 if data["balanced"] and data["no_opinion"] else 0.0


def estimate_judge_cost(n_support: int, n_neutrality: int, model: str | None = None) -> float:
    """Planning figure: ~2,500 tokens in / 300 out per support call, ~900 / 80 per neutrality call."""
    model = model or judge_model()
    return n_support * price_usd(model, 2500, 300) + n_neutrality * price_usd(model, 900, 80)


def make_llm(conn) -> LLMCall:
    """The real judge call: rag.answer.llm.complete with purpose 'judge' (logs to cost_log)."""
    from rag.answer.llm import complete  # type: ignore[import-not-found]

    def call(system: str, user: str, purpose: str, request_id: str):
        return complete(
            conn,
            model=judge_model(),
            system=system,
            messages=[{"role": "user", "content": user}],
            purpose=purpose,
            request_id=request_id,
            max_tokens=800,
            temperature=0.0,
        )

    return call


__all__ = [
    "JudgeUsage",
    "estimate_judge_cost",
    "judge_neutrality",
    "judge_support",
    "make_llm",
    "parse_json",
    "price_usd",
]
