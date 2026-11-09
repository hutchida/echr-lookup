import math

import pytest

from .metrics import (
    binary_qrels,
    dcg,
    gain,
    gold_from_qrels,
    mean_scores,
    ndcg_at_k,
    score_question,
)


def hits(*groups):
    return [{"paragraph_ids": list(g)} for g in groups]


def test_gain_is_two_to_the_grade_minus_one():
    assert [gain(g) for g in (0, 1, 2)] == [0, 1, 3]


def test_dcg_discounts_by_log2_rank():
    assert dcg([2, 1]) == pytest.approx(3 / math.log2(2) + 1 / math.log2(3))


def test_ndcg_worked_example():
    qrels = {"a": 2, "b": 1, "c": 0}
    ranked = hits(["b"], ["x"], ["a"])  # b at 1, x (ungraded) at 2, a at 3
    dcg_ = 1 / math.log2(2) + 0 + 3 / math.log2(4)
    idcg = 3 / math.log2(2) + 1 / math.log2(3)
    assert ndcg_at_k(ranked, qrels) == pytest.approx(dcg_ / idcg)


def test_ndcg_perfect_and_empty_hits():
    qrels = {"a": 2, "b": 1}
    assert ndcg_at_k(hits(["a"], ["b"]), qrels) == pytest.approx(1.0)
    assert ndcg_at_k([], qrels) == 0.0


def test_ndcg_none_without_any_relevant_paragraph():
    assert ndcg_at_k(hits(["a"]), {"a": 0, "b": 0}) is None
    assert ndcg_at_k(hits(["a"]), {}) is None


def test_ndcg_dedups_paragraphs_and_cuts_at_k_paragraphs():
    # 'a' repeated across hits counts once; k paragraphs, not k hits
    qrels = {"a": 1}
    assert ndcg_at_k(hits(["a", "a"], ["a"]), qrels) == pytest.approx(1.0)
    many = hits([f"p{i}" for i in range(12)], ["a"])  # a would be paragraph 13: beyond k=10
    assert ndcg_at_k(many, qrels) == 0.0


def test_ndcg_ideal_ranking_is_cut_at_k():
    qrels = {f"p{i}": 2 for i in range(15)}
    top = hits(*[[f"p{i}"] for i in range(10)])
    assert ndcg_at_k(top, qrels) == pytest.approx(1.0)


def test_binary_qrels_and_v2_gold():
    assert binary_qrels(["a", "b"]) == {"a": 1, "b": 1}
    assert gold_from_qrels({"a": 2, "b": 1, "c": 0, "d": 2}) == {"a", "d"}


def test_score_question_uses_gold_for_recall_and_qrels_for_ndcg():
    qrels = {"a": 2, "b": 2, "c": 1}
    s = score_question(hits(["x"], ["c"], ["a"]), gold_from_qrels(qrels), qrels)
    assert s["recall_at_5"] == 0.5 and s["recall_at_10"] == 0.5
    assert s["mrr"] == pytest.approx(1 / 3)
    assert 0 < s["ndcg_at_10"] < 1


def test_no_gold_gives_none_so_the_question_leaves_the_mean():
    qrels = {"c": 1}
    s = score_question(hits(["c"]), gold_from_qrels(qrels), qrels)
    assert s["recall_at_5"] is None and s["mrr"] is None and s["ndcg_at_10"] is not None
    m = mean_scores([s, {"recall_at_5": 1.0, "recall_at_10": 1.0, "mrr": 1.0, "ndcg_at_10": 0.5}])
    assert m["recall_at_5"] == 1.0 and m["n_recall_at_5"] == 1 and m["n_ndcg_at_10"] == 2


def test_original_key_binary_matches_rag_eval_metrics():
    from rag.eval.metrics import recall_at_k, reciprocal_rank

    h = hits(["x"], ["a", "q"], ["b"])
    expected = ["a", "b", "z"]
    s = score_question(h, set(expected), binary_qrels(expected))
    assert s["recall_at_5"] == recall_at_k(h, expected, 5)
    assert s["mrr"] == reciprocal_rank(h, expected, 10)
