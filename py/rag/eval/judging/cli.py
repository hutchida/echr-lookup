"""CLI: python -m rag.eval.judging <pool|preflight|smoke|judge|recheck|rescore|report|show> ...

Run from py/ as `uv run --group ml python -m rag.eval.judging ...` (see docs/eval-judging.md).
"""

import argparse
import json
import random
import statistics
import sys
import threading
import time
from datetime import UTC, datetime

from rag.eval.items import load_questions

from . import grader, preflight
from . import pool as pool_mod
from .budget import SpendGuard, spent_from_cost_log
from .common import (
    JUDGMENTS_DIR,
    POOL_PATH,
    QRELS_V2_PATH,
    RETRIEVAL_PATH,
    read_jsonl,
    run_path,
    write_jsonl,
)
from .grader import JUDGE_MODEL, load_run, run_judging
from .qrels import build_qrels, write_qrels
from .rescore import rescore

META_PATH = JUDGMENTS_DIR / "meta.json"
DEFAULT_SEED = 20261105
RECHECK_N = 15


def update_meta(key: str, value: dict) -> None:
    meta = json.loads(META_PATH.read_text()) if META_PATH.exists() else {}
    meta[key] = value
    META_PATH.write_text(json.dumps(meta, indent=2, sort_keys=True) + "\n")


def make_llm(model: str):
    """The judge call: a LiteLLM gateway through litellm_client, logged to cost_log. The
    client is built from LITELLM_BASE_URL / LITELLM_API_KEY in the repo .env only. One DB
    connection per worker thread."""
    from rag.index import connect

    from .litellm_client import LiteLLMJudge, litellm_settings

    local = threading.local()

    def conn():
        if not hasattr(local, "conn"):
            local.conn = connect()
        return local.conn

    base, key = litellm_settings()
    return LiteLLMJudge(model, base_url=base, api_key=key, conn_factory=conn)


def log(msg: str) -> None:
    print(msg, flush=True)


def load_pool(top_n: int | None = None) -> list[dict]:
    pool = read_jsonl(POOL_PATH)
    if not pool:
        raise SystemExit(f"{POOL_PATH} is missing; run the pool step first")
    return preflight.cap_pool(pool, top_n)


def cmd_pool(args: argparse.Namespace) -> int:
    from rag.eval.cli import build_backend
    from rag.index import connect, migrate

    items = load_questions()
    t0 = time.time()
    with connect() as conn:
        migrate(conn)
        backend = build_backend(conn, with_answers=False)
        runs = pool_mod.collect_runs(
            backend.search, items, on_progress=lambda m: log(f"  [{time.time() - t0:6.1f}s] {m}")
        )
        write_jsonl(RETRIEVAL_PATH, runs)
        ids = {pid for r in runs for hits in r["runs"].values() for h in hits for pid in h}
        ids |= {pid for i in items for pid in i["expected_paragraph_ids"]}
        paragraphs = pool_mod.fetch_paragraphs(conn, sorted(ids))
    pool = pool_mod.build_pool(items, runs, paragraphs)
    write_jsonl(POOL_PATH, pool)
    update_meta("pool", {"seconds": round(time.time() - t0), "questions": len(pool)})
    print_pool_stats(pool)
    log(f"Wrote {RETRIEVAL_PATH} and {POOL_PATH} in {time.time() - t0:.0f}s")
    return 0


def print_pool_stats(pool: list[dict]) -> None:
    s = pool_mod.pool_sizes(pool)
    log(
        f"Pool: {s['questions']} questions, {s['total']} paragraphs; per question "
        f"min {s['min']} / median {s['median']} / max {s['max']}"
    )
    missing = [(q["question_id"], p["id"]) for q in pool for p in q["paragraphs"] if not p["text"]]
    chars = [sum(len(p["text"] or "") for p in q["paragraphs"]) for q in pool]
    log(
        f"Paragraphs with no text in the database: {len(missing)}; paragraph chars per question "
        f"min/median/max {min(chars)}/{int(statistics.median(chars))}/{max(chars)}"
    )


def cmd_preflight(args: argparse.Namespace) -> int:
    pool = load_pool(args.top_n)
    print_pool_stats(pool)
    pr = preflight.projection(pool, args.recheck_n)
    log(
        f"Projected at {JUDGE_MODEL}: {pr['questions']} judge calls ${pr['judge_calls_usd']:.2f} + "
        f"{args.recheck_n} re-judge calls ${pr['recheck_usd']:.2f} = ${pr['total_usd']:.2f} "
        "(ESTIMATE at the proxy's list price; the measured cost comes from the proxy per call)"
    )
    return 0


def cmd_smoke(args: argparse.Namespace) -> int:
    from rag.index import connect

    with connect() as conn:
        res = make_llm(args.model)(
            "Reply with JSON only.",
            [{"role": "user", "content": 'Return {"ok": true}.'}],
            "relevance-smoke",
            args.max_tokens,
        )
        log(f"model {res.model}: reply {res.text!r} (finish: {res.finish_reason})")
        log(
            f"tokens in {res.tokens_in} out {res.tokens_out}; cost ${res.cost_usd:.6f} "
            f"({res.cost_source})"
        )
        log(f"cost_log total so far ${spent_from_cost_log(conn):.4f}")
    return 0


def spend_summary(conn) -> dict:
    row = conn.execute(
        "SELECT coalesce(sum(cost_usd), 0), count(*), coalesce(sum(tokens_in), 0), "
        "coalesce(sum(tokens_out), 0) FROM cost_log WHERE request_id LIKE 'relevance-%'"
    ).fetchone()
    conn.commit()
    return {"usd": float(row[0]), "calls": row[1], "tokens_in": row[2], "tokens_out": row[3]}


def _run_judge(args: argparse.Namespace, run: int, only: list[str] | None) -> int:
    from rag.index import connect

    pool = load_pool(args.top_n)
    pr = preflight.projection(pool, 0)
    n_calls = len(only) if only is not None else len(pool)
    est = pr["mean_per_question_usd"] * n_calls
    log(f"Pre-flight: ~${est:.2f} for {n_calls} questions this run")
    t0 = time.time()
    ledger_path = JUDGMENTS_DIR / "spend.log"
    with connect() as guard_conn:
        guard = SpendGuard(lambda: spent_from_cost_log(guard_conn), args.soft_limit)
        before = spend_summary(guard_conn)
        limit = f"soft limit ${args.soft_limit:.2f}" if args.soft_limit else "no limit"
        log(f"Spent so far under relevance-%: ${before['usd']:.4f} ({limit})")

        def on_record(rec: dict) -> None:
            s = spend_summary(guard_conn)
            line = (
                f"{datetime.now(UTC).strftime('%Y-%m-%dT%H:%M:%SZ')} run{rec['run']} "
                f"{rec['question_id']} calls={s['calls']} tokens_in={s['tokens_in']} "
                f"tokens_out={s['tokens_out']} usd={s['usd']:.4f}"
            )
            with ledger_path.open("a") as fh:
                fh.write(line + "\n")
            log("  ledger: " + line)

        res = run_judging(
            pool,
            make_llm(args.model),
            guard,
            run_path(run),
            run=run,
            seed=args.seed,
            model=args.model,
            only=only,
            retry_failed=args.retry_failed,
            workers=args.workers,
            max_tokens=args.max_tokens,
            on_progress=log,
            on_record=on_record,
        )
        spent = spent_from_cost_log(guard_conn)
    secs = round(time.time() - t0)
    log(f"Run {run}: {res}; wall {secs}s; spend under relevance-% now ${spent:.4f}")
    meta_key = f"judge_run{run}"
    prev = json.loads(META_PATH.read_text()).get(meta_key, {}) if META_PATH.exists() else {}
    update_meta(
        meta_key,
        {"seconds": secs + prev.get("seconds", 0), "seed": args.seed, "top_n": args.top_n,
         "model": args.model, "finished": datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")},
    )  # fmt: skip
    return 3 if res["not_run"] or res["errored"] else 0


def cmd_judge(args: argparse.Namespace) -> int:
    only = [q for q in args.only.split(",") if q] if args.only else None
    return _run_judge(args, 1, only)


def recheck_ids(seed: int, n: int = RECHECK_N) -> list[str]:
    """The re-judge sample: n questions that run 1 judged successfully, seeded."""
    ok = sorted(q for q, r in load_run(run_path(1)).items() if r["ok"])
    return sorted(random.Random(f"recheck:{seed}").sample(ok, min(n, len(ok))))


def cmd_recheck(args: argparse.Namespace) -> int:
    return _run_judge(args, 2, recheck_ids(args.seed, args.n))


def cmd_rescore(args: argparse.Namespace) -> int:
    pool = load_pool()
    run1 = load_run(run_path(1))
    rows = build_qrels(run1, pool)
    write_qrels(rows)
    log(f"Wrote {QRELS_V2_PATH} ({len(rows)} questions; run 1 grades)")
    from .qrels import load_qrels

    res = rescore(load_questions(), read_jsonl(RETRIEVAL_PATH), load_qrels())
    (JUDGMENTS_DIR / "rescore.json").write_text(json.dumps(res, indent=1) + "\n")
    for row in res["table"]:
        o, v = row["original"], row["v2"]
        log(
            f"{row['config']:24} recall@5 {o['recall_at_5']:.3f} -> {v['recall_at_5']:.3f}  "
            f"recall@10 {o['recall_at_10']:.3f} -> {v['recall_at_10']:.3f}  "
            f"MRR {o['mrr']:.3f} -> {v['mrr']:.3f}  nDCG@10 {o['ndcg_at_10']:.3f} -> "
            f"{v['ndcg_at_10']:.3f}"
        )
    log(f"v2 questions {res['v2_questions']}; no grade-2 paragraph: {res['v2_no_gold']}")
    return 0


def cmd_show(args: argparse.Namespace) -> int:
    """One question: pool size, the original gold with its grades, added gold with the judge's
    reasons, and original vs v2 scores for every config. Free: reads saved files only."""
    from .qrels import load_qrels

    qid = args.question_id
    pool = {q["question_id"]: q for q in read_jsonl(POOL_PATH)}
    if qid not in pool:
        raise SystemExit(f"{qid} is not a pooled retrieval question")
    q, rec = pool[qid], load_run(run_path(1)).get(qid)
    log(f"{qid}: {q['question']}")
    log(f"Pool: {len(q['paragraphs'])} paragraphs; original gold: {len(q['gold_ids'])}")
    if rec is None or not rec["ok"]:
        log("No usable judgment for this question yet.")
        return 1
    counts = {g: sum(v["grade"] == g for v in rec["grades"].values()) for g in (0, 1, 2)}
    log(f"Judge ({rec['model']}) grades: 0={counts[0]}  1={counts[1]}  2={counts[2]}")
    by_id = {p["id"]: p for p in q["paragraphs"]}
    log("Original gold:")
    for pid in q["gold_ids"]:
        g = rec["grades"][pid]
        log(f"  {pid}  grade {g['grade']}  {g['reason']}")
    added = [
        pid for pid, g in rec["grades"].items() if g["grade"] == 2 and pid not in q["gold_ids"]
    ]
    added.sort(key=lambda pid: (-by_id[pid]["n_configs"], pid))
    log(f"Graded 2 but not in the original key: {len(added)} (first {args.limit} shown)")
    for pid in added[: args.limit]:
        log(f"  {pid}  {rec['grades'][pid]['reason']}")
        log(f'      "{by_id[pid]["text"][:160].replace(chr(10), " ")}..."')
    rows = [r for r in read_jsonl(RETRIEVAL_PATH) if r["question_id"] == qid]
    res = rescore(load_questions(), rows, load_qrels())
    log("recall@10, original key -> v2 key (per config):")
    for cfg, v in res["per_question"][qid].items():
        o, n = v["original"]["recall_at_10"], v["v2"]["recall_at_10"] if v["v2"] else None
        log(f"  {cfg:24} {o:.2f} -> {'n/a' if n is None else f'{n:.2f}'}")
    return 0


def cmd_report(args: argparse.Namespace) -> int:
    from . import report

    return report.write_report()


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m rag.eval.judging", description=__doc__)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("pool", help="search every config, write retrieval.jsonl and pool.jsonl")

    def judge_opts(p: argparse.ArgumentParser) -> None:
        p.add_argument("--seed", type=int, default=DEFAULT_SEED)
        p.add_argument("--model", default=JUDGE_MODEL)
        p.add_argument("--workers", type=int, default=4)
        p.add_argument("--max-tokens", type=int, default=grader.MAX_TOKENS)
        p.add_argument("--top-n", type=int, default=None, help="cap the pool per question")
        p.add_argument("--soft-limit", type=float, default=None, help="refuse calls past this USD")
        p.add_argument("--retry-failed", action="store_true")

    p = sub.add_parser("preflight", help="projected spend from the real pool (free)")
    p.add_argument("--top-n", type=int, default=None)
    p.add_argument("--recheck-n", type=int, default=RECHECK_N)
    p = sub.add_parser("smoke", help="one tiny paid call to check the judge model works")
    p.add_argument("--model", default=JUDGE_MODEL)
    p.add_argument("--max-tokens", type=int, default=grader.MAX_TOKENS)
    p = sub.add_parser("judge", help="run 1: judge every pooled question (resumable)")
    judge_opts(p)
    p.add_argument("--only", default="", help="comma-separated question ids (e.g. a first try)")
    p = sub.add_parser("recheck", help="run 2: re-judge a seeded random sample (resumable)")
    judge_opts(p)
    p.add_argument("--n", type=int, default=RECHECK_N)
    sub.add_parser("rescore", help="write qrels-v2.jsonl and re-score all 12 configs (free)")
    sub.add_parser("report", help="write docs/eval-judging.md")
    p = sub.add_parser("show", help="one question: pool, grades, added gold, scores (free)")
    p.add_argument("question_id")
    p.add_argument("--limit", type=int, default=5, help="added-gold paragraphs to print")
    args = ap.parse_args(argv)
    cmds = {"pool": cmd_pool, "preflight": cmd_preflight, "smoke": cmd_smoke, "judge": cmd_judge,
            "recheck": cmd_recheck, "rescore": cmd_rescore, "report": cmd_report,
            "show": cmd_show}  # fmt: skip
    return cmds[args.cmd](args)


if __name__ == "__main__":
    sys.exit(main())
