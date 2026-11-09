"""tool_log: written for every call, survives rag.index.reset(), and never breaks a call."""

import psycopg
import pytest

from echr_mcp import toollog
from echr_mcp.server import Services
from rag.index import get_embedder, migrate, reset


@pytest.fixture
def services(seeded_url):
    def factory():
        return psycopg.connect(seeded_url)

    with factory() as conn:
        conn.execute("DELETE FROM tool_log")
        conn.commit()
    return Services(factory, get_embedder("fake"), None, "stdio"), factory


def test_a_call_writes_one_row(services):
    service, factory = services
    ok, text, structured = service.call("corpus_info", {})
    assert ok and structured["totals"]["documents"] == 7 and text.startswith("{")
    with factory() as conn:
        row = conn.execute(
            "SELECT tool, args, ok, error, latency_ms, result_bytes, data_source, transport "
            "FROM tool_log"
        ).fetchone()
    assert row[:4] == ("corpus_info", {}, True, None)
    assert float(row[4]) > 0 and row[5] == len(text.encode()) and row[6:] == ("snapshot", "stdio")


def test_failed_calls_are_logged_with_their_error(services):
    service, factory = services
    ok, text, structured = service.call("get_case", {"case_id": "001-99999"})
    assert not ok and structured is None and text.startswith("No case 001-99999")
    with factory() as conn:
        assert conn.execute("SELECT ok, error FROM tool_log").fetchone() == (False, text)


def test_tool_log_survives_reset(seeded_url, services):
    service, factory = services
    service.call("corpus_info", {})
    with factory() as conn:
        reset(conn)  # drops the app tables and migrates again
        assert conn.execute("SELECT count(*) FROM tool_log").fetchone()[0] == 1
        assert conn.execute("SELECT count(*) FROM documents").fetchone()[0] == 0
        migrate(conn)  # idempotent: the table and its row stay
        assert conn.execute("SELECT count(*) FROM tool_log").fetchone()[0] == 1


def test_a_logging_failure_never_fails_the_call(seeded_url):
    toollog.failures = 0

    def factory():
        conn = psycopg.connect(seeded_url)
        return conn

    service = Services(factory, get_embedder("fake"), None, "stdio")
    with factory() as conn:
        conn.execute("DROP TABLE tool_log")
        conn.commit()
    ok, _, structured = service.call("corpus_info", {})
    assert ok and structured is not None
    assert toollog.failures == 1
    with factory() as conn:  # put the table back for the other tests
        migrate(conn)
        conn.execute("DELETE FROM schema_migrations WHERE version LIKE 'mcp_%'")
        conn.commit()
        migrate(conn)
