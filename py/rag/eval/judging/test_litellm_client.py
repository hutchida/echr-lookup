import httpx
import pytest

from .litellm_client import LiteLLMJudge, ProxyError, litellm_settings, parse_response

OK_BODY = {
    "choices": [{"finish_reason": "stop", "message": {"content": '{"judgments": []}'}}],
    "usage": {
        "prompt_tokens": 1000,
        "completion_tokens": 40,
        "prompt_tokens_details": {"cached_tokens": 200},
    },
}


class FakeConn:
    def __init__(self):
        self.rows = []

    def execute(self, sql, params):
        assert "INSERT INTO cost_log" in sql
        self.rows.append(params)

    def commit(self):
        pass


def client(handler, conn=None, attempts=3):
    return LiteLLMJudge(
        "vertex-ai-claude-opus-4.8",
        base_url="https://proxy.example",
        api_key="secret-key",
        conn_factory=(lambda: conn) if conn is not None else None,
        http=httpx.Client(transport=httpx.MockTransport(handler)),
        attempts=attempts,
        sleep=lambda s: None,
    )


def test_call_shape_headers_and_cost_logging():
    seen = {}
    conn = FakeConn()

    def handler(request):
        seen["url"], seen["auth"] = str(request.url), request.headers["authorization"]
        seen["body"] = request.read()
        return httpx.Response(200, json=OK_BODY, headers={"x-litellm-response-cost": "0.0123"})

    res = client(handler, conn)(
        "SYS", [{"role": "user", "content": "hi"}], "relevance-q1-r1-a1", 99
    )
    assert seen["url"] == "https://proxy.example/chat/completions"
    assert seen["auth"] == "Bearer secret-key"
    assert b'"role":"system"' in seen["body"] and b"temperature" not in seen["body"]
    assert b'"max_tokens":99' in seen["body"]
    assert res.text == '{"judgments": []}' and res.cost_usd == 0.0123
    assert res.cost_source == "litellm-header"
    assert (res.tokens_in, res.tokens_out, res.tokens_cached) == (800, 40, 200)
    (row,) = conn.rows
    assert row["rid"] == "relevance-q1-r1-a1" and row["cost"] == 0.0123
    assert row["model"] == "vertex-ai-claude-opus-4.8"


def test_missing_cost_header_is_recorded_as_unreported_not_invented():
    res = parse_response(httpx.Response(200, json=OK_BODY), "m", 1.0)
    assert res.cost_usd == 0.0 and res.cost_source == "unreported"


def test_cost_falls_back_to_usage_field():
    body = {**OK_BODY, "usage": {**OK_BODY["usage"], "response_cost": 0.5}}
    res = parse_response(httpx.Response(200, json=body), "m", 1.0)
    assert res.cost_usd == 0.5 and res.cost_source == "usage"


def test_retries_on_429_and_5xx_then_succeeds():
    calls = []

    def handler(request):
        calls.append(1)
        if len(calls) < 3:
            return httpx.Response(429 if len(calls) == 1 else 503, text="busy")
        return httpx.Response(200, json=OK_BODY, headers={"x-litellm-response-cost": "0.01"})

    assert client(handler)("s", [{"role": "user", "content": "x"}], "relevance-x", 10).cost_usd
    assert len(calls) == 3


def test_retries_on_connection_errors_then_gives_up():
    def handler(request):
        raise httpx.ConnectError("down")

    with pytest.raises(ProxyError, match="gave up after 3 attempts"):
        client(handler)("s", [{"role": "user", "content": "x"}], "relevance-x", 10)


def test_client_errors_are_not_retried():
    calls = []

    def handler(request):
        calls.append(1)
        return httpx.Response(400, text="bad param")

    with pytest.raises(ProxyError, match="HTTP 400"):
        client(handler)("s", [{"role": "user", "content": "x"}], "relevance-x", 10)
    assert len(calls) == 1


def test_settings_come_from_the_repo_env_not_the_shell_anthropic_vars(monkeypatch, tmp_path):
    from . import litellm_client

    (tmp_path / ".env").write_text("LITELLM_BASE_URL=https://p.example/\nLITELLM_API_KEY=k1\n")
    monkeypatch.setattr(litellm_client, "REPO_ROOT", tmp_path)
    monkeypatch.setenv("ANTHROPIC_BASE_URL", "https://wrong.example")
    assert litellm_settings() == ("https://p.example", "k1")
