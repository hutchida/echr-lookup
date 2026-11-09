# ruff: noqa: E501 (prose strings)
"""Render eval results: docs/eval-results.md and the README section."""

from collections import defaultdict
from pathlib import Path

from rag.config import REPO_ROOT

from .runner import ConfigResult

START, END = "<!-- eval:start -->", "<!-- eval:end -->"
RESULTS_PATH = REPO_ROOT / "docs" / "eval-results.md"
README_PATH = REPO_ROOT / "README.md"


def _f(value: float | None, digits: int = 2) -> str:
    return "–" if value is None else f"{value:.{digits}f}"


def _secs(ms: float) -> str:
    return f"{ms / 1000:.1f} s"


def _label(r: ConfigResult) -> tuple[str, str]:
    c = r.run["config"]
    return c["chunking"], c["mode"] + (" ★" if r.run["config"]["generator_model"] else "")


def render_table(results: list[ConfigResult]) -> str:
    head = (
        "| Chunking | Mode | Recall@5 | Recall@10 | MRR | Case hit@10 | Faithfulness "
        "| Citation acc. | Neutrality | Stat acc. | Cost | Time |\n|---|---|---|---|---|---|---|---|---|---|---|---|\n"
    )
    rows = []
    for r in results:
        m = r.run["metrics"]
        chunking, mode = _label(r)
        rows.append(
            f"| {chunking} | {mode} | {_f(m['recall_at_5'])} | {_f(m['recall_at_10'])} "
            f"| {_f(m['mrr'])} | {_f(r.doc_hit_at_10)} | {_f(m['faithfulness'])} "
            f"| {_f(m['citation_accuracy'])} | {_f(m['neutrality'])} | {_f(r.stat_accuracy)} "
            f"| ${r.run['cost_usd']:.2f} "
            f"| {_secs(r.run['timings_ms']['total'])} |"
        )
    return head + "\n".join(rows)


def _avg(values: list[float]) -> float:
    return sum(values) / len(values)


def what_this_shows(results: list[ConfigResult]) -> str:
    """Plain-English reading of the numbers, built from the numbers (no hand-written claims)."""
    scored = [r for r in results if r.run["metrics"]["mrr"] is not None]
    if not scored:
        return "No retrieval results yet."
    by_cfg = {(r.run["config"]["chunking"], r.run["config"]["mode"]): r for r in scored}
    mrr = lambda r: r.run["metrics"]["mrr"]  # noqa: E731
    best, worst = max(scored, key=mrr), min(scored, key=mrr)
    out = [
        f"Across the {len(scored)} retrieval configs, the best first-hit quality (MRR) is "
        f"**{best.run['config']['chunking']} + {best.run['config']['mode']}** at {_f(mrr(best))}; "
        f"the weakest is {worst.run['config']['chunking']} + {worst.run['config']['mode']} "
        f"at {_f(mrr(worst))}. MRR of 1.0 would mean the expected paragraph is always the first hit."
    ]
    for key, name in (("mode", "search mode"), ("chunking", "chunking strategy")):
        groups: dict[str, list[float]] = defaultdict(list)
        for r in scored:
            groups[r.run["config"][key]].append(mrr(r))
        if len(groups) > 1:
            ranked = sorted(groups.items(), key=lambda kv: -_avg(kv[1]))
            out.append(
                f"By {name} (average MRR): "
                + ", ".join(f"{k} {_f(_avg(v))}" for k, v in ranked)
                + "."
            )
    doc = [r.doc_hit_at_10 for r in scored if r.doc_hit_at_10 is not None]
    if doc:
        out.append(
            f"Search usually finds the right *case*: on average {_f(_avg(doc))} of questions have a hit "
            "from the expected case in the top 10 (Case hit@10), while exact-paragraph recall@10 is "
            f"{_f(_avg([r.run['metrics']['recall_at_10'] for r in scored]))}. "
            "The gap is mostly neighbouring paragraphs of the right judgment, which the strict "
            "paragraph-level labels count as misses."
        )
    chunkings = sorted(
        {k[0] for k in by_cfg if all((k[0], m) in by_cfg for m in ("bm25", "vector", "hybrid"))}
    )
    if chunkings:

        def wins(metric: str) -> int:
            return sum(
                by_cfg[(c, "hybrid")].run["metrics"][metric]
                >= max(by_cfg[(c, m)].run["metrics"][metric] for m in ("bm25", "vector"))
                for c in chunkings
            )

        out.append(
            "Hybrid (BM25 and vector fused) matches or beats both BM25 and vector alone on recall@10 "
            f"in {wins('recall_at_10')} of {len(chunkings)} chunking strategies and on MRR in "
            f"{wins('mrr')} of {len(chunkings)}."
        )
    deltas = [
        mrr(by_cfg[(c, "hybrid_rerank")]) - mrr(by_cfg[(c, "hybrid")])
        for c in {k[0] for k in by_cfg}
        if (c, "hybrid_rerank") in by_cfg and (c, "hybrid") in by_cfg
    ]
    if deltas:
        d = _avg(deltas)
        verdict = "helps" if d > 0.01 else "hurts" if d < -0.01 else "makes little difference to"
        out.append(
            f"On average the reranker {verdict} MRR ({d:+.2f} against plain hybrid), "
            "at the price of the extra seconds shown in the Time column."
        )
    answered = [r for r in results if r.run["config"]["generator_model"]]
    for r in answered:
        m = r.run["metrics"]
        c = r.run["config"]
        out.append(
            f"Answer level ({c['chunking']} + {c['mode']}, {r.answered_items} questions): "
            f"faithfulness {_f(m['faithfulness'])} (share of claims the cited paragraphs support), "
            f"citation accuracy {_f(m['citation_accuracy'])}, neutrality pass rate "
            f"{_f(m['neutrality'])}, cost ${r.run['cost_usd']:.2f}."
            + (" The run stopped early at the cost limit." if r.truncated else "")
        )
    stat = [r for r in results if r.stat_accuracy is not None]
    if stat:
        out.append(
            "Counting questions answered with the exact expected number: "
            + ", ".join(
                f"{_f(r.stat_accuracy)} ({r.run['config']['chunking']} + {r.run['config']['mode']})"
                for r in stat
            )
            + "."
        )
    return "\n\n".join(out)


def render_results_md(
    results: list[ConfigResult], items: list[dict], *, generated_at: str, notes: list[str]
) -> str:
    kinds = defaultdict(int)
    for i in items:
        kinds[i["type"]] += 1
    drafts = sum(i["status"] == "draft" for i in items)
    stat_rows = [row for r in results for row in r.stat_rows]
    parts = [
        "# Evaluation results\n",
        f"Generated by `pnpm eval:snapshot` at {generated_at}. Source: snapshot corpus.\n",
        f"Question set: {len(items)} questions in `data/eval/questions.jsonl` "
        f"({kinds['explain']} explain, {kinds['stat']} stat, {kinds['neutrality']} neutrality); "
        f"**{drafts} of {len(items)} are still `draft`**, so treat the numbers as provisional "
        "until Dan has reviewed the expected paragraphs.\n",
        "## Results\n",
        render_table(results),
        "\n★ = answer-level config: the model wrote cited answers and the judge scored them. "
        "Retrieval columns are over explain and neutrality questions (stat questions have no "
        "expected paragraphs). `–` = not measured for that row. Cost and time are for that row "
        "alone (retrieval-only rows cost $0).\n",
        "## What this shows\n",
        what_this_shows(results) + "\n",
    ]
    if stat_rows:
        parts += [
            "## Counting questions\n",
            "Each row is one answer to a counting question. A mismatch is not always a wrong answer: "
            "it can be a different reading of the question (for example whether 'inadmissible' "
            "includes partly inadmissible decisions) or a real SQL mistake; check the SQL in `/ask`.\n",
            "| Question | Expected | Got | Route | Correct |\n|---|---|---|---|---|",
            *[
                f"| {r['question']} | {r['expected']} | {r['got'] if r['got'] is not None else '–'} "
                f"| {r['route']} | {'yes' if r['ok'] else 'no'} |"
                for r in stat_rows
            ],
            "",
        ]
    parts += ["## How to read the table\n", HOW_TO_READ]
    if notes:
        parts += ["## Notes for this run\n", *[f"- {n}" for n in notes], ""]
    return "\n".join(parts) + "\n"


HOW_TO_READ = """- **Recall@5 / Recall@10**: of the paragraphs we expect an answer to rest on, what share appear in
  the top 5 / top 10 hits. A hit "covers" every paragraph in its `paragraph_ids`.
- **Case hit@10**: share of questions where any top-10 hit comes from the right case, even if it is
  a neighbouring paragraph. Much looser than recall; the gap between the two shows how often search
  finds the right case but not the exact paragraph.
- **MRR** (mean reciprocal rank): 1 / the position of the first hit containing an expected paragraph,
  averaged over questions (1.0 = always first, 0.5 = typically second, 0 = never found in the top 10).
- **Faithfulness**: an LLM judge scores each claim 1 / 0.5 / 0 by whether its cited paragraphs
  support it; the number is the mean.
- **Citation accuracy**: share of cited paragraphs the judge says support their claim.
- **Neutrality**: share of neutrality questions whose answer is balanced and gives no opinion.
- **Stat acc.**: share of counting questions whose count equals the expected number.
"""


def render_readme_section(results: list[ConfigResult]) -> str:
    head = (
        "| Chunking | Mode | R@5 | R@10 | MRR | Faith. | Cite acc. | Neutral | Stat |\n"
        "|---|---|---|---|---|---|---|---|---|\n"
    )
    rows = []
    for r in results:
        m, (chunking, mode) = r.run["metrics"], _label(r)
        rows.append(
            f"| {chunking} | {mode} | {_f(m['recall_at_5'])} | {_f(m['recall_at_10'])} "
            f"| {_f(m['mrr'])} | {_f(m['faithfulness'])} | {_f(m['citation_accuracy'])} "
            f"| {_f(m['neutrality'])} | {_f(r.stat_accuracy)} |"
        )
    return (
        head
        + "\n".join(rows)
        + "\n\n★ = answer-level. Details, cost and what it shows: [docs/eval-results.md]"
        "(docs/eval-results.md). Question set is still in draft.\n"
    )


def replace_between_markers(text: str, body: str) -> str:
    start, end = text.find(START), text.find(END)
    if start < 0 or end < start:
        raise ValueError(f"README is missing the {START} / {END} markers")
    return text[: start + len(START)] + "\n" + body + text[end:]


def write_outputs(
    results: list[ConfigResult],
    items: list[dict],
    *,
    generated_at: str,
    notes: list[str],
    results_path: Path = RESULTS_PATH,
    readme_path: Path = README_PATH,
) -> None:
    results_path.write_text(
        render_results_md(results, items, generated_at=generated_at, notes=notes), encoding="utf-8"
    )
    readme = readme_path.read_text(encoding="utf-8")
    readme_path.write_text(
        replace_between_markers(readme, render_readme_section(results)), encoding="utf-8"
    )
