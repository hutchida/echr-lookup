# ruff: noqa: E501
"""The MCP server: advertises the contract's schemas, validates, times, logs and serialises.

Built on the SDK's low-level `Server` so the contract's JSON Schemas go out unchanged as each tool's
`inputSchema` / `outputSchema`. Arguments are checked here (the low-level server does not), and
every failure the model can act on is a tool error (`isError: true`) with one plain sentence.
"""

from __future__ import annotations

import json
import logging
import threading
import time
from collections.abc import Callable
from typing import Any

import anyio.to_thread
import psycopg
from mcp.server import Server, ServerRequestContext
from mcp.shared.exceptions import MCPError
from mcp.types import (
    INVALID_PARAMS,
    CallToolRequestParams,
    CallToolResult,
    ListToolsResult,
    PaginatedRequestParams,
    TextContent,
    Tool,
    ToolAnnotations,
)

from echr_mcp import toollog, tools
from echr_mcp.common import RESULT_MAX_BYTES, ToolError, json_bytes
from rag import config, index
from rag.contract import SCHEMA_DIR, contract_errors

log = logging.getLogger("echr_mcp")

INSTRUCTIONS = """\
echr-lookup supplies evidence from the European Court of Human Rights' case law against the United Kingdom, plus the Convention and the Human Rights Act 1998. You write the answer; these tools give you citable paragraphs.
1. Every factual sentence ends with a `cite` string copied exactly from a tool result (e.g. [Chahal v. the United Kingdom, Judgment, §79]). A sentence you cannot cite does not go in.
2. Quote only text copied from tool results, and call `check_quote` before any quoted phrase.
3. Use only cases the tools returned. If nothing relevant comes back, say so and state the corpus limits (see `corpus` in every result, or `corpus_info`). Never add cases from general knowledge; "not found here" does not mean the Court never decided it.
4. Open with one sentence that answers the question, even a broad one; then the evidence, grouped; about 8-10 claims at most.
5. No bare "Yes"/"No" unless a cited paragraph states the general rule. Otherwise lead with the holding's reach: "Only where…", "Not as a general rule: …".
6. For any "how many" question call `count_cases`; never count search results. Report its numbers with its definitions.
7. A "Legal summary" is the Court's digest of a case, not the judgment: say so when you cite one.
8. Stay neutral: no view on UK membership of the Convention or on whether a law or judgment is good. For value questions give the strongest sourced points on each side."""

# name -> (contract name, description)
TOOL_SPECS: dict[str, tuple[str, str]] = {
    "search_case_law": (
        "McpSearchCaseLaw",
        "Find the paragraphs that best match a question (hybrid keyword + meaning search, "
        "reranked). Each hit has a verbatim `quote` (the only text you may quote from it), a "
        "`cite` to copy after the claim it supports, a readable `para_label` and a `hudoc_url` "
        "that opens the document at that quote (for the reader, not a source). Use filters to "
        "narrow by Article, document type, outcome or years. Fetch more context with "
        "get_paragraphs before relying on a hit.",
    ),
    "get_paragraphs": (
        "McpGetParagraphs",
        "Full text of paragraphs by id, optionally with neighbouring paragraphs, with section "
        "labels. Use it to read the reasoning around a search hit. Cite with each paragraph's "
        "`cite`; quote only its `text`; `hudoc_url` opens the document at its first words.",
    ),
    "get_case": (
        "McpGetCase",
        "One document's metadata, outcome, operative provisions (what the Court decided, each "
        "with a `cite` to copy) and an outline of its sections with paragraph ranges. "
        "`hudoc_url` is the document's page.",
    ),
    "count_cases": (
        "McpCountCases",
        "Answer any 'how many' question by filling a fixed, validated template; the server runs "
        "read-only SQL and returns every number, the definitions used, the exact SQL and up to 20 "
        "matching cases. Never count search results instead. Its numbers need no `cite`; say "
        "which definitions they rest on.",
    ),
    "corpus_info": (
        "McpCorpusInfo",
        "What the corpus contains (counts by document type, Article, outcome, years) and what it "
        "lacks and why. Call it before saying something is not in the case law, and quote its "
        "limits when nothing relevant is found.",
    ),
    "check_quote": (
        "McpCheckQuote",
        "Check that a quote appears word for word in a paragraph; returns true/false, the closest "
        "matching passage and the paragraph's `cite`. Call it before any quoted phrase; if "
        "`verbatim` is false, quote `closest_match` instead or paraphrase.",
    ),
}

READ_ONLY = ToolAnnotations(
    read_only_hint=True, destructive_hint=False, idempotent_hint=True, open_world_hint=False
)


def contract_schema(name: str) -> dict:
    """`$defs[name]` of schema/<name>.json: what the contract fixes for that argument or result."""
    document = json.loads((SCHEMA_DIR / f"{name}.json").read_text())
    return document["$defs"][name]


def tool_definitions() -> list[Tool]:
    return [
        Tool(
            name=name,
            description=description,
            input_schema=contract_schema(f"{contract}Input"),
            output_schema=contract_schema(f"{contract}Result"),
            annotations=READ_ONLY,
        )
        for name, (contract, description) in TOOL_SPECS.items()
    ]


def _sentence(errors: list[str], tool: str) -> str:
    shown = "; ".join(errors[:3]) + ("; …" if len(errors) > 3 else "")
    return f"Invalid arguments for {tool}: {shown}. See the tool's input schema."


class Services:
    """What a call needs: a connection source, the two models, a lock around model use."""

    def __init__(self, conn_factory: Callable | None, embedder, reranker, transport: str):
        self.conn_factory = conn_factory or index.connect
        self.embedder = embedder
        self.reranker = reranker
        self.transport = transport
        self.model_lock = threading.Lock()

    def run(self, name: str, args: dict) -> dict:
        with self.conn_factory() as conn:
            if name == "search_case_law":
                with self.model_lock:
                    result = tools.search_case_law(
                        conn, args, embedder=self.embedder, reranker=self.reranker
                    )
            else:
                result = getattr(tools, name)(conn, args)
            conn.commit()  # search writes its embed/rerank rows to cost_log
        return result

    def call(self, name: str, args: dict) -> tuple[bool, str, dict | None]:
        """-> (ok, text, structured). Never raises."""
        started = time.perf_counter()
        structured: dict | None = None
        error: str | None = None
        try:
            if name not in TOOL_SPECS:
                raise ToolError(f"Unknown tool {name!r}. Tools: {', '.join(TOOL_SPECS)}.")
            contract = TOOL_SPECS[name][0]
            if problems := contract_errors(f"{contract}Input", args):
                raise ToolError(_sentence(problems, name))
            structured = self.run(name, args)
            if problems := contract_errors(f"{contract}Result", structured):
                log.error("%s result broke its contract: %s", name, problems[:3])
                structured = None
                raise ToolError(
                    f"{name} produced a result that does not match its published schema "
                    "(a bug in echr-lookup); try different arguments."
                )
            if json_bytes(structured) > RESULT_MAX_BYTES:
                structured = None
                raise ToolError(f"{name} produced a result over 25,000 bytes; narrow the request.")
        except ToolError as exc:
            error = str(exc)
        except psycopg.OperationalError as exc:
            log.error("database unavailable: %s", exc)
            error = (
                "The echr-lookup database is not reachable; ask the user to start it (pnpm db:up)."
            )
        except Exception:
            log.exception("%s failed", name)
            error = f"{name} hit an internal error; try again or change the arguments."
        text = (
            json.dumps(structured, ensure_ascii=False, separators=(",", ":"))
            if structured is not None
            else (error or "")
        )
        toollog.log_call(
            self.conn_factory,
            tool=name,
            args=args,
            ok=error is None,
            error=error,
            latency_ms=(time.perf_counter() - started) * 1000,
            result_bytes=len(text.encode("utf-8")),
            data_source=config.data_source(),
            transport=self.transport,
        )
        return error is None, text, structured


def warm_up(embedder, reranker) -> None:
    """One dummy embed and rerank, so the first real search is not a cold start."""
    if embedder is not None:
        embedder.embed_query("warm up")
    if reranker is not None:
        reranker.score("warm up", ["warm up text"])


def build_server(
    conn_factory: Callable | None = None,
    *,
    embedder=None,
    reranker=None,
    transport: str = "stdio",
    warm: bool = True,
) -> Server:
    """The configured server. Models load (and warm) once, here; tests inject fakes."""
    embedder = embedder or index.get_embedder()
    if reranker is None and config.rerank_enabled():
        from rag.search import get_reranker

        reranker = get_reranker()
    if warm:
        warm_up(embedder, reranker)
    services = Services(conn_factory, embedder, reranker, transport)
    try:
        with services.conn_factory() as conn:
            index.migrate(conn)  # creates tool_log on a database that predates it
    except Exception as exc:
        log.warning("could not run migrations (%s); tool_log may be missing", exc)

    definitions = tool_definitions()

    async def list_tools(
        ctx: ServerRequestContext, params: PaginatedRequestParams | None
    ) -> ListToolsResult:
        return ListToolsResult(tools=definitions)

    async def call_tool(ctx: ServerRequestContext, params: CallToolRequestParams) -> CallToolResult:
        args: Any = params.arguments or {}
        if params.name not in TOOL_SPECS:
            raise MCPError(INVALID_PARAMS, f"Unknown tool: {params.name}")
        ok, text, structured = await anyio.to_thread.run_sync(services.call, params.name, args)
        return CallToolResult(
            content=[TextContent(type="text", text=text)],
            structured_content=structured if ok else None,
            is_error=not ok,
        )

    server = Server(
        "echr-lookup",
        version="0.1.0",
        title="echr-lookup: UK cases at the European Court of Human Rights",
        instructions=INSTRUCTIONS,
        on_list_tools=list_tools,
        on_call_tool=call_tool,
    )
    server.services = services  # type: ignore[attr-defined]  # for tests and the warm-up report
    return server
