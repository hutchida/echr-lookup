"""Shared settings. Reads the repo-root .env (if present) once, then environment variables.

Every runtime knob lives here so the whole app is configured in one place (see .env.example).
"""

import os
from pathlib import Path
from typing import Literal

from dotenv import dotenv_values, load_dotenv

REPO_ROOT = Path(__file__).resolve().parents[2]
load_dotenv(REPO_ROOT / ".env", override=False)

DataSource = Literal["snapshot", "full"]


def database_url() -> str:
    return os.environ.get("DATABASE_URL", "postgresql://echr:echr@localhost:5433/echr")


def data_source() -> DataSource:
    value = os.environ.get("DATA_SOURCE", "snapshot")
    if value not in ("snapshot", "full"):
        raise ValueError(f"DATA_SOURCE must be 'snapshot' or 'full', got {value!r}")
    return value  # type: ignore[return-value]


def data_dir() -> Path:
    return REPO_ROOT / "data" / data_source()


# --- Models (app runtime, not build agents) -------------------------------------------------
# Anthropic model IDs as the Anthropic API names them. Prices: config/model-prices.json.


def answer_model() -> str:
    """Writes the cited answer."""
    return os.environ.get("ANSWER_MODEL", "claude-sonnet-5-5")


def router_model() -> str:
    """Decides explain (RAG) vs count/stat (SQL)."""
    return os.environ.get("ROUTER_MODEL", "claude-haiku-5-5")


def verify_model() -> str:
    """Checks each claim against the paragraph it cites."""
    return os.environ.get("VERIFY_MODEL", "claude-haiku-5-5")


def judge_model() -> str:
    """Eval faithfulness / citation judge."""
    return os.environ.get("JUDGE_MODEL", "claude-sonnet-5-5")


def embedder_name() -> str:
    """Local sentence-transformers model (D-004). 'fake' = deterministic test embedder."""
    return os.environ.get("EMBEDDER", "BAAI/bge-small-en-v1.5")


def reranker_name() -> str:
    return os.environ.get("RERANKER", "BAAI/bge-reranker-base")


def rerank_enabled() -> bool:
    return os.environ.get("RERANK_ENABLED", "1") == "1"


def llm_mode() -> Literal["live", "fake"]:
    """'fake' returns canned responses with no network (tests and CI). 'live' calls Anthropic."""
    value = os.environ.get("LLM_MODE", "live")
    if value not in ("live", "fake"):
        raise ValueError(f"LLM_MODE must be 'live' or 'fake', got {value!r}")
    return value  # type: ignore[return-value]


def model_prices_path() -> Path:
    return REPO_ROOT / "config" / "model-prices.json"


# --- Anthropic connection ---------------------------------------------------------------------
# Build the client ONLY from these two functions: anthropic.Anthropic(api_key=..., base_url=...).
# Never rely on the SDK's environment defaults. A developer shell may export ANTHROPIC_BASE_URL /
# ANTHROPIC_AUTH_TOKEN for a work proxy (Dan's does), which would send our key to that proxy.


def anthropic_api_key() -> str | None:
    """The key in the repo's .env wins over the shell; falls back to the environment (CI)."""
    return dotenv_values(REPO_ROOT / ".env").get("ANTHROPIC_API_KEY") or os.environ.get(
        "ANTHROPIC_API_KEY"
    )


def anthropic_base_url() -> str:
    """Project-specific override only; the shell's ANTHROPIC_BASE_URL is deliberately ignored."""
    return os.environ.get("ECHR_ANTHROPIC_BASE_URL", "https://api.anthropic.com")
