# ruff: noqa: E501
import json

from rag.eval.items import (
    SNAPSHOT_DIR,
    expected_count,
    load_questions,
    snapshot_paragraph_ids,
    validate_items,
)

DEMO_QUESTIONS = [
    "Does the Convention stop the UK deporting criminals?",
    "How has Article 8 been applied in UK immigration cases?",
    "How many UK deportation complaints in the corpus were declared inadmissible, and the most common reasons?",
]


def test_question_set_shape():
    items = load_questions()
    assert 60 <= len(items) <= 80
    by_type = {t: [i for i in items if i["type"] == t] for t in ("explain", "stat", "neutrality")}
    assert len(by_type["explain"]) >= 40
    assert len(by_type["stat"]) >= 8
    assert len(by_type["neutrality"]) >= 8
    assert {i["status"] for i in items} == {"draft"}
    assert all(set(i["tags"]) & {"easy", "medium", "hard"} for i in items)
    questions = {i["question"] for i in items}
    assert all(q in questions for q in DEMO_QUESTIONS)


def test_every_item_validates_against_the_contract():
    assert validate_items(load_questions()) == []


def test_expected_paragraph_ids_present_exactly_when_needed():
    for item in load_questions():
        if item["type"] == "stat":
            assert item["expected_paragraph_ids"] == []
            assert expected_count(item) is not None
            assert f"[expected_count={expected_count(item)}]" in item["reference_notes"]
        else:
            assert item["expected_paragraph_ids"], item["id"]


def test_every_expected_paragraph_exists_in_the_snapshot():
    known = snapshot_paragraph_ids()
    missing = [
        (i["id"], pid)
        for i in load_questions()
        for pid in i["expected_paragraph_ids"]
        if pid not in known
    ]
    assert missing == []


def test_stat_counts_match_the_manifest():
    manifest = json.loads((SNAPSHOT_DIR / "manifest.json").read_text())
    docs = lambda t: [e for e in manifest if e["doc_type"] == t]  # noqa: E731
    judgments, decisions = docs("judgment"), docs("decision")

    def has_article(e, a):
        return any(x == a or x.startswith(a + "-") for x in e["articles"])

    oracle = {
        "How many UK decisions in the corpus were declared inadmissible?": sum(
            e["outcome"] == "inadmissible" for e in decisions
        ),
        "How many UK judgments in the corpus found no violation?": sum(
            e["outcome"] == "no_violation" for e in judgments
        ),
        "How many UK judgments in the corpus found at least one violation?": sum(
            e["outcome"] in ("violation", "mixed") for e in judgments
        ),
        "How many UK decisions in the corpus were struck out?": sum(
            e["outcome"] == "struck_out" for e in decisions
        ),
        "How many Grand Chamber judgments about the UK are in the corpus?": sum(
            e["chamber"] == "Grand Chamber" for e in judgments
        ),
        "How many UK judgments in the corpus concern Article 8?": sum(
            has_article(e, "8") for e in judgments
        ),
        "How many UK judgments in the corpus concern Article 3?": sum(
            has_article(e, "3") for e in judgments
        ),
        "How many UK judgments in the corpus were delivered since 2010?": sum(
            e["date"] >= "2010-01-01" for e in judgments
        ),
        "How many legal summaries are in the corpus?": len(docs("legal_summary")),
    }
    by_question = {i["question"]: expected_count(i) for i in load_questions()}
    for question, count in oracle.items():
        assert by_question[question] == count, question
