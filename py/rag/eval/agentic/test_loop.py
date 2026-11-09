# ruff: noqa: E501
"""The tool loop, end to end over a real stdio MCP server (the fake) with a scripted fake model. Offline."""

import asyncio
import json
from types import SimpleNamespace

from rag.eval.agentic import fake_client
from rag.eval.agentic.cli import main, make_log_call, server_params
from rag.eval.agentic.common import Budget
from rag.eval.agentic.fake_client import FakeAnthropic, always_tool_use, text, tool_use
from rag.eval.agentic.fake_server import INSTRUCTIONS, TOOLS
from rag.eval.agentic.host import Host, collect_paragraph_ids, open_session
from rag.eval.agentic.runner import Deps, Job, Runner, load_owner_items, plan_jobs, read_rows


def run_turns(client, questions, *, budget=None, max_tool_calls=8, log_call=None):
    async def go():
        async with open_session(server_params("fake")) as session:
            host = Host(
                session, client, max_tool_calls=max_tool_calls, budget=budget, log_call=log_call
            )
            out, history = [], None
            for q in questions:
                turn, history = await host.ask(q, history)
                out.append(turn)
            return session, out, history

    return asyncio.run(go())


def test_loop_runs_over_stdio_with_the_fake_server():
    client = FakeAnthropic()
    session, [turn], messages = run_turns(client, ["Does Article 3 allow deportation?"])
    assert [t.name for t in session.tool_list] == list(TOOLS)
    assert session.instructions == INSTRUCTIONS
    assert [c.name for c in turn.tool_calls] == ["search_case_law", "get_paragraphs"]
    assert turn.answer_text.startswith("Not as a general rule")
    assert turn.status == "ok" and not turn.hit_cap
    assert "001-58004§79" in turn.tool_calls[1].paragraph_ids
    assert turn.tool_calls[1].result_bytes > 1000
    # the JSON text of each result went back to the model as a tool_result
    results = [
        b
        for m in messages
        if isinstance(m["content"], list)
        for b in m["content"]
        if b["type"] == "tool_result"
    ]
    assert len(results) == 2 and json.loads(results[1]["content"])["paragraphs"]
    assert turn.usage.api_calls == 3 and turn.usage.cost_usd > 0


def test_system_prompt_and_tools_are_cached_and_the_prefix_moves():
    client = FakeAnthropic()
    run_turns(client, ["q"])
    first = client.requests[0]
    assert first["system"][0]["text"] == INSTRUCTIONS
    assert first["system"][0]["cache_control"] == {"type": "ephemeral"}
    assert first["tools"][-1]["cache_control"] == {"type": "ephemeral"}
    assert {t["name"] for t in first["tools"]} == set(TOOLS)
    assert all("input_schema" in t for t in first["tools"])
    # one moving breakpoint on the last message block, none left on earlier ones
    for request in client.requests:
        marked = [
            b
            for m in request["messages"]
            for b in m["content"]
            if isinstance(b, dict) and "cache_control" in b
        ]
        assert len(marked) == 1 and "cache_control" in request["messages"][-1]["content"][-1]


def test_tool_call_cap_is_enforced_then_the_model_answers_without_tools():
    client = FakeAnthropic(always_tool_use)
    _, [turn], messages = run_turns(client, ["q"], max_tool_calls=3)
    assert len(turn.tool_calls) == 3 and turn.hit_cap
    assert turn.answer_text == "Final answer after the tool-call limit."
    assert client.requests[-1]["tool_choice"] == {"type": "none"}
    assert all("tool_choice" not in r for r in client.requests[:-1])
    assert len(client.requests) == 4
    assert "final answer" in json.dumps(messages[-2]["content"][-1]).lower()


def test_parallel_tool_calls_past_the_cap_get_an_error_result_not_a_run():
    def burst(kwargs, n):
        if kwargs.get("tool_choice", {}).get("type") == "none":
            return [text("done")]
        return [tool_use(f"t{n}{i}", "corpus_info", {}) for i in range(3)]

    client = FakeAnthropic(burst)
    _, [turn], messages = run_turns(client, ["q"], max_tool_calls=2)
    assert len(turn.tool_calls) == 2
    results = [b for b in messages[2]["content"] if b["type"] == "tool_result"]
    assert len(results) == 3 and results[2]["is_error"]  # every tool_use gets a tool_result


def test_a_second_turn_continues_the_conversation():
    client = FakeAnthropic()
    _, [first, second], messages = run_turns(client, ["q one", "q two"])
    assert len(first.tool_calls) == 2 and len(second.tool_calls) == 2
    assert [m["role"] for m in messages].count(
        "user"
    ) == 2 + 4  # 2 questions + 4 tool-result messages


def test_server_errors_reach_the_model_as_error_results():
    def bad_case(kwargs, n):
        if _seen(kwargs) == 0:
            return [tool_use("t0", "get_case", {"case_id": "001-99999"})]
        return [text("There is no such case.")]

    def _seen(kwargs):
        return sum(
            1 for m in kwargs["messages"] if isinstance(m["content"], list)
            for b in m["content"] if b.get("type") == "tool_result"
        )  # fmt: skip

    _, [turn], messages = run_turns(FakeAnthropic(bad_case), ["q"])
    assert turn.tool_calls[0].is_error and "No case 001-99999" in turn.tool_calls[0].result_text
    assert messages[2]["content"][0]["is_error"] is True


def test_cost_cap_stops_before_the_call_and_sends_nothing():
    client = FakeAnthropic()
    budget = Budget(0.00001)
    _, [turn], _ = run_turns(client, ["q"], budget=budget)
    assert turn.status == "skipped_budget" and client.requests == []
    assert "--max-cost" in turn.note


def test_cost_cap_stops_in_the_middle_of_a_question():
    client = FakeAnthropic()
    budget = Budget(0.0095)  # room for the first call, not for the second
    _, [turn], _ = run_turns(client, ["q"], budget=budget)
    assert turn.status == "skipped_budget" and len(client.requests) < 3
    assert budget.spent <= budget.limit + 0.01


def test_every_call_is_logged_with_purpose_agentic():
    rows = []
    conn = SimpleNamespace(execute=lambda sql, params: rows.append(params), commit=lambda: None)
    run_turns(FakeAnthropic(), ["q"], log_call=make_log_call(conn))
    assert len(rows) == 3 and {r["purpose"] for r in rows} == {"agentic"}
    assert rows[0]["tokens_in"] == 400 + 2000 and rows[1]["tokens_cached"] == 2000
    assert len({r["request_id"] for r in rows}) == 1


def test_collect_paragraph_ids_finds_every_returned_paragraph():
    result = {"hits": [{"paragraph_id": "a§1"}, {"paragraph_id": "a§1"}], "x": {"operative_provisions": [{"paragraph_id": "a§op1"}]},
              "outline": [{"first_paragraph_id": "a§1"}]}  # fmt: skip
    assert collect_paragraph_ids(result) == ["a§1", "a§op1"]


def fake_deps(**overrides):
    base = dict(
        conn=None, anthropic_client=FakeAnthropic(), server_params=server_params("fake"),
        judge_llm=fake_client.fake_judge_llm,
        paragraph_text=lambda pid: "However, the Convention prohibits in absolute terms torture or inhuman or degrading treatment or punishment, irrespective of the victim's conduct.",
        make_checker=lambda lookup: __import__("rag.eval.agentic.quotes", fromlist=["x"]).local_checker(lookup),
        ask_fn=fake_client.fake_ask,
    )  # fmt: skip
    return Deps(**{**base, **overrides})


def test_runner_skips_and_reports_what_the_cap_cuts_off(tmp_path):
    out = tmp_path / "r.jsonl"
    jobs = plan_jobs(
        systems=["mcp", "ask"],
        sets=["owner-review"],
        repeats=1,
        ask_repeats=1,
        only={"or-01", "or-05", "or-09"},
        subset_size=None,
    )
    runner = Runner(fake_deps(), Budget(0.04), judge=True, out=out)
    result = asyncio.run(runner.run(jobs))
    rows = read_rows(out)
    assert len(rows) == len(jobs) == 6  # nothing silently dropped
    skipped = [r for r in rows if r["status"] == "skipped_budget"]
    assert skipped and len(skipped) == len(result.skipped)
    assert "--max-cost" in skipped[0]["note"] or "earlier call" in skipped[0]["note"]
    assert runner.budget.spent <= 0.04 + 0.02


def test_cli_fake_run_end_to_end(tmp_path, capsys):
    out = tmp_path / "r.jsonl"
    code = main(
        [
            "--fake",
            "--set",
            "owner-review",
            "--repeats",
            "1",
            "--max-cost",
            "5",
            "--only",
            "or-01,or-04,or-05,or-09,or-10",
            "--out",
            str(out),
        ]
    )
    assert code == 0
    rows = read_rows(out)
    mcp = {(r["item_id"]): r for r in rows if r["system"] == "mcp" and not r["context_only"]}
    assert set(mcp) == {"or-01", "or-04", "or-05", "or-09", "or-10"}
    assert [c["name"] for c in mcp["or-05"]["tool_calls"]] == ["count_cases"]
    assert mcp["or-05"]["shape"]["passed"] is True  # count_cases used, 10 and 9 in the answer
    assert mcp["or-01"]["shape"]["passed"] is False  # one cited paragraph, no Article 8
    assert all(r["status"] == "ok" for r in rows)
    assert mcp["or-01"]["claim_accuracy"] == 1.0 and mcp["or-09"]["quote_rate"] == 1.0
    assert mcp["or-09"]["shape"]["passed"] is True
    ask = {r["item_id"]: r for r in rows if r["system"] == "ask"}
    assert ask["or-01"]["tokens"]["input"] == 3000 and ask["or-01"]["cost_usd"] == 0.009
    assert "SKIPPED" not in capsys.readouterr().out


def test_cli_resume_does_not_repeat_finished_answers(tmp_path):
    out = tmp_path / "r.jsonl"
    argv = [
        "--fake",
        "--set",
        "owner-review",
        "--repeats",
        "1",
        "--max-cost",
        "5",
        "--only",
        "or-01,or-10",
        "--systems",
        "mcp",
        "--out",
        str(out),
    ]
    main(argv)
    first = len(read_rows(out))
    main([*argv, "--resume"])
    assert (
        len(read_rows(out)) == first
    )  # or-01 and or-10 were both done: nothing new, not even context


def test_plan_gives_owner_review_repeats_and_one_subset_pass():
    owner = len(load_owner_items())
    jobs = plan_jobs(
        systems=["mcp", "ask"],
        sets=["owner-review", "subset"],
        repeats=3,
        ask_repeats=1,
        only=None,
        subset_size=20,
    )
    count = lambda s, name: sum(j.system == s and j.set_name == name for j in jobs)  # noqa: E731
    assert count("mcp", "owner-review") == 3 * owner and count("ask", "owner-review") == owner
    assert count("mcp", "subset") == count("ask", "subset") == 20


def test_or_10_pulls_in_or_01_as_context_only():
    jobs = plan_jobs(
        systems=["mcp"],
        sets=["owner-review"],
        repeats=2,
        ask_repeats=1,
        only={"or-10"},
        subset_size=None,
    )
    assert [(j.item["id"], j.repeat, j.context_only) for j in jobs] == [
        ("or-01", 1, True),
        ("or-10", 1, False),
        ("or-01", 2, True),
        ("or-10", 2, False),
    ]
    assert isinstance(jobs[0], Job)
