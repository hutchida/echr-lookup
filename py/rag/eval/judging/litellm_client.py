"""The judge's model client: a LiteLLM gateway, an OpenAI-compatible endpoint.

Why not rag.answer.llm: the Anthropic key's monthly limit was reached, so the judge runs through the
work proxy instead. The client is built explicitly from LITELLM_BASE_URL and LITELLM_API_KEY in the
repo .env (never from the shell's ANTHROPIC_* variables, and never printed). Every call is logged
to cost_log (purpose "judge", request_id "relevance-...") with the cost the proxy reports in the
`x-litellm-response-cost` header; rag.index.log_cost is not used because its price table has no
entry for the proxy's model ids (it would log $0, which would be misleading).
"""

import os
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

import httpx
from dotenv import dotenv_values

from rag.config import REPO_ROOT

COST_HEADER = "x-litellm-response-cost"
RETRY_STATUSES = {408, 409, 425, 429, 500, 502, 503, 504}
TIMEOUT_S = 600.0


@dataclass
class JudgeResult:
    text: str
    model: str
    tokens_in: int  # uncached input
    tokens_out: int
    tokens_cached: int
    latency_ms: float
    cost_usd: float  # as reported by the proxy; 0.0 when it reported none
    cost_source: str  # "litellm-header" | "usage" | "unreported"
    request_id: str = ""
    finish_reason: str | None = None


class ProxyError(RuntimeError):
    """The proxy refused the request or kept failing after retries."""


def litellm_settings() -> tuple[str, str]:
    """(base_url without trailing slash, api key) from the repo .env, or the process environment
    as a fallback (CI). Raises if either is missing."""
    env = dotenv_values(REPO_ROOT / ".env")
    base = env.get("LITELLM_BASE_URL") or os.environ.get("LITELLM_BASE_URL")
    key = env.get("LITELLM_API_KEY") or os.environ.get("LITELLM_API_KEY")
    if not base or not key:
        raise RuntimeError("LITELLM_BASE_URL / LITELLM_API_KEY are not set in the repo .env")
    return base.rstrip("/"), key


def parse_response(resp: httpx.Response, model: str, latency_ms: float) -> JudgeResult:
    data = resp.json()
    choice = (data.get("choices") or [{}])[0]
    text = (choice.get("message") or {}).get("content") or ""
    usage = data.get("usage") or {}
    cached = (usage.get("prompt_tokens_details") or {}).get("cached_tokens") or 0
    cached = cached or usage.get("cache_read_input_tokens") or 0
    prompt = usage.get("prompt_tokens") or 0
    out = usage.get("completion_tokens") or 0
    cost, source = 0.0, "unreported"
    header = resp.headers.get(COST_HEADER)
    try:
        if header is not None and float(header) > 0:
            cost, source = float(header), "litellm-header"
    except ValueError:
        pass
    reported = usage.get("response_cost")
    if source == "unreported" and isinstance(reported, int | float) and reported > 0:
        cost, source = float(reported), "usage"
    return JudgeResult(
        text=text,
        model=model,
        tokens_in=max(prompt - cached, 0),
        tokens_out=out,
        tokens_cached=cached,
        latency_ms=latency_ms,
        cost_usd=cost,
        cost_source=source,
        finish_reason=choice.get("finish_reason"),
    )


class LiteLLMJudge:
    """Callable with the judge's LLMCall shape: (system, messages, request_id, max_tokens)."""

    def __init__(
        self,
        model: str,
        *,
        base_url: str,
        api_key: str,
        conn_factory: Callable[[], Any] | None = None,
        http: httpx.Client | None = None,
        attempts: int = 4,
        sleep: Callable[[float], None] = time.sleep,
    ):
        self.model = model
        self.base_url = base_url
        self._key = api_key
        self._conn_factory = conn_factory
        self._http = http or httpx.Client(timeout=TIMEOUT_S)
        self.attempts = attempts
        self._sleep = sleep

    def __call__(
        self, system: str, messages: list[dict], request_id: str, max_tokens: int
    ) -> JudgeResult:
        body = {
            "model": self.model,
            "messages": [{"role": "system", "content": system}, *messages],
            "max_tokens": max_tokens,
        }  # no temperature: the proxy rejects temperature=0 for this model
        headers = {"Authorization": f"Bearer {self._key}"}
        last = "no attempt made"
        for attempt in range(1, self.attempts + 1):
            started = time.perf_counter()
            try:
                resp = self._http.post(
                    f"{self.base_url}/chat/completions", headers=headers, json=body
                )
            except httpx.TransportError as exc:
                last = f"{type(exc).__name__}: {exc}"
            else:
                if resp.status_code == 200:
                    result = parse_response(resp, self.model, (time.perf_counter() - started) * 1e3)
                    result.request_id = request_id
                    self._log_cost(result)
                    return result
                last = f"HTTP {resp.status_code}: {resp.text[:300]}"
                if resp.status_code not in RETRY_STATUSES:
                    raise ProxyError(last)
            if attempt < self.attempts:
                self._sleep(2.0**attempt)
        raise ProxyError(f"gave up after {self.attempts} attempts; last: {last}")

    def _log_cost(self, r: JudgeResult) -> None:
        if self._conn_factory is None:
            return
        conn = self._conn_factory()
        conn.execute(
            "INSERT INTO cost_log (id, timestamp, model, purpose, tokens_in, tokens_out, "
            "tokens_cached, cost_usd, latency_ms, request_id) VALUES "
            "(%(id)s, %(ts)s, %(model)s, 'judge', %(tin)s, %(tout)s, %(cached)s, %(cost)s, "
            "%(lat)s, %(rid)s)",
            {
                "id": f"cost-{uuid.uuid4().hex[:16]}",
                "ts": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
                "model": r.model,
                "tin": r.tokens_in,
                "tout": r.tokens_out,
                "cached": r.tokens_cached,
                "cost": r.cost_usd,
                "lat": float(r.latency_ms),
                "rid": r.request_id,
            },
        )
        conn.commit()
