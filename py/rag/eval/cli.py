"""CLI: python -m rag.eval --source snapshot [--quick] [--no-judge] [--max-cost 3.00]"""

import argparse
import sys
import time
from datetime import UTC, datetime

from rag import config
from rag.contract import contract_errors

from . import judge as judge_mod
from .items import load_questions, validate_items
from .report import render_table, write_outputs
from .runner import (
    Backend,
    CostGuardError,
    retrievable,
    run_eval,
    sample_items,
    store_run,
)


def build_backend(conn, *, with_answers: bool = True) -> Backend:
    """Wire the real rag.search (and rag.answer unless retrieval-only)."""
    from rag.index import connect, get_embedder
    from rag.search import get_reranker, search

    answer = llm = None
    if with_answers:
        try:
            from rag.answer import answer  # type: ignore[attr-defined,no-redef]
        except ImportError as exc:
            raise SystemExit(f"rag.answer is not available (S4 not merged?): {exc}") from exc
        llm = judge_mod.make_llm(conn)

    embedder = get_embedder()
    rerankers: dict[str, object] = {}

    def run_search(request: dict) -> dict:
        reranker = None
        if request["mode"] == "hybrid_rerank":
            reranker = rerankers.setdefault("r", get_reranker())
        return search(conn, request, embedder=embedder, reranker=reranker)

    cache: dict[str, str | None] = {}

    def paragraph_text(pid: str) -> str | None:
        if pid not in cache:
            row = conn.execute("SELECT text FROM paragraphs WHERE id = %s", (pid,)).fetchone()
            cache[pid] = row[0] if row else None
        return cache[pid]

    def fork() -> Backend:
        return build_backend(connect(), with_answers=with_answers)

    return Backend(
        fork=fork if with_answers else None,
        search=run_search,
        answer=(lambda request: answer(conn, request)) if answer else None,
        paragraph_text=paragraph_text,
        llm=llm,
        embedder_model=embedder.model_name,
        generator_model=config.answer_model(),
        judge_model=config.judge_model(),
    )


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="python -m rag.eval", description=__doc__)
    ap.add_argument("--source", choices=["snapshot"], required=True)
    ap.add_argument(
        "--quick", action="store_true", help="10 questions, retrieval only, nothing written"
    )
    ap.add_argument(
        "--retrieval-only",
        action="store_true",
        help="the 12 retrieval configs only; store and write",
    )
    ap.add_argument("--no-judge", action="store_true", help="skip answer generation and judging")
    ap.add_argument(
        "--max-cost", type=float, default=3.00, help="abort if the estimate is above (USD)"
    )
    ap.add_argument(
        "--compare-items", type=int, default=25, help="questions for the comparison config"
    )
    ap.add_argument("--workers", type=int, default=4, help="parallel answer/judge workers")
    args = ap.parse_args(argv)

    items = load_questions()
    errors = validate_items(items)
    if errors:
        print("question set is invalid:\n  " + "\n  ".join(errors[:10]), file=sys.stderr)
        return 1
    if args.quick:
        items = sample_items(retrievable(items), 10)

    from rag.index import connect, migrate

    t0 = time.time()
    with connect() as conn:
        migrate(conn)
        backend = build_backend(conn, with_answers=not (args.quick or args.retrieval_only))

        def progress(msg: str) -> None:
            print(f"  [{time.time() - t0:6.1f}s] {msg}", flush=True)

        def show_estimate(est: dict[str, float]) -> None:
            print(
                f"Estimated live cost: ${est['total']:.2f} (generation ${est['generation']:.2f}, "
                f"judging ${est['judging']:.2f}); limit ${args.max_cost:.2f}",
                flush=True,
            )

        try:
            results = run_eval(
                backend,
                items,
                answers=not (args.quick or args.retrieval_only),
                judge=not args.no_judge,
                max_cost=args.max_cost,
                compare_items=args.compare_items,
                workers=args.workers,
                on_progress=progress,
                on_estimate=show_estimate,
            )
        except CostGuardError as exc:
            print(f"Aborted before any paid call: {exc}", file=sys.stderr)
            return 2

        print("\n" + render_table(results))
        if args.quick:
            print("\n--quick: nothing stored or written.")
            return 0
        for r in results:
            bad = contract_errors("EvalRun", r.run)
            if bad:
                print(
                    f"EvalRun {r.run['run_id']} violates the contract: {bad[:3]}", file=sys.stderr
                )
                return 1
            store_run(conn, r.run)
        conn.commit()

    spent = sum(r.run["cost_usd"] for r in results)
    notes = [
        f"Wall time {time.time() - t0:.0f} s; live spend ${spent:.2f} "
        f"(limit ${args.max_cost:.2f}).",
        "Judge: "
        + (
            config.judge_model()
            if not (args.no_judge or args.retrieval_only)
            else "not run (retrieval only)"
        )
        + ".",
    ]
    write_outputs(
        results, items,
        generated_at=datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC"), notes=notes,
    )  # fmt: skip
    print("\nWrote docs/eval-results.md and the README eval section.")
    return 0
