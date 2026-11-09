# ruff: noqa: E501
import pytest

from rag.answer import llm, router

LABELLED = [
    # the three demo questions
    ("Does the Convention stop the UK deporting criminals?", "rag"),
    ("How has Article 8 been applied in UK immigration cases?", "rag"),
    (
        "How many UK deportation complaints in the corpus were declared inadmissible, "
        "and the most common reasons?",
        "stats",
    ),
    # counting words
    ("How many judgments found a violation of Article 3?", "stats"),
    ("What is the number of Article 8 cases against the UK?", "stats"),
    ("What percentage of UK decisions were inadmissible?", "stats"),
    ("What is the most common reason for inadmissibility?", "stats"),
    ("What proportion of cases concern prisoners' voting?", "stats"),
    # explanation questions
    ("What did the Court decide in Soering v UK?", "rag"),
    ("Explain the death row phenomenon.", "rag"),
    ("When can a State expel someone who has family in the country?", "rag"),
    ("Should the UK leave the ECHR?", "rag"),
]


@pytest.mark.parametrize(("question", "expected"), LABELLED)
def test_heuristic_routing(answer_db, monkeypatch, question, expected):
    def no_llm(*a, **k):
        raise AssertionError("heuristic questions must not call a model")

    monkeypatch.setattr(llm, "complete", no_llm)
    assert router.route(answer_db, question, "req-t") == expected


def test_ambiguous_question_uses_router_model(answer_db, monkeypatch):
    calls = []

    def fake_complete(conn, **kw):
        calls.append(kw)
        return llm.LLMResult('{"route": "stats"}', kw["model"], 10, 5, 0, 1.0, 0.001)

    monkeypatch.setattr(llm, "complete", fake_complete)
    route, step = router.route_with_step(
        answer_db, "How often does the Court find violations?", "r"
    )
    assert route == "stats"
    assert calls[0]["purpose"] == "route"
    assert step["model"] == calls[0]["model"] and step["cost_usd"] == 0.001


def test_router_failure_defaults_to_rag(answer_db, monkeypatch):
    def boom(conn, **kw):
        raise RuntimeError("down")

    monkeypatch.setattr(llm, "complete", boom)
    assert router.route(answer_db, "Show me the trend of Article 8 cases", "r") == "rag"
