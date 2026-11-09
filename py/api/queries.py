"""SQL -> contract-shaped dicts. Column names equal the contract field names (interfaces §3)."""

from datetime import UTC, date, datetime
from typing import Any

import psycopg

from rag.config import data_source

STRATEGIES = ("fixed", "recursive", "by_section")
LIST_LIMIT = 50  # LIMITS.listRunsMax
COST_RECENT = 100  # LIMITS.costRecentMax
TOP_ARTICLES = 25  # LIMITS.statsArticleBucketsMax

DOCUMENT_COLUMNS = (
    "item_id, case_name, application_numbers, ecli, doc_type, chamber, date, articles, "
    "outcome_raw, outcome, inadmissibility_grounds, inadmissibility_grounds_source, importance, "
    "language, source_url, sha256, data_source"
)


def iso(value: datetime) -> str:
    """UTC, trailing Z, milliseconds only when present (the contract's IsoDateTime)."""
    value = value.astimezone(UTC)
    if value.microsecond:
        return value.isoformat(timespec="milliseconds").replace("+00:00", "Z")
    return value.strftime("%Y-%m-%dT%H:%M:%SZ")


def now_iso() -> str:
    return iso(datetime.now(UTC))


def _num(value: Any) -> float:
    return float(value) if value is not None else 0.0


def get_case(conn: psycopg.Connection, item_id: str) -> dict | None:
    row = conn.execute(
        f"SELECT {DOCUMENT_COLUMNS} FROM documents WHERE item_id = %s", (item_id,)
    ).fetchone()
    if row is None:
        return None
    names = [n.strip() for n in DOCUMENT_COLUMNS.split(",")]
    document = dict(zip(names, row, strict=True))
    if isinstance(document["date"], date):
        document["date"] = document["date"].isoformat()
    paragraphs = conn.execute(
        "SELECT id, doc_id, number, section, text FROM paragraphs WHERE doc_id = %s "
        "ORDER BY position",
        (item_id,),
    ).fetchall()
    return {
        "document": document,
        "paragraphs": [
            {"id": r[0], "doc_id": r[1], "number": r[2], "section": r[3], "text": r[4]}
            for r in paragraphs
        ],
    }


def ingest_runs(conn: psycopg.Connection, limit: int = LIST_LIMIT) -> list[dict]:
    rows = conn.execute(
        "SELECT payload FROM ingest_runs ORDER BY started_at DESC, run_id LIMIT %s", (limit,)
    ).fetchall()
    return [r[0] for r in rows]


def eval_summary(payload: dict) -> dict:
    summary = {k: v for k, v in payload.items() if k != "items"}
    summary["item_count"] = len(payload.get("items", []))
    return summary


def eval_runs(conn: psycopg.Connection, limit: int = LIST_LIMIT) -> list[dict]:
    rows = conn.execute(
        "SELECT payload FROM eval_runs ORDER BY created_at DESC, run_id LIMIT %s", (limit,)
    ).fetchall()
    return [eval_summary(r[0]) for r in rows]


def eval_run(conn: psycopg.Connection, run_id: str) -> dict | None:
    row = conn.execute("SELECT payload FROM eval_runs WHERE run_id = %s", (run_id,)).fetchone()
    return row[0] if row else None


def cost_summary(conn: psycopg.Connection) -> dict:
    total, since = conn.execute(
        "SELECT COALESCE(sum(cost_usd), 0), min(timestamp) FROM cost_log"
    ).fetchone()
    usage = "count(*), sum(tokens_in), sum(tokens_out), sum(tokens_cached), sum(cost_usd)"

    def usage_dict(row: tuple) -> dict:
        calls, t_in, t_out, t_cached, cost = row
        return {
            "calls": int(calls),
            "tokens_in": int(t_in or 0),
            "tokens_out": int(t_out or 0),
            "tokens_cached": int(t_cached or 0),
            "cost_usd": _num(cost),
        }

    by_purpose = [
        {"purpose": r[0], **usage_dict(r[1:])}
        for r in conn.execute(
            f"SELECT purpose, {usage} FROM cost_log GROUP BY purpose "
            "ORDER BY sum(cost_usd) DESC, purpose"
        ).fetchall()
    ]
    by_model = [
        {"model": r[0], **usage_dict(r[1:])}
        for r in conn.execute(
            f"SELECT model, {usage} FROM cost_log GROUP BY model ORDER BY sum(cost_usd) DESC, model"
        ).fetchall()
    ]
    recent = [
        {
            "id": r[0],
            "timestamp": iso(r[1]),
            "model": r[2],
            "purpose": r[3],
            "tokens_in": r[4],
            "tokens_out": r[5],
            "tokens_cached": r[6],
            "cost_usd": _num(r[7]),
            "latency_ms": _num(r[8]),
            "request_id": r[9],
        }
        for r in conn.execute(
            "SELECT id, timestamp, model, purpose, tokens_in, tokens_out, tokens_cached, "
            "cost_usd, latency_ms, request_id FROM cost_log "
            "ORDER BY timestamp DESC, id DESC LIMIT %s",
            (COST_RECENT,),
        ).fetchall()
    ]
    return {
        "total_usd": _num(total),
        "since": iso(since) if since else None,
        "by_purpose": by_purpose,
        "by_model": by_model,
        "recent": recent,
    }


def _buckets(conn: psycopg.Connection, sql: str) -> list[dict]:
    return [{"key": r[0], "count": r[1]} for r in conn.execute(sql).fetchall()]


# Folds sub-paragraphs: 8-1 -> 8, 14+8 -> 14, 35-3-a -> 35; protocol codes keep their article
# (P1-3, P1-3-1 -> P1-3).
_ARTICLE_KEY = r"substring(a from '^(P[0-9]+-[0-9]+|[^-+]+)')"


def corpus_stats(conn: psycopg.Connection) -> dict:
    documents = conn.execute("SELECT count(*) FROM documents").fetchone()[0]
    paragraphs = conn.execute("SELECT count(*) FROM paragraphs").fetchone()[0]
    chunk_counts = dict(conn.execute("SELECT strategy, count(*) FROM chunks GROUP BY strategy"))
    runs = ingest_runs(conn, 1)
    latest = eval_runs(conn, 1)
    return {
        "data_source": data_source(),
        "generated_at": now_iso(),
        "totals": {
            "documents": documents,
            "paragraphs": paragraphs,
            "chunks": {s: chunk_counts.get(s, 0) for s in STRATEGIES},
        },
        "by_doc_type": _buckets(
            conn, "SELECT doc_type, count(*) FROM documents GROUP BY 1 ORDER BY 2 DESC, 1"
        ),
        "by_outcome": _buckets(
            conn, "SELECT outcome, count(*) FROM documents GROUP BY 1 ORDER BY 2 DESC, 1"
        ),
        "by_chamber": _buckets(
            conn,
            "SELECT chamber, count(*) FROM documents GROUP BY 1 ORDER BY 2 DESC, 1 NULLS LAST",
        ),
        "by_article": _buckets(
            conn,
            f"SELECT key, count(DISTINCT item_id) FROM "
            f"(SELECT item_id, {_ARTICLE_KEY} AS key FROM documents, unnest(articles) a) t "
            f"WHERE key IS NOT NULL GROUP BY key ORDER BY 2 DESC, 1 LIMIT {TOP_ARTICLES}",
        ),
        "by_year": _buckets(
            conn,
            "SELECT extract(year FROM date)::int::text, count(*) FROM documents "
            "GROUP BY 1 ORDER BY 1",
        ),
        "last_ingest_run": runs[0] if runs else None,
        "costs": cost_summary(conn),
        "latest_eval": latest[0] if latest else None,
    }
