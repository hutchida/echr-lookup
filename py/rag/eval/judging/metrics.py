"""Graded metrics for qrels v2. Pure functions, no I/O. The original-style metrics (recall@k, MRR)
are reused from rag.eval.metrics with a different gold set; only nDCG is new.

nDCG@k
------
Graded gain: gain(g) = 2**g - 1, so grade 0 -> 0, grade 1 -> 1, grade 2 -> 3 (a paragraph that
directly answers is worth three "context" paragraphs).
Ranking: the de-duplicated paragraph ids of the hits in rank order (rag.eval.metrics
.retrieved_paragraph_ids), cut at k paragraphs. A paragraph not in the qrels has grade 0.
DCG  = sum over positions i = 1..k of gain(grade_i) / log2(i + 1)
IDCG = the same sum over the best possible ranking: all graded paragraphs of the question sorted
       by grade, highest first, cut at k.
nDCG = DCG / IDCG; None when the question has no paragraph with grade > 0 (IDCG = 0).
The original key is binary, so its nDCG uses grade 1 for every gold paragraph (gain 1): the two
columns of the comparison are on the same scale.

v2 recall
---------
Gold under v2 = paragraphs graded 2. Recall@k, MRR and doc hits use rag.eval.metrics with that gold
set. A question with no grade-2 paragraph has no gold, so recall and MRR are None and the question
drops out of the v2 mean (rag.eval.metrics.mean ignores None); the report states how many.
"""

import math
from collections.abc import Mapping, Sequence

from rag.eval.metrics import (
    mean,
    recall_at_k,
    reciprocal_rank,
    retrieved_paragraph_ids,
)

NDCG_K = 10


def gain(grade: int) -> float:
    return float(2**grade - 1)


def dcg(grades: Sequence[int]) -> float:
    return sum(gain(g) / math.log2(i + 2) for i, g in enumerate(grades))


def ndcg_at_k(hits: Sequence[dict], qrels: Mapping[str, int], k: int = NDCG_K) -> float | None:
    """nDCG@k of a hit list against {paragraph_id: grade}; formula in the module docstring."""
    ideal = sorted((g for g in qrels.values() if g > 0), reverse=True)[:k]
    if not ideal:
        return None
    ranked = retrieved_paragraph_ids(hits, k)
    return dcg([qrels.get(pid, 0) for pid in ranked]) / dcg(ideal)


def gold_from_qrels(qrels: Mapping[str, int]) -> set[str]:
    """v2 gold: the paragraphs graded 2."""
    return {pid for pid, g in qrels.items() if g == 2}


def binary_qrels(expected: Sequence[str]) -> dict[str, int]:
    """The original key as a graded key (grade 1 = gold) so ndcg_at_k applies to it."""
    return dict.fromkeys(expected, 1)


def score_question(hits: Sequence[dict], gold: set[str], qrels: Mapping[str, int]) -> dict:
    """Recall@5/@10, MRR (against `gold`) and nDCG@10 (against `qrels`) for one hit list."""
    return {
        "recall_at_5": recall_at_k(hits, gold, 5),
        "recall_at_10": recall_at_k(hits, gold, 10),
        "mrr": reciprocal_rank(hits, gold, 10),
        "ndcg_at_10": ndcg_at_k(hits, qrels, NDCG_K),
    }


def mean_scores(rows: Sequence[Mapping[str, float | None]]) -> dict:
    """Mean of each metric over the questions where it is defined, plus how many that was."""
    out: dict = {}
    for key in ("recall_at_5", "recall_at_10", "mrr", "ndcg_at_10"):
        vals = [r[key] for r in rows]
        out[key] = mean(vals)
        out[f"n_{key}"] = sum(v is not None for v in vals)
    return out
