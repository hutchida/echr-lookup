"""G0b-fix: build the fixtures for the response schemas added after the first review of PR #2, plus the
SourceDocument fixture (a real decision with prototype-extracted inadmissibility grounds).

Run AFTER make_fixtures.py (it reads IngestRun.json, EvalRun.json and the bench outputs). No database needed.
Usage (from py/): uv run python ../scripts/g0b/make_fixtures_fix.py
"""

import json
import re
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path

from grounds_regex import extract
from proto_parse import parse_html

ROOT = Path(__file__).resolve().parents[2]
FIX = ROOT / "packages" / "contract" / "fixtures"
SNAP = ROOT / "data" / "snapshot"
BENCH = ROOT / "data" / "raw" / "g0b" / "bench"
manifest = {e["item_id"]: e for e in json.loads((SNAP / "manifest.json").read_text())}
SDOC_KEYS = [
    "item_id", "case_name", "application_numbers", "ecli", "doc_type", "chamber", "date", "articles",
    "outcome_raw", "outcome", "inadmissibility_grounds", "inadmissibility_grounds_source", "importance",
    "language", "source_url", "sha256", "data_source",
]  # fmt: skip
DEMO_DECISION = (
    "001-98645"  # Miah v UK (2010): manifestly ill-founded + incompatible ratione materiae
)


def load(name: str):
    return json.loads((FIX / f"{name}.json").read_text())


def write(name: str, obj) -> None:
    (FIX / f"{name}.json").write_text(json.dumps(obj, indent=2, ensure_ascii=False) + "\n")
    print("wrote", name)


def iso(ts: float) -> str:
    return datetime.fromtimestamp(ts, UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def main() -> None:
    # --- SourceDocument: a real decision, grounds extracted from its text by the regex prototype ---
    entry = dict(manifest[DEMO_DECISION])
    assert (
        entry["inadmissibility_grounds"] is None
    )  # HUDOC's conclusion is the bare word "Inadmissible"
    grounds = [g for g, _ in extract(SNAP / entry["path"])]
    assert grounds == ["manifestly_ill_founded", "incompatible_ratione_materiae"], grounds
    entry["inadmissibility_grounds"], entry["inadmissibility_grounds_source"] = grounds, "text"
    sdoc = {k: entry[k] for k in SDOC_KEYS}
    write("SourceDocument", sdoc)

    # --- CaseDetail: same decision, every paragraph in document order ---
    paras = parse_html(SNAP / entry["path"])
    write("CaseDetail", {
        "document": sdoc,
        "paragraphs": [
            {"id": f"{DEMO_DECISION}§{p['ref']}", "doc_id": DEMO_DECISION, "number": p["number"], "section": p["section"], "text": p["text"]}
            for p in paras
        ],
    })  # fmt: skip

    # --- ingest / eval lists (the prototype produced exactly one real run of each) ---
    ingest, evalrun = load("IngestRun"), load("EvalRun")
    write("IngestRunList", {"runs": [ingest]})
    summary = {k: v for k, v in evalrun.items() if k != "items"} | {
        "item_count": len(evalrun["items"])
    }
    write("EvalRunSummary", summary)
    write("EvalRunList", {"runs": [summary]})

    # --- costs: the four real embedding runs of the benchmark (local models: $0) ---
    emb = json.loads((BENCH / "embed.json").read_text())
    end = (BENCH / "embed.json").stat().st_mtime
    entries, t = [], end
    for i, r in reversed(list(enumerate(emb["runs"], 1))):
        short = r["model"].split("/")[1].replace("-en-v1.5", "")
        entries.append({
            "id": f"cost-g0b-embed-{i:03d}", "timestamp": iso(t), "model": r["model"], "purpose": "embed",
            "tokens_in": r["tokens"], "tokens_out": 0, "tokens_cached": 0, "cost_usd": 0.0,
            "latency_ms": round(r["seconds"] * 1000, 1), "request_id": f"bench-{short}-{r['strategy']}",
        })  # fmt: skip
        t -= r["seconds"]
    recent = entries  # newest first
    by_model: dict[str, dict] = {}
    for e in recent:
        m = by_model.setdefault(
            e["model"],
            {
                "model": e["model"],
                "calls": 0,
                "tokens_in": 0,
                "tokens_out": 0,
                "tokens_cached": 0,
                "cost_usd": 0.0,
            },
        )
        m["calls"] += 1
        m["tokens_in"] += e["tokens_in"]
    costs = {
        "total_usd": 0.0, "since": min(e["timestamp"] for e in recent),
        "by_purpose": [{"purpose": "embed", "calls": len(recent), "tokens_in": sum(e["tokens_in"] for e in recent), "tokens_out": 0, "tokens_cached": 0, "cost_usd": 0.0}],
        "by_model": list(by_model.values()), "recent": recent,
    }  # fmt: skip
    write("CostSummary", costs)

    # --- corpus stats: the 96 HTML documents the prototype ingested (legislation was not parsed) ---
    docs = [e for e in manifest.values() if e["format"] == "html"]
    pc = json.loads((BENCH / "parse_chunk.json").read_text())

    def buckets(keys) -> list[dict]:
        return [
            {"key": k, "count": n}
            for k, n in sorted(Counter(keys).items(), key=lambda kv: (-kv[1], str(kv[0])))
        ]

    def fold(code: str) -> str:
        m = re.match(r"P\d+-\d+|\d+", code)
        return m.group(0) if m else code

    by_article = Counter(a for e in docs for a in {fold(c) for c in e["articles"]})
    stats = {
        "data_source": "snapshot", "generated_at": iso((BENCH / "index.json").stat().st_mtime),
        "totals": {"documents": len(docs), "paragraphs": pc["parse"]["paragraphs_total"],
                   "chunks": {s: pc[s]["chunks"] for s in ("fixed", "recursive", "by_section")}},
        "by_doc_type": buckets(e["doc_type"] for e in docs),
        "by_outcome": buckets(e["outcome"] for e in docs),
        "by_chamber": buckets(e["chamber"] for e in docs),
        "by_article": [{"key": k, "count": n} for k, n in sorted(by_article.items(), key=lambda kv: (-kv[1], kv[0]))[:25]],
        "by_year": [{"key": k, "count": n} for k, n in sorted(Counter(e["date"][:4] for e in docs).items())],
        "last_ingest_run": ingest, "costs": costs, "latest_eval": summary,
    }  # fmt: skip
    write("CorpusStats", stats)

    # --- ApiError: what GET /case/{id} returns for an id that is not loaded ---
    assert "001-99999" not in manifest
    write("ApiError", {"error": "not_found", "detail": "No document with item_id '001-99999' in the loaded corpus (GET /stats shows what is loaded).",
                       "request_id": "req-g0b-fixture-not-found"})  # fmt: skip


if __name__ == "__main__":
    main()
