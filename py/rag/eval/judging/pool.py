"""Step 1: pool. Run every config on every retrieval question, take the union of the paragraphs
found plus the original gold, and record who found what.

retrieval.jsonl keeps, per question and config, the top-10 hits as lists of paragraph ids (rank
order), which is all the metrics need; re-scoring later never has to search again.
pool.jsonl has one line per question with each pooled paragraph's verbatim text and provenance.
"""

from collections.abc import Callable, Sequence

from rag.eval.runner import retrievable

from .common import CONFIGS, POOL_K, config_key


def collect_runs(
    search: Callable[[dict], dict],
    items: Sequence[dict],
    configs: Sequence[tuple[str, str]] = CONFIGS,
    on_progress: Callable[[str], None] | None = None,
) -> list[dict]:
    """One row per retrieval question: {question_id, runs: {"chunking/mode": [[pid, ...], ...]}}.
    The request has the same shape as rag.eval.runner.run_config."""
    rows = []
    for n, item in enumerate(retrievable(list(items)), start=1):
        runs = {}
        for chunking, mode in configs:
            request = {"query": item["question"], "mode": mode, "chunking": chunking, "k": POOL_K}
            hits = search(request)["hits"][:POOL_K]
            runs[config_key(chunking, mode)] = [list(h["paragraph_ids"]) for h in hits]
        rows.append({"question_id": item["id"], "runs": runs})
        if on_progress:
            on_progress(f"searched {n} questions ({item['id']})")
    return rows


def pool_for_question(item: dict, runs: dict[str, list[list[str]]]) -> list[dict]:
    """The pooled paragraphs of one question, without text: union of every paragraph in every
    config's hits and the gold ids. Each entry records the configs that found it with the best
    (lowest) hit rank, and whether it was original gold. Sorted: most configs first, then best rank,
    then id."""
    found: dict[str, dict[str, int]] = {}
    for key, hits in runs.items():
        for rank, pids in enumerate(hits, start=1):
            for pid in pids:
                best = found.setdefault(pid, {})
                best[key] = min(best.get(key, rank), rank)
    gold = list(dict.fromkeys(item["expected_paragraph_ids"]))
    for pid in gold:
        found.setdefault(pid, {})
    entries = [
        {
            "id": pid,
            "gold": pid in gold,
            "found_by": by_cfg,
            "n_configs": len(by_cfg),
            "best_rank": min(by_cfg.values()) if by_cfg else None,
        }
        for pid, by_cfg in found.items()
    ]
    entries.sort(key=lambda e: (-e["n_configs"], e["best_rank"] or 99, e["id"]))
    return entries


def fetch_paragraphs(conn, ids: Sequence[str]) -> dict[str, dict]:
    """Verbatim paragraph text and its case metadata from the database."""
    rows = conn.execute(
        "SELECT p.id, p.text, p.section, p.number, d.case_name, d.doc_type "
        "FROM paragraphs p JOIN documents d ON d.item_id = p.doc_id WHERE p.id = ANY(%s)",
        (list(ids),),
    ).fetchall()
    return {
        r[0]: {"text": r[1], "section": r[2], "number": r[3], "case_name": r[4], "doc_type": r[5]}
        for r in rows
    }


def build_pool(
    items: Sequence[dict], runs_rows: Sequence[dict], paragraphs: dict[str, dict]
) -> list[dict]:
    """pool.jsonl rows. A paragraph missing from the database is kept with text None so the gap
    is visible (the judge step refuses to grade a paragraph it cannot show)."""
    by_id = {i["id"]: i for i in items}
    out = []
    for row in runs_rows:
        item = by_id[row["question_id"]]
        entries = []
        for e in pool_for_question(item, row["runs"]):
            meta = paragraphs.get(e["id"], {})
            entries.append(
                {
                    **e,
                    "case_name": meta.get("case_name"),
                    "doc_type": meta.get("doc_type"),
                    "section": meta.get("section"),
                    "text": meta.get("text"),
                }
            )
        out.append(
            {
                "question_id": item["id"],
                "question": item["question"],
                "type": item["type"],
                "gold_ids": list(dict.fromkeys(item["expected_paragraph_ids"])),
                "paragraphs": entries,
            }
        )
    return out


def pool_sizes(pool: Sequence[dict]) -> dict[str, float]:
    sizes = sorted(len(q["paragraphs"]) for q in pool)
    n = len(sizes)
    if not n:
        return {"questions": 0, "min": 0, "median": 0, "max": 0, "total": 0}
    median = sizes[n // 2] if n % 2 else (sizes[n // 2 - 1] + sizes[n // 2]) / 2
    return {
        "questions": n,
        "min": sizes[0],
        "median": median,
        "max": sizes[-1],
        "total": sum(sizes),
    }
