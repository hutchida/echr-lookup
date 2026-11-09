# ruff: noqa: E501
"""`python -m rag.answer "<question>"` (pnpm ask): print the answer, citations, route, SQL and cost."""

from __future__ import annotations

import argparse
import json
import textwrap
import time

from rag import config, index
from rag.answer import answer
from rag.search import get_reranker

BADGES = {
    "supported": "[✓ supported]",
    "unsupported": "[✗ unsupported]",
    "unverified": "[? unverified]",
}


def _wrap(text: str, indent: str = "  ") -> str:
    """Wrap each line of `text` separately, so paragraph and group-heading breaks survive."""
    return "\n".join(
        textwrap.fill(line, width=100, initial_indent=indent, subsequent_indent=indent)
        if line.strip()
        else ""
        for line in text.split("\n")
    )


def render(a: dict) -> str:
    out = [f"Route: {a['route']}", "", "ANSWER", _wrap(a["answer_text"])]
    if a["refused_or_not_in_sources"]:
        out.append("  (the sources provided don't answer this)")
    if a["claims"]:
        out += ["", "CLAIMS"]
        for c in a["claims"]:
            ids = ", ".join(c["citation_ids"]) or "no valid citation"
            label = " (short answer)" if c.get("role") == "short_answer" else ""
            label += f" [{c['group']}]" if c.get("group") else ""
            out.append(f"  {c['id']} {BADGES[c['status']]}{label} {c['text']}")
            out.append(f"       cites: {ids}; {c['reason']}")
    if a["citations"]:
        out += ["", "CITATIONS"]
        for c in a["citations"]:
            out.append(f"  {c['paragraph_id']}  {c['case_name']}  {c['link_target']}")
            out.append(_wrap(f"“{c['quote']}”", "      "))
    if a["stats"]:
        s = a["stats"]
        out += ["", "SQL", textwrap.indent(s["sql"], "  "), "", f"ROWS (count = {s['count']})"]
        out.append("  " + " | ".join(s["columns"]))
        out += ["  " + " | ".join(str(v) for v in row) for row in s["rows"]]
        out += ["", "EXPLANATION", _wrap(s["explanation"])]
    out += ["", "STEPS"]
    for st in a["steps"]:
        out.append(
            f"  {st['step']:<9} {st['model'] or '-':<20} in {st['tokens_in']:>6} out {st['tokens_out']:>5}"
            f" cached {st['tokens_cached']:>6}  ${st['cost_usd']:.5f}  {st['latency_ms']:>8.0f} ms"
        )
    out.append(
        f"TOTAL ${a['total_cost_usd']:.5f}  {a['total_latency_ms']:.0f} ms  models: "
        + ", ".join(a["models_used"])
    )
    return "\n".join(out)


def main() -> None:
    p = argparse.ArgumentParser(prog="python -m rag.answer", description=__doc__)
    p.add_argument("question")
    p.add_argument("--mode", choices=["bm25", "vector", "hybrid", "hybrid_rerank"])
    p.add_argument("--chunking", choices=["fixed", "recursive", "by_section"])
    p.add_argument("-k", type=int)
    p.add_argument("--route", choices=["auto", "rag", "stats"], default="auto")
    p.add_argument("--json", action="store_true", help="print the raw Answer JSON")
    args = p.parse_args()
    options = {"route": args.route}
    for key, value in (("mode", args.mode), ("chunking", args.chunking), ("k", args.k)):
        if value is not None:
            options[key] = value
    load_started = time.perf_counter()
    embedder = index.get_embedder()
    reranker = None
    if config.rerank_enabled() and args.mode in (None, "hybrid_rerank"):
        reranker = get_reranker()
    # Models load (and run once) here, as the API does at startup, so the printed latency is the
    # warm per-request latency.
    embedder.embed_query("warm up")
    if reranker:
        reranker.score("warm up", ["warm up"])
    warm_s = time.perf_counter() - load_started
    with index.connect() as conn:
        result = answer(
            conn,
            {"question": args.question, "options": options},
            embedder=embedder,
            reranker=reranker,
        )
    print(json.dumps(result, indent=2, ensure_ascii=False) if args.json else render(result))
    if not args.json:
        print(f"(models loaded and warmed once in {warm_s:.1f} s; the API does this at startup)")


if __name__ == "__main__":
    main()
