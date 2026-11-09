"""Test database setup: the real migrations (`rag.index.reset`) plus rows built from the contract
fixtures."""

import copy
import json

import psycopg

from rag import index
from rag.contract import load_fixture

DOC_COLUMNS = (
    "item_id", "case_name", "application_numbers", "ecli", "doc_type", "chamber", "date",
    "articles", "outcome_raw", "outcome", "importance", "language", "source_url", "sha256",
    "data_source", "inadmissibility_grounds", "inadmissibility_grounds_source",
)  # fmt: skip

MIAH = "001-98645"
SOERING = "001-57619"  # the Chunk fixture's document (Soering)


def build_schema(conn: psycopg.Connection) -> None:
    index.reset(conn)
    conn.commit()


def second_document() -> dict:
    doc = copy.deepcopy(load_fixture("SourceDocument"))
    doc.update(
        item_id=SOERING,
        case_name="SOERING v. THE UNITED KINGDOM",
        application_numbers=["14038/88"],
        ecli=None,
        doc_type="judgment",
        chamber="Grand Chamber",
        date="1989-07-07",
        # "8" and "8-1" fold into one article 8 for this document; "14+8" counts for 14
        articles=["3", "8", "8-1", "14+8", "P1-3", "35-3-a"],
        outcome_raw="Violation of Art. 3",
        outcome="violation",
        inadmissibility_grounds=None,
        inadmissibility_grounds_source=None,
        importance=1,
        source_url="https://hudoc.echr.coe.int/eng?i=001-57619",
        sha256="a" * 64,
    )
    return doc


def third_document() -> dict:
    """A document with no chamber, from a different year."""
    doc = second_document()
    doc.update(
        item_id="echr-convention",
        case_name="Convention for the Protection of Human Rights",
        application_numbers=[],
        doc_type="legislation",
        chamber=None,
        date="1950-11-04",
        articles=[],
        outcome_raw=None,
        outcome="not_applicable",
        importance=None,
        source_url="https://www.echr.coe.int/documents/convention_eng.pdf",
        sha256="b" * 64,
    )
    return doc


def eval_runs_fixture() -> tuple[dict, dict]:
    newer = load_fixture("EvalRun")
    older = copy.deepcopy(newer)
    older["run_id"] = "older-run"
    older["started_at"] = older["finished_at"] = "2026-11-01T10:00:00Z"
    return newer, older


def ingest_runs_fixture() -> tuple[dict, dict]:
    newer = load_fixture("IngestRun")
    older = copy.deepcopy(newer)
    older["run_id"] = "older-ingest"
    older["started_at"] = "2026-11-01T09:00:00Z"
    older["finished_at"] = "2026-11-01T09:10:00Z"
    return newer, older


def extra_cost_rows() -> list[dict]:
    base = load_fixture("CostSummary")["recent"][0]
    return [
        {
            **base,
            "id": "cost-generate-1",
            "timestamp": "2026-11-03T18:00:00.123Z",
            "model": "claude-sonnet-5-5",
            "purpose": "generate",
            "tokens_in": 4000,
            "tokens_out": 500,
            "tokens_cached": 1000,
            "cost_usd": 0.0195,
            "latency_ms": 4200.5,
            "request_id": "req-a",
        },
        {
            **base,
            "id": "cost-route-1",
            "timestamp": "2026-11-03T18:00:01Z",
            "model": "claude-haiku-5-5",
            "purpose": "route",
            "tokens_in": 300,
            "tokens_out": 10,
            "tokens_cached": 0,
            "cost_usd": 0.0004,
            "latency_ms": 350.0,
            "request_id": "req-a",
        },
    ]


def seed(conn: psycopg.Connection, *, empty: bool = False) -> None:
    conn.execute("TRUNCATE chunks, paragraphs, documents, ingest_runs, cost_log, eval_runs CASCADE")
    if empty:
        conn.commit()
        return
    miah = load_fixture("SourceDocument")
    for doc in (miah, second_document(), third_document()):
        conn.execute(
            f"INSERT INTO documents ({', '.join(DOC_COLUMNS)}) "
            f"VALUES ({', '.join(['%s'] * len(DOC_COLUMNS))})",
            [doc[c] for c in DOC_COLUMNS],
        )
    for position, p in enumerate(load_fixture("CaseDetail")["paragraphs"], start=1):
        conn.execute(
            "INSERT INTO paragraphs (id, doc_id, position, number, section, text) "
            "VALUES (%s, %s, %s, %s, %s, %s)",
            (p["id"], p["doc_id"], position, p["number"], p["section"], p["text"]),
        )
    # Inserted in the "wrong" id order: position, not insertion order or id, defines the order.
    for position, number in ((2, 2), (1, 1)):
        conn.execute(
            "INSERT INTO paragraphs (id, doc_id, position, number, section, text) "
            "VALUES (%s, %s, %s, %s, 'The Law', %s)",
            (f"{SOERING}§{number}", SOERING, position, number, f"Soering paragraph {number}."),
        )
    chunk = load_fixture("Chunk")
    for i, strategy in enumerate(["recursive", "recursive", "fixed"]):
        conn.execute(
            "INSERT INTO chunks (id, doc_id, strategy, position, text, paragraph_ids, "
            "token_count, embedder_model) VALUES (%s, %s, %s, %s, %s, %s, %s, 'fake')",
            (
                f"{SOERING}:{strategy}:{i}",
                SOERING,
                strategy,
                i,
                chunk["text"],
                [f"{SOERING}§1"],
                chunk["token_count"],
            ),
        )
    for run in ingest_runs_fixture():
        conn.execute(
            "INSERT INTO ingest_runs (run_id, started_at, payload) VALUES (%s, %s, %s)",
            (run["run_id"], run["started_at"], json.dumps(run)),
        )
    for run in eval_runs_fixture():
        conn.execute(
            "INSERT INTO eval_runs (run_id, created_at, payload) VALUES (%s, %s, %s)",
            (run["run_id"], run["finished_at"], json.dumps(run)),
        )
    for row in [*load_fixture("CostSummary")["recent"], *extra_cost_rows()]:
        conn.execute(
            "INSERT INTO cost_log (id, timestamp, model, purpose, tokens_in, tokens_out, "
            "tokens_cached, cost_usd, latency_ms, request_id) "
            "VALUES (%(id)s, %(timestamp)s, %(model)s, %(purpose)s, %(tokens_in)s, "
            "%(tokens_out)s, %(tokens_cached)s, %(cost_usd)s, %(latency_ms)s, %(request_id)s)",
            row,
        )
    conn.commit()
