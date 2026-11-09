"""A tiny MCP client for poking at the echr-lookup server without Claude.

    cd py && uv run python ../scripts/mcp_call.py list                       # starts a stdio server
    cd py && uv run python ../scripts/mcp_call.py call count_cases '{"doc_types":["judgment"]}'
    cd py && uv run python ../scripts/mcp_call.py --url http://127.0.0.1:8101/mcp list

Without --url it starts `python -m echr_mcp --transport stdio` as a child process (the same thing
Claude Desktop does), with the repo .env. `call` prints the tool's JSON result, or its error
sentence and exits 1.
"""

import argparse
import json
import sys
import time
from pathlib import Path

import anyio
from mcp import Client, StdioServerParameters

PY_DIR = Path(__file__).resolve().parents[1] / "py"


def target(url: str | None):
    if url:
        return url
    return StdioServerParameters(
        command=sys.executable,
        args=["-m", "echr_mcp", "--transport", "stdio"],
        cwd=PY_DIR,
    )


async def run(args: argparse.Namespace) -> int:
    async with Client(target(args.url)) as client:
        if args.command == "list":
            for tool in (await client.list_tools()).tools:
                first = (tool.description or "").split(". ")[0]
                print(f"{tool.name:<16} {first}")
            return 0
        started = time.perf_counter()
        result = await client.call_tool(args.tool, json.loads(args.arguments))
        elapsed = time.perf_counter() - started
        if result.is_error:
            print(result.content[0].text)
            return 1
        print(json.dumps(result.structured_content, indent=2, ensure_ascii=False))
        print(f"-- {elapsed:.2f} s", file=sys.stderr)
        return 0


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    parser.add_argument("--url", help="streamable HTTP endpoint, e.g. http://127.0.0.1:8101/mcp")
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("list", help="list the tools")
    call = sub.add_parser("call", help="call one tool")
    call.add_argument("tool")
    call.add_argument("arguments", nargs="?", default="{}", help="JSON object of arguments")
    sys.exit(anyio.run(run, parser.parse_args()))


if __name__ == "__main__":
    main()
