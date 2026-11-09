"""Helpers for tests that talk to the server the way Claude does: through an MCP client."""

from __future__ import annotations

import json
import os
import sys
from contextlib import asynccontextmanager
from pathlib import Path

from mcp import Client, StdioServerParameters

from rag.contract import load_fixture

PY_DIR = Path(__file__).resolve().parents[2]

TOOL_FIXTURES: dict[str, str] = {
    "search_case_law": "McpSearchCaseLawInput",
    "get_paragraphs": "McpGetParagraphsInput",
    "get_case": "McpGetCaseInput",
    "count_cases": "McpCountCasesInput",
    "corpus_info": "McpCorpusInfoInput",
    "check_quote": "McpCheckQuoteInput",
}
RESULT_SCHEMAS = {
    "search_case_law": "McpSearchCaseLawResult",
    "get_paragraphs": "McpGetParagraphsResult",
    "get_case": "McpGetCaseResult",
    "count_cases": "McpCountCasesResult",
    "corpus_info": "McpCorpusInfoResult",
    "check_quote": "McpCheckQuoteResult",
}


def fixture_arguments() -> dict[str, dict]:
    return {tool: load_fixture(name) for tool, name in TOOL_FIXTURES.items()}


def server_env(database_url: str, **extra: str) -> dict[str, str]:
    env = {k: v for k, v in os.environ.items() if k != "PYTHONPATH"}
    env.update(DATABASE_URL=database_url, DATA_SOURCE="snapshot", LLM_MODE="fake")
    env.update(extra)
    return env


def stdio_params(database_url: str, **extra: str) -> StdioServerParameters:
    return StdioServerParameters(
        command=sys.executable,
        args=["-m", "echr_mcp", "--transport", "stdio"],
        env=server_env(database_url, **extra),
        cwd=PY_DIR,
    )


@asynccontextmanager
async def stdio_client(database_url: str, **extra: str):
    async with Client(stdio_params(database_url, **extra)) as client:
        yield client


def compact_bytes(structured: dict) -> int:
    return len(json.dumps(structured, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
