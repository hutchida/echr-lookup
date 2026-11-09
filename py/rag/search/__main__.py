"""`python -m rag.search "<query>" --mode hybrid --chunking recursive -k 10` (pnpm search)."""

import argparse
import json
import sys
import textwrap

from rag.index import connect
from rag.search.core import MODES, STRATEGIES, search

SHORT = {
    "bm25": ("bm25_score", "bm25_rank"),
    "vec": ("vector_score", "vector_rank"),
    "rrf": ("rrf_score", "rrf_rank"),
    "rerank": ("rerank_score", "rerank_rank"),
}


def _cell(scores: dict, keys: tuple[str, str], digits: int) -> str:
    score, rank = scores[keys[0]], scores[keys[1]]
    return "-" if score is None else f"{score:.{digits}f} #{rank}"


def _paras(ids: list[str]) -> str:
    refs = [i.split("§", 1)[1] for i in ids]
    return "§" + (",".join(refs) if len(refs) <= 3 else f"{refs[0]}..{refs[-1]}({len(refs)})")


def render(result: dict, snippet: int = 80) -> str:
    ran = [
        name
        for name, (score_key, _) in SHORT.items()
        if any(h["scores"][score_key] is not None for h in result["hits"])
    ]
    header = ["#", "case", "paragraphs", *ran, "snippet"]
    rows = []
    for h in result["hits"]:
        text = " ".join(h["chunk"]["text"].split())
        rows.append(
            [
                str(h["rank"]),
                h["case_name"].replace(" v. THE UNITED KINGDOM", " v UK")[:34],
                _paras(h["paragraph_ids"]),
                *[_cell(h["scores"], SHORT[n], 2 if n == "bm25" else 4) for n in ran],
                textwrap.shorten(text, snippet, placeholder="…"),
            ]
        )
    widths = [max(len(r[i]) for r in [header, *rows]) for i in range(len(header) - 1)]
    lines = []
    for r in [header, *rows]:
        lines.append("  ".join(c.ljust(w) for c, w in zip(r, widths, strict=False)) + "  " + r[-1])
    t = result["timings_ms"]
    timing = "  ".join(f"{k}={v:.1f}ms" for k, v in t.items() if v is not None)
    head = f"mode={result['mode']} chunking={result['chunking']} k={result['k']}  ({timing})"
    return head + "\n" + "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="rag.search", description="Search the indexed ECHR corpus.")
    ap.add_argument("query")
    ap.add_argument("--mode", choices=MODES, default="hybrid")
    ap.add_argument("--chunking", choices=STRATEGIES, default="recursive")
    ap.add_argument("-k", type=int, default=10)
    ap.add_argument("--article", help="HUDOC article code, e.g. 3 or P1-3")
    ap.add_argument("--doc-type", action="append", dest="doc_types")
    ap.add_argument("--outcome", action="append", dest="outcomes")
    ap.add_argument("--date-from")
    ap.add_argument("--date-to")
    ap.add_argument("--json", action="store_true", help="print the raw SearchResult JSON")
    args = ap.parse_args(argv)

    filters = {
        k: v
        for k, v in {
            "article": args.article,
            "doc_types": args.doc_types,
            "outcomes": args.outcomes,
            "date_from": args.date_from,
            "date_to": args.date_to,
        }.items()
        if v
    }
    request = {"query": args.query, "mode": args.mode, "chunking": args.chunking, "k": args.k}
    if filters:
        request["filters"] = filters
    with connect() as conn:
        result = search(conn, request)
    print(json.dumps(result, indent=1) if args.json else render(result))
    return 0


if __name__ == "__main__":
    sys.exit(main())
