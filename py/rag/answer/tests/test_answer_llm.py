# ruff: noqa: E501
import json

import pytest

from rag import config
from rag.answer import llm


def test_fake_mode_makes_no_client(answer_db, monkeypatch):
    def no_client():
        raise AssertionError("fake mode must not build an Anthropic client")

    monkeypatch.setattr(llm, "make_client", no_client)
    r = llm.complete(
        answer_db,
        model="claude-haiku-5-5",
        system="s",
        messages=[{"role": "user", "content": "Question: hi"}],
        purpose="route",
        request_id="req-t",
    )
    assert json.loads(r.text) == {"route": "rag"}
    assert r.tokens_in > 0 and r.cost_usd > 0 and r.request_id == "req-t"
    assert answer_db.execute("SELECT purpose, model FROM cost_log").fetchall() == [
        ("route", "claude-haiku-5-5")
    ]


def test_fake_output_is_deterministic(answer_db):
    kw = dict(
        model="m",
        system="s",
        messages=[{"role": "user", "content": "Question: x\n\n"}],
        purpose="generate",
        request_id="r",
    )
    assert llm.complete(answer_db, **kw).text == llm.complete(answer_db, **kw).text


def test_client_is_built_explicitly_from_config(monkeypatch):
    seen = {}

    class FakeAnthropic:
        def __init__(self, **kw):
            seen.update(kw)

    monkeypatch.setenv("ANTHROPIC_BASE_URL", "https://work-proxy.invalid")
    monkeypatch.setattr(config, "anthropic_api_key", lambda: "sk-test")
    monkeypatch.setattr(llm.anthropic, "Anthropic", FakeAnthropic)
    llm.make_client()
    assert seen["api_key"] == "sk-test"
    assert seen["base_url"] == config.anthropic_base_url() == "https://api.anthropic.com"
    assert seen["max_retries"] == 0


def test_missing_key_raises(monkeypatch):
    monkeypatch.setattr(config, "anthropic_api_key", lambda: None)
    with pytest.raises(RuntimeError, match="ANTHROPIC_API_KEY"):
        llm.make_client()


def test_retries_on_429_and_5xx_not_on_400(monkeypatch):
    import anthropic
    import httpx

    monkeypatch.setattr(llm._create.retry, "wait", lambda *a, **k: 0)
    req = httpx.Request("POST", "https://x")

    def err(cls, status):
        return cls("e", response=httpx.Response(status, request=req), body=None)

    class Client:
        def __init__(self, errors):
            self.errors, self.calls = list(errors), 0
            self.messages = self

        def create(self, **kw):
            self.calls += 1
            if self.errors:
                raise self.errors.pop(0)
            return "ok"

    c = Client([err(anthropic.RateLimitError, 429), err(anthropic.InternalServerError, 500)])
    assert llm._create(c) == "ok" and c.calls == 3
    c = Client([err(anthropic.BadRequestError, 400)])
    with pytest.raises(anthropic.BadRequestError):
        llm._create(c)
    assert c.calls == 1


def test_long_system_prompt_gets_cache_control():
    assert llm._system_blocks("short") == "short"
    blocks = llm._system_blocks("x" * 5000)
    assert blocks[0]["cache_control"] == {"type": "ephemeral"}


def test_parse_json_object():
    assert llm.parse_json_object('```json\n{"a": 1}\n```') == {"a": 1}
    assert llm.parse_json_object('Sure! {"a": {"b": 2}} done') == {"a": {"b": 2}}
    with pytest.raises(ValueError):
        llm.parse_json_object("no json")
    with pytest.raises(ValueError):
        llm.parse_json_object("[1, 2]")


def test_live_call_disables_thinking(monkeypatch):
    seen = {}

    class Usage:
        input_tokens, output_tokens = 5, 2
        cache_read_input_tokens = 3
        cache_creation_input_tokens = 0

    class Block:
        type, text = "text", "{}"

    class Resp:
        content, usage = [Block()], Usage()

    class Client:
        messages = None

        def __init__(self):
            self.messages = self

        def create(self, **kw):
            seen.update(kw)
            return Resp()

    monkeypatch.setattr(llm, "make_client", lambda: Client())
    r = llm._call_live(model="claude-haiku-x", system="s", messages=[], max_tokens=9)
    assert seen["thinking"] == {"type": "disabled"} and "temperature" not in seen
    assert (r.text, r.tokens_in, r.tokens_out, r.tokens_cached) == ("{}", 5, 2, 3)


def test_thinking_switch_falls_back_on_400(monkeypatch):
    import anthropic
    import httpx

    monkeypatch.setattr(llm._create.retry, "wait", lambda *a, **k: 0)
    llm._THINKING_OFF.clear()
    seen = []

    class Client:
        def __init__(self):
            self.messages = self

        def create(self, **kw):
            seen.append(kw["thinking"]["type"])
            if kw["thinking"]["type"] == "disabled":
                raise anthropic.BadRequestError(
                    'send "thinking": {"type": "between_tools"} instead',
                    response=httpx.Response(400, request=httpx.Request("POST", "https://x")),
                    body=None,
                )
            return "ok"

    assert llm._create_without_thinking(Client(), model="claude-weird-1", max_tokens=1) == "ok"
    assert seen == ["between_tools"]  # unknown family defaults straight to the Sonnet form
    assert llm._THINKING_OFF["claude-weird-1"] == {"type": "between_tools"}
    llm._THINKING_OFF.clear()
