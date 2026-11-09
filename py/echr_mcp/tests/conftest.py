import psycopg
import pytest

from echr_mcp.tests import seed


@pytest.fixture(scope="module")
def seeded_url(test_database_url: str) -> str:
    """`<db>_test` reset and loaded with the small MCP corpus (fake embedder)."""
    with psycopg.connect(test_database_url) as conn:
        seed.seed(conn)
    return test_database_url


@pytest.fixture
def seeded(seeded_url: str):
    with psycopg.connect(seeded_url) as conn:
        yield conn
