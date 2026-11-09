"""Shared constants, the cost budget and token pricing for the agentic comparison."""

import json
from dataclasses import dataclass, field

from rag.config import REPO_ROOT, model_prices_path

HOST_MODEL = "claude-sonnet-5-5"
MAX_TOOL_CALLS = 8
HOST_MAX_TOKENS = 3000
SUBSET_SEED = 20261104
SUBSET_SIZE = 30
OWNER_REVIEW_PATH = REPO_ROOT / "data" / "eval" / "owner-review.jsonl"
OUT_DIR = REPO_ROOT / "data" / "eval" / "agentic"
SUBSET_PATH = OUT_DIR / "subset.json"
CONTRACT_DIR = REPO_ROOT / "packages" / "contract"

# Planning figures used only to decide whether the next call still fits under --max-cost.
EST_OUTPUT_TOKENS = 1500
EST_ASK_COST = 0.05
EST_JUDGE_COST = 0.02
CHARS_PER_TOKEN = 3.5


class BudgetExceeded(Exception):
    """The next paid call would cross --max-cost; nothing was sent."""


def prices(model: str) -> dict:
    entry = json.loads(model_prices_path().read_text())["models"].get(model)
    if entry is None:
        raise KeyError(f"no price for {model} in {model_prices_path()}")
    return entry


def usd(model: str, uncached_in: int, out: int, cache_read: int = 0, cache_write: int = 0) -> float:
    """Honest cost of one call: cache writes at the write price (cost_log books them at the plain
    input price, so cost_log runs a little lower; see `docs/mcp-comparison.md`)."""
    p = prices(model)
    return (
        uncached_in * p["input_per_mtok"]
        + out * p["output_per_mtok"]
        + cache_read * p["cache_read_per_mtok"]
        + cache_write * p["cache_write_per_mtok"]
    ) / 1e6


@dataclass
class Budget:
    """One cap shared by every paid call (host, /ask, judge). Checked *before* each call."""

    limit: float
    spent: float = 0.0
    skipped: list[dict] = field(default_factory=list)

    def can_afford(self, estimate: float) -> bool:
        return self.spent + estimate <= self.limit

    def require(self, estimate: float, what: str) -> None:
        if not self.can_afford(estimate):
            raise BudgetExceeded(
                f"{what}: ${self.spent:.3f} spent + ~${estimate:.3f} would pass the "
                f"${self.limit:.2f} --max-cost"
            )

    def charge(self, amount: float) -> None:
        self.spent += amount
