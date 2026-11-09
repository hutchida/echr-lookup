"""Step 6: re-score all 12 configs against the original key and against qrels v2, from the saved
top-10 hit lists (retrieval.jsonl); no search is re-run.

Original key: gold = expected_paragraph_ids; nDCG@10 with gain 1 per gold paragraph (binary).
v2: gold = paragraphs graded 2; nDCG@10 with gain 2**grade - 1 (see rag.eval.judging.metrics).
A question without a grade-2 paragraph has no v2 gold: it is excluded from the v2 recall and MRR
means (reported as n), as is a question the judge failed on.
"""

from collections.abc import Mapping, Sequence

from .common import CONFIGS, config_key
from .metrics import binary_qrels, gold_from_qrels, mean_scores, score_question


def hits_from_run(run_hits: Sequence[Sequence[str]]) -> list[dict]:
    """Saved hit lists -> the minimal hit dicts rag.eval.metrics works on."""
    return [{"paragraph_ids": list(p)} for p in run_hits]


def rescore(
    items: Sequence[dict],
    retrieval_rows: Sequence[dict],
    qrels: Mapping[str, Mapping[str, int]],
    configs: Sequence[tuple[str, str]] = CONFIGS,
) -> dict:
    """-> {"table": [{"config", "chunking", "mode", "original": {...}, "v2": {...}}],
    "per_question": {qid: {cfg: {"original": {...}, "v2": {...}|None}}},
    "v2_questions": n judged, "v2_no_gold": [qids with no grade-2 paragraph]}"""
    by_id = {i["id"]: i for i in items}
    per_question: dict[str, dict] = {}
    for row in retrieval_rows:
        qid = row["question_id"]
        expected = by_id[qid]["expected_paragraph_ids"]
        gold_orig, graded_orig = set(expected), binary_qrels(expected)
        per_question[qid] = {}
        for chunking, mode in configs:
            key = config_key(chunking, mode)
            hits = hits_from_run(row["runs"][key])
            entry = {"original": score_question(hits, gold_orig, graded_orig), "v2": None}
            if qid in qrels:
                entry["v2"] = score_question(hits, gold_from_qrels(qrels[qid]), qrels[qid])
            per_question[qid][key] = entry
    table = []
    for chunking, mode in configs:
        key = config_key(chunking, mode)
        v2_rows = [q[key]["v2"] for q in per_question.values() if q[key]["v2"] is not None]
        table.append(
            {
                "config": key,
                "chunking": chunking,
                "mode": mode,
                "original": mean_scores([q[key]["original"] for q in per_question.values()]),
                "v2": mean_scores(v2_rows),
            }
        )
    return {
        "table": table,
        "per_question": per_question,
        "v2_questions": sum(qid in qrels for qid in per_question),
        "v2_no_gold": sorted(
            qid for qid in per_question if qid in qrels and not gold_from_qrels(qrels[qid])
        ),
        "unjudged": sorted(qid for qid in per_question if qid not in qrels),
    }
