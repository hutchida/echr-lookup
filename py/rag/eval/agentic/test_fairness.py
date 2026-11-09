# ruff: noqa: E501
"""The fairness helpers on hand-made data. No model, no database, no search."""

import json

from rag.eval.agentic import fairness
from rag.eval.agentic.checks import quote_report
from rag.eval.agentic.quotes import local_checker, quote_in_text
from rag.eval.agentic.text import Evidence, parse_answer

TEXTS = {
    "d1§1": "Even in the most difficult of circumstances, the Convention prohibits torture in absolute terms.",
    "d1§2": "The Court has held that deportation would be disproportionate in the circumstances.",
    "d2§1": "Unrelated paragraph about something else entirely.",
}


def test_quote_in_text_follows_the_check_quote_rule_and_can_ignore_case():
    q = "even in the most difficult of circumstances"
    assert not quote_in_text(TEXTS["d1§1"], q)
    assert quote_in_text(TEXTS["d1§1"], q, ignore_case=True)
    assert quote_in_text(TEXTS["d1§1"], "Even in … torture in absolute terms")
    assert not quote_in_text(TEXTS["d1§1"], "torture … Even in")  # segments must come in order
    assert not quote_in_text(None, q)
    assert not quote_in_text(TEXTS["d1§1"], " … ")  # nothing to find is not a match


def test_quote_report_adds_the_shown_figures_only_when_asked():
    ev = Evidence()
    answer = (
        'The Court said that "the Convention prohibits torture in absolute terms" here.\n'
        'It also said "deportation would be disproportionate in the circumstances" [001-58004§80].'
    )
    parsed = parse_answer(answer, ev)
    plain = quote_report(parsed, local_checker(TEXTS.get))
    assert "quote_rate_shown" not in plain and "in_shown" not in plain["quotes"][0]
    rich = quote_report(
        parsed, local_checker(TEXTS.get), shown=["d1§1", "d1§2"], text_lookup=TEXTS.get
    )
    assert [q["in_shown"] for q in rich["quotes"]] == [True, True]
    assert [q["verbatim"] for q in rich["quotes"]] == [
        False,
        False,
    ]  # the headline rule is unchanged
    assert rich["quote_rate"] == 0.0 and rich["quote_rate_shown"] == 1.0


def hits(*chunks: list[str]) -> list[list[str]]:
    return list(chunks)


def test_recall_table_counts_paragraphs_of_the_top_k_hits():
    h = {"q": hits(["a§1", "a§2"], ["b§1"], ["c§1", "c§2", "c§3"], ["d§1"])}
    gold = {"q": {"a§2", "c§3", "z§9", "d§1"}}
    rows = fairness.recall_table(h, gold, ["q"], ks=(1, 3, 4))
    assert [(r["k"], r["recall"], r["paragraphs"]) for r in rows] == [
        (1, 0.25, 2),
        (3, 0.5, 6),
        (4, 0.75, 7),
    ]
    assert fairness.recall_table(h, {"q": set()}, ["q"], ks=(1,))[0]["recall"] is None


def test_paragraph_budget_recall_cuts_at_distinct_paragraphs_not_hits():
    h = {"q": hits(["a§1", "a§2"], ["a§2", "b§1"], ["c§1"])}
    gold = {"q": {"b§1", "c§1"}}
    assert fairness.paragraph_budget_recall(h, gold, ["q"], 2) == 0.0
    assert fairness.paragraph_budget_recall(h, gold, ["q"], 3) == 0.5
    assert fairness.paragraph_budget_recall(h, gold, ["q"], 4) == 1.0


def test_agentic_recalls_old_key_and_v2_on_the_same_questions():
    rows = [
        {
            "system": "ask",
            "set": "subset",
            "status": "ok",
            "item_id": "q1",
            "fetched_paragraph_ids": ["a§1", "a§5"],
        },
        {
            "system": "ask",
            "set": "subset",
            "status": "ok",
            "item_id": "q2",
            "fetched_paragraph_ids": ["b§1"],
        },
        {
            "system": "ask",
            "set": "owner-review",
            "status": "ok",
            "item_id": "or-01",
            "fetched_paragraph_ids": ["x"],
        },
        {
            "system": "mcp",
            "set": "subset",
            "status": "ok",
            "item_id": "q1",
            "fetched_paragraph_ids": [],
        },
    ]
    gold = {"q1": {"a§1", "a§2"}, "q2": {"b§1"}}
    qrels = {"q1": {"a§1": 2, "a§5": 2, "a§2": 1}, "q2": {"b§1": 1}}  # q2 has no grade-2 paragraph
    a = fairness.agentic_recalls(rows, gold, qrels, "ask")
    assert a["questions"] == 2 and a["n_v2"] == 1
    assert a["orig_all"] == 0.75 and a["orig_on_v2_questions"] == 0.5 and a["v2"] == 1.0
    assert a["mean_shown"] == 1.5
    without = fairness.agentic_recalls(rows, gold, None, "ask")
    assert without["v2"] is None and without["orig_all"] == 0.75


def test_load_v2_qrels_is_none_when_the_file_is_missing(tmp_path):
    assert fairness.load_v2_qrels(tmp_path / "nope.jsonl") is None
    path = tmp_path / "q.jsonl"
    path.write_text(json.dumps({"question_id": "q", "qrels": {"a§1": 2, "a§2": 0}}) + "\n")
    q = fairness.load_v2_qrels(path)
    assert q == {"q": {"a§1": 2, "a§2": 0}} and fairness.v2_gold(q["q"]) == {"a§1"}


def test_audit_quotes_sorts_non_verbatim_quotes_into_causes():
    def q(quote, verbatim, cites):
        return {"quote": quote, "verbatim": verbatim, "attributed_to": cites}

    row = {
        "system": "mcp",
        "set": "owner-review",
        "status": "ok",
        "item_id": "or-09",
        "repeat": 1,
        "fetched_paragraph_ids": ["d1§1", "d1§2"],
        "quotes": [
            q("the Convention prohibits torture in absolute terms", False, []),  # uncited
            q("even in the most difficult of circumstances", False, ["d1§1"]),  # case only
            q(
                "deportation would be disproportionate in the circumstances", False, ["d2§1"]
            ),  # other paragraph
            q("the Convention permits torture in absolute terms", False, ["d1§1"]),  # not shown
            q("the Court has held that deportation", True, ["d1§2"]),  # ok
        ],
    }
    audit = fairness.audit_quotes([row], TEXTS.get)
    assert audit["classes"] == {
        "uncited": 1,
        "case only": 1,
        "other paragraph": 1,
        "not in any shown paragraph": 1,
        "ok": 1,
    }
    assert audit["strict_rate"] == 0.2 and audit["shown_rate"] == 0.8
    assert audit["per_answer"][("owner-review", "or-09", 1)] == {
        "quotes": 5,
        "strict": 1,
        "loose": 4,
    }


def test_audit_applies_the_nested_quote_rule():
    row = {
        "system": "mcp",
        "set": "subset",
        "status": "ok",
        "item_id": "x",
        "repeat": 1,
        "fetched_paragraph_ids": ["p"],
        "quotes": [
            {
                "quote": "did not constitute 'relevant new information' for the purposes",
                "verbatim": False,
                "attributed_to": [],
            }
        ],
    }
    audit = fairness.audit_quotes(
        [row], {"p": 'It did not constitute "relevant new information" for the purposes of it.'}.get
    )
    assert audit["classes"] == {"uncited": 1}
