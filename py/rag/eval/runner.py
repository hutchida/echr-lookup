"""The eval runner: retrieval metrics for every config, answer metrics for chosen configs.

Everything the runner needs from the rest of the system arrives through `Backend`, so tests run it
with fakes and the CLI wires in the real rag.search / rag.answer / rag.answer.llm.
"""

import threading
import time
import uuid
from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from rag.config import answer_model, verify_model

from . import judge as judge_mod
from .items import expected_count
from .metrics import (
    doc_hit_at_k,
    mean,
    recall_at_k,
    reciprocal_rank,
    retrieved_paragraph_ids,
    stat_correct,
)

CHUNKINGS = ("fixed", "recursive", "by_section")
MODES = ("bm25", "vector", "hybrid", "hybrid_rerank")
DEFAULT_CONFIG = ("recursive", "hybrid_rerank")
COMPARE_CONFIG = ("recursive", "hybrid")  # same chunks, no reranker: isolates what rerank adds
SEARCH_K = 10


class CostGuardError(Exception):
    """The estimated cost is above --max-cost; nothing was spent."""


@dataclass
class Backend:
    search: Callable[[dict], dict]
    answer: Callable[[dict], dict] | None = None
    paragraph_text: Callable[[str], str | None] | None = None
    llm: judge_mod.LLMCall | None = None
    embedder_model: str = "unknown"
    generator_model: str | None = None
    judge_model: str | None = None
    fork: Callable[[], "Backend"] | None = None  # a backend with its own DB connection


@dataclass
class Budget:
    limit: float
    spent: float = 0.0

    @property
    def exhausted(self) -> bool:
        return self.spent >= self.limit


@dataclass
class ConfigResult:
    run: dict
    answered_items: int = 0
    stat_accuracy: float | None = None
    doc_hit_at_10: float | None = None
    stat_rows: list[dict] = field(default_factory=list)
    truncated: bool = False


def now_iso() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def retrievable(items: list[dict]) -> list[dict]:
    return [i for i in items if i["expected_paragraph_ids"]]


def sample_items(items: list[dict], n: int) -> list[dict]:
    """n items spread evenly over the list (deterministic)."""
    if n >= len(items):
        return list(items)
    return [items[int(i * len(items) / n)] for i in range(n)]


def estimate_cost(
    n_default: int, n_compare: int, n_neutrality_default: int, n_neutrality_compare: int
) -> dict[str, float]:
    """Planning figures, in USD, printed before any paid call. Generation: ~3,000 tokens in and
    500 out on the answer model plus ~3,000 / 300 for the verifier; judging: see judge module."""
    gen_each = judge_mod.price_usd(answer_model(), 3000, 500) + judge_mod.price_usd(
        verify_model(), 3000, 300
    )
    n = n_default + n_compare
    n_neut = n_neutrality_default + n_neutrality_compare
    generation = n * gen_each
    judging = judge_mod.estimate_judge_cost(n, n_neut)
    return {"generation": generation, "judging": judging, "total": generation + judging}


def _item_result(item_id: str) -> dict:
    return {
        "item_id": item_id,
        "retrieved_paragraph_ids": [],
        "recall_at_5": None,
        "recall_at_10": None,
        "reciprocal_rank": None,
        "faithfulness": None,
        "citation_accuracy": None,
        "neutrality": None,
        "latency_ms": 0.0,
    }


def _answer_item(be: Backend, item: dict, chunking: str, mode: str, judge: bool) -> dict:
    """Answer one question and (for explain / neutrality) judge it. Returns the pieces to merge."""
    request = {
        "question": item["question"],
        "options": {"chunking": chunking, "mode": mode, "k": SEARCH_K, "route": "auto"},
    }
    assert be.answer is not None
    answer = be.answer(request)
    usage = judge_mod.JudgeUsage()
    res: dict = {"latency_ms": answer["total_latency_ms"]}
    stat_row = None
    if item["type"] == "stat":
        want = expected_count(item)
        got = answer["stats"]["count"] if answer.get("stats") else None
        stat_row = {
            "id": item["id"], "question": item["question"], "expected": want, "got": got,
            "route": answer["route"], "ok": want is not None and stat_correct(answer, want),
        }  # fmt: skip
    elif judge and be.llm is not None and be.paragraph_text is not None:
        rid = f"eval-{item['id']}-{uuid.uuid4().hex[:6]}"
        res["faithfulness"], res["citation_accuracy"] = judge_mod.judge_support(
            be.llm, answer, be.paragraph_text, rid, usage
        )
        if item["type"] == "neutrality":
            res["neutrality"] = judge_mod.judge_neutrality(
                be.llm, item["question"], answer["answer_text"], rid, usage
            )
    return {
        "item_id": item["id"], "res": res, "stat_row": stat_row, "usage": usage,
        "cost": answer["total_cost_usd"],
        "tokens_in": sum(s["tokens_in"] for s in answer["steps"]),
        "tokens_out": sum(s["tokens_out"] for s in answer["steps"]),
    }  # fmt: skip


def run_config(
    backend: Backend,
    items: list[dict],
    chunking: str,
    mode: str,
    *,
    answer_ids: set[str] | None = None,
    judge: bool = False,
    budget: Budget | None = None,
    on_progress: Callable[[str], None] | None = None,
    workers: int = 4,
) -> ConfigResult:
    """Run one chunking x mode config. Retrieval metrics always; if `answer_ids` is given, those
    items are also answered (stat items always, the rest only when `judge` is on) and judged."""
    started_at, t0 = now_iso(), time.perf_counter()
    results: dict[str, dict] = {}
    doc_hits: list[float | None] = []
    for item in items:
        res = _item_result(item["id"])
        if item["expected_paragraph_ids"]:
            request = {"query": item["question"], "mode": mode, "chunking": chunking, "k": SEARCH_K}
            t = time.perf_counter()
            hits = backend.search(request)["hits"]
            res["latency_ms"] = (time.perf_counter() - t) * 1000
            expected = item["expected_paragraph_ids"]
            res["retrieved_paragraph_ids"] = retrieved_paragraph_ids(hits, SEARCH_K)
            res["recall_at_5"] = recall_at_k(hits, expected, 5)
            res["recall_at_10"] = recall_at_k(hits, expected, 10)
            res["reciprocal_rank"] = reciprocal_rank(hits, expected, 10)
            doc_hits.append(doc_hit_at_k(hits, expected, 10))
        results[item["id"]] = res

    out = ConfigResult(run={}, doc_hit_at_10=mean(doc_hits))
    usage = judge_mod.JudgeUsage()
    gen_cost = 0.0
    gen_in = gen_out = 0
    if answer_ids is not None and backend.answer is not None:
        todo = [i for i in items if i["id"] in answer_ids and (i["type"] == "stat" or judge)]
        lock = threading.Lock()
        local = threading.local()

        def work(item: dict) -> dict | None:
            with lock:
                if budget is not None and budget.exhausted:
                    out.truncated = True
                    return None
            be = backend
            if backend.fork is not None:
                if not hasattr(local, "backend"):
                    local.backend = backend.fork()
                be = local.backend
            r = _answer_item(be, item, chunking, mode, judge)
            with lock:
                if budget is not None:
                    budget.spent += r["cost"] + r["usage"].cost_usd
                out.answered_items += 1
                if on_progress:
                    on_progress(f"{chunking}/{mode}: answered {out.answered_items}/{len(todo)}")
            return r

        with ThreadPoolExecutor(max_workers=workers if backend.fork else 1) as pool:
            done = [r for r in pool.map(work, todo) if r is not None]
        for r in done:
            results[r["item_id"]].update(r["res"])
            if r["stat_row"]:
                out.stat_rows.append(r["stat_row"])
            gen_cost += r["cost"]
            gen_in += r["tokens_in"]
            gen_out += r["tokens_out"]
            usage.cost_usd += r["usage"].cost_usd
            usage.tokens_in += r["usage"].tokens_in
            usage.tokens_out += r["usage"].tokens_out

    if out.stat_rows:
        out.stat_accuracy = sum(r["ok"] for r in out.stat_rows) / len(out.stat_rows)
    rows = list(results.values())
    total_ms = (time.perf_counter() - t0) * 1000
    judged = judge and answer_ids is not None and backend.llm is not None
    out.run = {
        "run_id": f"eval-{started_at.replace('-', '').replace(':', '')}-{chunking}-{mode}",
        "started_at": started_at,
        "finished_at": now_iso(),
        "data_source": "snapshot",
        "config": {
            "chunking": chunking,
            "mode": mode,
            "rerank": mode == "hybrid_rerank",
            "embedder_model": backend.embedder_model,
            "generator_model": backend.generator_model if judged else None,
            "judge_model": backend.judge_model if judged else None,
        },
        "metrics": {
            "recall_at_5": mean(r["recall_at_5"] for r in rows),
            "recall_at_10": mean(r["recall_at_10"] for r in rows),
            "mrr": mean(r["reciprocal_rank"] for r in rows),
            "faithfulness": mean(r["faithfulness"] for r in rows),
            "citation_accuracy": mean(r["citation_accuracy"] for r in rows),
            "neutrality": mean(r["neutrality"] for r in rows),
        },
        "cost_usd": gen_cost + usage.cost_usd,
        "tokens_in": gen_in + usage.tokens_in,
        "tokens_out": gen_out + usage.tokens_out,
        "timings_ms": {"total": total_ms, "mean_per_item": total_ms / max(len(rows), 1)},
        "items": rows,
    }
    return out


def run_eval(
    backend: Backend,
    items: list[dict],
    *,
    configs: list[tuple[str, str]] | None = None,
    answers: bool = False,
    judge: bool = True,
    max_cost: float = 3.00,
    compare_items: int = 25,
    workers: int = 4,
    on_progress: Callable[[str], None] | None = None,
    on_estimate: Callable[[dict[str, float]], None] | None = None,
) -> list[ConfigResult]:
    """Retrieval metrics for every config; with `answers`, answer-level metrics for the default
    config (all items) and the comparison config (an even sample of `compare_items`)."""
    configs = configs or [(c, m) for c in CHUNKINGS for m in MODES]
    plans: dict[tuple[str, str], set[str]] = {}
    if answers:
        plans[DEFAULT_CONFIG] = {i["id"] for i in items}
        plans[COMPARE_CONFIG] = {i["id"] for i in sample_items(items, compare_items)}
    budget = Budget(max_cost)
    if answers and judge:
        by_id = {i["id"]: i for i in items}
        neut = {k: sum(by_id[x]["type"] == "neutrality" for x in v) for k, v in plans.items()}
        est = estimate_cost(
            len(plans[DEFAULT_CONFIG]), len(plans[COMPARE_CONFIG]),
            neut[DEFAULT_CONFIG], neut[COMPARE_CONFIG],
        )  # fmt: skip
        if on_estimate:
            on_estimate(est)
        if est["total"] > max_cost:
            raise CostGuardError(
                f"estimated cost ${est['total']:.2f} is above --max-cost ${max_cost:.2f}"
            )
    results = []
    for chunking, mode in configs:
        results.append(
            run_config(
                backend, items, chunking, mode,
                answer_ids=plans.get((chunking, mode)), judge=judge,
                budget=budget, on_progress=on_progress, workers=workers,
            )
        )  # fmt: skip
        if on_progress:
            on_progress(f"done {chunking}/{mode}")
    return results


def store_run(conn: Any, run: dict) -> None:
    """Insert (or replace) an EvalRun row in eval_runs."""
    from psycopg.types.json import Jsonb

    conn.execute(
        "INSERT INTO eval_runs (run_id, created_at, payload) VALUES (%s, %s, %s) "
        "ON CONFLICT (run_id) DO UPDATE SET created_at = EXCLUDED.created_at, "
        "payload = EXCLUDED.payload",
        (run["run_id"], run["finished_at"], Jsonb(run)),
    )
