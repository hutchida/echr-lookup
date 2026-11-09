"""Build packages/contract/fixtures/*.json from REAL snapshot data (G0b). Throwaway generator, committed
so the fixtures are reproducible. Needs the g0b_bench schema from bench_index.py (KEEP=1).

Real: item IDs, paragraph text and quotes, chunk text and ids, hybrid-search scores/ranks (bm25 + bge-small
via pgvector, RRF k=60), snapshot counts, ingest/embed timings, eval recall numbers.
Illustrative (hand-written, NO LLM was called): answer prose, claim wording/status, token counts, step costs
(priced from config/model-prices.json).

Usage (from py/): uv run --group ml python ../scripts/g0b/make_fixtures.py
"""

import json
import os
import re
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

import psycopg

ROOT = Path(__file__).resolve().parents[2]
os.environ["HF_HOME"] = str(ROOT / "data" / "raw" / "g0b" / "hf")
os.environ["HF_HUB_OFFLINE"] = "1"
sys.path.insert(0, str(Path(__file__).parent))
from proto_parse import parse_html  # noqa: E402
from snapshot_ids import DECISIONS_IMMIGRATION_INADMISSIBLE  # noqa: E402

FIX = ROOT / "packages" / "contract" / "fixtures"
SNAP = ROOT / "data" / "snapshot"
BENCH = ROOT / "data" / "raw" / "g0b" / "bench"
DSN = os.environ.get("DATABASE_URL", "postgresql://echr:echr@localhost:5433/echr")
PRICES = json.loads((ROOT / "config" / "model-prices.json").read_text())["models"]
manifest = {e["item_id"]: e for e in json.loads((SNAP / "manifest.json").read_text())}
SDOC_KEYS = [
    "item_id",
    "case_name",
    "application_numbers",
    "ecli",
    "doc_type",
    "chamber",
    "date",
    "articles",
    "outcome_raw",
    "outcome",
    "importance",
    "language",
    "source_url",
    "sha256",
    "data_source",
]


def write(name: str, obj) -> None:
    (FIX / f"{name}.json").write_text(json.dumps(obj, indent=2, ensure_ascii=False) + "\n")
    print("wrote", name)


def paras(doc_id: str) -> dict[str, dict]:
    return {p["ref"]: p for p in parse_html(SNAP / manifest[doc_id]["path"])}


def pid(doc_id: str, ref: str) -> str:
    return f"{doc_id}§{ref}"


def quote(text: str, n: int = 280) -> str:
    if len(text) <= n:
        return text
    cut = text[:n].rsplit(" ", 1)[0]
    return cut


def citation(doc_id: str, ref: str, n: int = 280, needle: str | None = None) -> dict:
    p = paras(doc_id)[ref]
    text = p["text"][p["text"].index(needle) :] if needle else p["text"]
    q = quote(text, n)
    assert q in p["text"]
    return {
        "paragraph_id": pid(doc_id, ref),
        "doc_id": doc_id,
        "case_name": manifest[doc_id]["case_name"].title().replace(" V. ", " v. ")[:120],
        "quote": q,
        "link_target": f"/cases/{doc_id}#p{ref}",
    }


def cost(model: str, tin: int, tout: int, tcached: int = 0) -> float:
    p = PRICES[model]
    return round(
        (
            (tin - tcached) * p["input_per_mtok"]
            + tcached * p["cache_read_per_mtok"]
            + tout * p["output_per_mtok"]
        )
        / 1e6,
        6,
    )


# ---------------------------------------------------------------- real hybrid search
_model = None


def embed_query(q: str):
    global _model
    from sentence_transformers import SentenceTransformer

    if _model is None:
        _model = SentenceTransformer("BAAI/bge-small-en-v1.5", device="cpu")
    prefix = "Represent this sentence for searching relevant passages: "
    return (
        "["
        + ",".join(f"{x:.6f}" for x in _model.encode(prefix + q, normalize_embeddings=True))
        + "]"
    )


def passes(doc_id: str, f: dict | None) -> bool:
    if not f:
        return True
    m = manifest[doc_id]
    return (
        (not f.get("article") or f["article"] in m["articles"])
        and (not f.get("doc_types") or m["doc_type"] in f["doc_types"])
        and (not f.get("outcomes") or m["outcome"] in f["outcomes"])
        and (not f.get("date_from") or m["date"] >= f["date_from"])
        and (not f.get("date_to") or m["date"] <= f["date_to"])
    )


def hybrid(conn, query: str, k: int, filters: dict | None = None) -> dict:
    tbl = "g0b_bench.c_bge_small_en_v1_5_recursive"
    t0 = time.perf_counter()
    qv = embed_query(query)
    t1 = time.perf_counter()
    vec = conn.execute(
        f"SELECT id, doc_id, 1 - (embedding <=> %s::vector) FROM {tbl} ORDER BY embedding <=> %s::vector LIMIT 200",
        (qv, qv),
    ).fetchall()
    t2 = time.perf_counter()
    terms = " OR ".join(re.findall(r"[A-Za-z0-9]+", query))
    bm = conn.execute(
        f"SELECT id, doc_id, paradedb.score(id) FROM {tbl} WHERE text @@@ %s ORDER BY paradedb.score(id) DESC LIMIT 200",
        (terms,),
    ).fetchall()
    t3 = time.perf_counter()
    vec = [r for r in vec if passes(r[1], filters)][:50]
    bm = [r for r in bm if passes(r[1], filters)][:50]
    vr = {r[0]: (i, float(r[2])) for i, r in enumerate(vec, 1)}
    br = {r[0]: (i, float(r[2])) for i, r in enumerate(bm, 1)}
    rrf = {cid: sum(1 / (60 + d[cid][0]) for d in (vr, br) if cid in d) for cid in {*vr, *br}}
    order = sorted(rrf, key=lambda c: -rrf[c])
    t4 = time.perf_counter()
    chunks = {c["id"]: c for c in json.loads((BENCH / "chunks_recursive.json").read_text())}
    hits = []
    for rank, cid in enumerate(order[:k], 1):
        c = chunks[cid]
        pids = [pid(c["doc_id"], r) for r in c["paragraph_ids"]]
        hits.append(
            {
                "rank": rank,
                "case_name": manifest[c["doc_id"]]["case_name"],
                "chunk": {
                    "id": c["id"],
                    "doc_id": c["doc_id"],
                    "strategy": "recursive",
                    "text": c["text"],
                    "paragraph_ids": pids,
                    "token_count": c["token_count"],
                },
                "paragraph_ids": pids,
                "scores": {
                    "bm25_score": br[cid][1] if cid in br else None,
                    "bm25_rank": br[cid][0] if cid in br else None,
                    "vector_score": vr[cid][1] if cid in vr else None,
                    "vector_rank": vr[cid][0] if cid in vr else None,
                    "rrf_score": rrf[cid],
                    "rrf_rank": rank,
                    "rerank_score": None,
                    "rerank_rank": None,
                },
            }
        )
    return {
        "query": query,
        "mode": "hybrid",
        "chunking": "recursive",
        "k": k,
        "hits": hits,
        "timings_ms": {
            "bm25": round((t3 - t2) * 1000, 1),
            "vector": round((t2 - t1) * 1000, 1),
            "fuse": round((t4 - t3) * 1000, 2),
            "rerank": None,
            "total": round((t4 - t0) * 1000, 1),
        },
    }


def main() -> None:
    FIX.mkdir(parents=True, exist_ok=True)
    embed_query("warm up")  # exclude one-off model load from the search timings
    soering = manifest["001-57619"]
    # SourceDocument.json is written by make_fixtures_fix.py (a decision with text-extracted grounds)
    write("ManifestEntry", soering)
    p88 = paras("001-57619")["88"]
    write(
        "Paragraph",
        {
            "id": pid("001-57619", "88"),
            "doc_id": "001-57619",
            "number": 88,
            "section": p88["section"],
            "text": p88["text"],
        },
    )
    chunks = json.loads((BENCH / "chunks_recursive.json").read_text())
    ch = next(c for c in chunks if c["doc_id"] == "001-57619" and "88" in c["paragraph_ids"])
    write(
        "Chunk",
        {
            "id": ch["id"],
            "doc_id": ch["doc_id"],
            "strategy": "recursive",
            "text": ch["text"],
            "paragraph_ids": [pid("001-57619", r) for r in ch["paragraph_ids"]],
            "token_count": ch["token_count"],
        },
    )

    # --- ingest run: the prototype pass over the snapshot (parse + chunk + embed(bge-small) + index timings) ---
    pc = json.loads((BENCH / "parse_chunk.json").read_text())
    emb = json.loads((BENCH / "embed.json").read_text())
    idx = json.loads((BENCH / "index.json").read_text())
    log = [
        json.loads(line) for line in open(ROOT / "data" / "raw" / "g0b" / "hudoc-requests.jsonl")
    ]
    # Wall seconds the snapshot's HTML downloads took at the 1 req/s limiter: gap to the previous
    # request when that was <5 s earlier (same run), else the request's own duration.
    dl_s = 0.0
    for prev, r in zip([None, *log], log, strict=False):
        m = re.search(r"id=([0-9]{3}-[0-9]+)", r.get("url", ""))
        if r["tag"] == "snapshot-html" and r["status"] == 200 and m and m.group(1) in manifest:
            gap = r["t"] - prev["t"] if prev and r["t"] - prev["t"] < 5 else r["wall"]
            dl_s += gap
    dl_s = round(dl_s, 1)
    em = next(
        r
        for r in emb["runs"]
        if r["model"].endswith("small-en-v1.5") and r["strategy"] == "recursive"
    )
    ix = next(
        r for r in idx["runs"] if r["model"] == "bge-small-en-v1.5" and r["strategy"] == "recursive"
    )
    t_end = datetime.fromtimestamp((BENCH / "index.json").stat().st_mtime, UTC)
    total = (
        dl_s + pc["parse"]["total_s"] + pc["recursive"]["total_s"] + em["seconds"] + ix["total_s"]
    )
    t_start = datetime.fromtimestamp(t_end.timestamp() - total, UTC)
    write(
        "IngestRun",
        {
            "run_id": "g0b-prototype-snapshot",
            "data_source": "snapshot",
            "started_at": t_start.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "finished_at": t_end.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "stage_seconds": {
                "download": dl_s,
                "parse": round(pc["parse"]["total_s"], 3),
                "chunk": round(pc["recursive"]["total_s"], 3),
                "embed": round(em["seconds"], 2),
                "index": round(ix["total_s"], 2),
            },
            "counts": {
                "seen": pc["parse"]["docs"],
                "new": pc["parse"]["docs"],
                "changed": 0,
                "unchanged_skipped": 0,
                "failed": 0,
            },
            "embedder_model": "BAAI/bge-small-en-v1.5",
            "embedding_dim": 384,
        },
    )

    # --- search request / result (real hybrid retrieval on the bench index) ---
    q = "Can the UK extradite a person who faces the death row phenomenon?"
    filters = {
        "article": "3",
        "doc_types": ["judgment"],
        "outcomes": ["violation", "mixed"],
        "date_from": "1980-01-01",
        "date_to": "2000-12-31",
    }
    write(
        "SearchRequest",
        {"query": q, "mode": "hybrid", "chunking": "recursive", "k": 5, "filters": filters},
    )
    with psycopg.connect(DSN, autocommit=True) as conn:
        sr = hybrid(conn, q, 5, filters)
        write("SearchResult", sr)

        # --- eval: 2 retrieval-only items with expected paragraph ids verified by reading the text ---
        items = [
            {
                "id": "explain-001",
                "question": "Can the UK extradite a person who faces the death row phenomenon?",
                "type": "explain",
                "expected_paragraph_ids": ["001-57619§91", "001-57619§111"],
                "reference_notes": "Soering: extradition can engage Article 3 where there are substantial grounds to believe the person faces a real risk of inhuman or degrading treatment in the requesting state (§91), and exposure to the death row phenomenon in Virginia would breach it (§111).",
                "status": "reviewed",
                "tags": ["article-3", "extradition", "soering"],
            },
            {
                "id": "neutrality-001",
                "question": "Is a blanket ban on convicted prisoners voting compatible with the Convention?",
                "type": "neutrality",
                "expected_paragraph_ids": ["001-70442§82"],
                "reference_notes": "Hirst (No. 2) [GC]: a blanket ban applying automatically to all convicted prisoners is a 'blunt instrument' (§82); answer must state the Court's finding without taking a side on the policy.",
                "status": "draft",
                "tags": ["article-p1-3", "voting", "hirst", "neutrality"],
            },
        ]
        write("EvalItem", items[0])
        write(
            "EvalItem.stat",
            {
                "id": "stat-001",
                "question": "How many of the UK deportation or expulsion complaints in the snapshot were declared inadmissible?",
                "type": "stat",
                "expected_paragraph_ids": [],
                "reference_notes": "Counted from decision metadata: see Answer.stats fixture for the SQL shape and the snapshot count.",
                "status": "draft",
                "tags": ["count", "inadmissible", "deportation"],
            },
        )
        results, t_all0 = [], time.perf_counter()
        for it in items:
            t0 = time.perf_counter()
            res = hybrid(conn, it["question"], 10)
            got = [p for h in res["hits"] for p in h["paragraph_ids"]]

            # one entry per chunk: expected paragraph found within the first N chunks
            def recall(n: int) -> float:
                top = {p for h in res["hits"][:n] for p in h["paragraph_ids"]}
                return sum(e in top for e in it["expected_paragraph_ids"]) / len(
                    it["expected_paragraph_ids"]
                )

            first = next(
                (
                    i
                    for i, h in enumerate(res["hits"], 1)
                    if set(it["expected_paragraph_ids"]) & set(h["paragraph_ids"])
                ),
                None,
            )
            results.append(
                {
                    "item_id": it["id"],
                    "retrieved_paragraph_ids": list(dict.fromkeys(got))[:10],
                    "recall_at_5": recall(5),
                    "recall_at_10": recall(10),
                    "reciprocal_rank": (1 / first) if first else 0.0,
                    "faithfulness": None,
                    "citation_accuracy": None,
                    "neutrality": None,
                    "latency_ms": round((time.perf_counter() - t0) * 1000, 1),
                }
            )
        total_ms = (time.perf_counter() - t_all0) * 1000
    now = datetime.now(UTC)
    n = len(results)
    write(
        "EvalRun",
        {
            "run_id": "g0b-retrieval-only-demo",
            "started_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "finished_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "data_source": "snapshot",
            "config": {
                "chunking": "recursive",
                "mode": "hybrid",
                "rerank": False,
                "embedder_model": "BAAI/bge-small-en-v1.5",
                "generator_model": None,
                "judge_model": None,
            },
            "metrics": {
                "recall_at_5": sum(r["recall_at_5"] for r in results) / n,
                "recall_at_10": sum(r["recall_at_10"] for r in results) / n,
                "mrr": sum(r["reciprocal_rank"] for r in results) / n,
                "faithfulness": None,
                "citation_accuracy": None,
                "neutrality": None,
            },
            "items": results,
            "cost_usd": 0.0,
            "tokens_in": 0,
            "tokens_out": 0,
            "timings_ms": {"total": round(total_ms, 1), "mean_per_item": round(total_ms / n, 1)},
        },
    )

    # --- cost log: the real bge-small embed run (local model, so cost 0) ---
    write(
        "CostLogEntry",
        {
            "id": "cost-g0b-embed-001",
            "timestamp": t_end.strftime("%Y-%m-%dT%H:%M:%SZ"),
            "model": "BAAI/bge-small-en-v1.5",
            "purpose": "embed",
            "tokens_in": em["tokens"],
            "tokens_out": 0,
            "tokens_cached": 0,
            "cost_usd": 0.0,
            "latency_ms": round(em["seconds"] * 1000, 1),
            "request_id": "ingest-g0b-prototype-snapshot",
        },
    )

    # --- stats: snapshot counts (real) for the curated immigration-inadmissible decisions ---
    imm = [manifest[i] for i in DECISIONS_IMMIGRATION_INADMISSIBLE]
    by_art = {}
    for e in imm:
        for a in {x.split("-")[0] for x in e["articles"] if x.split("-")[0] in ("3", "5", "8")}:
            by_art[a] = by_art.get(a, 0) + 1
    rows = [[f"Article {a}", by_art[a]] for a in ("3", "8", "5")]
    refs = [("001-231646", "60"), ("001-223629", "16"), ("001-182755", "34")]
    cases = [citation(d, r) for d, r in refs]
    sql = (
        "SELECT 'Article ' || a AS article, count(DISTINCT d.item_id) AS decisions\n"
        "FROM documents d, unnest(d.articles) AS a\n"
        "WHERE d.doc_type = 'decision' AND d.outcome = 'inadmissible' AND a IN ('3', '8', '5')\n"
        "  AND d.item_id IN (SELECT doc_id FROM chunks WHERE text @@@ 'deportation OR expulsion OR removal OR extradition')\n"
        "GROUP BY a ORDER BY decisions DESC"
    )
    stats = {
        "question": "How many UK deportation or expulsion complaints in the snapshot were declared inadmissible, under which Articles?",
        "sql": sql,
        "columns": ["article", "decisions"],
        "rows": rows,
        "matching_cases": cases,
        "count": len(imm),
        "explanation": (
            f"{len(imm)} inadmissible Court decisions in the demo snapshot concern deportation, expulsion or extradition. "
            "A decision can raise several Articles, so the rows add up to more than the total. "
            "HUDOC metadata rarely says why a decision was inadmissible, so the reasons come from the decision text; three examples are cited."
        ),
    }
    write("StatsQueryResult", stats)

    # --- answers (illustrative prose over real paragraphs; no LLM call) ---
    c91, c111 = (
        citation("001-57619", "91"),
        citation("001-57619", "111", 300, needle="However, in the Court"),
    )
    sonnet = "claude-sonnet-5-5"
    haiku = "claude-haiku-5-5"
    steps = [
        {
            "step": "route",
            "model": haiku,
            "tokens_in": 410,
            "tokens_out": 12,
            "tokens_cached": 0,
            "cost_usd": cost(haiku, 410, 12),
            "latency_ms": 310.0,
        },
        {
            "step": "retrieve",
            "model": None,
            "tokens_in": 0,
            "tokens_out": 0,
            "tokens_cached": 0,
            "cost_usd": 0.0,
            "latency_ms": sr["timings_ms"]["total"],
        },
        {
            "step": "generate",
            "model": sonnet,
            "tokens_in": 3120,
            "tokens_out": 260,
            "tokens_cached": 1800,
            "cost_usd": cost(sonnet, 3120, 260, 1800),
            "latency_ms": 2850.0,
        },
        {
            "step": "verify",
            "model": haiku,
            "tokens_in": 1480,
            "tokens_out": 90,
            "tokens_cached": 0,
            "cost_usd": cost(haiku, 1480, 90),
            "latency_ms": 640.0,
        },
    ]
    write(
        "AnswerRequest",
        {
            "question": q,
            "options": {"chunking": "recursive", "mode": "hybrid", "k": 8, "route": "auto"},
        },
    )
    write(
        "Answer",
        {
            "request_id": "req-g0b-fixture-rag",
            "question": q,
            "route": "rag",
            "answer_text": (
                "Yes, but only within limits set by Article 3. In Soering v. the United Kingdom the Court held that extradition can itself engage "
                "the responsibility of the sending state where substantial grounds show a real risk of torture or inhuman or degrading treatment "
                "in the requesting country [001-57619§91]. Applying that test, it found that exposure to the 'death row phenomenon' in Virginia "
                "would breach Article 3 [001-57619§111]."
            ),
            "claims": [
                {
                    "id": "c1",
                    "text": "Extradition can engage the sending state's responsibility under Article 3 where there is a real risk of ill-treatment abroad.",
                    "citation_ids": ["001-57619§91"],
                    "status": "supported",
                    "reason": "Paragraph 91 states the test in these terms.",
                },
                {
                    "id": "c2",
                    "text": "The Court found the death row phenomenon in Virginia reached the Article 3 threshold.",
                    "citation_ids": ["001-57619§111"],
                    "status": "unverified",
                    "reason": "Fixture example: verifier has not checked this claim yet.",
                },
            ],
            "citations": [c91, c111],
            "stats": None,
            "refused_or_not_in_sources": False,
            "steps": steps,
            "total_cost_usd": round(sum(s["cost_usd"] for s in steps), 6),
            "total_latency_ms": round(sum(s["latency_ms"] for s in steps), 1),
            "models_used": [sonnet, haiku],
        },
    )
    stat_steps = [
        {
            "step": "route",
            "model": haiku,
            "tokens_in": 395,
            "tokens_out": 10,
            "tokens_cached": 0,
            "cost_usd": cost(haiku, 395, 10),
            "latency_ms": 290.0,
        },
        {
            "step": "generate",
            "model": sonnet,
            "tokens_in": 2200,
            "tokens_out": 180,
            "tokens_cached": 1800,
            "cost_usd": cost(sonnet, 2200, 180, 1800),
            "latency_ms": 1900.0,
        },
    ]
    write(
        "Answer.stats",
        {
            "request_id": "req-g0b-fixture-stats",
            "question": stats["question"],
            "route": "stats",
            "answer_text": (
                f"{len(imm)} decisions in the demo snapshot. {rows[0][0]} is raised in {rows[0][1]} of them and {rows[1][0]} in {rows[1][1]}. "
                "Most were rejected as manifestly ill-founded; a few for failure to exhaust domestic remedies."
            ),
            "claims": [
                {
                    "id": "c1",
                    "text": f"{len(imm)} inadmissible deportation/expulsion decisions are in the snapshot.",
                    "citation_ids": [c["paragraph_id"] for c in cases],
                    "status": "supported",
                    "reason": "Count comes straight from the SQL result.",
                }
            ],
            "citations": cases,
            "stats": stats,
            "refused_or_not_in_sources": False,
            "steps": stat_steps,
            "total_cost_usd": round(sum(s["cost_usd"] for s in stat_steps), 6),
            "total_latency_ms": round(sum(s["latency_ms"] for s in stat_steps), 1),
            "models_used": [sonnet, haiku],
        },
    )
    write(
        "Answer.refused",
        {
            "request_id": "req-g0b-fixture-refused",
            "question": "What is the Court's view on a UK exit from the Convention?",
            "route": "rag",
            "answer_text": "The indexed sources do not address whether the United Kingdom should remain a party to the Convention, so I cannot answer that from them.",
            "claims": [],
            "citations": [],
            "stats": None,
            "refused_or_not_in_sources": True,
            "steps": steps[:2],
            "total_cost_usd": round(sum(s["cost_usd"] for s in steps[:2]), 6),
            "total_latency_ms": round(sum(s["latency_ms"] for s in steps[:2]), 1),
            "models_used": [haiku],
        },
    )


if __name__ == "__main__":
    main()
