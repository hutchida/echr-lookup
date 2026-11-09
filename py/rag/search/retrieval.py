"""The two retrievers. Both join `documents` and apply the metadata filters INSIDE the query, so
each returns up to N rows that already satisfy the filters (never "top N, then filter")."""

import re

from rag.index.store import vector_literal

TOP_N = 50
_TERM = re.compile(r"[a-z0-9]+")
_STOPWORDS = frozenset(
    {"a", "an", "and", "are", "as", "at", "be", "by", "for", "from", "has", "have", "in", "is"}
    | {"it", "its", "of", "on", "or", "that", "the", "to", "was", "were", "what", "which", "who"}
    | {"with", "does", "do", "did", "can", "could", "how"}
)

_COLUMNS = (
    "c.id AS chunk_id, c.doc_id, c.strategy, c.text, c.paragraph_ids, c.token_count, d.case_name"
)


def bm25_query_string(query: str) -> str | None:
    """User text -> a safe pg_search query string: lowercase words OR-ed together, so operators
    and punctuation in the question can never be parsed as query syntax."""
    terms = list(dict.fromkeys(_TERM.findall(query.lower())))
    useful = [t for t in terms if t not in _STOPWORDS] or terms
    return " OR ".join(useful) if useful else None


def filter_sql(filters: dict | None) -> tuple[str, list]:
    """Filters -> (' AND ...' fragment over alias `d`, params)."""
    if not filters:
        return "", []
    parts: list[str] = []
    params: list = []
    if filters.get("article"):
        article = filters["article"]
        like = re.sub(r"([\\%_])", r"\\\1", article) + "-%"
        parts.append("EXISTS (SELECT 1 FROM unnest(d.articles) a WHERE a = %s OR a LIKE %s)")
        params += [article, like]
    if filters.get("doc_types"):
        parts.append("d.doc_type = ANY(%s)")
        params.append(list(filters["doc_types"]))
    if filters.get("outcomes"):
        parts.append("d.outcome = ANY(%s)")
        params.append(list(filters["outcomes"]))
    if filters.get("date_from"):
        parts.append("d.date >= %s")
        params.append(filters["date_from"])
    if filters.get("date_to"):
        parts.append("d.date <= %s")
        params.append(filters["date_to"])
    return "".join(f" AND {p}" for p in parts), params


def _rows(cur) -> list[dict]:
    names = [d.name for d in cur.description]
    return [dict(zip(names, r, strict=True)) for r in cur.fetchall()]


def bm25_search(
    conn, query: str, strategy: str, filters: dict | None, n: int = TOP_N
) -> list[dict]:
    """Top n chunks by BM25 (`paradedb.score`). Each row has `score`."""
    q = bm25_query_string(query)
    if q is None:
        return []
    where, params = filter_sql(filters)
    cur = conn.execute(
        f"SELECT {_COLUMNS}, paradedb.score(c.id) AS score "
        "FROM chunks c JOIN documents d ON d.item_id = c.doc_id "
        f"WHERE c.text @@@ %s AND c.strategy = %s{where} "
        "ORDER BY score DESC, c.id LIMIT %s",
        [q, strategy, *params, n],
    )
    return _rows(cur)


def vector_search(
    conn, query_vector: list[float], strategy: str, filters: dict | None, n: int = TOP_N
) -> list[dict]:
    """Top n chunks by cosine similarity. Each row has `score` (1 - cosine distance).

    HNSW is approximate and filters can starve it, so the scan is made iterative (pgvector 0.8):
    it keeps walking the graph until n rows pass the filters."""
    where, params = filter_sql(filters)
    vec = vector_literal(query_vector)
    with conn.transaction():
        conn.execute("SELECT set_config('hnsw.ef_search', '100', true)")
        conn.execute("SELECT set_config('hnsw.iterative_scan', 'strict_order', true)")
        cur = conn.execute(
            f"SELECT {_COLUMNS}, 1 - (c.embedding <=> %s::vector) AS score "
            "FROM chunks c JOIN documents d ON d.item_id = c.doc_id "
            f"WHERE c.strategy = %s AND c.embedding IS NOT NULL{where} "
            "ORDER BY c.embedding <=> %s::vector, c.id LIMIT %s",
            [vec, strategy, *params, vec, n],
        )
        return _rows(cur)
