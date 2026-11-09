# ruff: noqa: E501
"""The "after F1" column and question table, built from the recorded M2 rows (no model, no DB)."""

import copy
import json

from rag.config import REPO_ROOT
from rag.eval.agentic.report import render

RESULTS = REPO_ROOT / "data" / "eval" / "agentic" / "results.jsonl"


def m2_rows() -> list[dict]:
    return [json.loads(line) for line in RESULTS.read_text().splitlines() if line]


def test_without_a_rerun_the_tables_have_two_columns_and_no_after_section():
    doc = render(m2_rows())
    assert "| | Claude + tools | `/ask` |" in doc
    assert "After F1" not in doc


def test_rerun_rows_add_a_third_column_and_flag_regressions():
    rows = m2_rows()
    after = [{**copy.deepcopy(r), "run_label": "after-F1"} for r in rows if r["system"] == "mcp"]
    for r in after:  # make or-03 worse (2/3 → 0/3) and or-02 better (1/3 → 3/3)
        if r["set"] == "owner-review" and r["item_id"] == "or-03":
            r["shape"]["passed"] = False
        if r["set"] == "owner-review" and r["item_id"] == "or-02":
            r["shape"]["passed"] = True
    doc = render(rows, after=after, after_meta={"db": "echr_f3"})
    assert "| | Claude + tools | `/ask` | Claude + tools, after F1 |" in doc
    assert "## After F1: Claude + tools re-run on the improved server" in doc
    line = {ln.split("|")[1].strip(): ln for ln in doc.splitlines() if ln.startswith("| or-")}
    assert "2/3 → 0/3" in line["or-03"] and "**regression**" in line["or-03"]
    assert "1/3 → 3/3" in line["or-02"] and "better" in line["or-02"]
    assert line["or-01"].rstrip().endswith("|  |")  # unchanged: no flag
    assert "<!-- after-f1:start -->" in doc  # the verdict block is kept for the hand-written text


def test_a_written_verdict_survives_a_rewrite():
    rows = m2_rows()
    after = [{**copy.deepcopy(r), "run_label": "after-F1"} for r in rows if r["system"] == "mcp"]
    first = render(rows, after=after)
    written = first.replace("(To be written after the re-run.)", "Uncited claims did not drop.")
    again = render(rows, old=written, after=after)
    assert "Uncited claims did not drop." in again
    assert "Uncited claims did not drop." in render(rows, old=written)  # even without the rows


def test_a_rerun_that_was_not_run_shows_not_run_and_no_numbers():
    doc = render(m2_rows(), after_not_run="The key is at its usage limit until 2026-12-01.")
    assert "**After F1: not run.** The key is at its usage limit until 2026-12-01." in doc
    assert "| | Claude + tools | `/ask` | Claude + tools, after F1 |" in doc
    owner = doc.split("### Owner-review set")[1].split("### Retrieval subset")[0]
    rows = [ln for ln in owner.splitlines() if ln.startswith("| ")]
    assert all(ln.endswith("| not run |") for ln in rows[1:])
    assert "## After F1: not run" in doc and "What F1 changed" in doc
    assert "→" not in doc.split("## After F1: not run")[1].split("## Transcripts")[0]


def test_the_spend_table_is_kept_when_it_cannot_be_recomputed():
    first = render(
        m2_rows(), spend={"agentic": {"calls": 2, "in": 1, "out": 1, "cached": 0, "cost": 1.5}}
    )
    assert "| agentic | 2 |" in first
    again = render(m2_rows(), old=first, spend=None)
    assert "| agentic | 2 |" in again and "$1.500" in again
