import pytest

from .analysis import (
    agreement,
    cohen_kappa,
    grade_tables,
    paired_grades,
    reason_mismatches,
    review_list,
    trim,
)


def rec(grades, ok=True):
    return {"ok": ok, "grades": {p: {"grade": g, "reason": f"r{p}{g}"} for p, g in grades.items()}}


def para(pid, gold, n=1, text="Some text."):
    return {"id": pid, "gold": gold, "n_configs": n, "case_name": "C", "section": "S", "text": text}


POOL = [
    {"question_id": "q1", "question": "Q1?",
     "paragraphs": [para("a", True), para("b", True), para("c", False), para("d", False)]},
    {"question_id": "q2", "question": "Q2?", "paragraphs": [para("e", True), para("f", False)]},
    {"question_id": "q3", "question": "Q3?", "paragraphs": [para("g", True)]},
]  # fmt: skip
RUN1 = {
    "q1": rec({"a": 2, "b": 0, "c": 2, "d": 1}),
    "q2": rec({"e": 1, "f": 2}),
    "q3": rec({}, ok=False),
}
RUN2 = {"q1": rec({"a": 2, "b": 1, "c": 0, "d": 0}), "q2": rec({"e": 1, "f": 2})}


def test_grade_tables_counts_added_and_disputed_gold():
    t = grade_tables(POOL, RUN1)
    assert t["questions_judged"] == 2 and t["questions_failed"] == 1
    assert t["gold_total"] == 3 and t["gold_confirmed"] == 1
    assert t["gold_disputed_0"] == 1 and t["gold_disputed_1"] == 1
    assert t["gold_added"] == 2 and t["questions_with_added"] == 2
    assert t["grade_counts"] == {0: 1, 1: 2, 2: 3}


def test_paired_grades_skips_failed_and_missing_questions():
    pairs = paired_grades(RUN1, RUN2)
    assert len(pairs) == 6 and {p["question_id"] for p in pairs} == {"q1", "q2"}


def test_agreement_exact_two_vs_not_and_changes():
    a = agreement(paired_grades(RUN1, RUN2))
    assert a["paragraphs"] == 6 and a["exact"] == pytest.approx(3 / 6)
    assert a["changed"] == 3 and a["changed_by_two"] == 1  # c: 2 -> 0
    assert a["two_vs_not"] == pytest.approx(5 / 6)  # only c flips 2 <-> not 2
    assert 0 < a["kappa"] < 1


def test_cohen_kappa_known_values():
    assert cohen_kappa([(1, 1), (0, 0), (1, 1), (0, 0)]) == pytest.approx(1.0)
    assert cohen_kappa([(1, 0), (0, 1), (1, 0), (0, 1)]) == pytest.approx(-1.0)
    assert cohen_kappa([(1, 1), (1, 1)]) is None  # one label only: undefined
    assert cohen_kappa([]) is None


def test_trim_is_a_verbatim_prefix():
    text = "word " * 400
    out = trim(text, 100)
    assert out.endswith(" [...]") and text.startswith(out[: -len(" [...]")])
    assert trim("short") == "short"


def test_review_list_mixes_categories_and_is_deterministic():
    items = review_list(POOL, RUN1, RUN2, n=10)
    cats = [i["category"] for i in items]
    assert "gold_graded_0" in cats and "added_gold" in cats and "flipped" in cats
    zero = next(i for i in items if i["category"] == "gold_graded_0")
    assert zero["paragraph_id"] == "b" and zero["grade"] == 0 and zero["original_gold"]
    flip = next(i for i in items if i["category"] == "flipped")
    assert flip["paragraph_id"] == "d" and flip["grade"] == 1 and flip["other_run_grade"] == 0
    assert items == review_list(POOL, RUN1, RUN2, n=10)
    assert len({(i["question_id"], i["paragraph_id"]) for i in items}) == len(items)


def test_review_list_respects_n_and_fills_shortfall():
    items = review_list(POOL, RUN1, RUN2, n=2)
    assert len(items) == 2
    assert review_list(POOL, RUN1, {}, n=5)  # no second run: no flips, still lists the rest


def test_reason_mismatch_flags_a_reason_about_another_paragraph():
    pool = [{"question_id": "q", "paragraphs": [
        {"id": "a", "text": "The applicant was extradited to Virginia."},
        {"id": "b", "text": "Hearing in public at Strasbourg."},
    ]}]  # fmt: skip
    rec = {"q": {"ok": True, "grades": {
        "a": {"grade": 2, "reason": "Describes the applicant extradited to Virginia."},
        "b": {"grade": 2, "reason": "Holds that extradition engages responsibility."},
    }}}  # fmt: skip
    flagged = reason_mismatches(pool, rec)
    assert [f["paragraph_id"] for f in flagged] == ["b"]
