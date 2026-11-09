"""Transport-only retries in HudocClient: offline, fake transport and fake clock."""

import json

import pytest

from rag.ingest.hudoc import (
    RETRY_BACKOFF,
    HudocBlocked,
    HudocClient,
    HudocTransportError,
    HudocUnavailable,
    RawResponse,
)
from rag.ingest.ratelimit import RateLimiter

from .fakes import FakeClock

OK_BODY = b"<p>1. A document.</p>" * 100


class ScriptedTransport:
    """Answers each fetch from a script: an exception to raise or a RawResponse to return."""

    def __init__(self, script):
        self.script = list(script)
        self.fetches: list[str] = []
        self.refreshes = 0

    def fetch(self, url: str) -> RawResponse:
        self.fetches.append(url)
        step = self.script.pop(0)
        if isinstance(step, Exception):
            raise step
        return step

    def refresh(self) -> None:
        self.refreshes += 1


def ok() -> RawResponse:
    return RawResponse(200, OK_BODY, "text/html")


def boom(msg="`orca eval` failed: Command '['orca', 'eval']' returned non-zero exit status 1."):
    return HudocTransportError(msg)


def make(tmp_path, script):
    clock = FakeClock()
    limiter = RateLimiter(tmp_path, clock=clock.time, sleep=clock.sleep)
    lines: list[str] = []
    transport = ScriptedTransport(script)
    client = HudocClient(
        transport,
        limiter,
        tmp_path / "hudoc-requests.jsonl",
        clock=clock.time,
        sleep=clock.sleep,
        out=lines.append,
    )
    return client, transport, clock, lines


def log_rows(tmp_path):
    return [json.loads(x) for x in (tmp_path / "hudoc-requests.jsonl").read_text().splitlines()]


def test_one_failure_then_success_continues_the_run(tmp_path):
    client, transport, clock, lines = make(tmp_path, [boom(), ok()])
    resp = client.get("/app/conversion/docx/html/body", {"library": "ECHR", "id": "001-1"})
    assert resp.status == 200
    assert len(transport.fetches) == 2 and transport.refreshes == 1
    rows = log_rows(tmp_path)
    assert [(r["status"], r["retry"], r["bytes"]) for r in rows] == [
        (-1, 0, 0),
        (200, 1, len(OK_BODY)),
    ]
    assert rows[0]["url"] == rows[1]["url"]
    assert [r["n"] for r in rows] == [1, 2]
    assert len(lines) == 1
    assert lines[0].startswith("[retry 1/3] orca eval failed (")
    assert lines[0].endswith("waiting 5 s")
    assert clock.sleeps[0] == 5.0


def test_four_failures_stop_after_exactly_four_attempts(tmp_path):
    client, transport, clock, lines = make(tmp_path, [boom(f"failure {i}") for i in range(4)])
    with pytest.raises(HudocUnavailable, match="failure 3"):
        client.get("/app/query/results", {"query": "x"})
    assert len(transport.fetches) == 4 and transport.refreshes == 3
    rows = log_rows(tmp_path)
    assert [(r["status"], r["retry"]) for r in rows] == [(-1, 0), (-1, 1), (-1, 2), (-1, 3)]
    assert len(lines) == 3
    assert [x.split("]")[0] for x in lines] == ["[retry 1/3", "[retry 2/3", "[retry 3/3"]
    assert [x.rsplit("waiting ", 1)[1] for x in lines] == ["5 s", "15 s", "45 s"]
    assert RETRY_BACKOFF == (5.0, 15.0, 45.0)


@pytest.mark.parametrize(
    "block",
    [
        RawResponse(403, b"Forbidden", "text/html"),
        RawResponse(429, b"slow down", "text/html", retry_after="30"),
        RawResponse(200, b"<title>Just a moment...</title>", "text/html"),
        RawResponse(200, b"x", "text/html", cf_mitigated="challenge"),
    ],
)
def test_a_block_is_never_retried(tmp_path, block):
    client, transport, clock, lines = make(tmp_path, [block, ok()])
    with pytest.raises(HudocBlocked):
        client.get("/app/query/results")
    assert len(transport.fetches) == 1 and transport.refreshes == 0
    assert lines == [] and clock.sleeps == []
    assert [r["retry"] for r in log_rows(tmp_path)] == [0]


def test_non_json_search_answer_is_a_block_not_a_retry(tmp_path):
    client, transport, _, lines = make(tmp_path, [RawResponse(200, b"<html>hello</html>")])
    with pytest.raises(HudocBlocked):
        client.search("q", start=0, length=1)
    assert len(transport.fetches) == 1 and lines == []


def test_block_after_a_transport_failure_stops_at_once(tmp_path):
    client, transport, _, _ = make(tmp_path, [boom(), RawResponse(403, b"no"), ok()])
    with pytest.raises(HudocBlocked):
        client.get("/x")
    assert len(transport.fetches) == 2


def test_a_non_transport_unavailable_is_not_retried(tmp_path):
    client, transport, _, lines = make(
        tmp_path, [HudocUnavailable("the `orca` command was not found on PATH")]
    )
    with pytest.raises(HudocUnavailable):
        client.get("/x")
    assert len(transport.fetches) == 1 and lines == []


def test_limiter_spacing_holds_across_retries(tmp_path):
    client, transport, clock, _ = make(tmp_path, [ok(), boom(), boom(), ok(), ok()])
    for _ in range(3):
        client.get("/x")
    stats = client.stats()
    assert stats["requests"] == 5
    assert stats["min_gap_seconds"] >= 1.05 - 1e-6
    assert stats["mean_rate_per_second"] <= 1.0
    assert [r["retry"] for r in log_rows(tmp_path)] == [0, 0, 1, 2, 0]


def test_retries_count_against_the_request_cap(tmp_path):
    from rag.ingest.ratelimit import RequestCapReached

    clock = FakeClock()
    limiter = RateLimiter(tmp_path, clock=clock.time, sleep=clock.sleep, run_cap=2)
    transport = ScriptedTransport([boom(), boom(), ok()])
    client = HudocClient(
        transport, limiter, tmp_path / "log.jsonl", clock=clock.time, sleep=clock.sleep, out=print
    )
    with pytest.raises(RequestCapReached):
        client.get("/x")
    assert len(transport.fetches) == 2


def test_orca_transport_refreshes_the_tab_before_a_retry(monkeypatch):
    from rag.ingest import hudoc

    pages = iter(["page-2", None])
    monkeypatch.setattr(hudoc, "find_hudoc_page", lambda: next(pages))
    transport = hudoc.OrcaTransport("page-1")
    transport.refresh()
    assert transport.page_id == "page-2"
    transport.refresh()
    assert transport.page_id is None  # no tab: ensure_page() will recreate it as before


def test_orca_transport_refresh_survives_a_failing_tab_list(monkeypatch):
    from rag.ingest import hudoc

    def failing():
        raise HudocTransportError("tab list failed")

    monkeypatch.setattr(hudoc, "find_hudoc_page", failing)
    transport = hudoc.OrcaTransport("page-1")
    transport.refresh()
    assert transport.page_id is None


def test_orca_eval_failures_are_transport_errors(monkeypatch):
    import subprocess

    from rag.ingest import hudoc

    def run_fail(*a, **k):
        raise subprocess.CalledProcessError(1, ["orca", "eval"])

    monkeypatch.setattr(hudoc.subprocess, "run", run_fail)
    with pytest.raises(HudocTransportError):
        hudoc._orca_json(["eval", "--expression", "1"])

    def run_timeout(*a, **k):
        raise subprocess.TimeoutExpired(["orca"], 180)

    monkeypatch.setattr(hudoc.subprocess, "run", run_timeout)
    with pytest.raises(HudocTransportError):
        hudoc._orca_json(["eval", "--expression", "1"])

    class Done:
        stdout = "not json"

    monkeypatch.setattr(hudoc.subprocess, "run", lambda *a, **k: Done())
    with pytest.raises(HudocTransportError):
        hudoc._orca_json(["eval", "--expression", "1"])

    def run_missing(*a, **k):
        raise FileNotFoundError("orca")

    monkeypatch.setattr(hudoc.subprocess, "run", run_missing)
    with pytest.raises(HudocUnavailable) as info:
        hudoc._orca_json(["eval"])
    assert not isinstance(info.value, HudocTransportError)


def test_unparseable_eval_result_is_a_transport_error(monkeypatch):
    from rag.ingest import hudoc

    monkeypatch.setattr(hudoc, "_orca_json", lambda args, timeout=180: {"result": {"result": "x"}})
    with pytest.raises(HudocTransportError):
        hudoc.OrcaTransport("p").fetch("/x")
