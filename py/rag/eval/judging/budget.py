"""The optional spend limit, enforced in code before every paid call.

The limit is optional: by default there is none (the judge runs through a LiteLLM gateway
and Dan asked for visibility rather than a cap). With `--soft-limit USD` the running total is read
from cost_log (request_id LIKE 'relevance-%'), so it covers every call ever made under the prefix,
including earlier runs and smoke tests, and a call is refused if total + its estimate would pass it.
"""

import threading
from collections.abc import Callable

from rag.index.cost import price_usd

# List prices (USD per Mtok in, out) from the proxy's /model/info for models that are not in
# config/model-prices.json. The proxy bills about 10% above these for this model (measured), so a
# projection from them is labelled an estimate wherever it is shown.
LIST_PRICES: dict[str, tuple[float, float]] = {"vertex-ai-claude-opus-4.8": (5.0, 25.0)}

SOFT_LIMIT_USD: float | None = None  # no cap unless the CLI is given --soft-limit
REQUEST_PREFIX = "relevance-"
CHARS_PER_TOKEN = 4  # estimate only; the real cost always comes from the API's token counts
OUT_TOKENS_PER_PARAGRAPH = 60  # one JSON object with a one-line reason


class CapExceeded(Exception):
    """The next call could take total spend past the cap; nothing was spent on it."""


def estimate_call_usd(
    model: str, input_chars: int, n_paragraphs: int, *, extra_out_tokens: int = 100
) -> float:
    """Worst-sensible planning figure for one judge call (no cache discount assumed)."""
    tokens_in = input_chars // CHARS_PER_TOKEN
    tokens_out = n_paragraphs * OUT_TOKENS_PER_PARAGRAPH + extra_out_tokens
    if model in LIST_PRICES:
        p_in, p_out = LIST_PRICES[model]
        return (tokens_in * p_in + tokens_out * p_out) / 1e6
    return price_usd(model, tokens_in, tokens_out, 0)


def spent_from_cost_log(conn) -> float:
    row = conn.execute(
        "SELECT coalesce(sum(cost_usd), 0) FROM cost_log WHERE request_id LIKE %s",
        (REQUEST_PREFIX + "%",),
    ).fetchone()
    conn.commit()
    return float(row[0])


class SpendGuard:
    """reserve(estimate) before a call, release(estimate) after it (its real cost is then in the
    cost_log). Reservations cover calls still in flight when several run in parallel."""

    def __init__(self, spent: Callable[[], float], cap: float | None = SOFT_LIMIT_USD):
        self._spent = spent
        self.cap = cap
        self._reserved = 0.0
        self._lock = threading.Lock()

    def reserve(self, estimate: float) -> None:
        if self.cap is None:
            return
        with self._lock:
            spent = self._spent()
            if spent + self._reserved + estimate > self.cap:
                raise CapExceeded(
                    f"spent ${spent:.4f} + in flight ${self._reserved:.4f} + this call "
                    f"${estimate:.4f} would pass the ${self.cap:.2f} limit"
                )
            self._reserved += estimate

    def release(self, estimate: float) -> None:
        if self.cap is None:
            return
        with self._lock:
            self._reserved = max(self._reserved - estimate, 0.0)
