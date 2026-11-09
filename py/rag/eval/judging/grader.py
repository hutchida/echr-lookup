# ruff: noqa: E501 (prose strings)
"""Step 3: the judge. One call per question: the question plus every pooled paragraph, shuffled,
under a written rubric. The judge is never told which paragraphs were original gold or which
configs found them. Replies are validated strictly; one retry; failures are counted, never
dropped or filled in.

Paragraphs go to the judge under short aliases (P01, P02, ...) in a seeded shuffle, and the
aliases are mapped back to real ids here. The model is JUDGE_MODEL, an Opus served by a LiteLLM gateway (the Anthropic key's monthly limit was reached), deliberately not the Sonnet that
wrote the key and not rag.config.judge_model(). Calls go through litellm_client only, logged to
cost_log with purpose "judge" and a request_id starting "relevance-".
"""

import random
import threading
import time
from collections.abc import Callable, Sequence
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Any

from rag.eval.judge import parse_json

from .budget import REQUEST_PREFIX, CapExceeded, SpendGuard, estimate_call_usd
from .common import append_jsonl, read_jsonl

JUDGE_MODEL = "vertex-ai-claude-opus-4.8"
MAX_TOKENS = 16000  # ~190 paragraphs x ~60 tokens fits; the model allows up to 128k
GRADES = (0, 1, 2)

SYSTEM_PROMPT = """You are a careful legal-relevance assessor for a search engine over European Court of Human Rights (ECHR) judgments and decisions about the United Kingdom, plus UK and Convention legislation. A user asked one question. You are shown a pool of candidate paragraphs, each quoted verbatim with its case name, document type and section. Grade EVERY candidate paragraph for how well it helps answer the question.

GRADES
2 = Directly answers the question. The paragraph states the holding, rule, test or provision that answers it, or gives the Court's reasoning that decides it. Someone reading only this paragraph would have the answer, or the central part of it, and could cite it for that.
1 = Relevant context, not enough alone. It concerns the same issue (the facts, the background law, a related principle, one side's argument, a step in the reasoning, or only one aspect of a multi-part question) but does not by itself answer the question.
0 = Not relevant. Different topic or issue, procedural or administrative text (hearings, representation, costs, lists of parties), or it only shares keywords with the question.

RULES
- Judge only the text of the paragraph in front of you, against the question as asked. Do not rely on what you remember about the case, and do not reward a paragraph for being long or from a famous case.
- Each paragraph is graded on its own. Several paragraphs may deserve a 2; give 2 to every one that independently answers, and do not hold back a grade because another paragraph is better.
- A paragraph that only reports what a party argued, or what a lower court said, is at most 1 unless the question is about that argument.
- A paragraph from a case about another State is fine, and can be a 2, if it states the general principle the question asks about.
- Be strict with 2 and with 0: a 2 must answer the question, and a 0 must have nothing useful for it. Use 1 for everything in between.
- For questions that ask what a statute or Convention article says, the provision text itself is a 2.
- You are not told, and must not guess, which paragraphs anybody expected to be relevant.

WORKED EXAMPLE 1
Question: Does the long wait on death row count towards a breach of Article 3?
[P1] SOERING v. THE UNITED KINGDOM | judgment | The Law
"However, in the Court’s view, having regard to the very long period of time spent on death row in such extreme conditions, with the ever present and mounting anguish of awaiting execution of the death penalty, and to the personal circumstances of the applicant, especially his age and mental state at the time of the offence, the applicant’s extradition to the United States would expose him to a real risk of treatment going beyond the threshold set by Article 3 [...] Accordingly, the Secretary of State’s decision to extradite the applicant to the United States would, if implemented, give rise to a breach of Article 3"
-> grade 2: states the Court's conclusion that the long period on death row in such conditions crosses the Article 3 threshold.
[P2] SOERING v. THE UNITED KINGDOM | judgment | The Law
"The period that a condemned prisoner can expect to spend on death row in Virginia before being executed is on average six to eight years [...] the consequence is that the condemned prisoner has to endure for many years the conditions on death row and the anguish and mounting tension of living in the ever-present shadow of death."
-> grade 1: describes the length and effect of the wait, a step towards the answer, but does not say whether Article 3 is breached.
[P3] SOERING v. THE UNITED KINGDOM | judgment | The Facts
"On 29 June 1987 Mr Soering applied to the Divisional Court for a writ of habeas corpus in respect of his committal and for leave to apply for judicial review. On 11 December both applications were refused by the Divisional Court [...]"
-> grade 0: domestic court procedure; says nothing about death row or Article 3.

WORKED EXAMPLE 2
Question: Is the right to vote a privilege that a State may grant to whom it chooses?
[P1] HIRST v. THE UNITED KINGDOM (No. 2) | judgment | The Law
"As pointed out by the applicant, the right to vote is not a privilege. In the twenty-first century, the presumption in a democratic State must be in favour of inclusion [...] Universal suffrage has become the basic principle"
-> grade 2: states the principle that voting is a right, not a privilege, with a presumption in favour of inclusion.
[P2] HIRST v. THE UNITED KINGDOM (No. 2) | judgment | The Law
"Therefore, while the Court reiterates that the margin of appreciation is wide, it is not all-embracing [...] Such a general, automatic and indiscriminate restriction on a vitally important Convention right must be seen as falling outside any acceptable margin of appreciation"
-> grade 1: applies the limits on State discretion to one restriction (prisoners); it is related but does not state the general principle asked about.
[P3] HIRST v. THE UNITED KINGDOM (No. 2) | judgment | Procedure
"A hearing took place in public in the Human Rights Building, Strasbourg, on 27 April 2005 (Rule 59 § 3). There appeared before the Court: (a) for the Government Ms E. Willmott, Agent [...]"
-> grade 0: who appeared at the hearing; nothing about the right to vote.

OUTPUT
Reply with one JSON object and nothing else (no code fence, no prose):
{"judgments": [{"p": "P01", "grade": 2, "reason": "<one short sentence, at most 25 words, saying why>"}, ...]}
Include exactly one entry for each paragraph alias you were given: every alias once, no alias twice, no other aliases. "grade" must be the integer 0, 1 or 2. "reason" must not be empty."""

LLMCall = Callable[[str, list[dict], str, int], Any]
"""(system, messages, request_id, max_tokens) -> object with .text .model .tokens_in .tokens_out
.tokens_cached .cost_usd .latency_ms (litellm_client.JudgeResult)"""


def alias_for(n: int) -> str:
    return f"P{n:02d}"


def shuffled_order(question_id: str, ids: Sequence[str], seed: int, run: int) -> list[str]:
    """A reproducible shuffle: seeded by (seed, run, question id), so each run and question gets
    its own order and the same inputs always give the same one."""
    order = sorted(ids)
    random.Random(f"{seed}:{run}:{question_id}").shuffle(order)
    return order


def build_user_prompt(question: str, entries: Sequence[tuple[str, dict]]) -> str:
    """entries: (alias, pool paragraph) in the order to show them."""
    blocks = [
        f"[{alias}] {p['case_name']} | {p['doc_type']} | {p['section']}\n{p['text']}"
        for alias, p in entries
    ]
    aliases = ", ".join(a for a, _ in entries)
    return (
        f"Question: {question}\n\n"
        f"Candidate paragraphs ({len(entries)}; aliases {aliases}):\n\n" + "\n\n".join(blocks)
    )


def validate_reply(text: str, aliases: Sequence[str]) -> tuple[dict[str, dict] | None, list[str]]:
    """Strict check of a judge reply. -> ({alias: {"grade", "reason"}}, []) if it is valid, else
    (None, [every problem found]). Valid = a JSON object with a "judgments" list; every alias
    exactly once; no other aliases; grade is the integer 0, 1 or 2; reason is a non-empty string."""
    data = parse_json(text)
    if data is None:
        return None, ["reply is not a JSON object"]
    items = data.get("judgments")
    if not isinstance(items, list):
        return None, ['JSON has no "judgments" list']
    errors: list[str] = []
    expected = set(aliases)
    seen: dict[str, dict] = {}
    for i, it in enumerate(items):
        if not isinstance(it, dict):
            errors.append(f"entry {i} is not an object")
            continue
        alias = it.get("p")
        if not isinstance(alias, str) or alias not in expected:
            errors.append(f"entry {i} has unknown alias {alias!r}")
            continue
        if alias in seen:
            errors.append(f"alias {alias} appears more than once")
            continue
        grade, reason = it.get("grade"), it.get("reason")
        if isinstance(grade, bool) or not isinstance(grade, int) or grade not in GRADES:
            errors.append(f"{alias}: grade must be 0, 1 or 2, got {grade!r}")
            continue
        if not isinstance(reason, str) or not reason.strip():
            errors.append(f"{alias}: reason is empty")
            continue
        seen[alias] = {"grade": grade, "reason": reason.strip()}
    missing = [a for a in aliases if a not in seen]
    if missing and not errors:
        errors.append(f"missing aliases: {', '.join(missing[:10])}")
    elif missing:
        errors.append(f"{len(missing)} alias(es) missing or invalid")
    return (None, errors) if errors else (seen, [])


def retry_messages(user: str, bad_reply: str, errors: Sequence[str]) -> list[dict]:
    """The conversation for the one retry: the original prompt, the bad reply, what was wrong."""
    problems = "; ".join(errors[:8])
    ask = (
        f"Your reply could not be accepted: {problems}. Reply again with the complete JSON "
        "object only, covering every alias exactly once."
    )
    if not bad_reply.strip():
        return [{"role": "user", "content": user}]
    return [
        {"role": "user", "content": user},
        {"role": "assistant", "content": bad_reply},
        {"role": "user", "content": ask},
    ]


def _chars(system: str, messages: Sequence[dict]) -> int:
    return len(system) + sum(len(m["content"]) for m in messages)


def judge_question(
    q: dict,
    llm: LLMCall,
    guard: SpendGuard,
    *,
    run: int,
    seed: int,
    model: str = JUDGE_MODEL,
    max_tokens: int = MAX_TOKENS,
) -> dict:
    """Judge one pooled question; returns the record to persist. Raises CapExceeded (before the
    call) when the next call would pass the cap."""
    usable = {p["id"]: p for p in q["paragraphs"] if p.get("text")}
    base = {
        "question_id": q["question_id"],
        "run": run,
        "seed": seed,
        "model": model,
        "n_pooled": len(q["paragraphs"]),
    }
    if len(usable) != len(q["paragraphs"]):
        return {**base, "ok": False, "order": [], "attempts": [], "grades": {},
                "errors": ["a pooled paragraph has no text; refusing to judge a partial pool"]}  # fmt: skip
    order = shuffled_order(q["question_id"], list(usable), seed, run)
    aliases = [alias_for(i) for i in range(1, len(order) + 1)]
    alias_to_id = dict(zip(aliases, order, strict=True))
    user = build_user_prompt(q["question"], [(a, usable[alias_to_id[a]]) for a in aliases])
    messages = [{"role": "user", "content": user}]
    attempts: list[dict] = []
    errors: list[str] = []
    grades: dict[str, dict] | None = None
    for attempt in (1, 2):
        estimate = estimate_call_usd(model, _chars(SYSTEM_PROMPT, messages), len(order))
        guard.reserve(estimate)  # raises CapExceeded
        request_id = f"{REQUEST_PREFIX}{q['question_id']}-r{run}-a{attempt}"
        try:
            res = llm(SYSTEM_PROMPT, messages, request_id, max_tokens)
        finally:
            guard.release(estimate)
        grades, errors = validate_reply(res.text, aliases)
        attempts.append(
            {
                "request_id": request_id,
                "reply": res.text,
                "errors": errors,
                "tokens_in": res.tokens_in,
                "tokens_out": res.tokens_out,
                "tokens_cached": res.tokens_cached,
                "cost_usd": res.cost_usd,
                "cost_source": getattr(res, "cost_source", None),
                "finish_reason": getattr(res, "finish_reason", None),
                "latency_ms": round(res.latency_ms),
            }
        )
        if grades is not None:
            break
        messages = retry_messages(user, res.text, errors)
    return {
        **base,
        "ok": grades is not None,
        "order": [{"alias": a, "id": alias_to_id[a]} for a in aliases],
        "attempts": attempts,
        "grades": ({alias_to_id[a]: g for a, g in grades.items()} if grades is not None else {}),
        "errors": [] if grades is not None else errors,
    }


def load_run(path: Path) -> dict[str, dict]:
    """question id -> last record in a judgments file."""
    return {r["question_id"]: r for r in read_jsonl(path)}


def run_judging(
    pool: Sequence[dict],
    llm: LLMCall,
    guard: SpendGuard,
    out_path: Path,
    *,
    run: int,
    seed: int,
    model: str = JUDGE_MODEL,
    only: Sequence[str] | None = None,
    retry_failed: bool = False,
    workers: int = 4,
    max_tokens: int = MAX_TOKENS,
    on_progress: Callable[[str], None] | None = None,
    on_record: Callable[[dict], None] | None = None,
) -> dict:
    """Judge every pooled question (or `only`) not already in out_path, appending one record per
    question as it finishes, so a crash never re-spends. A question already recorded is skipped,
    including a failed one unless retry_failed. A question whose call raised (proxy down, ...) is not
    recorded, so a re-run does it again. -> {"judged", "skipped", "failed", "not_run", "errored"}."""
    done = load_run(out_path)
    todo = [
        q for q in pool
        if (only is None or q["question_id"] in only)
        and not (q["question_id"] in done and (done[q["question_id"]]["ok"] or not retry_failed))
    ]  # fmt: skip
    skipped = len([q for q in pool if only is None or q["question_id"] in only]) - len(todo)
    lock = threading.Lock()
    stop = threading.Event()
    counts = {"judged": 0, "failed": 0, "not_run": 0, "errored": 0}
    t0 = time.time()

    def work(q: dict) -> None:
        if stop.is_set():
            counts["not_run"] += 1
            return
        try:
            rec = judge_question(
                q, llm, guard, run=run, seed=seed, model=model, max_tokens=max_tokens
            )
        except CapExceeded as exc:
            stop.set()
            counts["not_run"] += 1
            if on_progress:
                on_progress(f"STOPPED by spend cap before {q['question_id']}: {exc}")
            return
        except Exception as exc:  # proxy error after retries: leave the question for a re-run
            with lock:
                counts["errored"] += 1
                if on_progress:
                    on_progress(f"ERROR on {q['question_id']}: {type(exc).__name__}: {exc}")
            return
        with lock:
            append_jsonl(out_path, rec)
            counts["judged"] += 1
            counts["failed"] += 0 if rec["ok"] else 1
            if on_record:
                on_record(rec)
            if on_progress:
                cost = sum(a["cost_usd"] for a in rec["attempts"])
                on_progress(
                    f"[{time.time() - t0:6.0f}s] {q['question_id']}: "
                    f"{'ok' if rec['ok'] else 'FAILED ' + '; '.join(rec['errors'][:2])} "
                    f"({rec['n_pooled']} paragraphs, {len(rec['attempts'])} call(s), ${cost:.3f})"
                )

    with ThreadPoolExecutor(max_workers=workers) as ex:
        list(ex.map(work, todo))
    return {**counts, "skipped": skipped}


__all__ = ["JUDGE_MODEL", "judge_question", "run_judging", "validate_reply"]
