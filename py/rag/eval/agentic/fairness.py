# ruff: noqa: E501
"""Fairness checks for "Claude + tools vs /ask" (task F3). Free: no model call anywhere.

  python -m rag.eval.agentic.fairness recall [--search]   recall@k of /ask's retrieval setup
  python -m rag.eval.agentic.fairness rescore             recorded runs against the old and the v2 key
  python -m rag.eval.agentic.fairness quotes              where the non-verbatim quotes come from

`recall --search` runs the search (local embedder + reranker, `DATABASE_URL`) and saves the hit lists
to `data/eval/agentic/fairness-hits.jsonl`; without `--search` it reads that file, so the numbers are
reproducible offline. `rescore` needs only results.jsonl and the answer keys. `quotes` reads paragraph
text from the database.
"""

import argparse
import json
import sys
from collections import Counter
from collections.abc import Callable, Mapping, Sequence
from pathlib import Path

from rag.eval.items import load_questions
from rag.eval.metrics import mean, recall_at_k

from .checks import agentic_recall, v2_gold
from .common import OUT_DIR, SUBSET_PATH
from .quotes import quote_in_any
from .report import usable

HITS_PATH = OUT_DIR / "fairness-hits.jsonl"
RESULTS_PATH = OUT_DIR / "results.jsonl"
FAIRNESS_PATH = OUT_DIR / "fairness.json"
ASK_CONFIG = {"mode": "hybrid_rerank", "chunking": "recursive"}  # rag.answer.context defaults
ASK_K = 12  # rag.answer.context.DEFAULT_K: the k /ask asks the search for
HITS_K = 40
KS = (5, 10, ASK_K, 20, HITS_K)


def load_v2_qrels(path: Path | None = None) -> dict[str, dict[str, int]] | None:
    """question id -> {paragraph id: grade}, or None when the file does not exist."""
    if path is None:
        from rag.eval.judging.common import QRELS_V2_PATH

        path = QRELS_V2_PATH
    if not path.exists():
        return None
    return {
        r["question_id"]: r["qrels"]
        for r in (json.loads(line) for line in path.read_text().splitlines() if line)
    }


def subset_ids(path: Path = SUBSET_PATH) -> list[str]:
    return json.loads(path.read_text())["ids"]


def distinct_paragraphs(hits: Sequence[Sequence[str]], k: int | None = None) -> list[str]:
    """Paragraph ids of the top-k hits, best first, each once."""
    out: list[str] = []
    for ids in hits[:k]:
        out += [p for p in ids if p not in out]
    return out


recall_of = agentic_recall


def recall_table(
    hits_by_q: Mapping[str, Sequence[Sequence[str]]],
    gold_by_q: Mapping[str, set[str]],
    qids: Sequence[str],
    ks: Sequence[int] = KS,
) -> list[dict]:
    """One row per k: mean recall@k (the share of gold paragraphs inside the paragraph_ids of the
    top-k hits, as rag.eval.metrics.recall_at_k) and the mean number of distinct paragraphs those
    k hits cover. Questions without gold are left out of the recall mean (n says how many count)."""
    rows = []
    for k in ks:
        vals, sizes = [], []
        for q in qids:
            hits = [{"paragraph_ids": list(p)} for p in hits_by_q[q]]
            vals.append(recall_at_k(hits, gold_by_q[q], k))
            sizes.append(len(distinct_paragraphs(hits_by_q[q], k)))
        rows.append(
            {
                "k": k,
                "recall": mean(vals),
                "n": sum(v is not None for v in vals),
                "paragraphs": mean(sizes),
            }
        )
    return rows


def paragraph_budget_recall(
    hits_by_q: Mapping[str, Sequence[Sequence[str]]],
    gold_by_q: Mapping[str, set[str]],
    qids: Sequence[str],
    n_paragraphs: int,
) -> float | None:
    """Recall when the ranked list is cut at `n_paragraphs` distinct paragraphs instead of k hits:
    the same amount of text as a model was shown, whatever the chunking."""
    return mean(
        recall_of(gold_by_q[q], distinct_paragraphs(hits_by_q[q])[:n_paragraphs]) for q in qids
    )


def search_hits(items: Sequence[dict], k: int = HITS_K) -> dict[str, list[list[str]]]:
    """Run /ask's retrieval setup (hybrid_rerank over recursive chunks) for each question."""
    from rag.index import connect, get_embedder
    from rag.search import get_reranker, search

    conn, embedder, reranker = connect(), get_embedder(), get_reranker()
    out = {}
    for item in items:
        request = {"query": item["question"], **ASK_CONFIG, "k": k}
        result = search(conn, request, embedder=embedder, reranker=reranker)
        out[item["id"]] = [list(h["paragraph_ids"]) for h in result["hits"]]
    return out


def save_hits(hits_by_q: Mapping[str, Sequence[Sequence[str]]], path: Path = HITS_PATH) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for qid, hits in hits_by_q.items():
            f.write(json.dumps({"question_id": qid, **ASK_CONFIG, "hits": hits}) + "\n")


def load_hits(path: Path = HITS_PATH) -> dict[str, list[list[str]]]:
    return {
        r["question_id"]: r["hits"]
        for r in (json.loads(line) for line in path.read_text().splitlines() if line)
    }


def agentic_recalls(
    rows: Sequence[dict],
    gold_orig: Mapping[str, set[str]],
    qrels: Mapping[str, Mapping[str, int]] | None,
    system: str,
) -> dict:
    """Agentic recall of the recorded subset answers for one system, old key and (if given) v2.
    The old key is reported over all answers and over the answers whose question has a v2 gold set,
    so the two keys can be read on the same questions."""
    mine = [
        r for r in rows if r["system"] == system and r["set"] == "subset" and r["status"] == "ok"
    ]
    per_q: dict[str, dict] = {}
    for r in mine:
        shown = r["fetched_paragraph_ids"]
        gold2 = v2_gold(qrels.get(r["item_id"])) if qrels is not None else set()
        per_q[r["item_id"]] = {
            "orig": recall_of(gold_orig[r["item_id"]], shown),
            "v2": recall_of(gold2, shown),
            "n_gold_orig": len(gold_orig[r["item_id"]]),
            "n_gold_v2": len(gold2),
            "n_shown": len(set(shown)),
        }
    both = [v for v in per_q.values() if v["v2"] is not None]
    return {
        "system": system,
        "questions": len(per_q),
        "orig_all": mean(v["orig"] for v in per_q.values()),
        "orig_on_v2_questions": mean(v["orig"] for v in both),
        "v2": mean(v["v2"] for v in both),
        "n_v2": len(both),
        "mean_shown": mean(v["n_shown"] for v in per_q.values()),
        "per_question": per_q,
    }


def audit_quotes(rows: Sequence[dict], text_lookup: Callable[[str], str | None]) -> dict:
    """Why quotes were not verbatim (system "mcp", every set). Classes, in order:
    ok: verbatim in a cited paragraph (the headline rule);
    uncited: verbatim in a paragraph the model was shown, but its claim cites none;
    other paragraph: verbatim in a shown paragraph, not the one its claim cites;
    case only: verbatim in a shown paragraph once upper/lower case is ignored (cited or not);
    not in any shown paragraph: altered, paraphrased or invented."""
    counts: Counter[str] = Counter()
    examples: dict[str, list[dict]] = {}
    per_answer: dict[tuple, dict] = {}
    detail: list[dict] = []
    for r in rows:
        if r["system"] != "mcp" or r["status"] != "ok":
            continue
        shown = list(dict.fromkeys(r["fetched_paragraph_ids"]))
        texts = [text_lookup(pid) for pid in shown]

        strict = loose = n = 0
        for q in r.get("quotes", []):
            quote = q["quote"]
            if q["verbatim"]:
                cls = "ok"
            elif quote_in_any(texts, quote):
                cls = "other paragraph" if q["attributed_to"] else "uncited"
            elif quote_in_any(texts, quote, ignore_case=True):
                cls = "case only"
            else:
                cls = "not in any shown paragraph"
            counts[cls] += 1
            n += 1
            strict += cls == "ok"
            loose += cls != "not in any shown paragraph"
            detail.append(
                {
                    "item": r["item_id"],
                    "repeat": r["repeat"],
                    "class": cls,
                    "quote": quote,
                    "cites": q["attributed_to"],
                }
            )
            if cls != "ok":
                examples.setdefault(cls, []).append(
                    {
                        "item": r["item_id"],
                        "repeat": r["repeat"],
                        "quote": quote[:120],
                        "cites": q["attributed_to"],
                    }
                )
        per_answer[(r["set"], r["item_id"], r["repeat"])] = {
            "quotes": n,
            "strict": strict,
            "loose": loose,
        }
    total = sum(counts.values())
    return {
        "quotes": total,
        "classes": dict(counts),
        "strict_rate": counts["ok"] / total if total else None,
        "shown_rate": (total - counts["not in any shown paragraph"]) / total if total else None,
        "examples": examples,
        "detail": detail,
        "per_answer": per_answer,
    }


def shape_with_loose_quotes(rows: Sequence[dict], per_answer: Mapping[tuple, dict]) -> dict:
    """Owner-review shape pass for the tool answers if `quotes_verbatim` meant "every quote is in a
    paragraph the model was shown" (case ignored); every other check as recorded."""
    done = same = 0
    for r in rows:
        if r["system"] != "mcp" or r["set"] != "owner-review" or r["status"] != "ok":
            continue
        checks = r["shape"]["checks"]
        a = per_answer[(r["set"], r["item_id"], r["repeat"])]
        passed = []
        for c in checks:
            ok = c["passed"]
            if c["kind"] == "quotes_verbatim":
                ok = a["loose"] == a["quotes"]
            passed.append(ok)
        done += all(p is not False for p in passed) and any(p is not None for p in passed)
        same += bool(r["shape"]["passed"])
    return {"recorded": same, "loose": done}


def pct(x: float | None) -> str:
    return "n/a" if x is None else f"{round(100 * x)}%"


def run_recall(args: argparse.Namespace) -> int:
    items = {i["id"]: i for i in load_questions() if i.get("expected_paragraph_ids")}
    if args.search:
        save_hits(search_hits(list(items.values())))
        print(f"wrote {HITS_PATH}")
    elif not HITS_PATH.exists():
        print(f"{HITS_PATH} is missing: run with --search", file=sys.stderr)
        return 1
    hits = load_hits()
    qrels = load_v2_qrels(Path(args.qrels) if args.qrels else None)
    sub = subset_ids()
    gold_orig = {q: set(i["expected_paragraph_ids"]) for q, i in items.items()}
    gold_v2 = {q: v2_gold(qrels.get(q)) for q in items} if qrels is not None else {}
    rows = [json.loads(line) for line in RESULTS_PATH.read_text().splitlines() if line]
    ok = usable(rows)
    out: dict = {"config": ASK_CONFIG, "ask_k": ASK_K, "tables": {}}
    for name, qids in (
        ("subset (30)", sub),
        (f"all retrieval questions ({len(items)})", list(items)),
    ):
        out["tables"][name] = {"orig": recall_table(hits, gold_orig, qids)}
        if qrels is not None:
            out["tables"][name]["v2"] = recall_table(hits, gold_v2, qids)
    agentic = {s: agentic_recalls(ok, gold_orig, qrels, s) for s in ("mcp", "ask")}
    out["agentic"] = {
        s: {k: v for k, v in a.items() if k != "per_question"} for s, a in agentic.items()
    }
    out["paragraph_budget"] = {}
    for s, a in agentic.items():
        n = round(a["mean_shown"])
        out["paragraph_budget"][s] = {
            "paragraphs": n,
            "orig": paragraph_budget_recall(hits, gold_orig, sub, n),
            "v2": paragraph_budget_recall(hits, gold_v2, sub, n) if qrels is not None else None,
        }
    FAIRNESS_PATH.write_text(json.dumps(out, indent=2) + "\n")
    for name, t in out["tables"].items():
        print(f"\n/ask retrieval ({ASK_CONFIG['chunking']}/{ASK_CONFIG['mode']}), {name}")
        print("| k | recall, old key | recall, v2 | distinct paragraphs in top k |")
        print("|---|---|---|---|")
        for i, r in enumerate(t["orig"]):
            v2 = t["v2"][i]["recall"] if "v2" in t else None
            print(f"| {r['k']} | {pct(r['recall'])} | {pct(v2)} | {r['paragraphs']:.0f} |")
    print("\nrecorded answers (subset):")
    for s, a in out["agentic"].items():
        print(
            f"  {s}: {a['questions']} answers, mean {a['mean_shown']:.0f} paragraphs shown, "
            f"old key {pct(a['orig_all'])}, on the {a['n_v2']} v2 questions old {pct(a['orig_on_v2_questions'])} / v2 {pct(a['v2'])}"
        )
    print("search cut at the same number of paragraphs the model saw:")
    for s, b in out["paragraph_budget"].items():
        print(f"  {s} ({b['paragraphs']} paragraphs): old key {pct(b['orig'])}, v2 {pct(b['v2'])}")
    return 0


def run_rescore(args: argparse.Namespace) -> int:
    items = {i["id"]: i for i in load_questions() if i.get("expected_paragraph_ids")}
    gold_orig = {q: set(i["expected_paragraph_ids"]) for q, i in items.items()}
    qrels = load_v2_qrels(Path(args.qrels) if args.qrels else None)
    if qrels is None:
        print(
            "qrels-v2 not found (docs/eval-judging.md, data/eval/judgments/qrels-v2.jsonl): skipping the v2 re-score"
        )
    rows = usable([json.loads(line) for line in RESULTS_PATH.read_text().splitlines() if line])
    print(
        "| system | answers | old key, all | old key, v2 questions | v2 key | questions with v2 gold | mean paragraphs shown |"
    )
    print("|---|---|---|---|---|---|---|")
    for s in ("mcp", "ask"):
        a = agentic_recalls(rows, gold_orig, qrels, s)
        print(
            f"| {s} | {a['questions']} | {pct(a['orig_all'])} | {pct(a['orig_on_v2_questions'])} | {pct(a['v2'])} | {a['n_v2']} | {a['mean_shown']:.0f} |"
        )
    if qrels is not None:
        tools = agentic_recalls(rows, gold_orig, qrels, "mcp")["per_question"]
        ask = agentic_recalls(rows, gold_orig, qrels, "ask")["per_question"]
        for q in sorted(ask):
            if tools[q]["v2"] is None:
                print(f"  {q}: no v2 gold (left out of v2 means)")
    print(
        "owner-review questions have no v2 key (qrels-v2 covers the 59 retrieval questions only)."
    )
    return 0


def run_quotes(args: argparse.Namespace) -> int:
    from rag.index import connect

    conn = connect()
    cache: dict[str, str | None] = {}

    def lookup(pid: str) -> str | None:
        if pid not in cache:
            row = conn.execute("SELECT text FROM paragraphs WHERE id = %s", (pid,)).fetchone()
            cache[pid] = row[0] if row else None
        return cache[pid]

    rows = [json.loads(line) for line in RESULTS_PATH.read_text().splitlines() if line]
    audit = audit_quotes(usable(rows), lookup)
    print(
        f"{audit['quotes']} quotes in tool answers: headline (verbatim in a cited paragraph) {pct(audit['strict_rate'])}, "
        f"in some paragraph the model was shown {pct(audit['shown_rate'])}"
    )
    for cls, n in sorted(audit["classes"].items(), key=lambda kv: -kv[1]):
        print(f"  {cls}: {n}")
    shape = shape_with_loose_quotes(usable(rows), audit["per_answer"])
    print(
        f"owner-review shape pass with tools: recorded {shape['recorded']}/30, "
        f"with quotes_verbatim = 'every quote is in a shown paragraph' {shape['loose']}/30"
    )
    for d in (d for d in audit["detail"] if d["item"] == args.item):
        print(
            f"  {d['item']} x{d['repeat']} [{d['class']}] {d['quote'][:100]!r} cites {d['cites']}"
        )
    for cls in ("case only", "not in any shown paragraph"):
        for e in audit["examples"].get(cls, [])[:6]:
            print(f"  [{cls}] {e['item']} x{e['repeat']}: {e['quote']!r} cites {e['cites']}")
    return 0


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m rag.eval.agentic.fairness", description=__doc__)
    ap.add_argument(
        "--qrels", help="path to qrels-v2.jsonl (default: data/eval/judgments/qrels-v2.jsonl)"
    )
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("recall")
    r.add_argument("--search", action="store_true", help="run the search and save the hit lists")
    r.set_defaults(fn=run_recall)
    sub.add_parser("rescore").set_defaults(fn=run_rescore)
    q = sub.add_parser("quotes")
    q.add_argument(
        "--item", help="also list every quote of this question (e.g. or-09) with its class"
    )
    q.set_defaults(fn=run_quotes)
    args = ap.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    raise SystemExit(main())
