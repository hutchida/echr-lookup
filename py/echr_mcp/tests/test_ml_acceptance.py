"""Acceptance with the real models on the snapshot database (`pytest -m ml`, local only).

Needs the `ml` uv group and a DATABASE_URL that holds the 98-document snapshot; skips otherwise.
Prints the warm latency of every tool (median of 5 calls, measured by the client over stdio)."""

import statistics
import time

import anyio
import psycopg
import pytest

from echr_mcp.tests.clientkit import (
    RESULT_SCHEMAS,
    compact_bytes,
    fixture_arguments,
    stdio_client,
)
from rag import config
from rag.contract import contract_errors, load_fixture

pytestmark = pytest.mark.ml

REAL_EMBEDDER = "BAAI/bge-small-en-v1.5"  # conftest sets EMBEDDER=fake for the test process
BUDGET_SECONDS = {"search_case_law": 3.0}
DEFAULT_BUDGET = 1.0
WARM_CALLS = 5


@pytest.fixture(scope="module")
def snapshot_url() -> str:
    url = config.database_url()
    try:
        with psycopg.connect(url) as conn:
            have = conn.execute(
                "SELECT count(*) FROM documents WHERE item_id = '001-58004'"
            ).fetchone()[0]
            total = conn.execute("SELECT count(*) FROM documents").fetchone()[0]
    except psycopg.Error as error:
        pytest.skip(f"database not reachable: {error}")
    if not have or total < 90:
        pytest.skip("DATABASE_URL does not hold the 98-document snapshot")
    return url


async def _measure(url: str) -> dict:
    real = {"EMBEDDER": REAL_EMBEDDER, "RERANK_ENABLED": "1"}
    out: dict = {}
    async with stdio_client(url, **real) as client:
        for name, args in fixture_arguments().items():
            first = await client.call_tool(name, args)  # also warms the connection and caches
            times = []
            for _ in range(WARM_CALLS):
                started = time.perf_counter()
                await client.call_tool(name, args)
                times.append(time.perf_counter() - started)
            out[name] = {"result": first, "median": statistics.median(times), "times": times}
        out["_search_all_filters"] = await client.call_tool(
            "search_case_law", load_fixture("McpSearchCaseLawInput.all-filters")
        )
    return out


@pytest.fixture(scope="module")
def measured(snapshot_url):
    return anyio.run(_measure, snapshot_url)


def test_every_result_is_valid_and_small(measured):
    for name, schema in RESULT_SCHEMAS.items():
        result = measured[name]["result"]
        assert not result.is_error, (name, result.content)
        assert contract_errors(schema, result.structured_content) == []
        assert compact_bytes(result.structured_content) <= 25_000
    filtered = measured["_search_all_filters"].structured_content
    assert contract_errors("McpSearchCaseLawResult", filtered) == []
    assert compact_bytes(filtered) <= 25_000


def test_search_finds_chahal_saadi_or_othman(measured):
    hits = measured["search_case_law"]["result"].structured_content["hits"]
    names = ("Chahal", "Saadi", "Othman")
    assert any(n in h["case_name"] for h in hits for n in names), [h["cite"] for h in hits]


def test_check_quote_is_verbatim_and_count_matches_the_snapshot(measured):
    assert measured["check_quote"]["result"].structured_content["verbatim"] is True
    counted = measured["count_cases"]["result"].structured_content
    assert (counted["count"], counted["scope_total"]) == (9, 10)


def test_warm_latencies_are_within_budget(measured, capsys):
    lines = ["tool                 median (s)   result bytes"]
    for name in RESULT_SCHEMAS:
        median = measured[name]["median"]
        size = compact_bytes(measured[name]["result"].structured_content)
        lines.append(f"{name:<20} {median:>10.3f}   {size:>12}")
    with capsys.disabled():
        print("\n" + "\n".join(lines))
    for name in RESULT_SCHEMAS:
        assert measured[name]["median"] < BUDGET_SECONDS.get(name, DEFAULT_BUDGET), name
