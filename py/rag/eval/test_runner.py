# ruff: noqa: E501
import json
from types import SimpleNamespace

import pytest

from rag.contract import contract_errors
from rag.eval import judge
from rag.eval.report import (
    README_PATH,
    render_readme_section,
    render_results_md,
    render_table,
    replace_between_markers,
)
from rag.eval.runner import (
    Backend,
    CostGuardError,
    run_eval,
    store_run,
)

# A tiny seeded corpus: each "hit" is one paragraph of a made-up case.
CORPUS = {
    "doc1§1": "extradition death row phenomenon article 3 soering",
    "doc1§2": "absolute prohibition torture inhuman treatment",
    "doc2§1": "deportation criminal family life article 8 proportionate",
    "doc2§2": "prisoners voting ban blanket margin appreciation",
}
ITEMS = [
    {"id": "explain-001", "question": "extradition death row", "type": "explain",
     "expected_paragraph_ids": ["doc1§1"], "reference_notes": "n", "status": "draft", "tags": []},
    {"id": "explain-002", "question": "deportation criminal family", "type": "explain",
     "expected_paragraph_ids": ["doc2§1", "doc2§2"], "reference_notes": "n", "status": "draft", "tags": []},
    {"id": "neutrality-001", "question": "prisoners voting", "type": "neutrality",
     "expected_paragraph_ids": ["doc2§2"], "reference_notes": "n", "status": "draft", "tags": []},
    {"id": "stat-001", "question": "how many inadmissible", "type": "stat",
     "expected_paragraph_ids": [], "reference_notes": "[expected_count=33]", "status": "draft",
     "tags": ["expected_count:33"]},
    {"id": "stat-002", "question": "how many struck out", "type": "stat",
     "expected_paragraph_ids": [], "reference_notes": "[expected_count=4]", "status": "draft",
     "tags": ["expected_count:4"]},
]  # fmt: skip


class Fake:
    def __init__(self):
        self.answer_calls = 0
        self.llm_calls = 0
        self.cost = 0.01

    def search(self, request):
        words = set(request["query"].split())
        scored = sorted(CORPUS, key=lambda p: -len(words & set(CORPUS[p].split())))
        return {"hits": [{"paragraph_ids": [p]} for p in scored[: request["k"]]]}

    def answer(self, request):
        self.answer_calls += 1
        if "inadmissible" in request["question"] or "struck out" in request["question"]:
            count = 33 if "inadmissible" in request["question"] else 5  # second one is wrong
            stats = {"count": count}
            return self._answer("stats", stats, [])
        claims = [{"id": "c1", "text": "A claim.", "citation_ids": ["doc1§1"],
                   "status": "supported", "reason": ""}]  # fmt: skip
        return self._answer("rag", None, claims)

    def _answer(self, route, stats, claims):
        return {
            "route": route, "stats": stats, "claims": claims, "answer_text": "text",
            "refused_or_not_in_sources": False, "total_cost_usd": self.cost, "total_latency_ms": 5.0,
            "steps": [{"tokens_in": 100, "tokens_out": 20}],
        }  # fmt: skip

    def llm(self, system, user, purpose, request_id):
        self.llm_calls += 1
        assert purpose == "judge"
        if "neutrality" in system:
            text = '{"balanced": true, "no_opinion": true, "reason": "ok"}'
        else:
            text = '```json\n{"claims": [{"id": "c1", "verdict": 0.5, "citations": {"doc1§1": true}}]}\n```'
        return SimpleNamespace(text=text, model="claude-sonnet-5-5", tokens_in=1000,
                               tokens_out=100, tokens_cached=0)  # fmt: skip


def default_cfg(r):
    c = r.run["config"]
    return (c["chunking"], c["mode"]) == ("recursive", "hybrid_rerank")


def backend(fake):
    return Backend(
        search=fake.search, answer=fake.answer, paragraph_text=CORPUS.get, llm=fake.llm,
        embedder_model="fake", generator_model="claude-sonnet-5-5", judge_model="claude-sonnet-5-5",
    )  # fmt: skip


def test_retrieval_only_covers_all_twelve_configs_at_zero_cost():
    fake = Fake()
    results = run_eval(backend(fake), ITEMS, answers=False)
    assert len(results) == 12
    assert {(r.run["config"]["chunking"], r.run["config"]["mode"]) for r in results} == {
        (c, m)
        for c in ("fixed", "recursive", "by_section")
        for m in ("bm25", "vector", "hybrid", "hybrid_rerank")
    }
    assert fake.answer_calls == fake.llm_calls == 0
    for r in results:
        assert contract_errors("EvalRun", r.run) == []
        assert r.run["cost_usd"] == 0
        assert r.run["metrics"]["faithfulness"] is None
        assert r.run["config"]["generator_model"] is None
    run = results[0].run
    # explain-001 finds doc1§1 at rank 1; explain-002 finds both expected; neutrality finds doc2§2
    assert run["metrics"]["recall_at_5"] == 1.0
    assert run["metrics"]["mrr"] == pytest.approx(1.0)


def test_end_to_end_with_answers_judge_and_stats():
    fake = Fake()
    estimates = []
    results = run_eval(
        backend(fake), ITEMS, answers=True, judge=True, max_cost=3.0, compare_items=3,
        on_estimate=estimates.append,
    )  # fmt: skip
    assert estimates and estimates[0]["total"] > 0
    answered = [r for r in results if r.run["config"]["generator_model"]]
    assert len(answered) == 2
    default = next(r for r in answered if default_cfg(r))
    assert default.run["config"]["rerank"] is True
    assert default.answered_items == 5
    m = default.run["metrics"]
    assert m["faithfulness"] == 0.5 and m["citation_accuracy"] == 1.0 and m["neutrality"] == 1.0
    assert default.stat_accuracy == 0.5
    assert [r["ok"] for r in default.stat_rows] == [True, False]
    assert default.run["cost_usd"] > 0 and default.run["tokens_in"] > 0
    for r in results:
        assert contract_errors("EvalRun", r.run) == []
    # a markdown table with one row per config, and the plain-English paragraph
    table = render_table(results)
    assert table.count("\n| ") == 12
    md = render_results_md(results, ITEMS, generated_at="now", notes=["n"])
    assert "## What this shows" in md and "Counting questions" in md and "draft" in md


def test_no_judge_answers_only_stat_items():
    fake = Fake()
    results = run_eval(backend(fake), ITEMS, answers=True, judge=False)
    assert fake.llm_calls == 0 and fake.answer_calls == 4  # 2 stat items x 2 answer configs
    default = next(r for r in results if default_cfg(r))
    assert default.stat_accuracy == 0.5
    assert default.run["metrics"]["faithfulness"] is None


def test_cost_guard_aborts_before_any_paid_call():
    fake = Fake()
    with pytest.raises(CostGuardError):
        run_eval(backend(fake), ITEMS, answers=True, judge=True, max_cost=0.0001)
    assert fake.answer_calls == fake.llm_calls == 0


def test_run_stops_when_budget_is_spent():
    fake = Fake()
    fake.cost = 0.03
    # Passes the up-front guard, but each fake answer costs 0.03, so the budget runs out.
    results = run_eval(backend(fake), ITEMS, answers=True, judge=True, max_cost=0.115,
                       compare_items=0)  # fmt: skip
    default = next(r for r in results if default_cfg(r))
    assert default.truncated and default.answered_items < 5


def test_judge_parsing_is_defensive():
    assert judge.parse_json('Sure: {"a": 1} done') == {"a": 1}
    assert judge.parse_json("no json here") is None
    usage = judge.JudgeUsage()
    junk = lambda *a: SimpleNamespace(  # noqa: E731
        text="not json", model="claude-sonnet-5-5", tokens_in=10, tokens_out=5, tokens_cached=0
    )
    answer = {"claims": [{"id": "c1", "text": "t", "citation_ids": ["doc1§1"]}],
              "refused_or_not_in_sources": False}  # fmt: skip
    assert judge.judge_support(junk, answer, CORPUS.get, "r", usage) == (None, None)
    assert judge.judge_neutrality(junk, "q", "a", "r", usage) is None
    assert usage.cost_usd > 0


def test_refusals_are_not_scored_for_faithfulness():
    answer = {"claims": [], "refused_or_not_in_sources": True}
    assert judge.judge_support(None, answer, CORPUS.get, "r", judge.JudgeUsage()) == (None, None)


def test_store_run_round_trips(db_conn):
    db_conn.execute(
        "CREATE TABLE IF NOT EXISTS eval_runs (run_id text PRIMARY KEY, "
        "created_at timestamptz NOT NULL, payload jsonb NOT NULL)"
    )
    run = run_eval(backend(Fake()), ITEMS, answers=False, configs=[("recursive", "bm25")])[0].run
    store_run(db_conn, run)
    store_run(db_conn, run)  # idempotent
    rows = db_conn.execute(
        "SELECT payload FROM eval_runs WHERE run_id = %s", (run["run_id"],)
    ).fetchall()
    assert len(rows) == 1 and json.loads(json.dumps(rows[0][0])) == run
    db_conn.rollback()


def test_readme_markers_are_replaced_in_place():
    results = run_eval(backend(Fake()), ITEMS, answers=False, configs=[("recursive", "bm25")])
    text = "before\n<!-- eval:start -->\nold\n<!-- eval:end -->\nafter\n"
    new = replace_between_markers(text, render_readme_section(results))
    assert new.startswith("before\n<!-- eval:start -->\n| Chunking")
    assert "old" not in new and new.endswith("<!-- eval:end -->\nafter\n")
    with pytest.raises(ValueError):
        replace_between_markers("no markers", "x")
    assert "<!-- eval:start -->" in README_PATH.read_text()


def test_parallel_workers_use_forked_backends_and_keep_order():
    fake = Fake()
    forks = []

    def fork():
        forks.append(1)
        return backend(fake)

    b = backend(fake)
    b.fork = fork
    results = run_eval(b, ITEMS, answers=True, judge=True, max_cost=3.0, compare_items=5, workers=3)
    default = next(r for r in results if default_cfg(r))
    assert 1 <= len(forks) <= 6
    assert [r["id"] for r in default.stat_rows] == ["stat-001", "stat-002"]
    assert default.answered_items == 5 and default.run["metrics"]["faithfulness"] == 0.5
