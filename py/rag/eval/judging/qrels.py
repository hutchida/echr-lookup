"""Step 5: qrels v2, the graded answer key written from the judge's run-1 grades.

One line per judged question: {question_id, qrels: {paragraph_id: grade}, judge_model, run, seed,
source}. A question whose judge reply failed validation is left out (there is no grade to write),
never filled in. The original key (data/eval/questions.jsonl) is not touched.
"""

from collections.abc import Mapping, Sequence
from pathlib import Path

from .common import QRELS_V2_PATH, read_jsonl, write_jsonl

QRELS_SOURCE = "pooled relevance judging (docs/eval-judging.md)"


def build_qrels(records: Mapping[str, dict], pool: Sequence[dict]) -> list[dict]:
    """qrels rows from judge records (one per question, from `run_judging`), in pool order. Every
    pooled paragraph carries its grade; failed or missing questions are skipped."""
    rows = []
    for q in pool:
        rec = records.get(q["question_id"])
        if rec is None or not rec["ok"]:
            continue
        grades = {pid: g["grade"] for pid, g in rec["grades"].items()}
        rows.append(
            {
                "question_id": q["question_id"],
                "qrels": dict(sorted(grades.items())),
                "judge_model": rec["model"],
                "run": rec["run"],
                "seed": rec["seed"],
                "source": QRELS_SOURCE,
            }
        )
    return rows


def write_qrels(rows: Sequence[dict], path: Path = QRELS_V2_PATH) -> None:
    write_jsonl(path, list(rows))


def load_qrels(path: Path = QRELS_V2_PATH) -> dict[str, dict[str, int]]:
    """question id -> {paragraph id: grade}."""
    return {r["question_id"]: r["qrels"] for r in read_jsonl(path)}
