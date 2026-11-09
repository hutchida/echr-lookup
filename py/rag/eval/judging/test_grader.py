import json
from types import SimpleNamespace

import pytest

from . import grader
from .budget import CapExceeded, SpendGuard
from .common import read_jsonl
from .grader import (
    build_user_prompt,
    judge_question,
    load_run,
    run_judging,
    shuffled_order,
    validate_reply,
)

ALIASES = ["P01", "P02", "P03"]


def reply(grades, reasons=None):
    return json.dumps(
        {
            "judgments": [
                {"p": a, "grade": g, "reason": (reasons or {}).get(a, f"because {a}")}
                for a, g in zip(ALIASES, grades, strict=False)
            ]
        }
    )


def make_pool_q(qid="q1", n=3):
    paras = [
        {
            "id": f"doc§{i}",
            "gold": i == 1,
            "found_by": {"fixed/bm25": 1},
            "n_configs": 1,
            "best_rank": 1,
            "case_name": "A v UK",
            "doc_type": "judgment",
            "section": "The Law",
            "text": f"Verbatim text {i}.",
        }
        for i in range(1, n + 1)
    ]
    return {"question_id": qid, "question": "Q?", "type": "explain", "gold_ids": ["doc§1"],
            "paragraphs": paras}  # fmt: skip


class FakeLLM:
    """Replies from a script; each reply may be a function of the aliases in the prompt."""

    def __init__(self, *texts, cost=0.1):
        self.texts, self.calls, self.cost = list(texts), [], cost

    def __call__(self, system, messages, request_id, max_tokens):
        self.calls.append({"system": system, "messages": messages, "request_id": request_id,
                           "max_tokens": max_tokens})  # fmt: skip
        text = self.texts[min(len(self.calls) - 1, len(self.texts) - 1)]
        return SimpleNamespace(text=text, model="claude-opus-5-5", tokens_in=100, tokens_out=50,
                               tokens_cached=0, cost_usd=self.cost, latency_ms=5.0)  # fmt: skip


def guard(spent=0.0, cap=8.0):
    return SpendGuard(lambda: spent, cap=cap)


# --- validation -----------------------------------------------------------------------------


def test_valid_reply_passes_and_is_keyed_by_alias():
    grades, errors = validate_reply(reply([2, 1, 0]), ALIASES)
    assert errors == [] and grades["P01"] == {"grade": 2, "reason": "because P01"}
    assert grades["P03"]["grade"] == 0


def test_code_fence_and_prose_around_json_are_tolerated():
    grades, errors = validate_reply("Here you go:\n```json\n" + reply([2, 2, 2]) + "\n```", ALIASES)
    assert errors == [] and len(grades) == 3


@pytest.mark.parametrize(
    "bad",
    [
        "not json",
        '{"judgments": "x"}',
        json.dumps({"judgments": [{"p": "P01", "grade": 3, "reason": "r"}] * 1}),
        json.dumps({"judgments": [{"p": "P01", "grade": "2", "reason": "r"}]}),
        json.dumps({"judgments": [{"p": "P01", "grade": True, "reason": "r"}]}),
        json.dumps({"judgments": [{"p": "P01", "grade": 2.0, "reason": "r"}]}),
        json.dumps({"judgments": [{"p": "P01", "grade": 2, "reason": "  "}]}),
        json.dumps({"judgments": [{"p": "P01", "grade": 2}]}),
    ],
)
def test_malformed_replies_are_rejected(bad):
    grades, errors = validate_reply(bad, ALIASES)
    assert grades is None and errors


def test_missing_duplicate_and_extra_aliases_are_rejected():
    full = json.loads(reply([2, 1, 0]))["judgments"]
    for judgments, needle in [
        (full[:2], "missing"),
        (full + [full[0]], "more than once"),
        (full + [{"p": "P99", "grade": 1, "reason": "r"}], "unknown alias"),
    ]:
        grades, errors = validate_reply(json.dumps({"judgments": judgments}), ALIASES)
        assert grades is None and any(needle in e for e in errors), errors


# --- prompt and shuffle ------------------------------------------------------------------------


def test_shuffle_is_seeded_per_run_and_question():
    ids = [f"d§{i}" for i in range(30)]
    a = shuffled_order("q1", ids, 7, 1)
    assert a == shuffled_order("q1", list(reversed(ids)), 7, 1)  # input order does not matter
    assert a != shuffled_order("q1", ids, 7, 2)  # re-judge uses a different order
    assert a != shuffled_order("q2", ids, 7, 1)
    assert sorted(a) == sorted(ids)


def test_prompt_shows_text_and_metadata_but_not_gold_or_configs():
    q = make_pool_q()
    llm = FakeLLM(reply([2, 1, 0]))
    judge_question(q, llm, guard(), run=1, seed=1)
    sent = llm.calls[0]["system"] + llm.calls[0]["messages"][0]["content"]
    assert "Verbatim text 2." in sent and "A v UK | judgment | The Law" in sent
    for leak in ("gold", "found_by", "fixed/bm25", "n_configs", "best_rank", "doc§"):
        assert leak not in sent.replace("gold", "") or leak == "gold"
    assert "doc§" not in sent  # real ids stay out of the prompt; aliases are used
    assert "[P01]" in sent


def test_system_prompt_has_rubric_and_two_worked_examples():
    s = grader.SYSTEM_PROMPT
    assert "WORKED EXAMPLE 1" in s and "WORKED EXAMPLE 2" in s
    assert "grade 2" in s and "grade 1" in s and "grade 0" in s


def test_build_user_prompt_lists_aliases():
    q = make_pool_q(n=2)
    text = build_user_prompt("Why?", [("P01", q["paragraphs"][0]), ("P02", q["paragraphs"][1])])
    assert text.startswith("Question: Why?") and "(2; aliases P01, P02)" in text


# --- judging one question ----------------------------------------------------------------------


def test_judge_question_maps_aliases_back_to_real_ids():
    q = make_pool_q()
    llm = FakeLLM(reply([2, 1, 0]))
    rec = judge_question(q, llm, guard(), run=1, seed=5)
    assert rec["ok"] and rec["errors"] == [] and len(rec["attempts"]) == 1
    order = {o["alias"]: o["id"] for o in rec["order"]}
    assert rec["grades"][order["P01"]]["grade"] == 2
    assert set(rec["grades"]) == {"doc§1", "doc§2", "doc§3"}
    assert rec["seed"] == 5 and rec["run"] == 1 and rec["model"] == grader.JUDGE_MODEL
    call = llm.calls[0]
    assert call["request_id"].startswith("relevance-") and call["max_tokens"] == grader.MAX_TOKENS


def test_one_retry_recovers_from_a_bad_first_reply():
    q = make_pool_q()
    llm = FakeLLM("sorry, here are my thoughts", reply([1, 1, 1]))
    rec = judge_question(q, llm, guard(), run=1, seed=5)
    assert rec["ok"] and len(rec["attempts"]) == 2
    assert rec["attempts"][0]["errors"] and rec["attempts"][1]["errors"] == []
    assert len(llm.calls) == 2 and llm.calls[1]["request_id"].endswith("-a2")
    assert [m["role"] for m in llm.calls[1]["messages"]] == ["user", "assistant", "user"]


def test_two_bad_replies_give_a_counted_failure_and_no_grades():
    q = make_pool_q()
    llm = FakeLLM(reply([2, 1]), reply([2, 1]))  # missing P03 both times
    rec = judge_question(q, llm, guard(), run=1, seed=5)
    assert not rec["ok"] and rec["grades"] == {} and rec["errors"]
    assert len(llm.calls) == 2  # retried once, not more
    assert len(rec["attempts"]) == 2 and rec["attempts"][1]["reply"]  # raw replies are kept


def test_paragraph_without_text_is_refused_without_a_call():
    q = make_pool_q()
    q["paragraphs"][0]["text"] = None
    llm = FakeLLM(reply([2, 1, 0]))
    rec = judge_question(q, llm, guard(), run=1, seed=5)
    assert not rec["ok"] and llm.calls == [] and "no text" in rec["errors"][0]


def test_cap_stops_the_call_before_it_is_made():
    llm = FakeLLM(reply([2, 1, 0]))
    with pytest.raises(CapExceeded):
        judge_question(make_pool_q(), llm, SpendGuard(lambda: 7.999999, cap=8.0), run=1, seed=1)
    assert llm.calls == []


def test_cap_is_checked_again_before_the_retry():
    state = {"spent": 0.0}

    class Llm(FakeLLM):
        def __call__(self, *a):
            r = super().__call__(*a)
            state["spent"] = 7.9999  # the first call "spent" nearly everything
            return r

    llm = Llm("garbage", reply([2, 1, 0]))
    with pytest.raises(CapExceeded):
        judge_question(
            make_pool_q(), llm, SpendGuard(lambda: state["spent"], cap=8.0), run=1, seed=1
        )
    assert len(llm.calls) == 1


# --- the resumable run -------------------------------------------------------------------------


def test_run_judging_persists_skips_done_and_counts_failures(tmp_path):
    pool = [make_pool_q("q1"), make_pool_q("q2"), make_pool_q("q3")]
    out = tmp_path / "judgments-run1.jsonl"
    texts = {}

    def llm(system, messages, request_id, max_tokens):
        qid = request_id.split("-")[1]
        text = "junk" if qid == "q2" else reply([2, 1, 0])
        texts[request_id] = text
        return SimpleNamespace(text=text, model="m", tokens_in=1, tokens_out=1, tokens_cached=0,
                               cost_usd=0.0, latency_ms=1.0)  # fmt: skip

    res = run_judging(pool, llm, guard(), out, run=1, seed=3, workers=1)
    assert res["judged"] == 3 and res["failed"] == 1 and res["skipped"] == 0
    recs = load_run(out)
    assert recs["q1"]["ok"] and not recs["q2"]["ok"] and recs["q3"]["ok"]
    assert len(read_jsonl(out)) == 3

    calls_before = len(texts)
    res2 = run_judging(pool, llm, guard(), out, run=1, seed=3, workers=1)  # resume: nothing to do
    assert res2["judged"] == 0 and res2["skipped"] == 3 and len(texts) == calls_before

    res3 = run_judging(pool, llm, guard(), out, run=1, seed=3, workers=1, retry_failed=True)
    assert res3["judged"] == 1 and res3["failed"] == 1 and res3["skipped"] == 2


def test_run_judging_stops_at_the_cap_and_reports_not_run(tmp_path):
    pool = [make_pool_q("q1"), make_pool_q("q2")]
    out = tmp_path / "r.jsonl"
    llm = FakeLLM(reply([2, 1, 0]))
    res = run_judging(pool, llm, SpendGuard(lambda: 8.0, cap=8.0), out, run=1, seed=1, workers=1)
    assert res["judged"] == 0 and res["not_run"] == 2 and llm.calls == []


def test_only_restricts_the_questions(tmp_path):
    pool = [make_pool_q("q1"), make_pool_q("q2")]
    out = tmp_path / "r.jsonl"
    res = run_judging(pool, FakeLLM(reply([2, 1, 0])), guard(), out, run=2, seed=1, only=["q2"],
                      workers=1)  # fmt: skip
    assert res["judged"] == 1 and list(load_run(out)) == ["q2"]
