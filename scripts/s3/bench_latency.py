"""DEV ONLY: warm p50/p95 latency of the four search modes over 10 queries against DATABASE_URL.

Usage (from py/):  uv run --group ml python ../scripts/s3/bench_latency.py
Reports the one-off model load time separately, then runs each query once as a warm-up
(not measured) and once measured. Latency is the wall time of search(), cost logging included.
"""

import statistics as st
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "py"))

from rag.index import connect, get_embedder  # noqa: E402
from rag.search import get_reranker, search  # noqa: E402

QUERIES = [
    "Soering",
    "extradition to face death row",
    "Does the Convention stop the UK deporting criminals?",
    "How has Article 8 been applied in UK immigration cases?",
    "prisoners voting ban general election",
    "inadmissible manifestly ill-founded deportation",
    "right to family life and removal of a settled migrant",
    "diplomatic assurances torture risk Article 3",
    "Hirst v United Kingdom",
    "indefinite detention of foreign terrorism suspects",
]
MODES = ("bm25", "vector", "hybrid", "hybrid_rerank")


def main() -> None:
    t0 = time.perf_counter()
    embedder = get_embedder()
    t_embedder = time.perf_counter() - t0
    t0 = time.perf_counter()
    reranker = get_reranker()
    t_reranker = time.perf_counter() - t0
    print(f"model load (one-off): embedder {t_embedder:.2f}s, reranker {t_reranker:.2f}s")
    with connect() as conn:
        n = conn.execute("SELECT count(*) FROM chunks WHERE strategy = 'recursive'").fetchone()[0]
        print(f"recursive chunks in database: {n}")
        for mode in MODES:
            times = []
            for q in QUERIES:
                req = {"query": q, "mode": mode, "chunking": "recursive", "k": 10}
                search(conn, req, embedder=embedder, reranker=reranker)  # warm-up
                t0 = time.perf_counter()
                search(conn, req, embedder=embedder, reranker=reranker)
                times.append((time.perf_counter() - t0) * 1000)
            times.sort()
            print(
                f"{mode:14s} p50 {st.median(times):7.1f} ms   max {times[-1]:7.1f} ms   "
                f"min {times[0]:7.1f} ms"
            )


if __name__ == "__main__":
    main()
