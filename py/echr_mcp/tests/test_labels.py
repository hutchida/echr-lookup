"""para_label rules, cite uniqueness, and that paragraph ids did not change."""

import json
from pathlib import Path

from echr_mcp import tools
from echr_mcp.common import cite, unique_cites
from echr_mcp.labels import legislation_label, para_label, unnumbered_labels
from echr_mcp.tests import seed
from rag.index import get_embedder

GOLDEN = json.loads((Path(__file__).parent / "golden_paragraph_ids.json").read_text())


def test_numbered_paragraphs_are_section_signs():
    assert para_label("001-58004§79", 79, {}) == "§79"


def test_unnumbered_paragraphs_count_within_their_section_in_document_order():
    rows = [
        ("d§1", 1, "The Facts", "Numbered."),
        ("d§u1", None, "The Facts", "First unnumbered fact."),
        ("d§u2", None, "The Law", "First unnumbered law."),
        ("d§u3", None, "The Facts", "Second unnumbered fact."),
        ("d§op1", None, "Operative provisions", "Holds that"),
        ("d§op2", None, "Operative provisions", "Holds that"),
        ("d§u4", None, "Other", "Dissent."),
        ("d§u5", None, "Procedure", "Hearing."),
    ]
    assert unnumbered_labels("judgment", rows) == {
        "d§u1": "Facts, para 1",
        "d§u2": "Law, para 1",
        "d§u3": "Facts, para 2",
        "d§op1": "Operative provisions, para 1",
        "d§op2": "Operative provisions, para 2",
        "d§u4": "Other, para 1",
        "d§u5": "Procedure, para 1",
    }


def test_legal_summary_sections_come_from_the_text_not_the_stored_section():
    rows = [
        ("s§u1", None, "Other", "Harkins and Edwards v. the United Kingdom - 9146/07"),
        ("s§u2", None, "Other", "Judgment 17.1.2012 [Section IV]"),
        ("s§u3", None, "Other", "Proposed extradition to United States"),
        ("s§u4", None, "Other", "Facts – Both applicants faced extradition"),
        ("s§u5", None, "Other", "Law – Article 3"),
        ("s§u6", None, "Other", "(a) Death penalty – The Court reiterated"),
        ("s§u7", None, "Other", "Conclusion: inadmissible."),
        ("s§u8", None, "Other", "[1] R (Wellington) v. Secretary of State"),
    ]
    labels = unnumbered_labels("legal_summary", rows)
    assert labels["s§u1"] == "Summary, para 1"
    assert labels["s§u3"] == "Summary, para 3"
    assert labels["s§u4"] == "Facts, para 1"
    assert labels["s§u5"] == "Law, para 1"
    assert labels["s§u6"] == "Law, para 2"
    assert labels["s§u7"] == "Law, para 3"
    assert labels["s§u8"] == "Notes, para 1"


def test_legal_summary_headings_as_the_snapshot_writes_them():
    for facts, law in [
        ("Facts: The applicant", "Law: Article 5"),
        ("Facts– Both", "Law– Article 3"),
    ]:
        rows = [("s§u1", None, "Other", "Title"), ("s§u2", None, "The Facts", facts)]
        rows.append(("s§u3", None, "The Law", law))
        assert unnumbered_labels("legal_summary", rows)["s§u3"] == "Law, para 1"
    # a paragraph merely starting with the letters is not a heading
    rows = [("s§u1", None, "Other", "Lawful detention"), ("s§u2", None, "Other", "Factsheet")]
    assert set(unnumbered_labels("legal_summary", rows).values()) == {
        "Summary, para 1",
        "Summary, para 2",
    }


def test_legislation_labels_read_the_id():
    cases = {
        "echr-convention§art8": "Article 8",
        "echr-convention§preamble": "Preamble",
        "echr-convention§p1-art1": "Protocol 1, Article 1",
        "ukpga-1998-42§s3": "section 3",
        "ukpga-1998-42§s2A": "section 2A",
        "ukpga-1998-42§sch1-p1-art1": "Schedule 1, Protocol 1, Article 1",
        "ukpga-1998-42§sch1-part1": "Schedule 1, Part 1",
        "ukpga-1998-42§sch2-para1": "Schedule 2, paragraph 1",
        "ukpga-1998-42§odd-ref": "§odd-ref",
    }
    for pid, label in cases.items():
        assert legislation_label(pid) == label, pid
    assert unnumbered_labels("legislation", [("x§art8", None, "The Law", "")]) == {
        "x§art8": "Article 8"
    }


def test_cite_uses_the_label():
    assert (
        cite("Harkins and Edwards v. the United Kingdom", "legal_summary", "Law, para 2")
        == "[Harkins and Edwards v. the United Kingdom, Legal summary, Law, para 2]"
    )
    assert cite("Saadi v. the United Kingdom [GC]", "judgment", "§79") == (
        "[Saadi v. the United Kingdom (GC), Judgment, §79]"
    )
    assert cite("X v. UK", "judgment", "§1", "001-1") == "[X v. UK, Judgment (001-1), §1]"


def test_cites_that_would_clash_get_the_doc_id():
    def item(doc_id, pid, label="§79"):
        name, kind = "Chahal v. the United Kingdom", "judgment"
        return {
            "paragraph_id": pid,
            "doc_id": doc_id,
            "case_name": name,
            "doc_type": kind,
            "para_label": label,
            "cite": cite(name, kind, label),
        }

    items = [item("001-1", "001-1§79"), item("001-2", "001-2§79"), item("001-1", "001-1§80", "§80")]
    unique_cites(items)
    assert [i["cite"] for i in items] == [
        "[Chahal v. the United Kingdom, Judgment (001-1), §79]",
        "[Chahal v. the United Kingdom, Judgment (001-2), §79]",
        "[Chahal v. the United Kingdom, Judgment, §80]",
    ]
    assert len({i["cite"] for i in items}) == 3
    same = [item("001-1", "001-1§79"), item("001-1", "001-1§79")]  # one paragraph twice: unchanged
    unique_cites(same)
    assert same[0]["cite"].endswith("Judgment, §79]")


def test_two_documents_with_one_name_get_distinct_cites_from_the_tools(seeded):
    seeded.execute(
        "UPDATE documents SET case_name = (SELECT case_name FROM documents WHERE item_id = %s) "
        "WHERE item_id = %s",
        (seed.OTHMAN, seed.CHAHAL),
    )
    try:
        result = tools.get_paragraphs(seeded, {"paragraph_ids": ["001-58004§79", "001-108629§79"]})
        cites = [p["cite"] for p in result["paragraphs"]]
        assert len(set(cites)) == 2
        assert cites == [
            "[Othman (Abu Qatada) v. the United Kingdom, Judgment (001-58004), §79]",
            "[Othman (Abu Qatada) v. the United Kingdom, Judgment (001-108629), §79]",
        ]
    finally:
        seeded.rollback()


def test_labels_in_tool_results(seeded):
    got = tools.get_paragraphs(seeded, {"paragraph_ids": ["001-58004§79", "001-58004§op2"]})
    assert [(p["para_label"], p["cite"]) for p in got["paragraphs"]] == [
        ("§79", "[Chahal v. the United Kingdom, Judgment, §79]"),
        (
            "Operative provisions, para 2",
            "[Chahal v. the United Kingdom, Judgment, Operative provisions, para 2]",
        ),
    ]
    case = tools.get_case(seeded, {"case_id": seed.CHAHAL})
    assert case["operative_provisions"][0]["para_label"] == "Operative provisions, para 1"
    assert case["operative_provisions"][1]["cite"].endswith(
        "Judgment, Operative provisions, para 2]"
    )
    checked = tools.check_quote(seeded, {"paragraph_id": "002-44§u3", "quote": "Real risk"})
    assert checked["para_label"] == "Summary, para 1"
    assert checked["cite"].endswith("Legal summary, Summary, para 1]")
    missing = tools.check_quote(seeded, {"paragraph_id": "001-58004§9999", "quote": "x"})
    assert missing["para_label"] is None


def test_paragraph_ids_are_unchanged(seeded):
    """GOLDEN was recorded from the tools before para_label existed: same queries, same ids."""
    embedder = get_embedder("fake")
    for query, ids in GOLDEN.items():
        if query in ("get", "case"):
            continue
        found = tools.search_case_law(seeded, {"query": query, "limit": 10}, embedder=embedder)
        # the fake embedder breaks ties differently on different machines: compare as sets
        assert sorted(h["paragraph_id"] for h in found["hits"]) == sorted(ids), query
    paragraphs = tools.get_paragraphs(
        seeded,
        {
            "paragraph_ids": ["001-58004§79", "001-58004§op2", "002-44§u3", "001-57943§2"],
            "neighbours": 1,
        },
    )
    assert [p["paragraph_id"] for p in paragraphs["paragraphs"]] == GOLDEN["get"]
    case = tools.get_case(seeded, {"case_id": "001-58004"})
    assert [o["paragraph_id"] for o in case["operative_provisions"]] == GOLDEN["case"]
