#!/usr/bin/env python3
"""Cold-start, latency and memory measurements for the echr-deploy stack (stdlib only).

    python3 infra/deploy/measure.py api    # restart the api container, time it, search, sample RAM
    python3 infra/deploy/measure.py mcp    # same for the mcp container (MCP over HTTP, stdlib client)
"""

import json
import statistics
import subprocess
import sys
import threading
import time
import urllib.request

COMPOSE = ["docker", "compose", "-f", "infra/deploy/compose.yml", "-p", "echr-deploy"]
QUERIES = [
    "Can the UK extradite a person who faces the death row phenomenon?",
    "When is detention without trial compatible with Article 5?",
    "Does deportation breach the right to family life?",
    "What is the test for use of lethal force by the state under Article 2?",
    "Are prisoners entitled to vote?",
    "Is a stop and search power without suspicion lawful?",
    "What are the Court's views on corporal punishment in schools?",
    "Positive obligation to investigate deaths in custody",
    "Fair trial and anonymous witnesses",
    "Surveillance by intelligence services and Article 8",
]


def run(cmd):
    return subprocess.run(cmd, check=True, capture_output=True, text=True).stdout.strip()


def post(url, body):
    req = urllib.request.Request(
        url, json.dumps(body).encode(), {"Content-Type": "application/json"}
    )
    with urllib.request.urlopen(req, timeout=120) as r:
        return json.load(r)


class McpClient:
    """Just enough streamable-HTTP MCP (JSON-RPC over POST, JSON or SSE replies) to time the tools."""

    def __init__(self, url):
        self.url, self.session, self.n = url, None, 0

    def rpc(self, method, params=None, notify=False):
        body = {"jsonrpc": "2.0", "method": method, "params": params or {}}
        if not notify:
            self.n += 1
            body["id"] = self.n
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        }
        if self.session:
            headers["Mcp-Session-Id"] = self.session
        req = urllib.request.Request(self.url, json.dumps(body).encode(), headers)
        with urllib.request.urlopen(req, timeout=120) as r:
            self.session = r.headers.get("Mcp-Session-Id") or self.session
            text = r.read().decode()
        if notify or not text.strip():
            return None
        if text.lstrip().startswith("{"):
            return json.loads(text)["result"]
        data = [line[5:].strip() for line in text.splitlines() if line.startswith("data:")]
        return json.loads(data[-1])["result"]

    def start(self):
        self.rpc(
            "initialize",
            {
                "protocolVersion": "2025-06-18",
                "capabilities": {},
                "clientInfo": {"name": "measure", "version": "0"},
            },
        )
        self.rpc("notifications/initialized", notify=True)


def mem_mib(container):
    out = run(["docker", "stats", "--no-stream", "--format", "{{.MemUsage}}", container])
    used = out.split("/")[0].strip()
    num = float("".join(c for c in used if c.isdigit() or c == "."))
    return num * (1024 if "GiB" in used else 1)


def sampler(container, stop, peak):
    while not stop.is_set():
        peak[0] = max(peak[0], mem_mib(container))


def wait_mcp(client, t0, container, limit=300):
    while time.perf_counter() - t0 < limit:
        try:
            client.start()
            return time.perf_counter() - t0
        except Exception:
            client.session = None
            time.sleep(0.1)
            if run(["docker", "inspect", "-f", "{{.State.Status}}", container]) == "exited":
                raise SystemExit(run(["docker", "logs", "--tail", "15", container]))
    raise SystemExit(f"MCP not ready after {limit}s")


def wait_http(url, t0, container, limit=300):
    while time.perf_counter() - t0 < limit:
        try:
            with urllib.request.urlopen(url, timeout=2) as r:
                if r.status == 200:
                    return time.perf_counter() - t0
        except Exception:
            time.sleep(0.1)
            if run(["docker", "inspect", "-f", "{{.State.Status}}", container]) == "exited":
                raise SystemExit(run(["docker", "logs", "--tail", "15", container]))
    raise SystemExit(f"{url} not ready after {limit}s")


def main(service):
    container = f"echr-deploy-{service}-1"
    run(COMPOSE + ["stop", service])
    t0 = time.perf_counter()
    run(COMPOSE + ["up", "-d", "--no-deps", service])
    started = time.perf_counter() - t0
    if service == "api":
        ready = wait_http("http://localhost:8003/health", t0, container)
        search = lambda q: post(  # noqa: E731
            "http://localhost:8003/search",
            {"query": q, "mode": "hybrid_rerank", "chunking": "recursive", "k": 30},
        )
    else:
        client = McpClient("http://localhost:8103/mcp")
        ready = wait_mcp(client, t0, container)
        t = time.perf_counter()
        tools = client.rpc("tools/list")["tools"]
        print(f"{service}: tools/list {time.perf_counter() - t:.2f}s: {', '.join(x['name'] for x in tools)}")

        def search(q):
            res = client.rpc(
                "tools/call", {"name": "search_case_law", "arguments": {"query": q}}
            )
            assert not res.get("isError"), res
            return res["structuredContent"]

    print(f"{service}: container started {started:.2f}s, first /health 200 (MCP: first initialize ok) at {ready:.2f}s")
    time.sleep(5)
    print(f"{service}: RAM idle {mem_mib(container):.0f} MiB")

    t = time.perf_counter()
    first = search(QUERIES[0])
    print(f"{service}: first search {time.perf_counter() - t:.2f}s ({len(first['hits'])} hits)")

    stop, peak = threading.Event(), [0.0]
    th = threading.Thread(target=sampler, args=(container, stop, peak))
    th.start()
    lat = []
    for q in QUERIES * 2:
        t = time.perf_counter()
        search(q)
        lat.append(time.perf_counter() - t)
    stop.set()
    th.join()
    lat.sort()
    print(
        f"{service}: warm search (hybrid_rerank, k=30, n={len(lat)}) "
        f"median {statistics.median(lat):.2f}s min {lat[0]:.2f}s p90 {lat[int(len(lat) * 0.9)]:.2f}s "
        f"max {lat[-1]:.2f}s; peak RAM {peak[0]:.0f} MiB"
    )


main(sys.argv[1] if len(sys.argv) > 1 else "api")
