"""Cost logging. Prices come from config/model-prices.json; local models cost $0 but still log."""

import json
import uuid
from datetime import UTC, datetime
from functools import cache

from rag import config


@cache
def _prices() -> dict:
    return json.loads(config.model_prices_path().read_text())["models"]


def price_usd(model: str, tokens_in: int, tokens_out: int, tokens_cached: int) -> float:
    """USD for one request. `tokens_in` = uncached input tokens, `tokens_cached` = cache reads
    (Anthropic reports them separately). A model with a `long_context` tier uses it for the whole
    request when the prompt (input + cached) is over its threshold. Unknown local models
    (fake, or anything not Anthropic) cost 0; an unknown `claude-*` model is an error."""
    entry = _prices().get(model)
    if entry is None:
        if model.startswith("claude-"):
            raise KeyError(f"no price for {model} in {config.model_prices_path()}")
        return 0.0
    tier = entry.get("long_context")
    if tier and tokens_in + tokens_cached > tier["prompt_tokens_over"]:
        entry = tier
    return (
        tokens_in * entry["input_per_mtok"]
        + tokens_out * entry["output_per_mtok"]
        + tokens_cached * entry["cache_read_per_mtok"]
    ) / 1_000_000


def log_cost(
    conn,
    *,
    model: str,
    purpose: str,
    tokens_in: int,
    tokens_out: int,
    tokens_cached: int,
    latency_ms: float,
    request_id: str,
) -> dict:
    """Insert a cost_log row and return it as a CostLogEntry dict. Commits."""
    entry = {
        "id": f"cost-{uuid.uuid4().hex[:16]}",
        "timestamp": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "model": model,
        "purpose": purpose,
        "tokens_in": tokens_in,
        "tokens_out": tokens_out,
        "tokens_cached": tokens_cached,
        "cost_usd": price_usd(model, tokens_in, tokens_out, tokens_cached),
        "latency_ms": float(latency_ms),
        "request_id": request_id,
    }
    conn.execute(
        "INSERT INTO cost_log (id, timestamp, model, purpose, tokens_in, tokens_out, tokens_cached,"
        " cost_usd, latency_ms, request_id) VALUES (%(id)s, %(timestamp)s, %(model)s, %(purpose)s,"
        " %(tokens_in)s, %(tokens_out)s, %(tokens_cached)s, %(cost_usd)s, %(latency_ms)s,"
        " %(request_id)s)",
        entry,
    )
    conn.commit()
    return entry
