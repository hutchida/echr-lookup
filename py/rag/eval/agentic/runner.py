# ruff: noqa: E501
"""Run the questions through both systems, judge them, write one JSONL row per answer."""

import contextlib
import json
import sys
import time
import uuid
from collections.abc import Callable
from contextlib import AsyncExitStack
from dataclasses import dataclass, field, replace
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from mcp.client.stdio import StdioServerParameters

from rag.eval import judge as judge_mod
from rag.eval.items import QUESTIONS_PATH, load_questions

from .ask_side import AskRun, ask_claims, ask_tokens, run_ask
from .checks import agentic_recall, quote_report, shape_check
from .common import (
    EST_ASK_COST,
    OWNER_REVIEW_PATH,
    SUBSET_PATH,
    Budget,
    BudgetExceeded,
)
from .host import Host, McpSession, open_session
from .judging import budgeted, judge_claims, judge_requirements
from .quotes import Checker
from .text import Evidence, ParsedAnswer, parse_answer


def load_owner_items(path: Path = OWNER_REVIEW_PATH) -> list[dict]:
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]


def load_subset_items(size: int | None = None, path: Path = SUBSET_PATH) -> list[dict]:
    wanted = json.loads(path.read_text())["ids"]
    by_id = {i["id"]: i for i in load_questions(QUESTIONS_PATH)}
    items = [by_id[i] for i in wanted]
    return items[:size] if size else items


@dataclass
class Job:
    system: str  # "mcp" | "ask"
    set_name: str  # "owner-review" | "subset"
    item: dict
    repeat: int
    context_only: bool = False  # run only to give a follow-up its earlier turn

    @property
    def key(self) -> tuple[str, str, int]:
        return (self.system, self.item["id"], self.repeat)


def plan_jobs(
    *,
    systems: list[str],
    sets: list[str],
    repeats: int,
    ask_repeats: int,
    only: set[str] | None,
    subset_size: int | None,
) -> list[Job]:
    jobs: list[Job] = []
    owner = load_owner_items()
    subset = load_subset_items(subset_size)
    for set_name in sets:
        items = owner if set_name == "owner-review" else subset
        for system in systems:
            n = (repeats if system == "mcp" else ask_repeats) if set_name == "owner-review" else 1
            for repeat in range(1, n + 1):
                for item in items:
                    chosen = only is None or item["id"] in only
                    if chosen:
                        jobs.append(Job(system, set_name, item, repeat))
                    elif system == "mcp" and only and _is_parent_of_chosen(item, owner, only):
                        jobs.append(Job(system, set_name, item, repeat, context_only=True))
    return jobs


def _is_parent_of_chosen(item: dict, owner: list[dict], only: set[str]) -> bool:
    return any(o.get("follow_up_of") == item["id"] and o["id"] in only for o in owner)


@dataclass
class Deps:
    conn: Any  # psycopg connection or None (--fake)
    anthropic_client: Any
    server_params: StdioServerParameters | None
    judge_llm: judge_mod.LLMCall | None
    paragraph_text: Callable[[str], str | None]
    make_checker: Callable[[Callable[[str], str | None]], Checker]
    log_call: Callable | None = None
    ask_fn: Callable[[dict], dict] | None = None


@dataclass
class RunResult:
    rows: list[dict] = field(default_factory=list)
    skipped: list[dict] = field(default_factory=list)
    spent: float = 0.0


def _now() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def _log(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)


def _base_row(job: Job, run_id: str) -> dict:
    return {
        "run_id": run_id,
        "system": job.system,
        "set": job.set_name,
        "item_id": job.item["id"],
        "repeat": job.repeat,
        "question": job.item["question"],
        "context_only": job.context_only,
        "finished_at": _now(),
        "status": "ok",
    }


class Runner:
    def __init__(
        self, deps: Deps, budget: Budget, *, judge: bool, out: Path, run_label: str | None = None
    ):
        self.run_label = run_label
        self.deps = deps
        self.budget = budget
        self.judge = judge and deps.judge_llm is not None
        self.out = out
        self.judge_llm = budgeted(deps.judge_llm, budget) if deps.judge_llm else None
        self.conversations: dict[int, tuple[list[dict], Evidence, set[str]]] = {}
        self.ask_costs: list[float] = []

    def _append(self, row: dict) -> None:
        if self.run_label:
            row = {**row, "run_label": self.run_label}
        self.out.parent.mkdir(parents=True, exist_ok=True)
        with self.out.open("a", encoding="utf-8") as f:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")

    def _metrics(
        self,
        job: Job,
        row: dict,
        *,
        answer_text: str,
        parsed: ParsedAnswer,
        fetched: list[str],
        text_lookup: Callable[[str], str | None],
        tool_names: list[str] | None,
        turn_tool_calls: int | None,
        route: str | None,
    ) -> None:
        item = job.item
        row["answer_text"] = answer_text
        row["claims"] = parsed.claims
        row["unresolved_citations"] = parsed.unresolved
        row["cited_paragraph_ids"] = parsed.cited_ids
        row["fetched_paragraph_ids"] = fetched
        gold = item.get("expected_paragraph_ids")
        row["gold_paragraph_ids"] = gold
        row["agentic_recall"] = agentic_recall(gold or [], fetched)
        quotes = quote_report(
            parsed, self.deps.make_checker(text_lookup), shown=fetched, text_lookup=text_lookup
        )
        row.update(quotes)
        request_id = f"agentic-judge-{uuid.uuid4().hex[:10]}"
        judged: dict = {}
        shape_judge_cost = 0.0
        try:
            if self.judge and not job.context_only:
                judged = judge_claims(self.judge_llm, parsed.claims, text_lookup, request_id)
        except BudgetExceeded as exc:
            row["judge_skipped"] = str(exc)
        row.update(
            judged
            or {
                "n_claims": len(parsed.claims),
                "uncited_claims": sum(not c["citation_ids"] for c in parsed.claims),
            }
        )
        if job.set_name == "owner-review":
            holder: dict[str, float] = {"cost": 0.0}

            def judge_checks(requirements: list[str]) -> list[bool | None]:
                if not self.judge or job.context_only:
                    return [None] * len(requirements)
                try:
                    verdicts, cost = judge_requirements(
                        self.judge_llm, item["question"], answer_text, requirements, request_id
                    )
                except BudgetExceeded as exc:
                    row["judge_skipped"] = str(exc)
                    return [None] * len(requirements)
                holder["cost"] += cost
                return verdicts

            row["shape"] = shape_check(
                item["checks"],
                answer_text=answer_text,
                parsed=parsed,
                tool_names=tool_names,
                turn_tool_calls=turn_tool_calls,
                route=route,
                quotes=quotes,
                judge_checks=judge_checks,
            )
            shape_judge_cost = holder["cost"]
        row["judge_cost_usd"] = row.get("judge_cost_usd", 0.0) + shape_judge_cost

    async def run_mcp(self, job: Job, host: Host, row: dict) -> dict:
        item = job.item
        parent = item.get("follow_up_of")
        history, evidence, seen = (
            self.conversations.get(job.repeat, ([], Evidence(), set()))
            if parent
            else ([], Evidence(), set())
        )
        if parent and not history:
            raise RuntimeError(f"{item['id']} follows {parent}, which has not been answered yet")
        turn, messages = await host.ask(item["question"], history)
        row["tool_calls"] = [c.to_json() for c in turn.tool_calls]
        row["n_tool_calls"] = len(turn.tool_calls)
        row["hit_tool_cap"] = turn.hit_cap
        row["tokens"] = {
            k: getattr(turn.usage, k)
            for k in ("input", "output", "cache_read", "cache_write", "api_calls")
        }
        row["cost_usd"] = turn.usage.cost_usd
        row["latency_ms"] = round(turn.latency_ms, 1)
        if turn.status != "ok":
            row["status"] = turn.status
            row["note"] = turn.note
            return row
        fetched = set(seen)
        for call in turn.tool_calls:
            fetched.update(call.paragraph_ids)
            if not call.is_error:
                with contextlib.suppress(ValueError):
                    evidence.absorb(json.loads(call.result_text))
        if not parent:
            self.conversations[job.repeat] = (messages, evidence, fetched)
        fetched_list = sorted(fetched)

        def text_lookup(pid: str) -> str | None:
            return self.deps.paragraph_text(pid) or evidence.texts.get(pid)

        parsed = parse_answer(turn.answer_text, evidence)
        self._metrics(
            job,
            row,
            answer_text=turn.answer_text,
            parsed=parsed,
            fetched=fetched_list,
            text_lookup=text_lookup,
            tool_names=[c.name for c in turn.tool_calls],
            turn_tool_calls=len(turn.tool_calls),
            route=None,
        )
        return row

    def run_ask_job(self, job: Job, row: dict) -> dict:
        estimate = sum(self.ask_costs) / len(self.ask_costs) if self.ask_costs else EST_ASK_COST
        self.budget.require(estimate, "/ask call")
        run: AskRun = run_ask(self.deps.conn, job.item["question"], self.deps.ask_fn)
        answer = run.answer
        cost = float(answer.get("total_cost_usd", 0.0))
        self.budget.charge(cost)
        self.ask_costs.append(cost)
        row["route"] = answer.get("route")
        row["refused"] = answer.get("refused_or_not_in_sources")
        row["tokens"] = ask_tokens(answer)
        row["cost_usd"] = cost
        row["latency_ms"] = round(answer.get("total_latency_ms") or run.latency_ms, 1)
        row["models_used"] = answer.get("models_used")
        claims = ask_claims(answer)
        parsed = ParsedAnswer(claims, [])
        fetched = run.fetched_ids
        self._metrics(
            job,
            row,
            answer_text=answer.get("answer_text", ""),
            parsed=parsed,
            fetched=fetched,
            text_lookup=self.deps.paragraph_text,
            tool_names=None,
            turn_tool_calls=None,
            route=answer.get("route"),
        )
        return row

    async def run(
        self, jobs: list[Job], *, done: set[tuple[str, str, int]] | None = None
    ) -> RunResult:
        done = done or set()
        result = RunResult()
        run_id = f"run-{uuid.uuid4().hex[:8]}"
        todo: list[Job] = []
        for j in jobs:
            if j.key not in done:
                todo.append(j)
            elif any(
                o.system == j.system
                and o.repeat == j.repeat
                and o.item.get("follow_up_of") == j.item["id"]
                and o.key not in done
                for o in jobs
            ):  # already answered, but a follow-up still needs its conversation
                todo.append(replace(j, context_only=True))
        async with AsyncExitStack() as stack:
            host: Host | None = None
            if any(j.system == "mcp" for j in todo):
                if self.deps.server_params is None:
                    raise RuntimeError("no MCP server configured")
                session: McpSession = await stack.enter_async_context(
                    open_session(self.deps.server_params)
                )
                host = Host(
                    session,
                    self.deps.anthropic_client,
                    log_call=self.deps.log_call,
                    budget=self.budget,
                )
            stopped = False
            for n, job in enumerate(todo, start=1):
                row = _base_row(job, run_id)
                if stopped:
                    row.update(status="skipped_budget", note="an earlier call hit --max-cost")
                    result.skipped.append(row)
                    result.rows.append(row)
                    self._append(row)
                    continue
                started = time.perf_counter()
                try:
                    if job.system == "mcp":
                        assert host is not None
                        row = await self.run_mcp(job, host, row)
                    else:
                        row = self.run_ask_job(job, row)
                except BudgetExceeded as exc:
                    row.update(status="skipped_budget", note=str(exc))
                except Exception as exc:  # one broken question must not lose the rest of the run
                    row.update(status="error", note=f"{type(exc).__name__}: {exc}")
                if row["status"] == "skipped_budget":
                    stopped = True
                    result.skipped.append(row)
                row["finished_at"] = _now()
                self._append(row)
                result.rows.append(row)
                _log(
                    f"[{n}/{len(todo)}] {job.system:3} {job.item['id']:12} x{job.repeat} "
                    f"{row['status']:14} {time.perf_counter() - started:5.1f}s  spent ${self.budget.spent:.3f}"
                )
        result.spent = self.budget.spent
        return result


def read_rows(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text().splitlines() if line.strip()]
