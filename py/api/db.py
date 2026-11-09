"""Per-request database connection.

psycopg_pool is not in the lockfile, and a local TCP connection costs a few milliseconds, so each
request opens its own connection and closes it afterwards.
"""

from collections.abc import Iterator

import psycopg

from rag.config import database_url


def get_conn() -> Iterator[psycopg.Connection]:
    conn = psycopg.connect(database_url(), connect_timeout=5)
    try:
        yield conn
    finally:
        conn.close()
