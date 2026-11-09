"""Index the snapshot chunks into scratch schema g0b_bench (regular tables, BM25 + HNSW), time it,
then run the 10-query quality check. Drops the schema at the end unless KEEP=1.

Usage: uv run --group ml python ../scripts/g0b/bench_index.py
"""

import json
import os
import re
import sys
import time
from pathlib import Path

import numpy as np
import psycopg

ROOT = Path(__file__).resolve().parents[2]
os.environ["HF_HOME"] = str(ROOT / "data" / "raw" / "g0b" / "hf")
os.environ["HF_HUB_OFFLINE"] = "1"
BENCH = ROOT / "data" / "raw" / "g0b" / "bench"
SCHEMA = "g0b_bench"
DSN = os.environ.get("DATABASE_URL", "postgresql://echr:echr@localhost:5433/echr")
KEEP = os.environ.get("KEEP") == "1"
sys.path.insert(0, str(Path(__file__).parent))
from queries import QUERIES  # noqa: E402

RUNS = [
    ("bge-small-en-v1.5", "recursive", 384),
    ("bge-small-en-v1.5", "fixed", 384),
    ("bge-small-en-v1.5", "by_section", 384),
    ("bge-base-en-v1.5", "recursive", 768),
]


def vec_literal(v: np.ndarray) -> str:
    return "[" + ",".join(f"{x:.6f}" for x in v) + "]"


def main() -> None:
    results: dict = {"runs": [], "quality": []}
    with psycopg.connect(DSN, autocommit=True) as conn:
        conn.execute(f"DROP SCHEMA IF EXISTS {SCHEMA} CASCADE")
        conn.execute(f"CREATE SCHEMA {SCHEMA}")
        for short, strat, dim in RUNS:
            chunks = json.loads((BENCH / f"chunks_{strat}.json").read_text())
            emb = np.load(BENCH / f"emb_{short}_{strat}.npy")
            tbl = f"{SCHEMA}.c_{short.replace('-', '_').replace('.', '_')}_{strat}"
            conn.execute(
                f"CREATE TABLE {tbl} (id text PRIMARY KEY, doc_id text NOT NULL, strategy text NOT NULL, "
                f"text text NOT NULL, paragraph_ids text[] NOT NULL, embedding vector({dim}) NOT NULL)"
            )
            t0 = time.perf_counter()
            with (
                conn.cursor() as cur,
                cur.copy(
                    f"COPY {tbl} (id, doc_id, strategy, text, paragraph_ids, embedding) FROM STDIN"
                ) as cp,
            ):
                for c, v in zip(chunks, emb, strict=True):
                    cp.write_row(
                        (
                            c["id"],
                            c["doc_id"],
                            c["strategy"],
                            c["text"],
                            c["paragraph_ids"],
                            vec_literal(v),
                        )
                    )
            t_insert = time.perf_counter() - t0
            t0 = time.perf_counter()
            conn.execute(
                f"CREATE INDEX {tbl.split('.')[1]}_bm25 ON {tbl} USING bm25 (id, text) WITH (key_field='id')"
            )
            t_bm25 = time.perf_counter() - t0
            t0 = time.perf_counter()
            conn.execute(
                f"CREATE INDEX {tbl.split('.')[1]}_hnsw ON {tbl} USING hnsw (embedding vector_cosine_ops)"
            )
            t_hnsw = time.perf_counter() - t0
            conn.execute(f"ANALYZE {tbl}")
            size = conn.execute(f"SELECT pg_total_relation_size('{tbl}')").fetchone()[0]
            run = {
                "model": short,
                "strategy": strat,
                "rows": len(chunks),
                "insert_s": t_insert,
                "bm25_index_s": t_bm25,
                "hnsw_index_s": t_hnsw,
                "table_plus_indexes_mb": size / 2**20,
                "total_s": t_insert + t_bm25 + t_hnsw,
                "docs": len({c["doc_id"] for c in chunks}),
            }
            results["runs"].append(run)
            print(
                {k: (round(v, 3) if isinstance(v, float) else v) for k, v in run.items()},
                flush=True,
            )

        # --- quality check: 10 hand-written queries, is an expected case in the top 5 chunks? ---
        from sentence_transformers import SentenceTransformer

        prefix = "Represent this sentence for searching relevant passages: "
        for short, strat, dim in [r for r in RUNS if r[1] == "recursive"]:
            tbl = f"{SCHEMA}.c_{short.replace('-', '_').replace('.', '_')}_{strat}"
            model = SentenceTransformer(f"BAAI/{short}", device="cpu")
            for qi, (q, expected) in enumerate(QUERIES):
                qv = vec_literal(model.encode(prefix + q, normalize_embeddings=True))
                vec = conn.execute(
                    f"SELECT id, doc_id FROM {tbl} ORDER BY embedding <=> %s::vector LIMIT 50",
                    (qv,),
                ).fetchall()
                terms = " OR ".join(re.findall(r"[A-Za-z0-9]+", q))
                bm = conn.execute(
                    f"SELECT id, doc_id FROM {tbl} WHERE text @@@ %s ORDER BY paradedb.score(id) DESC LIMIT 50",
                    (terms,),
                ).fetchall()
                # reciprocal rank fusion, k=60
                score: dict[str, float] = {}
                doc_of = {}
                for lst in (vec, bm):
                    for r, (cid, did) in enumerate(lst, 1):
                        score[cid] = score.get(cid, 0) + 1 / (60 + r)
                        doc_of[cid] = did
                hyb = [(cid, doc_of[cid]) for cid, _ in sorted(score.items(), key=lambda x: -x[1])][
                    :50
                ]
                for mode, lst in (("vector", vec), ("bm25", bm), ("hybrid", hyb)):
                    docs_top5 = []
                    for _, did in lst:
                        if did not in docs_top5:
                            docs_top5.append(did)
                    chunk_top5 = [did for _, did in lst[:5]]
                    first = next((i for i, (_, did) in enumerate(lst, 1) if did in expected), None)
                    results["quality"].append(
                        {
                            "model": short,
                            "mode": mode,
                            "q": qi,
                            "hit_top5_chunks": any(d in expected for d in chunk_top5),
                            "first_expected_chunk_rank": first,
                        }
                    )
        if not KEEP:
            conn.execute(f"DROP SCHEMA {SCHEMA} CASCADE")
    (BENCH / "index.json").write_text(json.dumps(results, indent=1))
    from collections import defaultdict

    agg: dict = defaultdict(list)
    for r in results["quality"]:
        agg[(r["model"], r["mode"])].append(r["first_expected_chunk_rank"])
    summary = {}
    for (model, mode), ranks in sorted(agg.items()):
        n = len(ranks)
        summary[f"{model}/{mode}"] = {
            "hit@1": sum(1 for r in ranks if r and r <= 1),
            "hit@3": sum(1 for r in ranks if r and r <= 3),
            "hit@5": sum(1 for r in ranks if r and r <= 5),
            "mrr": sum(1 / r for r in ranks if r) / n,
            "ranks": ranks,
        }
        print(model, mode, summary[f"{model}/{mode}"])
    results["summary"] = summary
    (BENCH / "index.json").write_text(json.dumps(results, indent=1))


if __name__ == "__main__":
    main()
