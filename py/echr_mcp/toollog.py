"""One `tool_log` row per tool call. Logging never fails a call (errors are swallowed, counted)."""

from __future__ import annotations

import logging
from collections.abc import Callable

from psycopg.types.json import Jsonb

log = logging.getLogger("echr_mcp")

failures = 0  # log writes that failed since this process started


def log_call(
    conn_factory: Callable,
    *,
    tool: str,
    args: dict,
    ok: bool,
    error: str | None,
    latency_ms: float,
    result_bytes: int,
    data_source: str,
    transport: str,
) -> bool:
    """Insert one row; True if it was written."""
    global failures
    try:
        with conn_factory() as conn:
            conn.execute(
                "INSERT INTO tool_log (tool, args, ok, error, latency_ms, result_bytes, "
                "data_source, transport) VALUES (%s, %s, %s, %s, %s, %s, %s, %s)",
                (
                    tool,
                    Jsonb(args),
                    ok,
                    error,
                    round(latency_ms, 3),
                    result_bytes,
                    data_source,
                    transport,
                ),
            )
        return True
    except Exception as exc:
        failures += 1
        log.warning("tool_log write failed (%s): %s", type(exc).__name__, exc)
        return False
