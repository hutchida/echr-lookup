import pytest

from .rescore import rescore

ITEMS = [
    {"id": "q1", "expected_paragraph_ids": ["a", "b"]},
    {"id": "q2", "expected_paragraph_ids": ["x"]},
    {"id": "q3", "expected_paragraph_ids": ["m"]},
]
ROWS = [
    {"question_id": "q1", "runs": {"fixed/bm25": [["a"], ["c"], ["d"]]}},
    {"question_id": "q2", "runs": {"fixed/bm25": [["y"], ["x"]]}},
    {"question_id": "q3", "runs": {"fixed/bm25": [["m"]]}},
]
QRELS = {"q1": {"a": 1, "b": 0, "c": 2, "d": 2}, "q2": {"x": 1, "y": 1}}  # q3 unjudged, q2 no gold
CFG = [("fixed", "bm25")]


def test_rescore_original_vs_v2():
    out = rescore(ITEMS, ROWS, QRELS, configs=CFG)
    (row,) = out["table"]
    # original: q1 recall 0.5, q2 1.0, q3 1.0
    assert row["original"]["recall_at_5"] == pytest.approx((0.5 + 1 + 1) / 3)
    # v2: q1 gold {c,d} both found -> 1.0; q2 has no grade-2 -> excluded; q3 unjudged -> excluded
    assert row["v2"]["recall_at_5"] == 1.0 and row["v2"]["n_recall_at_5"] == 1
    assert row["v2"]["n_ndcg_at_10"] == 2  # q1 and q2 have grade>0 paragraphs
    assert out["v2_questions"] == 2 and out["v2_no_gold"] == ["q2"] and out["unjudged"] == ["q3"]
    assert out["per_question"]["q3"]["fixed/bm25"]["v2"] is None


def test_original_ndcg_is_binary_on_gold():
    out = rescore(ITEMS, ROWS, QRELS, configs=CFG)
    q1 = out["per_question"]["q1"]["fixed/bm25"]["original"]
    # gold a at rank 1, b missing: dcg 1, ideal 1 + 1/log2(3)
    assert q1["ndcg_at_10"] == pytest.approx(1 / (1 + 1 / 1.5849625007211563))
