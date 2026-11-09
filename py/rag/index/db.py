"""Connection and migrations."""

from pathlib import Path

import psycopg

from rag import config

MIGRATIONS_DIR = config.REPO_ROOT / "infra" / "migrations"
APP_TABLES = (
    "eval_runs",
    "cost_log",
    "ingest_runs",
    "chunks",
    "paragraphs",
    "documents",
    "schema_migrations",
)
_LOCK_KEY = 7_301_001


def connect(url: str | None = None) -> psycopg.Connection:
    return psycopg.connect(url or config.database_url())


def migration_files() -> list[Path]:
    return sorted(MIGRATIONS_DIR.glob("*.sql"))


def migrate(conn: psycopg.Connection) -> None:
    """Apply every infra/migrations/*.sql not yet recorded in schema_migrations, in name order."""
    conn.commit()
    conn.execute("SELECT pg_advisory_xact_lock(%s)", (_LOCK_KEY,))
    conn.execute(
        "CREATE TABLE IF NOT EXISTS schema_migrations ("
        "version text PRIMARY KEY, applied_at timestamptz NOT NULL DEFAULT now())"
    )
    done = {r[0] for r in conn.execute("SELECT version FROM schema_migrations")}
    for path in migration_files():
        if path.name in done:
            continue
        conn.execute(path.read_text())
        conn.execute("INSERT INTO schema_migrations (version) VALUES (%s)", (path.name,))
    conn.commit()


def reset(conn: psycopg.Connection) -> None:
    """Drop every app table and migrate again: 'start from empty'."""
    conn.commit()
    for table in APP_TABLES:
        conn.execute(f"DROP TABLE IF EXISTS {table} CASCADE")
    conn.commit()
    migrate(conn)
