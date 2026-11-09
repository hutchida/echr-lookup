"""The baseline: the existing `/ask` pipeline, called in-process and read-only."""

import time
from collections.abc import Callable
from dataclasses import dataclass, field


@dataclass
class AskRun:
    answer: dict
    fetched_ids: list[str] = field(default_factory=list)
    latency_ms: float = 0.0


def run_ask(conn, question: str, ask_fn: Callable[[dict], dict] | None = None) -> AskRun:
    """`rag.answer.answer(conn, {"question": q})`, and record which paragraphs it put in the
    generation context. The context is observed by wrapping `rag.answer.generate.generate` for the
    duration of the call (it only records its `sources` argument; behaviour is untouched)."""
    seen: list[str] = []
    if ask_fn is not None:
        started = time.perf_counter()
        answer = ask_fn({"question": question})
        return AskRun(answer, seen, (time.perf_counter() - started) * 1000)

    from rag.answer import answer as ask
    from rag.answer import generate

    original = generate.generate

    def recording(conn_, question_, sources, *args, **kwargs):
        for source in sources:
            if source.id not in seen:
                seen.append(source.id)
        return original(conn_, question_, sources, *args, **kwargs)

    generate.generate = recording
    started = time.perf_counter()
    try:
        answer = ask(conn, {"question": question})
    finally:
        generate.generate = original
    return AskRun(answer, seen, (time.perf_counter() - started) * 1000)


def ask_claims(answer: dict) -> list[dict]:
    """The claims `/ask` actually shows: its claims minus those its own verifier marked unsupported
    (those are kept in the data but left out of `answer_text`)."""
    return [
        {
            "id": c["id"],
            "text": c["text"],
            "citation_ids": list(c["citation_ids"]),
            "blockquote": False,
        }
        for c in answer.get("claims", [])
        if c.get("status") != "unsupported"
    ]


def ask_tokens(answer: dict) -> dict:
    steps = answer.get("steps", [])
    return {
        "input": sum(s["tokens_in"] for s in steps),
        "output": sum(s["tokens_out"] for s in steps),
        "cache_read": sum(s["tokens_cached"] for s in steps),
        "cache_write": 0,
        "api_calls": sum(1 for s in steps if s.get("model") and s["tokens_in"] + s["tokens_out"]),
    }
