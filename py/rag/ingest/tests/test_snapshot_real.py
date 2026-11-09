"""Run against the committed snapshot: fake parser/embedder (offline, fast), and, when S2 + S3
are merged, the real modules in the `<db>_test` database."""

from rag import index
from rag.config import REPO_ROOT
from rag.contract import contract_errors
from rag.ingest import run_ingest
from rag.ingest.pipeline import discard_document

from .fakes import FakeConn, FakeDb

SNAPSHOT = REPO_ROOT / "data" / "snapshot"


def test_whole_snapshot_verifies_and_second_run_skips_all():
    db = FakeDb()
    first = run_ingest(FakeConn(), "snapshot", deps=db.deps(), out=lambda s: None)
    assert first["counts"]["failed"] == 0
    assert first["counts"]["new"] == first["counts"]["seen"] == 98
    assert contract_errors("IngestRun", first) == []
    second = run_ingest(FakeConn(), "snapshot", deps=db.deps(), out=lambda s: None)
    assert second["counts"]["unchanged_skipped"] == 98


def test_real_modules_ingest_a_few_documents(db_conn):
    """Real rag.parse + rag.index (fake embedder in tests) against the `<db>_test` database."""
    run = run_ingest(db_conn, "snapshot", limit=4, reset=True, out=lambda s: None)
    assert contract_errors("IngestRun", run) == []
    assert run["counts"]["failed"] == 0 and run["counts"]["new"] == 4
    docs = db_conn.execute("SELECT count(*) FROM documents").fetchone()[0]
    paras = db_conn.execute("SELECT count(*) FROM paragraphs").fetchone()[0]
    strategies = {r[0] for r in db_conn.execute("SELECT DISTINCT strategy FROM chunks")}
    assert docs == 4 and paras > 40
    assert strategies == {"fixed", "recursive", "by_section"}
    stored = db_conn.execute("SELECT payload FROM ingest_runs WHERE run_id = %s", (run["run_id"],))
    assert contract_errors("IngestRun", stored.fetchone()[0]) == []

    again = run_ingest(db_conn, "snapshot", limit=4, out=lambda s: None)
    assert again["counts"]["unchanged_skipped"] == 4 and again["counts"]["new"] == 0


def test_real_discard_document_removes_rows_and_hash(db_conn):
    run_ingest(db_conn, "snapshot", limit=1, reset=True, out=lambda s: None)
    (item_id,) = (r[0] for r in db_conn.execute("SELECT item_id FROM documents"))
    discard_document(db_conn, item_id)
    assert index.stored_hashes(db_conn) == {}
    assert db_conn.execute("SELECT count(*) FROM chunks").fetchone()[0] == 0
