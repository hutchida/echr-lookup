"""A fake echr-lookup MCP server over stdio, for developing and testing the harness offline.

It has the six tool names, the contract's input schemas, the real server's instructions and tool
descriptions (imported from `echr_mcp.server`), and answers every call with the matching contract
fixture (real-snapshot data). It does not search: whatever the model asks, it gets the fixture.
That is enough to exercise the client, the tool loop, the caps and the metrics. The real server
is `python -m echr_mcp`.

Run:  python -m rag.eval.agentic.fake_server
"""

import json
from typing import Any

import anyio
import mcp_types as types
from mcp.server import Server
from mcp.server.stdio import stdio_server

from echr_mcp import server as real_server

from .common import CONTRACT_DIR

# The text the model sees is the real server's (F1's wording), imported so it cannot drift.
INSTRUCTIONS = real_server.INSTRUCTIONS
# tool name -> (description, contract name)
TOOLS: dict[str, tuple[str, str]] = {
    name: (description, contract)
    for name, (contract, description) in real_server.TOOL_SPECS.items()
}


def _schema(file: str, name: str) -> dict[str, Any]:
    return json.loads((CONTRACT_DIR / "schema" / file).read_text())["$defs"][name]


def _fixture(name: str) -> dict[str, Any]:
    return json.loads((CONTRACT_DIR / "fixtures" / f"{name}.json").read_text())


def tool_definitions() -> list[types.Tool]:
    return [
        types.Tool(
            name=name,
            description=description,
            input_schema=_schema(f"{contract}Input.json", f"{contract}Input"),
            output_schema=_schema(f"{contract}Result.json", f"{contract}Result"),
            annotations=types.ToolAnnotations(
                read_only_hint=True,
                destructive_hint=False,
                idempotent_hint=True,
                open_world_hint=False,
            ),
        )
        for name, (description, contract) in TOOLS.items()
    ]


def _validate(name: str, args: dict[str, Any]) -> str | None:
    try:
        import jsonschema
    except ImportError:  # dev dependency; the fake still works without it
        return None
    contract = TOOLS[name][1]
    try:
        jsonschema.validate(args, _schema(f"{contract}Input.json", f"{contract}Input"))
    except jsonschema.ValidationError as exc:
        return f"Bad arguments for {name}: {exc.message}"
    return None


def fake_result(name: str, args: dict[str, Any]) -> tuple[dict[str, Any] | None, str | None]:
    """-> (result, error): the fixture that fits the call; an error where the real server errors."""
    if name == "search_case_law":
        return _fixture("McpSearchCaseLawResult"), None
    if name == "get_paragraphs":
        main = _fixture("McpGetParagraphsResult")
        known = {p["paragraph_id"] for p in main["paragraphs"]}
        if set(args["paragraph_ids"]) <= known:
            return main, None
        return _fixture("McpGetParagraphsResult.not-found"), None
    if name == "get_case":
        case = _fixture("McpGetCaseResult")
        if args["case_id"] == case["doc_id"]:
            return case, None
        return None, f"No case {args['case_id']} in this corpus (snapshot: 98 UK documents)."
    if name == "count_cases":
        return _fixture(
            "McpCountCasesResult.top-group"
            if args.get("group_by") == "reason"
            else "McpCountCasesResult"
        ), None
    if name == "corpus_info":
        return _fixture("McpCorpusInfoResult"), None
    return _fixture("McpCheckQuoteResult"), None


def _error(message: str) -> types.CallToolResult:
    return types.CallToolResult(
        content=[types.TextContent(type="text", text=message)], is_error=True
    )


async def _list_tools(ctx: Any, params: Any) -> types.ListToolsResult:
    return types.ListToolsResult(tools=tool_definitions())


async def _call_tool(ctx: Any, params: types.CallToolRequestParams) -> types.CallToolResult:
    args = params.arguments or {}
    if params.name not in TOOLS:
        return _error(f"Unknown tool {params.name}.")
    problem = _validate(params.name, args)
    if problem:
        return _error(problem)
    result, error = fake_result(params.name, args)
    if error or result is None:
        return _error(error or "No result.")
    text = json.dumps(result, ensure_ascii=False, separators=(",", ":"))
    return types.CallToolResult(
        content=[types.TextContent(type="text", text=text)], structured_content=result
    )


def build_server() -> Server:
    return Server(
        "echr-lookup-fake",
        instructions=INSTRUCTIONS,
        on_list_tools=_list_tools,
        on_call_tool=_call_tool,
    )


async def _serve() -> None:
    server = build_server()
    async with stdio_server() as (read_stream, write_stream):
        await server.run(read_stream, write_stream, server.create_initialization_options())


def main() -> None:
    anyio.run(_serve)


if __name__ == "__main__":
    main()
