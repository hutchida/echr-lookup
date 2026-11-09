"""`python -m echr_mcp --transport stdio` or `--transport http [--port 8100]`.

stdio: Claude Desktop / Claude Code start this as a child process and talk over stdin/stdout, so
nothing but MCP messages may reach stdout (logs go to stderr).
http: streamable HTTP at http://127.0.0.1:<port>/mcp (localhost only unless --host / $MCP_HOST says
otherwise; DNS-rebinding protection stays on, see transport_security()).
"""

from __future__ import annotations

import argparse
import contextlib
import logging
import os
import sys

DEFAULT_PORT = 8100
DEFAULT_HOST = "127.0.0.1"
LOCAL_HOSTS = ("127.0.0.1", "localhost", "::1")


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    from rag import config  # noqa: F401  (loads the repo .env, so MCP_PORT can live there)

    parser = argparse.ArgumentParser(prog="python -m echr_mcp", description=__doc__)
    parser.add_argument("--transport", choices=("stdio", "http"), required=True)
    parser.add_argument(
        "--port",
        type=int,
        default=int(os.environ.get("MCP_PORT") or DEFAULT_PORT),
        help=f"http only; default $MCP_PORT or {DEFAULT_PORT}",
    )
    parser.add_argument(
        "--host",
        default=os.environ.get("MCP_HOST") or DEFAULT_HOST,
        help=f"http only; default $MCP_HOST or {DEFAULT_HOST} (0.0.0.0 only in a container)",
    )
    return parser.parse_args(argv)


def transport_security(host: str, allowed_hosts: str | None = None):
    """Host/Origin allow-list for the HTTP transport; None keeps the SDK's localhost default.

    The SDK only turns DNS-rebinding protection on by itself for a localhost bind, so any other
    bind (e.g. 0.0.0.0 in a container) gets explicit settings: localhost on any port plus the
    comma-separated `allowed_hosts` ($MCP_ALLOWED_HOSTS, e.g. "mcp.example.com").
    """
    extra = [h.strip() for h in (allowed_hosts or "").split(",") if h.strip()]
    if host in LOCAL_HOSTS and not extra:
        return None
    from mcp.server.transport_security import TransportSecuritySettings

    return TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=["127.0.0.1:*", "localhost:*", "[::1]:*", *extra],
        allowed_origins=[
            "http://127.0.0.1:*",
            "http://localhost:*",
            "http://[::1]:*",
            *(f"{scheme}://{h}" for h in extra for scheme in ("http", "https")),
        ],
    )


def main(argv: list[str] | None = None) -> None:
    args = parse_args(argv)
    logging.basicConfig(
        stream=sys.stderr,
        level=logging.WARNING,  # third-party libraries stay quiet; ours speaks at INFO
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )
    logging.getLogger("echr_mcp").setLevel(logging.INFO)
    from echr_mcp.server import build_server

    # Model loading must not write to stdout: on stdio that is the protocol channel.
    with contextlib.redirect_stdout(sys.stderr):
        server = build_server(transport=args.transport)
    logging.getLogger("echr_mcp").info("ready (transport=%s)", args.transport)

    if args.transport == "stdio":
        import anyio
        from mcp.server.stdio import stdio_server

        async def run_stdio() -> None:
            async with stdio_server() as (read, write):
                await server.run(read, write, server.create_initialization_options())

        anyio.run(run_stdio)
    else:
        import uvicorn

        app = server.streamable_http_app(
            host=args.host,
            transport_security=transport_security(args.host, os.environ.get("MCP_ALLOWED_HOSTS")),
        )
        uvicorn.run(app, host=args.host, port=args.port, log_level="info")


if __name__ == "__main__":
    main()
