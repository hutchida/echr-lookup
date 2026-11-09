"""The real server as a subprocess over stdio, driven by the SDK's client (fake embedder, no
reranker, seeded test database): what Claude Desktop does, minus the model."""

import json

import anyio
import psycopg
import pytest
from mcp import MCPError

from echr_mcp.server import INSTRUCTIONS, TOOL_SPECS, contract_schema
from echr_mcp.tests.clientkit import (
    RESULT_SCHEMAS,
    compact_bytes,
    fixture_arguments,
    stdio_client,
)
from rag.contract import contract_errors

OFFLINE = {"EMBEDDER": "fake", "RERANK_ENABLED": "0"}
TOOLS = list(TOOL_SPECS)


async def _session(url: str) -> dict:
    out: dict = {"calls": {}}
    async with stdio_client(url, **OFFLINE) as client:
        out["instructions"] = client.instructions
        out["tools"] = (await client.list_tools()).tools
        for name, args in fixture_arguments().items():
            result = await client.call_tool(name, args)
            out["calls"][name] = result
        out["not_found"] = await client.call_tool("get_case", {"case_id": "001-99999"})
        out["bad_args"] = await client.call_tool("search_case_law", {"query": "x", "limit": 99})
        out["extra_arg"] = await client.call_tool("corpus_info", {"nope": 1})
        try:
            await client.call_tool("no_such_tool", {})
        except MCPError as error:
            out["unknown_tool"] = error
    return out


@pytest.fixture(scope="module")
def session(seeded_url):
    with psycopg.connect(seeded_url) as conn:
        conn.execute("DELETE FROM tool_log")
        conn.commit()
    return anyio.run(_session, seeded_url)


def test_lists_exactly_the_six_tools_with_contract_schemas(session):
    tools = {t.name: t for t in session["tools"]}
    assert list(tools) == TOOLS
    for name, (contract, description) in TOOL_SPECS.items():
        tool = tools[name]
        assert tool.description == description
        assert tool.input_schema == contract_schema(f"{contract}Input")
        assert tool.output_schema == contract_schema(f"{contract}Result")
        hints = tool.annotations
        assert (hints.read_only_hint, hints.destructive_hint) == (True, False)
        assert (hints.idempotent_hint, hints.open_world_hint) == (True, False)


def test_server_instructions(session):
    assert session["instructions"] == INSTRUCTIONS
    assert "check_quote" in session["instructions"] and "count_cases" in session["instructions"]


@pytest.mark.parametrize("name", TOOLS)
def test_fixture_arguments_return_valid_small_results(session, name):
    result = session["calls"][name]
    assert not result.is_error, result.content
    structured = result.structured_content
    assert contract_errors(RESULT_SCHEMAS[name], structured) == []
    assert compact_bytes(structured) <= 25_000
    # the text block carries the same JSON for clients that do not read structuredContent
    assert len(result.content) == 1 and json.loads(result.content[0].text) == structured


def test_check_quote_fixture_is_verbatim_over_stdio(session):
    assert session["calls"]["check_quote"].structured_content["verbatim"] is True


def test_tool_errors_are_plain_sentences(session):
    missing = session["not_found"]
    assert missing.is_error
    assert missing.content[0].text == "No case 001-99999 in this corpus (snapshot: 7 UK documents)."
    for key in ("bad_args", "extra_arg"):
        assert session[key].is_error
        assert session[key].content[0].text.startswith("Invalid arguments for ")
    assert "limit" in session["bad_args"].content[0].text


def test_unknown_tool_is_a_protocol_error(session):
    assert "Unknown tool" in str(session["unknown_tool"])


def test_every_call_is_logged_with_transport_stdio(session, seeded_url):
    with psycopg.connect(seeded_url) as conn:
        rows = conn.execute(
            "SELECT tool, ok, error, transport, data_source, result_bytes, latency_ms, args "
            "FROM tool_log ORDER BY id"
        ).fetchall()
    # six fixture calls, then the three failing ones (the unknown tool never reaches a tool)
    assert [r[0] for r in rows] == [*TOOLS, "get_case", "search_case_law", "corpus_info"]
    assert [r[1] for r in rows] == [True] * 6 + [False] * 3
    assert rows[6][2].startswith("No case 001-99999")
    assert {r[3] for r in rows} == {"stdio"} and {r[4] for r in rows} == {"snapshot"}
    assert all(r[5] > 0 and float(r[6]) > 0 for r in rows)
    assert rows[0][7]["query"].startswith("deport a person")
