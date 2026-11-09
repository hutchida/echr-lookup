# ruff: noqa: E501
"""python -m rag.eval.agentic --set owner-review|subset|all --systems mcp,ask --repeats N --max-cost USD"""

import argparse
import asyncio
import os
import sys
from pathlib import Path

from mcp.client.stdio import StdioServerParameters

from rag import config

from . import fake_server
from .common import OUT_DIR, SUBSET_PATH, SUBSET_SIZE, Budget
from .fake_client import FakeAnthropic, fake_ask, fake_judge_llm
from .quotes import Checker, local_checker, server_checker
from .runner import Deps, Runner, plan_jobs, read_rows
from .subset import write_subset

META_PATH = OUT_DIR / "meta.json"
AFTER_META_PATH = OUT_DIR / "meta-after-f1.json"
PY_DIR = config.REPO_ROOT / "py"
PASS_THROUGH_ENV = (
    "DATABASE_URL", "DATA_SOURCE", "EMBEDDER", "RERANKER", "RERANK_ENABLED", "HF_HOME",
    "HF_HUB_OFFLINE", "TRANSFORMERS_OFFLINE",
)  # fmt: skip


def server_params(kind: str) -> StdioServerParameters:
    """Start the server over stdio: the fake (contract fixtures) or the real `python -m echr_mcp`."""
    module = ["-m", "rag.eval.agentic.fake_server"] if kind == "fake" else [
        "-m", "echr_mcp", "--transport", "stdio",
    ]  # fmt: skip
    env = {k: os.environ[k] for k in PASS_THROUGH_ENV if k in os.environ}
    env.setdefault("DATABASE_URL", config.database_url())
    env.setdefault("DATA_SOURCE", config.data_source())
    return StdioServerParameters(command=sys.executable, args=module, env=env, cwd=str(PY_DIR))


def _fixture_texts() -> dict[str, str]:
    texts: dict[str, str] = {}
    result, _ = fake_server.fake_result("get_paragraphs", {"paragraph_ids": ["001-58004§79"]})
    for p in (result or {}).get("paragraphs", []):
        texts[p["paragraph_id"]] = p["text"]
    return texts


def make_log_call(conn):
    """One cost_log row per model call (purpose 'agentic'). cost_log books cache writes at the plain
    input price, so tokens_in = uncached input + cache writes, as rag.answer.llm does."""
    from rag.index import log_cost

    def log_call(model, usage, latency_ms, request_id) -> None:
        log_cost(
            conn,
            model=model,
            purpose="agentic",
            tokens_in=usage.input + usage.cache_write,
            tokens_out=usage.output,
            tokens_cached=usage.cache_read,
            latency_ms=latency_ms,
            request_id=request_id,
        )

    return log_call


def build_deps(args: argparse.Namespace) -> Deps:
    if args.fake:
        texts = _fixture_texts()
        return Deps(
            conn=None,
            anthropic_client=FakeAnthropic(),
            server_params=server_params("fake"),
            judge_llm=fake_judge_llm,
            paragraph_text=texts.get,
            make_checker=lambda lookup: local_checker(lookup),
            ask_fn=fake_ask,
        )
    import anthropic

    from rag.eval import judge as judge_mod
    from rag.index import connect

    if config.llm_mode() != "live":
        raise SystemExit("LLM_MODE is 'fake': unset it for a live run, or use --fake")
    key = config.anthropic_api_key()
    if not key:
        raise SystemExit("ANTHROPIC_API_KEY is not set in the repo .env")
    client = anthropic.Anthropic(
        api_key=key, base_url=config.anthropic_base_url(), max_retries=0, timeout=120.0
    )
    conn = connect()
    cache: dict[str, str | None] = {}

    def paragraph_text(pid: str) -> str | None:
        if pid not in cache:
            row = conn.execute("SELECT text FROM paragraphs WHERE id = %s", (pid,)).fetchone()
            cache[pid] = row[0] if row else None
        return cache[pid]

    def make_checker(lookup) -> Checker:
        try:
            return server_checker(conn)
        except ImportError:
            return local_checker(lookup)

    return Deps(
        conn=conn,
        anthropic_client=client,
        server_params=server_params(args.server),
        judge_llm=None if args.no_judge else judge_mod.make_llm(conn),
        paragraph_text=paragraph_text,
        make_checker=make_checker,
        log_call=make_log_call(conn),
    )


def _display_path(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(config.REPO_ROOT))
    except ValueError:
        return str(path)


def write_doc(path: Path, results: Path, args: argparse.Namespace) -> None:
    """Write the comparison doc. `results` is the M2 file, or the re-run when --baseline is the M2
    file; spend comes from cost_log (this task's DB) since the baselines in the meta files."""
    import json

    from .fairness import load_v2_qrels
    from .report import spend_since, write_report

    base = (args.baseline or OUT_DIR / "results.jsonl").resolve()
    after = results.resolve() if results.resolve() != base else None
    meta = json.loads(META_PATH.read_text()) if META_PATH.exists() else {}
    after_meta = json.loads(AFTER_META_PATH.read_text()) if AFTER_META_PATH.exists() else {}
    spend = after_spend = None
    text_lookup = None
    if not args.fake:
        from rag.index import connect

        conn = connect()
        if meta.get("spend_since") and config.database_url().rsplit("/", 1)[-1] == meta.get("db"):
            spend = spend_since(conn, meta["spend_since"])  # else: the doc's M2 table stays
        if after is not None and after_meta.get("spend_since"):
            after_spend = spend_since(conn, after_meta["spend_since"])

        def text_lookup(pid: str) -> str | None:
            row = conn.execute("SELECT text FROM paragraphs WHERE id = %s", (pid,)).fetchone()
            return row[0] if row else None

    write_report(
        read_rows(base),
        path,
        spend=spend,
        cap=meta.get("cap_usd", 8.0),
        meta=meta,
        after=read_rows(after) if after else None,
        after_meta={**after_meta, "results": _display_path(after)} if after else None,
        after_spend=after_spend,
        qrels=load_v2_qrels(),
        text_lookup=text_lookup,
        after_not_run=args.after_not_run,
    )
    print(f"wrote {path}")


def parse_args(argv: list[str] | None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(prog="python -m rag.eval.agentic", description=__doc__)
    ap.add_argument(
        "--set", dest="set_name", choices=["owner-review", "subset", "all"], default="all"
    )
    ap.add_argument("--systems", default="mcp,ask", help="comma list of: mcp, ask")
    ap.add_argument("--repeats", type=int, default=3, help="samples per owner-review question")
    ap.add_argument(
        "--ask-repeats", type=int, default=None, help="/ask samples (default: --repeats)"
    )
    ap.add_argument("--subset-size", type=int, default=SUBSET_SIZE)
    ap.add_argument(
        "--max-cost",
        type=float,
        default=None,
        help="USD cap for every paid call (required for a run)",
    )
    ap.add_argument("--only", default="", help="comma list of question ids, e.g. or-03,or-07")
    ap.add_argument(
        "--fake", action="store_true", help="fake server, model, /ask and judge: offline"
    )
    ap.add_argument("--server", choices=["real", "fake"], default="real")
    ap.add_argument("--no-judge", action="store_true")
    ap.add_argument("--out", type=Path, default=None, help="results JSONL (default by mode)")
    ap.add_argument(
        "--run-label", default=None, help='stored on every row, e.g. "after-F1" (a new --out file)'
    )
    ap.add_argument(
        "--after-not-run",
        default=None,
        metavar="REASON",
        help="report an 'after F1' column as not run, with this reason (no re-run rows yet)",
    )
    ap.add_argument(
        "--baseline",
        type=Path,
        default=None,
        help="the earlier results JSONL the report compares --out with (default results.jsonl)",
    )
    ap.add_argument("--resume", action="store_true", help="skip answers already ok in --out")
    ap.add_argument(
        "--report", type=Path, default=None, help="write the comparison doc here after the run"
    )
    ap.add_argument("--report-only", action="store_true", help="only (re)write the doc from --out")
    ap.add_argument(
        "--write-subset", action="store_true", help="(re)draw data/eval/agentic/subset.json"
    )
    return ap.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.write_subset:
        subset = write_subset()
        print(f"wrote {SUBSET_PATH} ({len(subset['ids'])} ids, seed {subset['seed']})")
        return 0
    out = args.out or OUT_DIR / ("fake-results.jsonl" if args.fake else "results.jsonl")
    if args.report_only:
        write_doc(args.report or config.REPO_ROOT / "docs" / "mcp-comparison.md", out, args)
        return 0
    if args.max_cost is None:
        raise SystemExit("--max-cost is required: the USD cap for every paid call")
    systems = [s for s in args.systems.split(",") if s]
    if not set(systems) <= {"mcp", "ask"}:
        raise SystemExit("--systems takes mcp and/or ask")
    sets = ["owner-review", "subset"] if args.set_name == "all" else [args.set_name]
    only = {s for s in args.only.split(",") if s} or None
    jobs = plan_jobs(
        systems=systems,
        sets=sets,
        repeats=args.repeats,
        ask_repeats=args.ask_repeats or args.repeats,
        only=only,
        subset_size=args.subset_size,
    )
    done = (
        {
            (r["system"], r["item_id"], r["repeat"])
            for r in read_rows(out)
            if r["status"] == "ok" and not r.get("context_only")
        }
        if args.resume
        else set()
    )
    deps = build_deps(args)
    budget = Budget(args.max_cost)
    runner = Runner(deps, budget, judge=not args.no_judge, out=out, run_label=args.run_label)
    print(
        f"{len(jobs)} answers planned ({len(done)} already done), cap ${args.max_cost:.2f}, "
        f"results -> {out}",
        file=sys.stderr,
    )
    result = asyncio.run(runner.run(jobs, done=done))
    print(f"spent ${result.spent:.3f} of ${args.max_cost:.2f}; {len(result.rows)} rows written")
    if result.skipped:
        ids = ", ".join(f"{r['system']}:{r['item_id']}x{r['repeat']}" for r in result.skipped)
        print(f"SKIPPED for the cost cap ({len(result.skipped)}): {ids}")
    if args.report:
        write_doc(args.report, out, args)
    return 0
