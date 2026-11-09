import psycopg
import pytest
from fastapi.testclient import TestClient

from api.main import app
from api.tests.helpers import build_schema, seed


@pytest.fixture(scope="module")
def schema_ready(test_database_url: str) -> str:
    with psycopg.connect(test_database_url) as conn:
        build_schema(conn)
    return test_database_url


@pytest.fixture
def app_env(schema_ready: str, monkeypatch: pytest.MonkeyPatch) -> str:
    """Point the app at the test database (it reads DATABASE_URL on every request)."""
    monkeypatch.setenv("DATABASE_URL", schema_ready)
    return schema_ready


@pytest.fixture
def client(app_env: str):
    """Seeded database; server errors come back as responses, like a real server."""
    with psycopg.connect(app_env) as conn:
        seed(conn)
    with TestClient(app, raise_server_exceptions=False) as test_client:
        yield test_client


@pytest.fixture
def empty_client(app_env: str):
    with psycopg.connect(app_env) as conn:
        seed(conn, empty=True)
    with TestClient(app, raise_server_exceptions=False) as test_client:
        yield test_client
