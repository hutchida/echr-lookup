# ruff: noqa: E501
"""Write docs/mcp-comparison.md from the results JSONL. Hand-written sections survive a rewrite."""

import json
import statistics
from collections import Counter
from pathlib import Path

from rag import config

from .checks import agentic_recall, v2_gold
from .common import HOST_MODEL, MAX_TOOL_CALLS, SUBSET_SEED
from .quotes import quote_in_any

SYSTEMS = [("mcp", "Claude + tools"), ("ask", "`/ask`")]
AFTER = ("mcp_after", "Claude + tools, after F1")  # the re-run's rows, relabelled for the tables
KEEP = {
    "what-we-saw": "## What we saw\n\n(To be written after the full run.)\n",
    "fairness-free": "## Fairness checks, free part\n\n(To be written.)\n",
    "after-f1": "### Verdict\n\n(To be written after the re-run.)\n",
    "decision": "## Decision memo\n\nTo be written after the owner review.\n",
}
MARK = "<!-- {}:{} -->"
PENDING_TEXT = """### After F1: what changed and what the re-run will answer

- **What F1 changed (merged, PR #30):** every hit and paragraph now has a readable `para_label` in its `cite` (for example "Law, para 2"), a `hudoc_url` that opens the document at the quoted words, and tighter server `instructions` (cite every factual sentence, quote only copied text, no cases from general knowledge, answer first). Paragraph ids are unchanged.
- **What the re-run will answer:** whether those changes alone cut uncited claims, non-verbatim quotes and outside cases (or-06) and raise the shape pass, and at what cost. The harness is ready (new cites and links map back to ids); the commands are in `docs/learn/F3.md`."""
PENDING_NOTE = (
    "> **After F1: not run.** {reason} The third column below is the planned re-run of "
    "Claude + tools against F1's server; every other number is the M2 run (2026-11-04), unchanged."
)


def usable(rows: list[dict]) -> list[dict]:
    """Latest row per (system, item, repeat); context-only and failed rows dropped."""
    latest: dict[tuple, dict] = {}
    for r in rows:
        if not r.get("context_only"):
            latest[(r["system"], r["item_id"], r["repeat"])] = r
    return list(latest.values())


def mean(values) -> float | None:
    vals = [v for v in values if v is not None]
    return sum(vals) / len(vals) if vals else None


def pct(value: float | None, digits: int = 0) -> str:
    return "n/a" if value is None else f"{value * 100:.{digits}f}%"


def num(value: float | None, digits: int = 1) -> str:
    return "n/a" if value is None else f"{value:,.{digits}f}"


def usd(value: float | None, digits: int = 3) -> str:
    return "n/a" if value is None else f"${value:.{digits}f}"


def fill_shown_quotes(rows: list[dict], text_lookup) -> None:
    """Rows from before the runner recorded `in_shown_nocase`: work it out from the paragraph text
    (in memory only; the JSONL is not touched)."""
    for r in rows:
        if r.get("status") != "ok" or r["system"] == "ask" or not r.get("quotes"):
            continue
        if all("in_shown_nocase" in q for q in r["quotes"]):
            continue
        texts = [text_lookup(pid) for pid in dict.fromkeys(r["fetched_paragraph_ids"])]
        for q in r["quotes"]:
            q["in_shown_nocase"] = quote_in_any(texts, q["quote"], ignore_case=True)


def summarise(rows: list[dict], system: str, set_name: str, qrels: dict | None = None) -> dict:
    ok = [r for r in rows if r["system"] == system and r["set"] == set_name and r["status"] == "ok"]
    quotes = [q for r in ok for q in r.get("quotes", [])]
    shape = [
        r["shape"]["passed"] for r in ok if r.get("shape") and r["shape"]["passed"] is not None
    ]
    tokens = [r["tokens"] for r in ok]
    return {
        "n": len(ok),
        "shape": (sum(shape), len(shape)) if shape else None,
        "claim_acc": mean(r.get("claim_accuracy") for r in ok),
        "fully": mean(r.get("fully_supported") for r in ok),
        "per_cite": mean(r.get("per_citation_accuracy") for r in ok),
        "judged": sum(r.get("claim_accuracy") is not None for r in ok),
        "uncited": (
            sum(r.get("uncited_claims") or 0 for r in ok) / sum(r.get("n_claims") or 0 for r in ok)
            if sum(r.get("n_claims") or 0 for r in ok)
            else None
        ),
        "claims": mean(r.get("n_claims") for r in ok),
        "recall": mean(r.get("agentic_recall") for r in ok),
        "recall_v2": mean(
            agentic_recall(v2_gold(qrels.get(r["item_id"])), r["fetched_paragraph_ids"])
            for r in ok
            if qrels is not None
        ),
        "quote_shown": (
            sum(q["in_shown_nocase"] for q in quotes) / len(quotes)
            if quotes and all("in_shown_nocase" in q for q in quotes)
            else None
        ),
        "quote_rate": (sum(q["verbatim"] for q in quotes) / len(quotes)) if quotes else None,
        "quotes": len(quotes),
        "tool_calls": mean(r.get("n_tool_calls") for r in ok) if system.startswith("mcp") else None,
        "cap_hits": sum(bool(r.get("hit_tool_cap")) for r in ok),
        "tok_in": mean(t["input"] for t in tokens),
        "tok_out": mean(t["output"] for t in tokens),
        "tok_read": mean(t["cache_read"] for t in tokens),
        "tok_write": mean(t["cache_write"] for t in tokens),
        "cost": mean(r["cost_usd"] for r in ok),
        "judge_cost": mean(r.get("judge_cost_usd") for r in ok),
        "latency": mean(r["latency_ms"] / 1000 for r in ok),
        "latency_median": statistics.median([r["latency_ms"] / 1000 for r in ok]) if ok else None,
    }


def side_by_side(
    rows: list[dict],
    set_name: str,
    title: str,
    systems: list[tuple[str, str]] = SYSTEMS,
    qrels: dict | None = None,
) -> list[str]:
    s = {sys: summarise(rows, sys, set_name, qrels) for sys, _ in systems}
    if not any(v["n"] for v in s.values()):
        return []
    systems_ = systems

    def cell(key, fmt):
        return [fmt(s[sys][key]) for sys, _ in systems_]

    def shape(v):
        return "n/a" if not v else f"{v[0]}/{v[1]} ({pct(v[0] / v[1])})"

    names = " | ".join(name for _, name in systems_)
    lines = [f"### {title}", "", f"| | {names} |", "|" + "---|" * (len(systems_) + 1)]
    lines.append("| answers scored | " + " | ".join(str(s[x]["n"]) for x, _ in systems_) + " |")
    if set_name == "owner-review":
        lines.append(
            "| shape checks: answers passing all | " + " | ".join(cell("shape", shape)) + " |"
        )
    lines.append(
        "| citation accuracy, per claim (all its citations together; mean verdict 1 / ½ / 0) | "
        + " | ".join(cell("claim_acc", pct))
        + " |"
    )
    lines.append("| … share of claims fully supported | " + " | ".join(cell("fully", pct)) + " |")
    lines.append("| citation accuracy, per citation | " + " | ".join(cell("per_cite", pct)) + " |")
    lines.append("| claims per answer | " + " | ".join(cell("claims", num)) + " |")
    lines.append(
        "| claims with no citation (share of all claims; not judged) | "
        + " | ".join(cell("uncited", pct))
        + " |"
    )
    if set_name == "subset":
        lines.append(
            "| agentic recall (gold paragraphs the model was shown) | "
            + " | ".join(cell("recall", pct))
            + " |"
        )
    if set_name == "subset" and qrels is not None:
        lines.append(
            "| … the same, against the wider answer key qrels-v2 | "
            + " | ".join(cell("recall_v2", pct))
            + " |"
        )
    lines.append(
        "| verbatim-quote rate (quotes checked) | "
        + " | ".join(f"{pct(s[x]['quote_rate'])} ({s[x]['quotes']})" for x, _ in systems_)
        + " |"
    )
    if any(s[x]["quote_shown"] is not None for x, _ in systems_):
        lines.append(
            "| … quote text found in any paragraph the model was shown (case ignored) | "
            + " | ".join(cell("quote_shown", pct))
            + " |"
        )
    lines.append(
        "| tool calls per question | "
        + " | ".join(cell("tool_calls", lambda v: "n/a" if v is None else num(v)))
        + " |"
    )
    lines.append(
        "| tokens per question: input (uncached) | "
        + " | ".join(cell("tok_in", lambda v: num(v, 0)))
        + " |"
    )
    lines.append("| … output | " + " | ".join(cell("tok_out", lambda v: num(v, 0))) + " |")
    lines.append(
        "| … cache read / cache write | "
        + " | ".join(
            f"{num(s[x]['tok_read'], 0)} / {num(s[x]['tok_write'], 0)}" for x, _ in systems_
        )
        + " |"
    )
    lines.append("| cost per question (answering only) | " + " | ".join(cell("cost", usd)) + " |")
    lines.append(
        "| latency per question, mean (median), seconds | "
        + " | ".join(f"{num(s[x]['latency'])} ({num(s[x]['latency_median'])})" for x, _ in systems_)
        + " |"
    )
    lines.append("")
    return lines


def mark_not_run(line: str) -> str:
    """A third column for the planned re-run, filled with "not run" (no numbers)."""
    if line.startswith("| | "):
        return line + f" {AFTER[1]} |"
    if line.startswith("|---"):
        return line + "---|"
    if line.startswith("| "):
        return line + " not run |"
    return line


def describe(check: dict) -> str:
    param = check.get("tool") or check.get("any") or check.get("n") or check.get("doc_id")
    param = param or check.get("paragraph_id") or check.get("text") or check.get("snapshot")
    if check["kind"] == "judge":
        return f"judge ({param[:40]}…)"
    return f"{check['kind']} {param}" if param else check["kind"]


def per_question(rows: list[dict], owner: list[dict]) -> list[str]:
    ok = [r for r in rows if r["set"] == "owner-review" and r["status"] == "ok"]
    if not ok:
        return []
    lines = [
        "| id | question | Claude + tools: shape pass | `/ask`: shape pass | checks that failed (Claude + tools / `/ask`) | tool calls (mean) | cost: tools / ask |",
        "|---|---|---|---|---|---|---|",
    ]
    for item in owner:
        cells, failed, cost = {}, {}, {}
        for sys, _ in SYSTEMS:
            mine = [r for r in ok if r["system"] == sys and r["item_id"] == item["id"]]
            marks = [r["shape"]["passed"] for r in mine if r.get("shape")]
            cells[sys] = f"{sum(bool(m) for m in marks)}/{len(marks)}" if marks else "n/a"
            bad = Counter(
                describe(item["checks"][i])
                for r in mine
                for i, c in enumerate(r["shape"]["checks"])
                if c["passed"] is False
            )
            failed[sys] = ", ".join(f"{k}×{v}" for k, v in bad.most_common()) or "none"
            cost[sys] = mean(r["cost_usd"] for r in mine)
        tool = mean(
            r.get("n_tool_calls") for r in ok if r["system"] == "mcp" and r["item_id"] == item["id"]
        )
        question = item["question"].replace("|", "\\|")
        lines.append(
            f"| {item['id']} | {question} | {cells['mcp']} | {cells['ask']} | {failed['mcp']} / {failed['ask']} | "
            f"{num(tool)} | {usd(cost['mcp'])} / {usd(cost['ask'])} |"
        )
    lines.append("")
    return lines


def after_table(rows: list[dict], owner: list[dict]) -> list[str]:
    """Owner-review questions, Claude + tools before F1 (M2) and after it, regressions flagged."""
    ok = [r for r in rows if r["set"] == "owner-review" and r["status"] == "ok"]
    lines = [
        "| id | shape pass: M2 → after F1 | claims with no citation | verbatim quotes | checks that failed after F1 | cost per answer | |",
        "|---|---|---|---|---|---|---|",
    ]

    def share(mine, key_n, key_x):
        n, x = sum(r.get(key_n) or 0 for r in mine), sum(r.get(key_x) or 0 for r in mine)
        return x / n if n else None

    for item in owner:
        old = [r for r in ok if r["system"] == "mcp" and r["item_id"] == item["id"]]
        new = [r for r in ok if r["system"] == AFTER[0] and r["item_id"] == item["id"]]
        if not new:
            continue

        def passed(mine):
            return sum(bool(r["shape"]["passed"]) for r in mine if r.get("shape"))

        def verbatim(mine):
            qs = [q for r in mine for q in r.get("quotes", [])]
            return sum(q["verbatim"] for q in qs) / len(qs) if qs else None

        bad = Counter(
            describe(item["checks"][i])
            for r in new
            for i, c in enumerate(r["shape"]["checks"])
            if c["passed"] is False
        )
        flag = (
            "**regression**"
            if passed(new) / len(new) < passed(old) / len(old) - 1e-9
            else "better"
            if passed(new) / len(new) > passed(old) / len(old) + 1e-9
            else ""
        )
        lines.append(
            f"| {item['id']} | {passed(old)}/{len(old)} → {passed(new)}/{len(new)} "
            f"| {pct(share(old, 'n_claims', 'uncited_claims'))} → {pct(share(new, 'n_claims', 'uncited_claims'))} "
            f"| {pct(verbatim(old))} → {pct(verbatim(new))} "
            f"| {', '.join(f'{k}×{v}' for k, v in bad.most_common()) or 'none'} "
            f"| {usd(mean(r['cost_usd'] for r in old))} → {usd(mean(r['cost_usd'] for r in new))} | {flag} |"
        )
    lines.append("")
    return lines


def transcripts(rows: list[dict], owner: list[dict]) -> list[str]:
    lines: list[str] = []
    for item in owner:
        mine = sorted(
            (
                r
                for r in rows
                if r["system"] == "mcp" and r["item_id"] == item["id"] and r["status"] == "ok"
            ),
            key=lambda r: r["repeat"],
        )
        if not mine:
            continue
        r = mine[0]
        lines += [f"### {item['id']}: {item['question']}", ""]
        if item.get("follow_up_of"):
            lines += [
                f"*Second turn of a conversation: asked after {item['follow_up_of']}; the model also had that turn's tool results.*",
                "",
            ]
        lines += [
            f"Sample 1 of {len(mine)}; {r['n_tool_calls']} tool calls, {usd(r['cost_usd'])}, {num(r['latency_ms'] / 1000)} s.",
            "",
        ]
        if r["tool_calls"]:
            lines += ["| # | tool | arguments | result |", "|---|---|---|---|"]
            for n, c in enumerate(r["tool_calls"], start=1):
                args = json.dumps(c["args"], ensure_ascii=False).replace("|", "\\|")
                result = "error: " if c["is_error"] else ""
                lines.append(
                    f"| {n} | `{c['name']}` | `{args}` | {result}{c['result_bytes']:,} bytes |"
                )
            lines.append("")
        else:
            lines += ["No tool calls.", ""]
        lines += [f"> {line}" if line else ">" for line in r["answer_text"].splitlines()] + [""]
        if r.get("shape"):
            marks = ", ".join(
                f"{c['kind']} {'✓' if c['passed'] else '✗' if c['passed'] is False else '–'}"
                for c in r["shape"]["checks"]
            )
            lines += [f"Shape checks: {marks}.", ""]
    return lines


def after_f1_section(
    both: list[dict],
    owner: list[dict],
    old: str,
    after_meta: dict | None,
    after_spend: dict | None,
    after_rows: list[dict],
    pending: bool = False,
) -> list[str]:
    if pending:
        return [
            "## After F1: not run",
            "",
            MARK.format("after-f1", "start"),
            PENDING_TEXT,
            MARK.format("after-f1", "end"),
            "",
        ]
    if not after_rows:  # never lose a verdict that was already written
        start = MARK.format("after-f1", "start")
        if start not in old:
            return []
        return [start, kept(old, "after-f1").rstrip("\n"), MARK.format("after-f1", "end"), ""]
    meta = after_meta or {}
    when = sorted(r["finished_at"] for r in after_rows)
    lines = [
        "## After F1: Claude + tools re-run on the improved server",
        "",
        f"Same host, judge, questions and tool cap as M2; the server is F1's (`cite` with `para_label`, `hudoc_url` with a text fragment, tighter `instructions`), database `{meta.get('db', 'echr_f3')}`. "
        f"Run label `{meta.get('run_label', 'after-F1')}`, {when[0][:10]} (UTC), raw rows in `{meta.get('results', 'data/eval/agentic/results-after-f1.jsonl')}`; the M2 rows are untouched and `/ask` is not re-run (its M2 answers are the comparison). "
        "Compare the columns *Claude + tools* (M2), *`/ask`* (M2) and *after F1* in the tables above.",
        "",
        "### Owner review, question by question (Claude + tools: M2 → after F1)",
        "",
        *after_table(both, owner),
    ]
    if after_spend:
        lines += [
            "### Spend of the re-run",
            *spend_section(after_spend, meta.get("cap_usd", 5.0)),
            "",
        ]
    lines += [
        MARK.format("after-f1", "start"),
        kept(old, "after-f1").rstrip("\n"),
        MARK.format("after-f1", "end"),
        "",
    ]
    return lines


def spend_section(spend: dict | None, cap: float) -> list[str]:
    if not spend:
        return ["Spend from `cost_log`: not available when this document was written."]
    total = sum(v["cost"] for v in spend.values())
    lines = [
        "| purpose | calls | tokens in | tokens out | cached | cost (`cost_log`) |",
        "|---|---|---|---|---|---|",
    ]
    for purpose, v in sorted(spend.items()):
        lines.append(
            f"| {purpose} | {v['calls']} | {v['in']:,} | {v['out']:,} | {v['cached']:,} | {usd(v['cost'])} |"
        )
    lines.append(
        f"| **total** | {sum(v['calls'] for v in spend.values())} | | | | **{usd(total)}** of ${cap:.2f} |"
    )
    return ["", *lines]


def old_spend(old: str) -> list[str]:
    """The Spend table already in the doc: kept when it cannot be recomputed (this database's
    cost_log does not hold the run it was written from)."""
    if "## Spend\n" not in old or "`cost_log` books cache writes" not in old:
        return []
    block = old.split("## Spend\n", 1)[1].split("`cost_log` books cache writes", 1)[0]
    return block.rstrip("\n").split("\n")


def kept(old: str, name: str) -> str:
    start, end = MARK.format(name, "start"), MARK.format(name, "end")
    if start in old and end in old:
        return old.split(start, 1)[1].split(end, 1)[0].strip("\n") + "\n"
    return KEEP[name]


def render(
    rows: list[dict],
    *,
    old: str = "",
    spend: dict | None = None,
    cap: float = 8.0,
    meta: dict | None = None,
    after: list[dict] | None = None,
    after_meta: dict | None = None,
    after_spend: dict | None = None,
    qrels: dict | None = None,
    text_lookup=None,
    after_not_run: str | None = None,
) -> str:
    from .runner import load_owner_items

    owner = load_owner_items()
    rows = usable(rows)
    after_rows = [{**r, "system": AFTER[0]} for r in usable(after or [])]
    if text_lookup is not None:
        fill_shown_quotes(rows + after_rows, text_lookup)
    pending = bool(after_not_run) and not after_rows
    systems = [*SYSTEMS, AFTER] if after_rows else SYSTEMS
    both = rows + after_rows
    tables = side_by_side(both, "owner-review", "Owner-review set", systems, qrels) + side_by_side(
        both, "subset", "Retrieval subset", systems, qrels
    )
    if pending:
        tables = [mark_not_run(line) for line in tables]
    done = [r for r in rows if r["status"] == "ok"]
    problems = [r for r in [*rows, *after_rows] if r["status"] != "ok"]
    when = sorted(r["finished_at"] for r in rows) or [""]
    n_owner = {
        s: len({r["repeat"] for r in done if r["system"] == s and r["set"] == "owner-review"})
        for s, _ in SYSTEMS
    }
    n_subset = len({r["item_id"] for r in done if r["set"] == "subset" and r["system"] == "mcp"})
    meta = meta or {}
    out = [
        "# Claude + MCP tools vs `/ask`",
        "",
        "Gate 1 comparison eval (task M2). Claude answers the same questions two ways: **with the echr-lookup MCP tools** (Claude does the searching, reading and writing) and through the existing **`/ask` pipeline** (our code retrieves, one model writes, a second model checks each claim). Facts only here; the decision memo comes after the owner review.",
        "",
        "## Setup",
        "",
        f"- **Host model with tools:** `{HOST_MODEL}` through the Anthropic Messages API, system prompt = the server's `instructions`, the six tools exactly as the server lists them, prompt caching on the system prompt, the tools and the growing conversation, at most {MAX_TOOL_CALLS} tool calls per question (then it must answer without tools), thinking turned off the way `/ask` does.",
        f"- **Tool server:** `{meta.get('server', 'python -m echr_mcp --transport stdio')}`, one process for the whole run, database `{meta.get('db', 'echr_m2')}` ({meta.get('docs', 98)} UK documents, snapshot). Embedder and reranker run locally.",
        f'- **`/ask`:** `rag.answer.answer(conn, {{"question": q}})` in-process, unchanged: router `{config.router_model()}`, answer `{config.answer_model()}`, claim check `{config.verify_model()}`.',
        f"- **Judge:** `{config.judge_model()}` with the existing `judge_support` rubric (unchanged), the same judge for both systems. It also judges the owner-review prose checks, one call per answer.",
        f"- **Questions:** the 10 owner-review questions (status: draft) × {n_owner['mcp']} samples with tools and × {n_owner['ask']} with `/ask` (or-10 is asked as a second turn after or-01 in the same conversation with tools; `/ask` is stateless, so it gets or-10 alone), and a fixed random retrieval subset of {n_subset} questions from `data/eval/questions.jsonl` × 1 (seed `{SUBSET_SEED}`; ids in `data/eval/agentic/subset.json`).",
        f"- **When:** {when[0][:10]} to {when[-1][:10]} (UTC). Raw per-answer results: `data/eval/agentic/results.jsonl`.",
        "",
        "How each number is computed:",
        "",
        "- *Claims*: the answer is split into sentences and bullets; a claim's citations are the paragraph ids it contains or the tool `cite` strings it contains (mapped through what the tools returned). `/ask` claims are its own claim list minus those its verifier marked unsupported (they are not in its answer text). A list introduced by a cited sentence inherits that citation.",
        "- *Citation accuracy, per claim*: `judge_support` scores each claim 1 / ½ / 0 against all its cited paragraphs together; mean over the claims that cite something, then mean over answers. *Per citation*: the share of (claim, citation) pairs that support the claim on their own. Claims with no citation are not sent to the judge; they are counted as *uncited claims*.",
        "- *Agentic recall* (subset only): share of the question's gold paragraphs (`expected_paragraph_ids`) among every paragraph id the model was shown. With tools: any paragraph id in any tool result (search hits, `get_paragraphs` including neighbours, operative provisions). For `/ask`: the paragraphs it put in its generation context.",
        "- *Verbatim-quote rate*: every double-quoted passage of four or more words in the answer, attributed to the paragraphs cited by its claim and checked with `check_quote`; a quote with no citation counts as not verbatim. Pooled over quotes.",
        '- *Shape checks*: the `checks` of `owner-review.jsonl`: deterministic ones in code, `judge` ones in one judge call; an answer passes if every applicable check passes. `tool_used count_cases` is met by `/ask` when it took its SQL stats route; `new_tool_calls` does not apply to `/ask`. `no_bare_yes_no` fails an answer whose first sentence starts with Yes or No and has no qualifier ("No, not as a general rule" passes; "No." fails).',
        "- *Cost*: model calls that produce the answer (tools: every Messages call, cache writes at the cache-write price; `/ask`: its `total_cost_usd`); judging is extra and not in these rows.",
        "",
        "## Side by side",
        "",
        *([PENDING_NOTE.format(reason=after_not_run), ""] if pending else []),
        *tables,
        "## Owner review, question by question",
        "",
        *per_question(rows, owner),
        *after_f1_section(both, owner, old, after_meta, after_spend, after_rows, pending),
        "## Transcripts (sample 1 of each, with tools)",
        "",
        *transcripts(rows, owner),
    ]
    if problems:
        out += ["## Skipped or failed", ""]
        out += [
            f"- {r['system']} {r['item_id']} sample {r['repeat']}: {r['status']}: {r.get('note', '')}"
            for r in problems
        ]
        out.append("")
    out += [
        "## Spend",
        *(spend_section(spend, cap) if spend or not old_spend(old) else old_spend(old)),
        "",
        "`cost_log` books cache writes at the plain input price; the per-question costs above use the cache-write price, so they run slightly higher than `cost_log`.",
        "",
        MARK.format("what-we-saw", "start"),
        kept(old, "what-we-saw").rstrip("\n"),
        MARK.format("what-we-saw", "end"),
        "",
        MARK.format("fairness-free", "start"),
        kept(old, "fairness-free").rstrip("\n"),
        MARK.format("fairness-free", "end"),
        "",
        MARK.format("decision", "start"),
        kept(old, "decision").rstrip("\n"),
        MARK.format("decision", "end"),
        "",
    ]
    return "\n".join(out)


def spend_since(conn, since: str) -> dict:
    cur = conn.execute(
        "SELECT purpose, count(*), coalesce(sum(tokens_in),0), coalesce(sum(tokens_out),0),"
        " coalesce(sum(tokens_cached),0), coalesce(sum(cost_usd),0) FROM cost_log"
        " WHERE timestamp > %s::timestamptz AND cost_usd > 0 GROUP BY purpose",
        (since,),
    )
    return {
        p: {"calls": c, "in": i, "out": o, "cached": k, "cost": float(usd_)}
        for p, c, i, o, k, usd_ in cur.fetchall()
    }


def write_report(
    rows: list[dict],
    path: Path,
    *,
    spend: dict | None = None,
    cap: float = 8.0,
    meta: dict | None = None,
    **extra,
) -> None:
    """`extra`: after, after_meta, after_spend, qrels, text_lookup (see `render`)."""
    old = path.read_text() if path.exists() else ""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render(rows, old=old, spend=spend, cap=cap, meta=meta, **extra))


__all__ = ["render", "spend_since", "write_report"]
