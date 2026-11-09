#!/usr/bin/env python3
"""Token + cost report for opencode sessions (orchestrator and build agents).

Usage: python3 scripts/orchestration/usage.py <label>=<session_id> [...]

Reads `opencode session export` (no estimates). Prices: USD per million tokens from the plan
(docs/orchestration/status.md). Two costs are shown:
  - opencode: opencode's own figure (Copilot price table; cache writes priced at $0)
  - budget:   conservative figure used for the $50 budget (cache writes priced at input rate)
"""

import json
import subprocess
import sys
import tempfile

PRICES = {  # model id -> (input, output, cache_read)
    "claude-opus-5.5": (4.0, 20.0, 0.20),
    "claude-sonnet-5.5": (2.0, 10.0, 0.10),
    "claude-haiku-5.5": (0.10, 0.50, 0.01),
}


def usage(session_id: str) -> dict:
    # opencode truncates large exports written to a pipe, so export to a real file.
    with tempfile.TemporaryFile("w+") as f:
        subprocess.run(["opencode", "session", "export", session_id], stdout=f, check=True)
        f.seek(0)
        info = json.load(f)["info"]
    model = info["model"]["id"]
    t = info["tokens"]
    p_in, p_out, p_cr = PRICES.get(model, (0.0, 0.0, 0.0))
    out_tokens = t["output"] + t.get("reasoning", 0)
    budget = (
        (t["input"] + t["cache"]["write"]) * p_in + out_tokens * p_out + t["cache"]["read"] * p_cr
    ) / 1e6
    created, updated = info["time"]["created"], info["time"]["updated"]
    return {
        "model": f'{info["model"]["providerID"]}/{model}',
        "input": t["input"],
        "output": t["output"],
        "reasoning": t.get("reasoning", 0),
        "cache_read": t["cache"]["read"],
        "cache_write": t["cache"]["write"],
        "cost_opencode": round(info.get("cost", 0.0), 2),
        "cost_budget": round(budget, 2),
        "wall_min": round((updated - created) / 60000, 1),
    }


def main(args: list[str]) -> None:
    rows = {}
    for arg in args:
        label, _, sid = arg.partition("=")
        rows[label] = usage(sid)
    cols = ["model", "input", "output", "reasoning", "cache_read", "cache_write"]
    cols += ["cost_opencode", "cost_budget", "wall_min"]
    print("| task | " + " | ".join(cols) + " |")
    print("|" + "---|" * (len(cols) + 1))
    for label, r in rows.items():
        print(f"| {label} | " + " | ".join(str(r[c]) for c in cols) + " |")
    total = sum(r["cost_budget"] for r in rows.values())
    print(f"\nTotal (budget figure): ${total:.2f}")


if __name__ == "__main__":
    main(sys.argv[1:])
