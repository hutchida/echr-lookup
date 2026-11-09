"""Deterministic canned model outputs for LLM_MODE=fake (tests, CI, offline demos).

The fakes read the prompt they are given, so the whole pipeline (route -> retrieve -> generate ->
verify, or route -> stats) runs end to end with no network and no key. They are NOT a model: the
"answer" just restates the first sentences of the retrieved paragraphs, which is exactly enough to
exercise citation assembly, verification and size caps.
"""

from __future__ import annotations

import json
import re

from rag.answer.llm import LLMResult

_CONTEXT_ENTRY = re.compile(r"^\[([^\]\s]+§[^\]\s]+)\][^\n]*\n([^\n]*)", re.MULTILINE)
UNSUPPORTED_MARKER = "[[unsupported]]"  # tests put this in a claim to make the fake verifier object


def _text_of(messages: list[dict]) -> str:
    parts = []
    for m in messages:
        c = m["content"]
        parts.append(c if isinstance(c, str) else " ".join(b.get("text", "") for b in c))
    return "\n".join(parts)


def _question_of(prompt: str) -> str:
    m = re.search(r"^Question:\s*(.+)$", prompt, re.MULTILINE)
    return m.group(1).strip() if m else prompt.strip()


def _first_sentence(text: str, limit: int = 250) -> str:
    sentence = re.split(r"(?<=[.!?])\s", text.strip(), maxsplit=1)[0]
    return sentence[:limit].rstrip()


def _generate(prompt: str, system: str = "") -> str:
    entries = _CONTEXT_ENTRY.findall(prompt)
    if not entries:
        return json.dumps(
            {
                "not_in_sources": True,
                "message": "The sources provided don't answer this.",
                "claims": [],
            }
        )
    claims = [{"text": _first_sentence(text), "citation_ids": [pid]} for pid, text in entries[:3]]
    if "ANSWER FIRST" in system:  # answer-first prompt: first paragraph is the short answer
        pid, text = entries[0]
        short = {"text": _first_sentence(text), "citation_ids": [pid]}
        points = [
            {**c, "group": "Fake group one" if i < 1 else "Fake group two"}
            for i, c in enumerate(claims[1:] or claims)
        ]
        return json.dumps(
            {"not_in_sources": False, "message": "", "short_answer": short, "claims": points}
        )
    return json.dumps({"not_in_sources": False, "message": "", "claims": claims})


def _verify(prompt: str) -> str:
    claim = re.search(r"^Claim:\s*(.+)$", prompt, re.MULTILINE)
    if claim and UNSUPPORTED_MARKER in claim.group(1):
        return json.dumps({"status": "unsupported", "reason": "Fake verifier: marker present."})
    return json.dumps({"status": "supported", "reason": "Fake verifier: accepted."})


def _stats_params(prompt: str) -> str:
    """Rule-based stand-in for the parameter-extraction model (mirrors PARAMS_SYSTEM's rules)."""
    q = _question_of(prompt).lower()
    params: dict = {"group_by": "none"}
    if re.search(r"deport|expuls|expel|extradit|remov", q):
        params["topic"] = "deportation"
    if "inadmissib" in q:
        params["outcomes"] = (
            ["inadmissible", "partly_inadmissible"] if "partly" in q else ["inadmissible"]
        )
    if re.search(r"at least one violation|any violation|found a violation|with a violation", q):
        params["outcomes"] = ["violation", "mixed"]
    elif re.search(r"no violation", q):
        params["outcomes"] = ["no_violation"]
    if "exhaust" in q:
        params["grounds"] = ["non_exhaustion"]
    if "grand chamber" in q:
        params["chambers"] = ["Grand Chamber"]
    if re.search(r"judgment", q):
        params["doc_types"] = ["judgment"]
    if re.search(r"most common.*(how many|rest on)", q):
        params["count_of"] = "top_group"
    elif re.search(r"how many.+(and|,)\s*how many", q):
        params["count_of"] = "total_and_subset"
    if re.search(r"reason|ground", q):
        params["group_by"] = "reason"
    elif re.search(r"which article|by article|per article", q):
        params["group_by"] = "article"
    elif re.search(r"per year|by year|each year", q):
        params["group_by"] = "year"
    m = re.search(r"article (\d+)", q)
    if m:
        params["articles"] = [m.group(1)]
    return json.dumps(params)


def fake_complete(*, model: str, system: str, messages: list[dict], key: str) -> LLMResult:
    prompt = _text_of(messages)
    if key == "route":
        out = json.dumps({"route": "rag"})
    elif key == "generate":
        out = _generate(prompt, system)
    elif key == "short_rewrite":
        points = re.findall(r"^\d+\. (.+)$", prompt, re.MULTILINE)
        if points:
            out = json.dumps({"short_answer": {"text": points[0], "based_on": [1]}})
        else:
            out = json.dumps({"short_answer": None})
    elif key == "verify":
        out = _verify(prompt)
    elif key == "plan":
        q = _question_of(prompt)
        out = json.dumps(
            {
                "queries": [
                    f"{q} Court reasoning and holding",
                    f"{q} Government argument margin of appreciation",
                ]
            }
        )
    elif key == "stats_params":
        out = _stats_params(prompt)
    else:
        out = json.dumps({"note": f"fake output for {key}"})
    return LLMResult(
        text=out,
        model=model,
        tokens_in=max(1, (len(system) + len(prompt)) // 4),
        tokens_out=max(1, len(out) // 4),
        tokens_cached=0,
        latency_ms=1.0,
    )
