# ruff: noqa: E501
"""Recall, quote rate, shape checks, claim parsing and check_quote, on hand-made answers. No model, no DB."""

import pytest

from rag.eval.agentic.checks import (
    agentic_recall,
    no_bare_yes_no,
    quote_report,
    shape_check,
)
from rag.eval.agentic.quotes import check_text, local_checker
from rag.eval.agentic.text import Evidence, ParsedAnswer, extract_quotes, parse_answer

CHAHAL79 = (
    "The Court is well aware of the immense difficulties faced by States in modern times in "
    "protecting their communities from terrorist violence. However, even in these circumstances, "
    "the Convention prohibits in absolute terms torture or inhuman or degrading treatment or "
    "punishment, irrespective of the victim's conduct. Article 3 makes no provision for exceptions."
)
TEXTS = {
    "001-58004§79": CHAHAL79,
    "001-58004§80": "The prohibition is equally absolute in expulsion cases.",
}


def evidence() -> Evidence:
    ev = Evidence()
    ev.absorb(
        {
            "hits": [
                {
                    "paragraph_id": "001-58004§79",
                    "doc_id": "001-58004",
                    "case_name": "Chahal v. the United Kingdom",
                    "doc_type_label": "Judgment",
                    "cite": "[Chahal v. the United Kingdom, Judgment, §79]",
                }
            ],
            "paragraphs": [{"paragraph_id": "001-58004§80", "text": TEXTS["001-58004§80"]}],
        }
    )
    return ev


def test_agentic_recall():
    assert agentic_recall(["a§1", "a§2"], ["a§1", "b§9"]) == 0.5
    assert agentic_recall(["a§1"], []) == 0.0
    assert agentic_recall([], ["a§1"]) is None


def test_parse_answer_resolves_cite_strings_and_bare_ids():
    text = (
        "## Summary\n"
        "Not as a general rule: Article 3 is absolute. [Chahal v. the United Kingdom, Judgment, §79]\n"
        "- The ban is equally absolute when someone is expelled (001-58004§80).\n"
        "- A second point with a case no tool returned. [Soering v. the United Kingdom, Judgment, §88]\n"
        "The corpus is a UK-only sample of the Court's case law."
    )
    parsed = parse_answer(text, evidence())
    assert [c["citation_ids"] for c in parsed.claims] == [
        ["001-58004§79"],
        ["001-58004§80"],
        [],
        [],
    ]
    assert parsed.unresolved == ["[Soering v. the United Kingdom, Judgment, §88]"]
    assert parsed.cited_ids == ["001-58004§79", "001-58004§80"]


def test_parse_answer_keeps_abbreviations_whole_and_attaches_trailing_citations():
    text = "In A.A. v. the United Kingdom the Court found a breach of Art. 8. [001-58004§79] It was a close call."
    claims = parse_answer(text, Evidence()).claims
    assert len(claims) == 2
    assert claims[0]["citation_ids"] == ["001-58004§79"] and claims[1]["citation_ids"] == []


def test_extract_quotes_needs_four_words():
    claim = {
        "text": 'The Court said "absolute" and "irrespective of the victim\'s conduct" in §79.',
        "blockquote": False,
    }
    assert extract_quotes(claim) == ["irrespective of the victim's conduct"]
    assert extract_quotes(
        {"text": "> the Convention prohibits in absolute terms torture", "blockquote": True}
    )


def test_check_text_follows_the_spec():
    exact = check_text(CHAHAL79, "the Convention prohibits in absolute terms torture")
    assert exact["verbatim"] and exact["similarity"] == 1.0
    curly = check_text(CHAHAL79, "irrespective of the victim’s conduct")  # curly apostrophe
    assert curly["verbatim"]
    gapped = check_text(
        CHAHAL79, "However, even in these circumstances … irrespective of the victim's conduct"
    )
    assert gapped["verbatim"]
    reordered = check_text(
        CHAHAL79, "irrespective of the victim's conduct … even in these circumstances"
    )
    assert not reordered["verbatim"]
    wrong = check_text(CHAHAL79, "the Convention permits deportation in absolute terms")
    assert not wrong["verbatim"] and 0.3 < wrong["similarity"] < 1
    assert "absolute terms" in wrong["closest_match"]
    missing = check_text(None, "anything")
    assert missing == {
        "paragraph_found": False,
        "verbatim": False,
        "similarity": 0.0,
        "closest_match": None,
    }


def test_quote_report_attributes_each_quote_to_its_claims_citations():
    good = '"prohibits in absolute terms torture or inhuman or degrading treatment" [001-58004§79]'
    bad = 'The Court said "deportation is always lawful for dangerous people" [001-58004§80].'
    none = 'It also said "nothing at all was ever said here" without a citation.'
    parsed = parse_answer("\n".join(["Article 3 is absolute " + good, bad, none]), evidence())
    report = quote_report(parsed, local_checker(TEXTS.get))
    assert [q["verbatim"] for q in report["quotes"]] == [True, False, False]
    assert report["quote_rate"] == pytest.approx(1 / 3)
    assert report["quotes"][2]["attributed_to"] == []
    assert quote_report(ParsedAnswer([], []), local_checker(TEXTS.get))["quote_rate"] is None


@pytest.mark.parametrize(
    "text,bare",
    [("Yes, the Convention stops it.", True), ("No. It does not.", True), ("No: Article 3 is absolute.", True),
     ("Not as a general rule: Article 3 is absolute.", False), ("It depends on Article 8.", False),
     ("**Yes** — always.", True), ("No general rule exists.", False)],
)  # fmt: skip
def test_no_bare_yes_no(text, bare):
    assert no_bare_yes_no(text) is (not bare)


def run_shape(checks, answer, *, tools=None, turn_calls=None, route=None, judge=None):
    parsed = parse_answer(answer, evidence())
    quotes = quote_report(parsed, local_checker(TEXTS.get))
    return shape_check(checks, answer_text=answer, parsed=parsed, tool_names=tools,
                       turn_tool_calls=turn_calls, route=route, quotes=quotes, judge_checks=judge)  # fmt: skip


def test_shape_checks_each_deterministic_kind():
    answer = (
        "Not as a general rule: Article 3 is absolute, see Al-Skeini and Article 8. "
        "[Chahal v. the United Kingdom, Judgment, §79] The Court held that the Convention "
        '"prohibits in absolute terms torture or inhuman or degrading treatment or punishment, '
        "irrespective of the victim's conduct\" (001-58004§79). There were 10 judgments, 9 with a violation."
    )
    checks = [
        {"kind": "no_bare_yes_no"}, {"kind": "cites_min", "n": 1}, {"kind": "cites_min", "n": 2},
        {"kind": "distinct_cases_min", "n": 1}, {"kind": "mentions", "any": ["Al-Skeini"]},
        {"kind": "mentions", "any": ["Legal summary", "legal summary"]},
        {"kind": "tool_used", "tool": "count_cases"}, {"kind": "contains_numbers", "snapshot": [10, 9]},
        {"kind": "contains_numbers", "snapshot": [10, 11]}, {"kind": "cites_doc", "doc_id": "001-58004"},
        {"kind": "cites_doc", "doc_id": "002-11569"}, {"kind": "cites_paragraph", "paragraph_id": "001-58004§79"},
        {"kind": "quotes_contain", "text": "irrespective of the victim's conduct"}, {"kind": "quotes_verbatim"},
        {"kind": "new_tool_calls"},
    ]  # fmt: skip
    result = run_shape(checks, answer, tools=["search_case_law", "count_cases"], turn_calls=2)
    assert [c["passed"] for c in result["checks"]] == [
        True, True, False, True, True, False, True, True, False, True, False, True, True, True, True,
    ]  # fmt: skip
    assert result["passed"] is False
    only_good = [c for c, r in zip(checks, result["checks"], strict=True) if r["passed"]]
    assert run_shape(only_good, answer, tools=["count_cases"], turn_calls=2)["passed"] is True


def test_shape_checks_for_ask_have_no_tools():
    checks = [{"kind": "tool_used", "tool": "count_cases"}, {"kind": "new_tool_calls"}]
    stats = run_shape(checks, "Ten.", route="stats")
    assert [c["passed"] for c in stats["checks"]] == [True, None] and stats["passed"] is True
    rag = run_shape(checks, "Ten.", route="rag")
    assert rag["passed"] is False


def test_shape_judge_checks_come_from_one_call_and_a_missing_judge_is_not_a_pass():
    checks = [
        {"kind": "judge", "text": "A"},
        {"kind": "judge", "text": "B"},
        {"kind": "mentions", "any": ["Article"]},
    ]
    seen = []

    def judge(requirements):
        seen.append(requirements)
        return [True, False]

    result = run_shape(checks, "Article 3.", judge=judge)
    assert seen == [["A", "B"]] and [c["passed"] for c in result["checks"]] == [True, False, True]
    assert result["passed"] is False
    assert run_shape(checks, "Article 3.", judge=None)["passed"] is False
    assert run_shape(checks, "Article 3.", judge=lambda r: [True, True])["passed"] is True


def test_numbers_as_words_and_inside_other_numbers():
    checks = [{"kind": "contains_numbers", "snapshot": [10, 9]}]
    assert run_shape(checks, "Ten were Grand Chamber and nine found a violation.")["passed"] is True
    assert run_shape(checks, "There were 110 and 19 of them.")["passed"] is False


def test_a_list_introduced_by_a_cited_sentence_inherits_its_citations():
    text = (
        "The Court listed the criteria [Chahal v. the United Kingdom, Judgment, §79]:\n"
        "- the nature and seriousness of the offence;\n"
        "- the length of the applicant's stay;\n"
        "A separate point with no citation at all follows here."
    )
    claims = parse_answer(text, evidence()).claims
    assert [c["citation_ids"] for c in claims] == [
        ["001-58004§79"],
        ["001-58004§79"],
        ["001-58004§79"],
        [],
    ]
    assert [c["inherited"] for c in claims] == [False, True, True, False]


def test_a_reworded_case_name_resolves_when_the_section_is_unique_among_what_the_tools_returned():
    parsed = parse_answer("Article 3 is absolute here. [Chahal, §79]", evidence())
    assert parsed.claims[0]["citation_ids"] == ["001-58004§79"] and parsed.unresolved == []
    ambiguous = Evidence()
    ambiguous.absorb([{"paragraph_id": "a§1"}, {"paragraph_id": "b§1"}])
    assert parse_answer("A claim with a vague cite. [Someone, §1]", ambiguous).unresolved == [
        "[Someone, §1]"
    ]


def test_nested_single_quotes_are_read_as_the_double_quotes_of_the_original():
    para = "The Court held that it must be justified \u201cin accordance with the law\u201d and \u201cnecessary in a democratic society\u201d."
    answer = "The Court said \"it must be justified 'in accordance with the law' and 'necessary in a democratic society'\" [001-58004§79]."
    report = quote_report(
        parse_answer(answer, Evidence()), local_checker({"001-58004§79": para}.get)
    )
    assert report["quote_rate"] == 1.0
    wrong = answer.replace("necessary in a democratic society", "required in a free society")
    assert (
        quote_report(parse_answer(wrong, Evidence()), local_checker({"001-58004§79": para}.get))[
            "quote_rate"
        ]
        == 0.0
    )


def test_a_qualified_no_is_not_bare():
    assert no_bare_yes_no("**No, not as a general rule.** The Convention limits it.")
    assert no_bare_yes_no("Not as a general rule: Article 3 is absolute.")
    assert not no_bare_yes_no("No. The Convention does not stop it.")
    assert not no_bare_yes_no("Yes, it does.")


def test_ranges_and_several_citations_in_one_bracket():
    ev = evidence()
    ev.absorb(
        {
            "paragraph_id": "001-95777§37",
            "doc_id": "001-95777",
            "case_name": "Omojudi v. the United Kingdom",
            "doc_type_label": "Judgment",
        }
    )
    text = (
        "The Court said so at length here [Chahal v. the United Kingdom, Judgment, §§79-80]. "
        "Both cases found violations [Omojudi v. the United Kingdom, Judgment, §37; Chahal v. the United Kingdom, Judgment, §79]."
    )
    claims = parse_answer(text, ev).claims
    assert claims[0]["citation_ids"] == ["001-58004§79", "001-58004§80"]
    assert claims[1]["citation_ids"] == ["001-95777§37", "001-58004§79"]


def test_section_refs_with_hyphens_are_kept_whole():
    ev = Evidence()
    ev.absorb(
        {
            "paragraph_id": "ukpga-1998-42§sch1-art8",
            "doc_id": "ukpga-1998-42",
            "case_name": "Human Rights Act 1998",
            "doc_type_label": "Legislation",
        }
    )
    claims = parse_answer(
        "The Act repeats the Article. [Human Rights Act 1998, Legislation, §sch1-art8]", ev
    ).claims
    assert claims[0]["citation_ids"] == ["ukpga-1998-42§sch1-art8"]
