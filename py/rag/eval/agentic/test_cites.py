# ruff: noqa: E501
"""The citation formats the F1 server hands out, from its own contract fixtures: `cite` strings
with a `para_label` that has no § ("Summary, para 3"), and `hudoc_url`s with a `#:~:text=` fragment
(which can contain parentheses). Each must map back to the paragraph id. No model, no database."""

import json

import pytest

from rag.config import REPO_ROOT
from rag.eval.agentic.text import Evidence, parse_answer

FIXTURES = REPO_ROOT / "packages" / "contract" / "fixtures"


def evidence() -> Evidence:
    ev = Evidence()
    for name in ("McpSearchCaseLawResult", "McpGetParagraphsResult", "McpGetCaseResult"):
        ev.absorb(json.loads((FIXTURES / f"{name}.json").read_text()))
    return ev


SUMMARY = "[Othman (Abu Qatada) v. the United Kingdom, Legal summary, Summary, para 3]"
OPERATIVE = "[Chahal v. the United Kingdom, Judgment, Operative provisions, para 1]"
NUMBERED = "[Chahal v. the United Kingdom, Judgment, §79]"


def cited(answer: str) -> tuple[list[str], list[str]]:
    parsed = parse_answer(answer, evidence())
    return parsed.cited_ids, parsed.unresolved


def test_fixtures_carry_the_new_format():
    ev = evidence()
    assert ev.cites[SUMMARY] == "002-44§u3"
    assert ev.cites[OPERATIVE] == "001-58004§op1"
    assert any(":~:text=" in u for u in ev.urls)
    assert any("(" in u and ":~:text=" in u for u in ev.urls)  # parentheses survive encoding


@pytest.mark.parametrize(
    ("answer", "expected"),
    [
        (
            f"The Court summarised the risk of unfair evidence at a retrial. {SUMMARY}",
            ["002-44§u3"],
        ),
        (
            f"The Court found that deportation would breach Article 3. {OPERATIVE}",
            ["001-58004§op1"],
        ),
        (f"Article 3 is absolute even for suspected terrorists. {NUMBERED}", ["001-58004§79"]),
        (f"- A bullet with the new label form {SUMMARY}.", ["002-44§u3"]),
        (
            f"A claim with a lower-case, re-spaced cite. {SUMMARY.lower().replace(', ', ',  ')}",
            ["002-44§u3"],
        ),
        (
            f"Two cites in one claim, as the model writes them. {SUMMARY} {NUMBERED}",
            ["002-44§u3", "001-58004§79"],
        ),
    ],
)
def test_new_cite_strings_map_to_paragraph_ids(answer, expected):
    ids, unresolved = cited(answer)
    assert ids == expected and unresolved == []


def test_hudoc_url_links_map_to_paragraph_ids_even_with_parentheses_in_the_fragment():
    ev = evidence()
    url = next(
        u
        for u in ev.urls
        if u.startswith("https://hudoc.echr.coe.int/eng?i=001-58004#:~:text=The%20Commission")
    )
    answer = f"The Commission rejected the Government's arguments. [Chahal, para 78]({url})"
    parsed = parse_answer(answer, ev)
    assert parsed.cited_ids == ["001-58004§78"] and parsed.unresolved == []
    assert "http" not in parsed.claims[0]["text"]  # the link target is not part of the claim


def test_cite_followed_by_its_own_link():
    ev = evidence()
    url = next(u for u, pid in ev.urls.items() if pid == "002-44§u3")
    parsed = parse_answer(f"Real risk of tainted evidence at a retrial. {SUMMARY}({url})", ev)
    assert parsed.cited_ids == ["002-44§u3"]
    assert "http" not in parsed.claims[0]["text"]


def test_a_cite_shaped_bracket_no_tool_returned_is_reported_unresolved():
    ids, unresolved = cited(
        "A claim citing a case no tool returned. [Soering v. the United Kingdom, Judgment, Law, para 4]"
    )
    assert ids == []
    assert unresolved == ["[Soering v. the United Kingdom, Judgment, Law, para 4]"]


def test_other_brackets_are_left_alone():
    ids, unresolved = cited("The Court said [sic] that Article 3 is absolute in all cases.")
    assert ids == [] and unresolved == []


def test_old_format_still_resolves():
    ids, unresolved = cited(
        "Article 3 is absolute. [Chahal v. the United Kingdom, Judgment, §79] Also 001-58004§80 says so."
    )
    assert ids == ["001-58004§79", "001-58004§80"] and unresolved == []
