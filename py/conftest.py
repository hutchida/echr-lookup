"""Shared pytest setup for every Python test in py/.

- Tests never call paid APIs or load real ML models unless explicitly marked.
- Tests that need Postgres use the `test_database_url` / `db_conn` fixtures, which point at a
  separate `<your-db>_test` database, so running tests can never wipe ingested demo data.
"""

import importlib.util
import os

# Safe defaults for tests; set before anything reads rag.config.
os.environ.setdefault("EMBEDDER", "fake")
os.environ.setdefault("LLM_MODE", "fake")
os.environ.setdefault("RERANK_ENABLED", "0")

import psycopg  # noqa: E402
import pytest  # noqa: E402
from psycopg import conninfo, sql  # noqa: E402

from rag.config import database_url  # noqa: E402


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line(
        "markers", "ml: needs the uv 'ml' group (sentence-transformers/torch); skipped if missing"
    )
    config.addinivalue_line(
        "markers", "live: calls a network service or paid API; runs only when RUN_LIVE=1"
    )


def pytest_collection_modifyitems(config: pytest.Config, items: list[pytest.Item]) -> None:
    has_ml = importlib.util.find_spec("sentence_transformers") is not None
    run_live = os.environ.get("RUN_LIVE") == "1"
    for item in items:
        if "ml" in item.keywords and not has_ml:
            item.add_marker(pytest.mark.skip(reason="ml group not installed: uv sync --group ml"))
        if "live" in item.keywords and not run_live:
            item.add_marker(pytest.mark.skip(reason="live test: set RUN_LIVE=1 to run"))


@pytest.fixture(scope="session")
def test_database_url() -> str:
    """URL of `<DATABASE_URL db name>_test`, created on first use with both extensions."""
    base = database_url()
    name = f"{conninfo.conninfo_to_dict(base).get('dbname', 'echr')}_test"
    with psycopg.connect(conninfo.make_conninfo(base, dbname="postgres"), autocommit=True) as c:
        exists = c.execute("SELECT 1 FROM pg_database WHERE datname = %s", (name,)).fetchone()
        if not exists:
            c.execute(sql.SQL("CREATE DATABASE {}").format(sql.Identifier(name)))
    url = conninfo.make_conninfo(base, dbname=name)
    with psycopg.connect(url, autocommit=True) as c:
        c.execute("CREATE EXTENSION IF NOT EXISTS vector")
        c.execute("CREATE EXTENSION IF NOT EXISTS pg_search")
    return url


@pytest.fixture
def db_conn(test_database_url: str):
    with psycopg.connect(test_database_url) as conn:
        yield conn
