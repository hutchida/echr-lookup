"""search(): SearchRequest dict -> SearchResult dict, in four modes."""

import time
import uuid

from rag import config
from rag.index import Embedder, get_embedder, log_cost
from rag.search.fusion import RRF_K, rrf
from rag.search.rerank import get_reranker
from rag.search.retrieval import TOP_N, bm25_search, vector_search

MODES = ("bm25", "vector", "hybrid", "hybrid_rerank")
STRATEGIES = ("fixed", "recursive", "by_section")
MAX_HITS = 50
RERANK_TOP = 30
SCORE_KEYS = (
    "bm25_score",
    "bm25_rank",
    "vector_score",
    "vector_rank",
    "rrf_score",
    "rrf_rank",
    "rerank_score",
    "rerank_rank",
)


def _ms(t0: float) -> float:
    return round((time.perf_counter() - t0) * 1000, 3)


def _check(request: dict) -> None:
    if not str(request.get("query", "")).strip():
        raise ValueError("query must not be empty")
    if request.get("mode") not in MODES:
        raise ValueError(f"mode must be one of {MODES}")
    if request.get("chunking") not in STRATEGIES:
        raise ValueError(f"chunking must be one of {STRATEGIES}")
    if not isinstance(request.get("k"), int) or not 1 <= request["k"] <= MAX_HITS:
        raise ValueError(f"k must be an integer from 1 to {MAX_HITS}")


def _hit(row: dict, scores: dict, rank: int) -> dict:
    return {
        "rank": rank,
        "case_name": row["case_name"],
        "chunk": {
            "id": row["chunk_id"],
            "doc_id": row["doc_id"],
            "strategy": row["strategy"],
            "text": row["text"],
            "paragraph_ids": list(row["paragraph_ids"]),
            "token_count": row["token_count"],
        },
        # Cite every paragraph the chunk covers: safe, and chunks are only a few paragraphs long.
        "paragraph_ids": list(row["paragraph_ids"]),
        "scores": scores,
    }


def search(conn, request: dict, *, embedder: Embedder | None = None, reranker=None) -> dict:
    """Run one search. Fills every score/rank for the methods that ran and null for the rest.

    - bm25: top 50 by BM25 score. vector: top 50 by cosine similarity.
    - hybrid: Reciprocal Rank Fusion (k=60) of those two lists.
    - hybrid_rerank: hybrid, then a cross-encoder re-scores the top 30 fused chunks. If
      rag.config.rerank_enabled() is false and no reranker is passed, this degrades to hybrid
      (rerank fields stay null) instead of loading the cross-encoder.
    The query embedding and any rerank are logged to cost_log. Hits are capped at 50."""
    _check(request)
    t_start = time.perf_counter()
    query, mode, strategy, k = (request[x] for x in ("query", "mode", "chunking", "k"))
    filters = request.get("filters") or None
    request_id = f"search-{uuid.uuid4().hex[:12]}"
    timings: dict[str, float | None] = {"bm25": None, "vector": None, "fuse": None, "rerank": None}

    rows: dict[str, dict] = {}
    scores: dict[str, dict] = {}

    def score_of(chunk_id: str) -> dict:
        return scores.setdefault(chunk_id, dict.fromkeys(SCORE_KEYS))

    bm25_ids: list[str] = []
    vector_ids: list[str] = []
    if mode in ("bm25", "hybrid", "hybrid_rerank"):
        t0 = time.perf_counter()
        for rank, r in enumerate(bm25_search(conn, query, strategy, filters, TOP_N), start=1):
            rows[r["chunk_id"]] = r
            s = score_of(r["chunk_id"])
            s["bm25_score"], s["bm25_rank"] = float(r["score"]), rank
            bm25_ids.append(r["chunk_id"])
        timings["bm25"] = _ms(t0)
    if mode in ("vector", "hybrid", "hybrid_rerank"):
        embedder = embedder or get_embedder()
        t0 = time.perf_counter()
        qvec = embedder.embed_query(query)
        embed_ms = _ms(t0)
        for rank, r in enumerate(vector_search(conn, qvec, strategy, filters, TOP_N), start=1):
            rows.setdefault(r["chunk_id"], r)
            s = score_of(r["chunk_id"])
            s["vector_score"], s["vector_rank"] = float(r["score"]), rank
            vector_ids.append(r["chunk_id"])
        timings["vector"] = _ms(t0)  # includes embedding the query
        log_cost(
            conn,
            model=embedder.model_name,
            purpose="embed",
            tokens_in=embedder.count_tokens(query),
            tokens_out=0,
            tokens_cached=0,
            latency_ms=embed_ms,
            request_id=request_id,
        )

    if mode == "bm25":
        order = bm25_ids
    elif mode == "vector":
        order = vector_ids
    else:
        t0 = time.perf_counter()
        fused = rrf([bm25_ids, vector_ids], RRF_K)
        for rank, (cid, value) in enumerate(fused, start=1):
            s = score_of(cid)
            s["rrf_score"], s["rrf_rank"] = value, rank
        order = [cid for cid, _ in fused]
        timings["fuse"] = _ms(t0)

    if mode == "hybrid_rerank" and (reranker is not None or config.rerank_enabled()):
        reranker = reranker or get_reranker()
        head, tail = order[:RERANK_TOP], order[RERANK_TOP:]
        t0 = time.perf_counter()
        texts = [rows[c]["text"] for c in head]
        values = reranker.score(query, texts)
        timings["rerank"] = _ms(t0)
        ranked = sorted(zip(head, values, strict=True), key=lambda p: (-p[1], head.index(p[0])))
        for rank, (cid, value) in enumerate(ranked, start=1):
            s = score_of(cid)
            s["rerank_score"], s["rerank_rank"] = float(value), rank
        order = [cid for cid, _ in ranked] + tail
        log_cost(
            conn,
            model=reranker.model_name,
            purpose="rerank",
            tokens_in=reranker.count_tokens(query, texts),
            tokens_out=0,
            tokens_cached=0,
            latency_ms=timings["rerank"],
            request_id=request_id,
        )

    hits = [_hit(rows[cid], scores[cid], i) for i, cid in enumerate(order[:k], start=1)]
    timings["total"] = _ms(t_start)
    return {
        "query": query,
        "mode": mode,
        "chunking": strategy,
        "k": k,
        "hits": hits,
        "timings_ms": timings,
    }
