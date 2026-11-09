"""Writes: documents, paragraphs, chunks (with embeddings) and ingest runs. Each call commits."""

from psycopg.types.json import Jsonb

_DOC_COLUMNS = (
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
    "inadmissibility_grounds",
    "inadmissibility_grounds_source",
)


def vector_literal(v: list[float]) -> str:
    return "[" + ",".join(f"{x:.7g}" for x in v) + "]"


def upsert_document(conn, document: dict, paragraphs: list[dict]) -> None:
    """Insert or update a document and replace all of its paragraphs (position = list order).
    Chunks are left alone: the caller re-chunks with replace_chunks."""
    cols = ", ".join(_DOC_COLUMNS)
    marks = ", ".join(f"%({c})s" for c in _DOC_COLUMNS)
    updates = ", ".join(f"{c} = EXCLUDED.{c}" for c in _DOC_COLUMNS[1:])
    row = {c: document.get(c) for c in _DOC_COLUMNS}
    with conn.transaction():
        conn.execute(
            f"INSERT INTO documents ({cols}) VALUES ({marks}) "
            f"ON CONFLICT (item_id) DO UPDATE SET {updates}, ingested_at = now()",
            row,
        )
        conn.execute("DELETE FROM paragraphs WHERE doc_id = %s", (document["item_id"],))
        with conn.cursor() as cur:
            cur.executemany(
                "INSERT INTO paragraphs (id, doc_id, position, number, section, text)"
                " VALUES (%s, %s, %s, %s, %s, %s)",
                [
                    (p["id"], document["item_id"], i, p.get("number"), p["section"], p["text"])
                    for i, p in enumerate(paragraphs)
                ],
            )
    conn.commit()


def replace_chunks(
    conn,
    doc_id: str,
    strategy: str,
    chunks: list[dict],
    vectors: list[list[float]],
    embedder_model: str,
) -> None:
    """Replace every chunk of (doc_id, strategy) with `chunks` + their embedding vectors."""
    if len(chunks) != len(vectors):
        raise ValueError(f"{len(chunks)} chunks but {len(vectors)} vectors")
    with conn.transaction():
        conn.execute("DELETE FROM chunks WHERE doc_id = %s AND strategy = %s", (doc_id, strategy))
        with (
            conn.cursor() as cur,
            cur.copy(
                "COPY chunks (id, doc_id, strategy, position, text, paragraph_ids, token_count,"
                " embedding, embedder_model) FROM STDIN"
            ) as cp,
        ):
            for i, (c, v) in enumerate(zip(chunks, vectors, strict=True)):
                cp.write_row(
                    (
                        c["id"],
                        doc_id,
                        strategy,
                        i,
                        c["text"],
                        c["paragraph_ids"],
                        c["token_count"],
                        vector_literal(v),
                        embedder_model,
                    )
                )
    conn.commit()


def stored_hashes(conn) -> dict[str, str]:
    """item_id -> sha256 of every stored document (for incremental ingest)."""
    rows = conn.execute("SELECT item_id, sha256 FROM documents").fetchall()
    conn.commit()
    return dict(rows)


def record_ingest_run(conn, run: dict) -> None:
    conn.execute(
        "INSERT INTO ingest_runs (run_id, started_at, payload) VALUES (%s, %s, %s) "
        "ON CONFLICT (run_id) DO UPDATE SET started_at = EXCLUDED.started_at,"
        " payload = EXCLUDED.payload",
        (run["run_id"], run["started_at"], Jsonb(run)),
    )
    conn.commit()
