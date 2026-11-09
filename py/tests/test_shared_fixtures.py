"""Proves the shared test fixtures in py/conftest.py work (orchestrator-owned plumbing)."""

from psycopg import conninfo

from rag.config import database_url


def test_db_fixture_uses_separate_test_database_with_both_extensions(db_conn, test_database_url):
    app_db = conninfo.conninfo_to_dict(database_url())["dbname"]
    assert conninfo.conninfo_to_dict(test_database_url)["dbname"] == f"{app_db}_test"
    exts = {r[0] for r in db_conn.execute("SELECT extname FROM pg_extension").fetchall()}
    assert {"vector", "pg_search"} <= exts


def test_safe_defaults_for_tests():
    import os

    assert os.environ["EMBEDDER"] == "fake"
    assert os.environ["LLM_MODE"] == "fake"
