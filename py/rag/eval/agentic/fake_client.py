"""A scripted stand-in for `anthropic.Anthropic`: no network, deterministic, records every request.

`FakeAnthropic().messages.create(**kwargs)` returns an object shaped like the SDK's Message
(`content` blocks, `usage`, `stop_reason`). What it says comes from `behaviour(kwargs, n)`; the
default one searches, reads two paragraphs, then answers citing what the fixtures returned.
"""

import json
from collections.abc import Callable
from types import SimpleNamespace
from typing import Any

Behaviour = Callable[[dict, int], list[dict]]

FIXTURE_ANSWER = (
    "Not as a general rule: Article 3 is absolute. "
    "[Chahal v. the United Kingdom, Judgment, §79] says the Convention "
    '"prohibits in absolute terms torture or inhuman or degrading treatment or punishment, '
    "irrespective of the victim's conduct\". "
    "This corpus covers UK cases only, and in snapshot mode a small sample."
)


def text(value: str) -> dict:
    return {"type": "text", "text": value}


def tool_use(call_id: str, name: str, args: dict) -> dict:
    return {"type": "tool_use", "id": call_id, "name": name, "input": args}


def _tool_results_seen(messages: list[dict]) -> int:
    """Tool results in the current turn (after the latest question)."""
    count = 0
    for m in reversed(messages):
        if m["role"] != "user":
            continue
        content = m["content"]
        if isinstance(content, str) or content[0].get("type") == "text":
            break
        count += sum(1 for b in content if b.get("type") == "tool_result")
    return count


def _last_question(messages: list[dict]) -> str:
    for m in reversed(messages):
        content = m["content"]
        if m["role"] == "user" and isinstance(content, str):
            return content
        if m["role"] == "user" and content and content[0].get("type") == "text":
            return content[0]["text"]
    return ""


def default_behaviour(kwargs: dict, n: int) -> list[dict]:
    messages = kwargs["messages"]
    seen = _tool_results_seen(messages)
    if kwargs.get("tool_choice", {}).get("type") == "none":
        return [text(FIXTURE_ANSWER)]
    question = _last_question(messages).lower()
    if "how many" in question:
        if seen == 0:
            return [tool_use(f"toolu_{n}", "count_cases", {"group_by": "none"})]
        return [text("The corpus has 10 Grand Chamber judgments; 9 found a violation.")]
    if seen == 0:
        return [tool_use(f"toolu_{n}", "search_case_law", {"query": _last_question(messages)})]
    if seen == 1:
        return [
            tool_use(f"toolu_{n}", "get_paragraphs", {"paragraph_ids": ["001-58004§79"]}),
        ]
    return [text(FIXTURE_ANSWER)]


def always_tool_use(kwargs: dict, n: int) -> list[dict]:
    """A model that never stops calling tools, until the harness forbids them (tool_choice none)."""
    if kwargs.get("tool_choice", {}).get("type") == "none":
        return [text("Final answer after the tool-call limit.")]
    return [tool_use(f"toolu_{n}", "corpus_info", {})]


class FakeAnthropic:
    def __init__(self, behaviour: Behaviour = default_behaviour, *, input_tokens: int = 400):
        self.behaviour = behaviour
        self.requests: list[dict] = []
        self.input_tokens = input_tokens
        self.messages = SimpleNamespace(create=self._create)

    def _create(self, **kwargs: Any) -> SimpleNamespace:
        n = len(self.requests)
        self.requests.append(json.loads(json.dumps(kwargs, default=str)))
        blocks = self.behaviour(kwargs, n)
        uses_tools = any(b["type"] == "tool_use" for b in blocks)
        usage = SimpleNamespace(
            input_tokens=self.input_tokens,
            output_tokens=120,
            cache_read_input_tokens=0 if n == 0 else 2000,
            cache_creation_input_tokens=2000 if n == 0 else 0,
        )
        return SimpleNamespace(
            content=[SimpleNamespace(**b) for b in blocks],
            usage=usage,
            stop_reason="tool_use" if uses_tools else "end_turn",
            model=kwargs.get("model", "claude-sonnet-5-5"),
        )


def fake_judge_llm(system: str, user: str, purpose: str, request_id: str) -> SimpleNamespace:
    """A judge stand-in: every claim fully supported by every citation, every requirement met."""
    import re

    if "numbered claims" in system:
        claims = []
        for m in re.finditer(
            r"^Claim (\S+): .*?\nCited paragraphs:\n(.*?)(?=\n\nClaim |\Z)", user, re.S | re.M
        ):
            ids = re.findall(r"^\[([^\]]+)\]", m.group(2), re.M)
            claims.append({"id": m.group(1), "verdict": 1, "citations": dict.fromkeys(ids, True)})
        reply = {"claims": claims}
    else:
        count = len(re.findall(r"^\d+\. ", user, re.M))
        reply = {"checks": [{"n": i, "pass": True} for i in range(1, count + 1)]}
    return SimpleNamespace(
        text=json.dumps(reply),
        model="claude-sonnet-5-5",
        tokens_in=900,
        tokens_out=60,
        tokens_cached=0,
    )


def fake_ask(request: dict) -> dict:
    """A stand-in for `rag.answer.answer`: one cited claim, the shape of the Answer contract."""
    claim = {
        "id": "c1",
        "text": "Article 3 is absolute, whatever the person has done.",
        "citation_ids": ["001-58004§79"],
        "status": "supported",
        "reason": "",
    }
    return {
        "route": "rag",
        "answer_text": "Article 3 is absolute, whatever the person has done. [Chahal v UK §79]",
        "claims": [claim],
        "citations": [],
        "refused_or_not_in_sources": False,
        "steps": [
            {
                "step": "generate",
                "model": "claude-sonnet-5-5",
                "tokens_in": 3000,
                "tokens_out": 300,
                "tokens_cached": 0,
                "cost_usd": 0.009,
                "latency_ms": 1000.0,
            },
        ],  # fmt: skip
        "total_cost_usd": 0.009,
        "total_latency_ms": 1000.0,
    }
