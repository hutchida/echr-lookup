# ruff: noqa: E501 (prose in the generated doc)
"""Step 6/4b output: docs/eval-judging.md, generated from the saved judgments so the numbers in the
doc are always the numbers in data/eval/judgments/."""

import json
import statistics
from datetime import UTC, datetime

from rag.config import REPO_ROOT
from rag.eval.items import load_questions

from . import analysis
from . import pool as pool_mod
from .budget import REQUEST_PREFIX
from .common import JUDGMENTS_DIR, POOL_PATH, RETRIEVAL_PATH, read_jsonl, run_path
from .grader import load_run
from .qrels import build_qrels, load_qrels, write_qrels
from .rescore import rescore

DOC_PATH = REPO_ROOT / "docs" / "eval-judging.md"
META_PATH = JUDGMENTS_DIR / "meta.json"


def fmt(x: float | None, nd: int = 2) -> str:
    return "n/a" if x is None else f"{x:.{nd}f}"


def pct(x: float | None) -> str:
    return "n/a" if x is None else f"{x * 100:.0f}%"


def spend_from_db() -> dict:
    from rag.index import connect

    with connect() as conn:
        row = conn.execute(
            "SELECT coalesce(sum(cost_usd), 0), count(*), coalesce(sum(tokens_in), 0), "
            "coalesce(sum(tokens_out), 0), coalesce(sum(tokens_cached), 0) "
            "FROM cost_log WHERE request_id LIKE %s",
            (REQUEST_PREFIX + "%",),
        ).fetchone()
    return {"usd": float(row[0]), "calls": row[1], "tokens_in": row[2], "tokens_out": row[3],
            "tokens_cached": row[4]}  # fmt: skip


def comparison_table(res: dict) -> str:
    head = (
        "| Config | R@5 orig | R@5 v2 | R@10 orig | R@10 v2 | MRR orig | MRR v2 "
        "| nDCG@10 orig | nDCG@10 v2 |\n|---|---|---|---|---|---|---|---|---|\n"
    )
    rows = []
    for t in res["table"]:
        o, v = t["original"], t["v2"]
        rows.append(
            f"| {t['config']} | {fmt(o['recall_at_5'])} | {fmt(v['recall_at_5'])} "
            f"| {fmt(o['recall_at_10'])} | {fmt(v['recall_at_10'])} "
            f"| {fmt(o['mrr'])} | {fmt(v['mrr'])} "
            f"| {fmt(o['ndcg_at_10'])} | {fmt(v['ndcg_at_10'])} |"
        )
    return head + "\n".join(rows)


def movement_statement(res: dict) -> str:
    t = res["table"]

    def avg(side: str, key: str) -> float:
        return sum(r[side][key] for r in t) / len(t)

    best_o = max(t, key=lambda r: r["original"]["recall_at_10"])
    best_v = max(t, key=lambda r: r["v2"]["recall_at_10"])
    d5 = avg("v2", "recall_at_5") - avg("original", "recall_at_5")
    d10 = avg("v2", "recall_at_10") - avg("original", "recall_at_10")
    dm = avg("v2", "mrr") - avg("original", "mrr")
    direction = "rose" if d10 > 0.02 else "fell" if d10 < -0.02 else "barely moved"
    return (
        f"Averaged over the 12 configs, recall@5 went from {avg('original', 'recall_at_5'):.2f} "
        f"to {avg('v2', 'recall_at_5'):.2f}, recall@10 from {avg('original', 'recall_at_10'):.2f} "
        f"to {avg('v2', 'recall_at_10'):.2f} and MRR from {avg('original', 'mrr'):.2f} to "
        f"{avg('v2', 'mrr'):.2f} ({d5:+.2f}, {d10:+.2f}, {dm:+.2f}). Scores {direction} under "
        f"the wider key. Best recall@10 on the original key: {best_o['config']} "
        f"{best_o['original']['recall_at_10']:.2f} (v2 {best_o['v2']['recall_at_10']:.2f}); best on "
        f"v2: {best_v['config']} {best_v['v2']['recall_at_10']:.2f} (original "
        f"{best_v['original']['recall_at_10']:.2f}). Best recall@5 original: "
        f"{max(r['original']['recall_at_5'] for r in t):.2f}; v2: "
        f"{max(r['v2']['recall_at_5'] for r in t):.2f}."
    )


def review_section(items: list[dict]) -> str:
    labels = {
        "gold_graded_0": "Original gold, judge says 0",
        "added_gold": "Judge says 2, not in the original key",
        "flipped": "Grade changed between run 1 and run 2",
    }
    out = []
    for n, it in enumerate(items, start=1):
        other = (
            f" Run 2: grade {it['other_run_grade']}: {it['other_run_reason']}"
            if it["other_run_grade"] is not None
            else ""
        )
        quote = it["quote"].replace("\n", " ")
        out.append(
            f"**{n}. {labels[it['category']]}** ({it['question_id']}, `{it['paragraph_id']}`, "
            f"{it['case_name']}, {it['section']})\n\n"
            f"- Question: {it['question']}\n"
            f'- Paragraph: "{quote}"\n'
            f"- Run 1 grade {it['grade']}: {it['reason']}{other}\n"
        )
    return "\n".join(out)


def write_report() -> int:
    items = load_questions()
    pool = read_jsonl(POOL_PATH)
    run1, run2 = load_run(run_path(1)), load_run(run_path(2))
    rows = build_qrels(run1, pool)
    write_qrels(rows)
    qrels = load_qrels()
    res = rescore(items, read_jsonl(RETRIEVAL_PATH), qrels)
    (JUDGMENTS_DIR / "rescore.json").write_text(json.dumps(res, indent=1) + "\n")
    tables = analysis.grade_tables(pool, run1)
    pairs = analysis.paired_grades(run1, run2)
    agree = analysis.agreement(pairs)
    review = analysis.review_list(pool, run1, run2)
    (JUDGMENTS_DIR / "review-list.json").write_text(json.dumps(review, indent=1) + "\n")
    meta = json.loads(META_PATH.read_text()) if META_PATH.exists() else {}
    spend = spend_from_db()
    meta["spend"] = spend
    META_PATH.write_text(json.dumps(meta, indent=2, sort_keys=True) + "\n")
    sizes = pool_mod.pool_sizes(pool)
    ran = [q for q in pool if q["question_id"] in run1]
    sizes_judged = pool_mod.pool_sizes(ran)
    failures = [(q, r) for q, r in run1.items() if not r["ok"]]
    failures2 = [(q, r) for q, r in run2.items() if not r["ok"]]
    judge_model = next((r["model"] for r in run1.values()), "vertex-ai-claude-opus-4.8")
    seed = next((r["seed"] for r in run1.values()), None)
    seed2 = next((r["seed"] for r in run2.values()), None)
    secs = {k: meta.get(k, {}).get("seconds") for k in ("pool", "judge_run1", "judge_run2")}
    top_n = meta.get("judge_run1", {}).get("top_n")
    orig_fixed = next(t for t in res["table"] if t["config"] == "fixed/hybrid_rerank")["original"]
    orig_bm25 = next(t for t in res["table"] if t["config"] == "fixed/bm25")["original"]
    orig_median_h = statistics.median(len(q["gold_ids"]) for q in pool if q["question_id"] in run1)
    v2_median_h = statistics.median(sum(g == 2 for g in qr.values()) for qr in qrels.values())
    added_h = tables["gold_added"]
    mismatches = analysis.reason_mismatches(pool, run1)
    n_two = tables["grade_counts"][2]
    flips = [p for p in pairs if p["g1"] != p["g2"]]
    attempts = [a for r in list(run1.values()) + list(run2.values()) for a in r["attempts"]]
    unreported = sum(1 for a in attempts if a.get("cost_source") == "unreported")
    list_estimate = (
        spend["tokens_in"] * 5.0 + spend["tokens_cached"] * 0.5 + spend["tokens_out"] * 25.0
    ) / 1e6
    orig_per_q = [len(q["gold_ids"]) for q in pool if q["question_id"] in run1]
    v2_per_q = [sum(g == 2 for g in qr.values()) for qr in qrels.values()]
    orig_median, v2_median = statistics.median(orig_per_q), statistics.median(v2_per_q)
    v2_min, v2_max = min(v2_per_q), max(v2_per_q)
    gold_added_share = tables["gold_added"] / max(tables["gold_total"], 1)

    doc = f"""# Relevance judging: is the answer key too narrow?

Generated by `python -m rag.eval.judging report` on {datetime.now(UTC).strftime("%Y-%m-%d %H:%M UTC")}.
Data: `data/eval/judgments/`. Plain-English background: `docs/learn/relevance-judging.md`.

## Did the scores move?

{movement_statement(res)}

The original key (`data/eval/questions.jsonl`) was not changed. "v2" is a second, graded key
(`data/eval/judgments/qrels-v2.jsonl`) built from the grades of an AI judge: {judge_model}, served by a LiteLLM gateway (the Anthropic key's monthly limit was reached, and Opus 5.5 is not on the proxy). It is a different model from the Sonnet 5.5 agent that wrote the original key, but both are Claude models, so a shared family bias is possible. A run with a GPT-5.x model through the same proxy would be the next independence check; it was not run. v2 gold = paragraphs graded 2.
Treat v2 as a better estimate, not as ground truth: see "Review list" for what a human should check.

How to read the movement: v2 is a much wider key (median {v2_median_h:g} grade-2 paragraphs per question against {orig_median_h:g} originally; {added_h} added gold paragraphs), so part of the rise in recall and most of the rise in MRR is simply that there are more right answers to hit. One thing argues it is not only a generous judge: recall still rises although its denominator grew several-fold, so the extra paragraphs are being retrieved. Two things argue for caution: the judge is a Claude model like the key's author, and it graded about one paragraph in nine as a direct answer. Whatever the exact size of the effect, the original key was too narrow to be used as the only measure.

## Comparison: original key vs v2

{res["v2_questions"]} of {res["table"][0]["original"]["n_recall_at_5"]} retrieval questions have a v2 key.
Questions with no grade-2 paragraph have no v2 gold, so they leave the v2 recall and MRR means:
{len(res["v2_no_gold"])} question(s){(": " + ", ".join(res["v2_no_gold"])) if res["v2_no_gold"] else ""}.
v2 recall/MRR therefore average over {res["table"][0]["v2"]["n_recall_at_5"]} questions; v2 nDCG@10 over
{res["table"][0]["v2"]["n_ndcg_at_10"]} (every question with any paragraph graded above 0). Unjudged (failed)
questions: {len(res["unjudged"])}.

{comparison_table(res)}

Metric definitions (code: `py/rag/eval/judging/metrics.py`):

- recall@k and MRR: as in `rag.eval.metrics` (a hit covers all the paragraphs of its chunk), only the gold set differs: original = the key's `expected_paragraph_ids`; v2 = paragraphs graded 2.
- nDCG@10: graded gain `2^grade - 1` (grade 0 = 0, grade 1 = 1, grade 2 = 3). Ranking = de-duplicated paragraph ids of the hits in rank order, cut at 10 paragraphs. DCG = sum of gain / log2(rank + 1); nDCG = DCG / DCG of the ideal order of the graded paragraphs. For the original key every gold paragraph has grade 1 (gain 1), so the two columns are on the same scale. A paragraph nobody graded counts as 0.
- Sanity check: the original-key numbers for the fixed chunking reproduce the known baseline (hybrid_rerank recall@5 {fmt(orig_fixed["recall_at_5"])}, recall@10 {fmt(orig_fixed["recall_at_10"])}, MRR {fmt(orig_fixed["mrr"])}; bm25 recall@5 {fmt(orig_bm25["recall_at_5"])}).
- The 12 stat/counting questions have no paragraph key and are not part of any number here.

## What the judge said about the original key

Judged questions: {tables["questions_judged"]}; paragraphs graded: {tables["paragraphs"]}
(grade 0: {tables["grade_counts"][0]}, grade 1: {tables["grade_counts"][1]}, grade 2: {tables["grade_counts"][2]}).

| | count |
|---|---|
| Original gold paragraphs (judged questions) | {tables["gold_total"]} |
| Confirmed (graded 2) | {tables["gold_confirmed"]} |
| Disputed: original gold graded 1 (context, not an answer on its own) | {tables["gold_disputed_1"]} |
| Disputed: original gold graded 0 (not relevant) | {tables["gold_disputed_0"]} |
| Gold added: graded 2 but not in the original key | {tables["gold_added"]} (in {tables["questions_with_added"]} questions; {gold_added_share:.1f}x the original gold count) |
| Gold per question: original / v2 (grade 2) | median {orig_median:g} / {v2_median:g} (v2 min {v2_min}, max {v2_max}) |

## Judge consistency (run 2)

Re-judged {agree["questions"]} questions chosen at random (seed {seed2}), same pool, paragraphs reshuffled, same prompt. Run 1 grades are used for qrels v2.

- Exact-grade agreement per paragraph: {pct(agree["exact"])} ({agree["paragraphs"]} paragraphs); Cohen's kappa (grades 0/1/2): {fmt(agree["kappa"])}.
- Agreement on "grade 2 or not": {pct(agree["two_vs_not"])}; kappa {fmt(agree["kappa_two_vs_not"])}.
- Grades that changed: {agree["changed"]} ({agree["changed_by_two"]} of them jumped between 0 and 2). Summary below.

{flips_table(flips, run1, run2, pool)}

## Judge failures

- Run 1: {len(failures)} of {len(run1)} judged questions failed validation after one retry{(": " + ", ".join(q for q, _ in failures)) if failures else ""}. Failed questions have no v2 key and are excluded from the v2 means (never filled in).
- Run 2: {len(failures2)} of {len(run2)}{(": " + ", ".join(q for q, _ in failures2)) if failures2 else ""}.
- Reason/paragraph check (free, run 1): {len(mismatches)} of {n_two} grade-2 paragraphs have a reason sharing no content word with the paragraph text{(": " + ", ".join(f"{m['question_id']} `{m['paragraph_id']}`" for m in mismatches)) if mismatches else ""}. This is a smoke alarm for a reason attached to the wrong paragraph, not a proof of alignment. The two 0 <-> 2 jumps between runs (see above) were of this kind: in run 1 the judge's reason did not describe the paragraph it was filed under (run 2 got both right), so the judge is not perfectly careful over ~100-paragraph lists. At ~0.1% of paragraphs this does not move the table, but it is why a human should spot-check.
- Retries used (a first reply that failed validation but the second passed): {sum(1 for r in list(run1.values()) + list(run2.values()) if r["ok"] and len(r["attempts"]) > 1)}.

## Review list for a human spot-check

{len(review)} items, chosen by a fixed rule (no randomness): up to 4 original-gold paragraphs the judge graded 0 (the judge may be wrong, or the key may be), up to 4 paragraphs graded 2 that were not original gold (the added gold), and up to 2 grade flips between the runs (largest jumps first). Within each group one item per question first, preferring paragraphs found by the most configs; any shortfall is filled from the other groups. Quotes are verbatim, trimmed to 600 characters. Also saved as `data/eval/judgments/review-list.json`.

{review_section(review)}

## Pool

- Questions pooled: {sizes["questions"]}; paragraphs in pools: {sizes["total"]} (per question min {sizes["min"]} / median {sizes["median"]:g} / max {sizes["max"]}).
- Pool = every paragraph in the `paragraph_ids` of the top-10 hits of all 12 configs (3 chunkings x bm25/vector/hybrid/hybrid_rerank) plus the original gold. `pool.jsonl` records, per paragraph, which configs found it and the best hit rank; the judge never saw that, nor which paragraphs were gold.
- Pool cap applied when judging: {"none" if not top_n else f"top {top_n} paragraphs per question by number of configs that found it (all original gold always kept); judged pool per question min {sizes_judged['min']} / median {sizes_judged['median']:g} / max {sizes_judged['max']}"}.

## Cost and time

- **Measured (reported by the proxy per call, logged to `cost_log`):** {spend["calls"]} calls under `request_id LIKE 'relevance-%'` (includes one smoke call), {spend["tokens_in"]:,} uncached input tokens, {spend["tokens_cached"]:,} cached input tokens, {spend["tokens_out"]:,} output tokens, **${spend["usd"]:.2f}** from the proxy's `x-litellm-response-cost` header. Calls without a reported cost: {unreported} (their cost is recorded as 0 and is therefore missing from the total). Query: `SELECT sum(cost_usd), count(*), sum(tokens_in), sum(tokens_out) FROM cost_log WHERE request_id LIKE 'relevance-%'`. Running ledger: `data/eval/judgments/spend.log`.
- **Estimated (list price, not a bill):** {spend["tokens_in"]:,} in x $5/Mtok + {spend["tokens_cached"]:,} cached x $0.5/Mtok + {spend["tokens_out"]:,} out x $25/Mtok = **${list_estimate:.2f}**. The proxy's measured cost was about 10% above this list price in the smoke test (26 in / 9 out tokens billed $0.000391 vs $0.000355 list).
- No spend cap was applied (the proxy route has none, by Dan's decision); `--soft-limit USD` exists and is unit-tested (`budget.py`). The earlier $8 cap was dropped when the judge moved from the Anthropic API to the proxy.
- Wall time: pooling {secs["pool"]} s (search is local and free), run 1 {secs["judge_run1"]} s, run 2 {secs["judge_run2"]} s.
- Judge: {judge_model}, seed {seed} (shuffle seed per run, question: `random.Random("seed:run:question")`), `max_tokens` 16000, no temperature parameter (the proxy rejects 0), via the LiteLLM proxy (`litellm_client.py`), purpose `judge`.

## Reproduce

```sh
cd py
uv run --group ml python -m rag.eval.judging pool        # free: search + pool.jsonl, retrieval.jsonl
uv run --group ml python -m rag.eval.judging preflight   # free: projected spend
uv run --group ml python -m rag.eval.judging judge       # paid, resumable, run 1
uv run --group ml python -m rag.eval.judging recheck     # paid, resumable, run 2 (15 questions)
uv run --group ml python -m rag.eval.judging rescore     # free: qrels-v2.jsonl + table on screen
uv run --group ml python -m rag.eval.judging report      # free: rewrites this file
```

Files in `data/eval/judgments/`: `retrieval.jsonl` (top-10 hit lists per question and config), `pool.jsonl`, `judgments-run1.jsonl` / `judgments-run2.jsonl` (raw replies, alias order, grades with reasons), `qrels-v2.jsonl`, `rescore.json`, `review-list.json`, `meta.json`.
"""
    DOC_PATH.write_text(doc, encoding="utf-8")
    print(f"Wrote {DOC_PATH}")
    return 0


def flips_table(flips: list[dict], run1: dict, run2: dict, pool: list[dict]) -> str:
    """A run 1 x run 2 count table of the changes, plus every 0 <-> 2 jump listed in full (the
    complete list of changed paragraphs is derivable from the two judgments files)."""
    if not flips:
        return "No grade changed between the two runs."
    counts: dict[tuple[int, int], int] = {}
    for p in flips:
        counts[(p["g1"], p["g2"])] = counts.get((p["g1"], p["g2"]), 0) + 1
    lines = ["| Run 1 grade -> run 2 grade | paragraphs |", "|---|---|"]
    for (a, b), n in sorted(counts.items()):
        lines.append(f"| {a} -> {b} | {n} |")
    big = [p for p in flips if abs(p["g1"] - p["g2"]) == 2]
    lines.append("")
    lines.append(
        "Jumps of two grades (0 <-> 2): "
        + (", ".join(f"{p['question_id']} `{p['paragraph_id']}` ({p['g1']}->{p['g2']})" for p in big)
           if big else "none")
        + ". Every changed paragraph is in `judgments-run1.jsonl` vs `judgments-run2.jsonl`."
    )  # fmt: skip
    return "\n".join(lines)
