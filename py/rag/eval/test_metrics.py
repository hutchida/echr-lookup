import pytest

from rag.eval.metrics import (
    mean,
    recall_at_k,
    reciprocal_rank,
    retrieved_paragraph_ids,
    stat_correct,
)


def hit(*pids):
    return {"paragraph_ids": list(pids)}


# Expected evidence for a Soering question: two paragraphs.
EXPECTED = ["001-57619§91", "001-57619§111"]

# Ranked hits: 1 irrelevant, 2 irrelevant, 3 irrelevant, 4 irrelevant, 5 irrelevant,
# 6 irrelevant, 7 a chunk covering §110 and §111 (relevant), 8-10 irrelevant.
HITS = [hit(f"001-57619§{n}") for n in (81, 92, 99, 98, 76, 105)]
HITS += [hit("001-57619§110", "001-57619§111")]
HITS += [hit("001-57619§107"), hit("001-57619§37"), hit("002-74§u1")]


def test_recall_counts_expected_paragraphs_covered():
    assert recall_at_k(HITS, EXPECTED, 5) == 0.0
    # one of two expected paragraphs (§111) is covered by hit 7 -> 1/2
    assert recall_at_k(HITS, EXPECTED, 10) == 0.5


def test_recall_full_when_all_covered():
    hits = [hit("001-57619§91"), hit("001-57619§111")]
    assert recall_at_k(hits, EXPECTED, 5) == 1.0


def test_reciprocal_rank_uses_first_relevant_hit_any_paragraph_id():
    assert reciprocal_rank(HITS, EXPECTED) == pytest.approx(1 / 7)
    assert reciprocal_rank([hit("001-57619§91")], EXPECTED) == 1.0
    assert reciprocal_rank(HITS[:5], EXPECTED) == 0.0


def test_reciprocal_rank_ignores_hits_below_the_cutoff():
    hits = [hit("x§1")] * 10 + [hit("001-57619§91")]
    assert reciprocal_rank(hits, EXPECTED, 10) == 0.0


def test_no_expected_paragraphs_gives_none():
    assert recall_at_k(HITS, [], 5) is None
    assert reciprocal_rank(HITS, []) is None


def test_mean_skips_none():
    assert mean([1.0, None, 0.0]) == 0.5
    assert mean([None, None]) is None


def test_retrieved_ids_best_first_deduplicated_and_capped():
    hits = [hit("a§1", "a§2"), hit("a§2", "a§3")] + [hit(f"b§{n}") for n in range(20)]
    ids = retrieved_paragraph_ids(hits, 10)
    assert ids[:3] == ["a§1", "a§2", "a§3"]
    assert len(ids) == 10


def test_stat_correct_needs_stats_route_and_matching_count():
    ok = {"route": "stats", "stats": {"count": 33}}
    assert stat_correct(ok, 33)
    assert not stat_correct(ok, 27)
    assert not stat_correct({"route": "rag", "stats": None}, 33)


def test_doc_hit_counts_right_case_wrong_paragraph():
    from rag.eval.metrics import doc_hit_at_k

    assert doc_hit_at_k(HITS, EXPECTED, 5) == 1.0  # Soering hits, none of them §91 or §111
    assert doc_hit_at_k([hit("002-74§u1")], EXPECTED, 5) == 0.0
    assert doc_hit_at_k(HITS, [], 5) is None
