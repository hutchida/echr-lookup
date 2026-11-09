"""Streamable HTTP: the server as a subprocess on a free local port, listed and called over HTTP."""

import socket
import subprocess
import sys
import time

import anyio
import psycopg
import pytest
from mcp import Client

from echr_mcp.server import TOOL_SPECS
from echr_mcp.tests.clientkit import PY_DIR, RESULT_SCHEMAS, fixture_arguments, server_env
from rag.contract import contract_errors


def free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="module")
def http_server(seeded_url):
    port = free_port()
    assert port not in (3000, 3100, 8000, 8100)
    proc = subprocess.Popen(
        [sys.executable, "-m", "echr_mcp", "--transport", "http", "--port", str(port)],
        cwd=PY_DIR,
        env=server_env(seeded_url, EMBEDDER="fake", RERANK_ENABLED="0"),
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    deadline = time.time() + 40
    while time.time() < deadline:
        if proc.poll() is not None:
            pytest.fail("the HTTP server exited early")
        try:
            socket.create_connection(("127.0.0.1", port), timeout=0.5).close()
            break
        except OSError:
            time.sleep(0.2)
    else:
        proc.kill()
        pytest.fail("the HTTP server did not start in 40 s")
    yield port
    proc.terminate()
    proc.wait(timeout=10)


def test_list_and_call_over_http(http_server, seeded_url):
    async def run():
        async with Client(f"http://127.0.0.1:{http_server}/mcp") as client:
            tools = [t.name for t in (await client.list_tools()).tools]
            args = fixture_arguments()
            searched = await client.call_tool("search_case_law", args["search_case_law"])
            counted = await client.call_tool("count_cases", args["count_cases"])
            return tools, searched, counted

    tools, searched, counted = anyio.run(run)
    assert tools == list(TOOL_SPECS)
    for name, result in (("search_case_law", searched), ("count_cases", counted)):
        assert not result.is_error
        assert contract_errors(RESULT_SCHEMAS[name], result.structured_content) == []
    with psycopg.connect(seeded_url) as conn:
        transports = conn.execute(
            "SELECT DISTINCT transport FROM tool_log WHERE tool = 'count_cases'"
        ).fetchall()
    assert ("http",) in transports


def test_only_localhost_is_served(http_server):
    """The server binds 127.0.0.1: the loopback address answers, and the Host check is on."""
    import httpx

    response = httpx.post(
        f"http://127.0.0.1:{http_server}/mcp",
        headers={"Host": "evil.example.com", "Accept": "application/json, text/event-stream"},
        json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
    )
    assert response.status_code in (400, 403, 421)
