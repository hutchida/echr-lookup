# ruff: noqa: E501
"""The ONLY place the app calls Anthropic.

Why one door: every model call is retried the same way, logged to `cost_log` the same way, and can
be faked the same way in tests. The client is built explicitly from `rag.config` because the shell
may export ANTHROPIC_BASE_URL for a work proxy; the SDK's env defaults must never be used.
"""

from __future__ import annotations

import importlib
import json
import logging
import re
import threading
import time
import uuid
from dataclasses import dataclass
from typing import Any

import anthropic
from tenacity import (
    before_sleep_log,
    retry,
    retry_if_exception,
    stop_after_attempt,
    wait_exponential_jitter,
)

from rag import config

log = logging.getLogger(__name__)

# System prompts longer than this (characters, ~1000 tokens) are marked for Anthropic prompt caching.
CACHE_MIN_CHARS = 4000

_log_lock = threading.Lock()


@dataclass
class LLMResult:
    text: str
    model: str
    tokens_in: int
    tokens_out: int
    tokens_cached: int
    latency_ms: float
    cost_usd: float = 0.0
    request_id: str = ""


def _retryable(exc: BaseException) -> bool:
    if isinstance(exc, anthropic.APIConnectionError | anthropic.RateLimitError):
        return True
    if isinstance(exc, anthropic.APIStatusError):
        return exc.status_code == 429 or exc.status_code >= 500
    return False


def make_client() -> anthropic.Anthropic:
    """Explicit key and base URL; retries are handled by tenacity below, not by the SDK."""
    key = config.anthropic_api_key()
    if not key:
        raise RuntimeError("ANTHROPIC_API_KEY is not set (repo .env); use LLM_MODE=fake offline")
    return anthropic.Anthropic(
        api_key=key, base_url=config.anthropic_base_url(), max_retries=0, timeout=60.0
    )


@retry(
    retry=retry_if_exception(_retryable),
    stop=stop_after_attempt(4),
    wait=wait_exponential_jitter(initial=1, max=8),
    before_sleep=before_sleep_log(log, logging.WARNING),
    reraise=True,
)
def _create(client: anthropic.Anthropic, **kwargs: Any) -> Any:
    return client.messages.create(**kwargs)


# These models think by default, and thinking tokens would eat max_tokens and add seconds. How to
# turn it off differs per model: Haiku takes "disabled", Sonnet takes "between_tools" (found by
# testing; the API's 400 message names the right value, so we also fall back on it).
_THINKING_OFF: dict[str, dict[str, str]] = {}


def _create_without_thinking(client: anthropic.Anthropic, *, model: str, **kwargs: Any) -> Any:
    preferred = _THINKING_OFF.get(model) or {
        "type": "disabled" if "haiku" in model else "between_tools"
    }
    try:
        resp = _create(client, model=model, thinking=preferred, **kwargs)
    except anthropic.BadRequestError as exc:
        other = "disabled" if preferred["type"] == "between_tools" else "between_tools"
        if "thinking" not in str(exc) and other not in str(exc):
            raise
        preferred = {"type": other}
        resp = _create(client, model=model, thinking=preferred, **kwargs)
    _THINKING_OFF[model] = preferred
    return resp


def _system_blocks(system: str) -> str | list[dict[str, Any]]:
    if len(system) < CACHE_MIN_CHARS:
        return system
    return [{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}]


def _call_live(*, model: str, system: str, messages: list[dict], max_tokens: int) -> LLMResult:
    client = make_client()
    started = time.perf_counter()
    resp = _create_without_thinking(
        client, model=model, system=_system_blocks(system), messages=messages, max_tokens=max_tokens
    )
    latency_ms = (time.perf_counter() - started) * 1000
    text = "".join(b.text for b in resp.content if getattr(b, "type", "") == "text")
    usage = resp.usage
    cached = getattr(usage, "cache_read_input_tokens", 0) or 0
    created = getattr(usage, "cache_creation_input_tokens", 0) or 0
    # Contract: tokens_in = uncached input; cache reads are reported separately and priced lower.
    return LLMResult(
        text=text,
        model=model,
        tokens_in=(usage.input_tokens or 0) + created,
        tokens_out=usage.output_tokens or 0,
        tokens_cached=cached,
        latency_ms=latency_ms,
    )


def complete(
    conn,
    *,
    model: str,
    system: str,
    messages: list[dict],
    purpose: str,
    request_id: str,
    max_tokens: int = 1024,
    temperature: float = 0.0,
    fake_key: str | None = None,
) -> LLMResult:
    """One model call, logged to cost_log. `purpose` is a CostPurpose (route/generate/verify/judge).

    `temperature` is accepted for signature compatibility but not sent: the current Anthropic SDK
    / models take no temperature parameter (sampling is fixed by the API).

    `fake_key` only matters when LLM_MODE=fake: it picks which canned output to return when the
    purpose alone is ambiguous (e.g. stats parameter extraction is logged as "generate").
    """
    if config.llm_mode() == "fake":
        from rag.answer import llm_fake

        result = llm_fake.fake_complete(
            model=model, system=system, messages=messages, key=fake_key or purpose
        )
    else:
        result = _call_live(
            model=model,
            system=system,
            messages=messages,
            max_tokens=max_tokens,
        )
    entry = _log_cost(conn, result, purpose=purpose, request_id=request_id)
    result.cost_usd = float(entry.get("cost_usd", 0.0))
    result.request_id = request_id
    return result


def _log_cost(conn, result: LLMResult, *, purpose: str, request_id: str) -> dict:
    index = importlib.import_module("rag.index")
    with _log_lock:  # verification runs in threads; keep cost_log writes one at a time
        return index.log_cost(
            conn,
            model=result.model,
            purpose=purpose,
            tokens_in=result.tokens_in,
            tokens_out=result.tokens_out,
            tokens_cached=result.tokens_cached,
            latency_ms=result.latency_ms,
            request_id=request_id,
        )


def new_request_id() -> str:
    return f"req-{uuid.uuid4().hex[:12]}"


_FENCE = re.compile(r"^```(?:json)?\s*|\s*```$", re.IGNORECASE)


def parse_json_object(text: str) -> dict:
    """Pull a JSON object out of a model reply (tolerates code fences and surrounding prose)."""
    cleaned = _FENCE.sub("", text.strip())
    try:
        value = json.loads(cleaned)
    except json.JSONDecodeError:
        start, end = cleaned.find("{"), cleaned.rfind("}")
        if start < 0 or end <= start:
            raise ValueError("no JSON object in model reply") from None
        value = json.loads(cleaned[start : end + 1])
    if not isinstance(value, dict):
        raise ValueError("model reply is not a JSON object")
    return value
