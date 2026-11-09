# ruff: noqa: E501
"""Value questions ("Should ...?", "Is X good for the UK?") get a sourced, balanced answer with no
verdict, not a refusal (S6's judged eval had neutrality at 6/11 before this)."""

import pytest

from rag.answer import answer, context, generate, llm, plan
from rag.contract import contract_errors

SOERING = ["001-57619§88", "001-57619§91", "001-57619§111"]

VALUE = [
    "Should the UK be responsible under the Convention for what its soldiers do abroad?",
    "Should murderers be sentenced to life in prison with no chance of release?",
    "Should assisted suicide be legal in the UK?",
    "Should UK courts have to follow decisions from the Strasbourg Court?",
    "Is the Human Rights Act good for the UK?",
    "Is it right to deport foreign nationals who commit serious crimes?",
    "Was it right for the UK to detain foreign terrorism suspects without trial?",
]
NOT_VALUE = [
    "Does the Convention stop the UK deporting criminals?",
    "How has Article 8 been applied in UK immigration cases?",
    "What did the Court decide in Soering v UK?",
    "Explain the death row phenomenon.",
]


@pytest.mark.parametrize("question", VALUE)
def test_value_questions_are_detected(question):
    assert plan.is_value_question(question)


@pytest.mark.parametrize("question", NOT_VALUE)
def test_explain_questions_are_not_value_questions(question):
    assert not plan.is_value_question(question)


def spy(monkeypatch):
    calls = []
    real = llm.complete

    def complete(conn, **kw):
        calls.append(kw)
        return real(conn, **kw)

    monkeypatch.setattr(llm, "complete", complete)
    return calls


def test_value_question_plans_queries_and_uses_value_rules(answer_db, fake_search, monkeypatch):
    fake_search["ids"] = SOERING
    calls = spy(monkeypatch)
    a = answer(
        answer_db,
        {"question": "Should UK courts have to follow Strasbourg?", "options": {"route": "rag"}},
    )
    assert contract_errors("Answer", a) == []
    gen = next(c for c in calls if c["purpose"] == "generate")
    assert "THIS IS A VALUE QUESTION" in gen["system"] and "must NOT refuse" in gen["system"]
    assert any(c["purpose"] == "route" for c in calls)  # the query-planning call
    # the original question plus the planned queries were each searched; extras skip the reranker
    queries = [r["query"] for r in fake_search["requests"]]
    assert queries[0] == "Should UK courts have to follow Strasbourg?" and len(queries) == 3
    assert all(r["mode"] != "hybrid_rerank" for r in fake_search["requests"][1:])
    assert [s["step"] for s in a["steps"]][0] == "route" and a["steps"][0]["model"] is not None
    assert a["steps"][0]["cost_usd"] > 0  # planning cost is folded into the route step
    assert not a["refused_or_not_in_sources"] and a["citations"]


def test_explain_question_is_planned_and_answered_first(answer_db, fake_search, monkeypatch):
    fake_search["ids"] = SOERING
    calls = spy(monkeypatch)
    a = answer(answer_db, {"question": "What did the Court decide in Soering v UK?"})
    gen = next(c for c in calls if c["purpose"] == "generate")
    assert "VALUE QUESTION" not in gen["system"] and "ANSWER FIRST" in gen["system"]
    plan_call = next(c for c in calls if c["purpose"] == "route")
    assert plan_call["system"] == plan.LEGAL_PLAN_SYSTEM  # the legal planner, not the value one
    assert len(fake_search["requests"]) == 3  # the question + two planned queries
    assert a["claims"][0]["role"] == "short_answer"


def test_planner_failure_falls_back_to_the_original_question(answer_db, fake_search, monkeypatch):
    fake_search["ids"] = SOERING
    real = llm.complete

    def flaky(conn, **kw):
        if kw["purpose"] == "route":
            raise RuntimeError("planner down")
        return real(conn, **kw)

    monkeypatch.setattr(llm, "complete", flaky)
    a = answer(
        answer_db,
        {"question": "Is the Human Rights Act good for the UK?", "options": {"route": "rag"}},
    )
    assert len(fake_search["requests"]) == 1 and a["citations"]


def test_value_rules_say_what_to_do():
    rules = generate.VALUE_RULES
    for must in (
        "NOT refuse",
        "EACH side",
        "The Government argued",
        "dissenting",
        "legislation",
        "never as your own view",
        "do not say which side is right",
    ):
        assert must in rules
    # neutrality rules of the base prompt still apply
    assert "Never give your own opinion" in generate.SYSTEM_PROMPT


# --- the value-question path is exactly what it was before "answer first" -------------------------


def _seed_long_case(conn):
    """One case with 8 paragraphs that would be capped (4 per case) and demoted (recited statute),
    plus one operative provision that states an outcome and one that is boilerplate."""
    conn.execute(
        "INSERT INTO documents (item_id, case_name, doc_type, date, articles, outcome) VALUES "
        "('001-777', 'LONG v. THE UNITED KINGDOM', 'judgment', '2000-01-01', ARRAY['8'], 'violation')"
    )
    rows = [
        (
            f"001-777§{i}",
            "001-777",
            i,
            i,
            "The Law",
            f"Section {i} of the Immigration Act 1971 provides that x.",
        )
        for i in range(1, 9)
    ]
    rows += [
        (
            "001-777§op1",
            "001-777",
            20,
            None,
            "Operative provisions",
            "Holds that there has been a violation of Article 8;",
        ),
        (
            "001-777§op2",
            "001-777",
            21,
            None,
            "Operative provisions",
            "that the respondent State is to pay the applicant EUR 5,000;",
        ),
    ]
    for r in rows:
        conn.execute(
            "INSERT INTO paragraphs (id, doc_id, position, number, section, text) VALUES (%s,%s,%s,%s,%s,%s)",
            r,
        )


def _pre_answer_first_context(conn, ids, cap=30):
    """The context the value path built before A1, written out independently of the new code."""
    by_id = context.fetch_sources(conn, ids[:cap])
    sources = [by_id[i] for i in ids[:cap] if i in by_id]
    docs = list(dict.fromkeys(s.doc_id for s in sources))[:8]
    have = {s.id for s in sources}
    rows = conn.execute(
        "SELECT p.id, p.doc_id FROM paragraphs p WHERE p.doc_id = ANY(%s) AND p.section = 'Operative provisions' "
        "ORDER BY p.doc_id, p.position",
        (docs,),
    ).fetchall()
    per_doc: dict[str, int] = {}
    extra = []
    for pid, doc in rows:
        if pid in have or per_doc.get(doc, 0) >= 4:
            continue
        per_doc[doc] = per_doc.get(doc, 0) + 1
        extra.append(pid)
    extra.sort(key=lambda pid: docs.index(pid.split("§")[0]))
    return [s.id for s in sources] + extra


def test_value_question_context_is_unchanged_but_explain_context_is_diversified(
    answer_db, fake_search
):
    _seed_long_case(answer_db)
    ids = [f"001-777§{i}" for i in range(1, 9)] + SOERING
    fake_search["ids"] = ids
    kwargs = {"extra_queries": ["a second query"]}
    value = [
        s.id for s in context.retrieve(answer_db, "Should x?", {}, value_question=True, **kwargs)[0]
    ]
    assert value == _pre_answer_first_context(answer_db, ids + [])  # same sources, same order
    assert value.count("001-777§op2") == 1  # boilerplate operative provision kept, as before
    assert (
        sum(1 for i in value if i.startswith("001-777§") and "op" not in i) == 8
    )  # no per-case cap
    explain = [s.id for s in context.retrieve(answer_db, "What?", {}, **kwargs)[0]]
    assert sum(1 for i in explain if i.startswith("001-777§") and "op" not in i) == 4  # capped
    assert "001-777§op2" not in explain and "001-777§op1" in explain  # outcomes only


def test_value_question_planning_and_generation_calls_are_unchanged(
    answer_db, fake_search, monkeypatch
):
    fake_search["ids"] = SOERING
    calls = spy(monkeypatch)
    answer(
        answer_db,
        {"question": "Should UK courts have to follow Strasbourg?", "options": {"route": "rag"}},
    )
    plan_call = next(c for c in calls if c["purpose"] == "route")
    assert plan_call["system"] == plan.PLAN_SYSTEM and plan_call["max_tokens"] == 300
    gen = next(c for c in calls if c["purpose"] == "generate")
    assert (
        gen["system"] == generate.SYSTEM_PROMPT + generate.VALUE_RULES and gen["max_tokens"] == 1800
    )
    assert "ANSWER FIRST" not in gen["system"]
