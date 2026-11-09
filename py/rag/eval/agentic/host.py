# ruff: noqa: E501
"""The host: Claude over the Messages API, using the MCP server's tools.

One `McpSession` (one server process) is reused for every question. `Host.ask` runs the tool loop:
call the model; run each `tool_use` through the MCP session; send the JSON back as `tool_result`;
stop at a final answer, or after MAX_TOOL_CALLS tool calls, when the model is told to answer
without more tools (`tool_choice: none`, so the cached tool definitions stay valid).
"""

import contextlib
import copy
import json
import time
import uuid
from collections.abc import Callable
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from typing import Any

from mcp import Client
from mcp.client.stdio import StdioServerParameters

from rag.answer.llm import _create_without_thinking

from .common import (
    CHARS_PER_TOKEN,
    EST_OUTPUT_TOKENS,
    HOST_MAX_TOKENS,
    HOST_MODEL,
    MAX_TOOL_CALLS,
    Budget,
    BudgetExceeded,
    usd,
)

CACHE = {"type": "ephemeral"}
LIMIT_MESSAGE = "Tool-call limit reached for this question: answer from what you already have."
FORCE_FINAL_NOTE = (
    "You have used all your tool calls for this question. Write your final answer now, "
    "from the results you already have."
)


@dataclass
class Usage:
    input: int = 0  # uncached input tokens
    output: int = 0
    cache_read: int = 0
    cache_write: int = 0
    api_calls: int = 0
    cost_usd: float = 0.0

    def add(self, other: "Usage") -> None:
        for name in ("input", "output", "cache_read", "cache_write", "api_calls", "cost_usd"):
            setattr(self, name, getattr(self, name) + getattr(other, name))


@dataclass
class ToolCallRecord:
    name: str
    args: dict
    result_bytes: int
    latency_ms: float
    is_error: bool
    paragraph_ids: list[str] = field(default_factory=list)
    result_text: str = field(default="", repr=False)  # kept in memory only, never written out

    def to_json(self) -> dict:
        return {
            "name": self.name,
            "args": self.args,
            "result_bytes": self.result_bytes,
            "latency_ms": round(self.latency_ms, 1),
            "is_error": self.is_error,
            "paragraph_ids": self.paragraph_ids,
        }


@dataclass
class Turn:
    question: str
    answer_text: str = ""
    tool_calls: list[ToolCallRecord] = field(default_factory=list)
    usage: Usage = field(default_factory=Usage)
    latency_ms: float = 0.0
    hit_cap: bool = False
    status: str = "ok"  # ok | skipped_budget
    note: str = ""


def collect_paragraph_ids(value: Any) -> list[str]:
    """Every `paragraph_id` value anywhere in a tool result (search hits, paragraphs, operative provisions)."""
    found: list[str] = []

    def walk(node: Any) -> None:
        if isinstance(node, dict):
            for key, child in node.items():
                if key == "paragraph_id" and isinstance(child, str):
                    if child not in found:
                        found.append(child)
                else:
                    walk(child)
        elif isinstance(node, list):
            for child in node:
                walk(child)

    walk(value)
    return found


class McpSession:
    """An open MCP client: the server's instructions and tools, and `call`."""

    def __init__(self, client: Client):
        self._client = client
        self.instructions: str = client.instructions or ""
        self.tool_list: list[Any] = []

    async def load_tools(self) -> None:
        self.tool_list = list((await self._client.list_tools()).tools)

    @property
    def anthropic_tools(self) -> list[dict]:
        tools = [
            {"name": t.name, "description": t.description or "", "input_schema": t.input_schema}
            for t in self.tool_list
        ]
        if tools:
            tools[-1] = {**tools[-1], "cache_control": CACHE}
        return tools

    async def call(self, name: str, args: dict) -> tuple[str, bool]:
        result = await self._client.call_tool(name, args)
        text = "".join(c.text for c in result.content if getattr(c, "type", "") == "text")
        if not text and result.structured_content is not None:
            text = json.dumps(result.structured_content, ensure_ascii=False, separators=(",", ":"))
        return text, bool(result.is_error)


@asynccontextmanager
async def open_session(params: StdioServerParameters, *, timeout_s: float = 180.0):
    async with Client(params, read_timeout_seconds=timeout_s) as client:
        session = McpSession(client)
        await session.load_tools()
        yield session


def block_dict(block: Any) -> dict:
    """An SDK content block (or the fake's) as a plain dict that can go back into `messages`."""
    d = block.model_dump(exclude_none=True) if hasattr(block, "model_dump") else dict(vars(block))
    if d["type"] == "text":
        return {"type": "text", "text": d["text"]}
    if d["type"] == "tool_use":
        return {"type": "tool_use", "id": d["id"], "name": d["name"], "input": d["input"]}
    return d


def _with_cache_marker(messages: list[dict]) -> list[dict]:
    """Copy of `messages` whose last block carries cache_control (so the growing prefix is reused)."""
    out = copy.deepcopy(messages)
    last = out[-1]
    if isinstance(last["content"], str):
        last["content"] = [{"type": "text", "text": last["content"]}]
    last["content"][-1]["cache_control"] = CACHE
    return out


LogCall = Callable[[str, Usage, float, str], None]
"""(model, usage of this one call, latency_ms, request_id) -> None; writes the cost_log row."""


class Host:
    def __init__(
        self,
        session: McpSession,
        client: Any,
        *,
        model: str = HOST_MODEL,
        max_tool_calls: int = MAX_TOOL_CALLS,
        max_tokens: int = HOST_MAX_TOKENS,
        log_call: LogCall | None = None,
        budget: Budget | None = None,
    ):
        self.session = session
        self.client = client
        self.model = model
        self.max_tool_calls = max_tool_calls
        self.max_tokens = max_tokens
        self.log_call = log_call
        self.budget = budget
        self.system = [{"type": "text", "text": session.instructions, "cache_control": CACHE}]
        self.tools = session.anthropic_tools

    def _estimate(self, messages: list[dict], previous_prompt_tokens: int) -> float:
        chars = len(json.dumps([self.system, self.tools, messages], default=str))
        prompt = int(chars / CHARS_PER_TOKEN)
        reused = min(previous_prompt_tokens, prompt)
        return usd(self.model, 0, EST_OUTPUT_TOKENS, cache_read=reused, cache_write=prompt - reused)

    def _call_model(
        self, messages: list[dict], force_final: bool, turn: Turn, request_id: str, prev: int
    ) -> Any:
        if self.budget is not None:
            self.budget.require(self._estimate(messages, prev), "host call")
        kwargs: dict[str, Any] = {
            "model": self.model,
            "system": self.system,
            "tools": self.tools,
            "messages": _with_cache_marker(messages),
            "max_tokens": self.max_tokens,
        }
        if force_final:
            kwargs["tool_choice"] = {"type": "none"}
        started = time.perf_counter()
        response = _create_without_thinking(self.client, **kwargs)
        latency_ms = (time.perf_counter() - started) * 1000
        u = response.usage
        call = Usage(
            input=getattr(u, "input_tokens", 0) or 0,
            output=getattr(u, "output_tokens", 0) or 0,
            cache_read=getattr(u, "cache_read_input_tokens", 0) or 0,
            cache_write=getattr(u, "cache_creation_input_tokens", 0) or 0,
            api_calls=1,
        )
        call.cost_usd = usd(self.model, call.input, call.output, call.cache_read, call.cache_write)
        turn.usage.add(call)
        if self.budget is not None:
            self.budget.charge(call.cost_usd)
        if self.log_call is not None:
            self.log_call(self.model, call, latency_ms, request_id)
        return response

    async def _run_tool(self, block: Any) -> tuple[ToolCallRecord, dict]:
        args = dict(block.input or {})
        started = time.perf_counter()
        try:
            text, is_error = await self.session.call(block.name, args)
        except Exception as exc:  # a broken call is the model's problem to read, not a crash
            text, is_error = f"Tool call failed: {type(exc).__name__}: {exc}", True
        latency_ms = (time.perf_counter() - started) * 1000
        ids: list[str] = []
        if not is_error:
            with contextlib.suppress(ValueError):
                ids = collect_paragraph_ids(json.loads(text))
        record = ToolCallRecord(
            block.name, args, len(text.encode("utf-8")), latency_ms, is_error, ids, text
        )
        result_block: dict = {"type": "tool_result", "tool_use_id": block.id, "content": text}
        if is_error:
            result_block["is_error"] = True
        return record, result_block

    async def ask(
        self, question: str, history: list[dict] | None = None
    ) -> tuple[Turn, list[dict]]:
        """One question (a turn). `history` is the messages of earlier turns in the same conversation.
        -> (turn, the full message list including this turn)."""
        messages = list(history or [])
        messages.append({"role": "user", "content": question})
        turn = Turn(question=question)
        request_id = f"agentic-{uuid.uuid4().hex[:12]}"
        started = time.perf_counter()
        force_final = False
        prev_prompt = 0
        try:
            while True:
                response = self._call_model(messages, force_final, turn, request_id, prev_prompt)
                prev_prompt = self._prompt_tokens(response, prev_prompt)
                blocks = list(response.content)
                messages.append({"role": "assistant", "content": [block_dict(b) for b in blocks]})
                uses = [b for b in blocks if b.type == "tool_use"]
                if not uses or force_final:
                    turn.answer_text = "".join(b.text for b in blocks if b.type == "text").strip()
                    break
                results: list[dict] = []
                for block in uses:
                    if len(turn.tool_calls) >= self.max_tool_calls:
                        results.append(
                            {
                                "type": "tool_result",
                                "tool_use_id": block.id,
                                "content": LIMIT_MESSAGE,
                                "is_error": True,
                            }
                        )
                        continue
                    record, result_block = await self._run_tool(block)
                    turn.tool_calls.append(record)
                    results.append(result_block)
                if len(turn.tool_calls) >= self.max_tool_calls:
                    force_final = True
                    turn.hit_cap = True
                    results.append({"type": "text", "text": FORCE_FINAL_NOTE})
                messages.append({"role": "user", "content": results})
        except BudgetExceeded as exc:
            turn.status = "skipped_budget"
            turn.note = str(exc)
        turn.latency_ms = (time.perf_counter() - started) * 1000
        return turn, messages

    @staticmethod
    def _prompt_tokens(response: Any, fallback: int) -> int:
        u = response.usage
        total = (
            (getattr(u, "input_tokens", 0) or 0)
            + (getattr(u, "cache_read_input_tokens", 0) or 0)
            + (getattr(u, "cache_creation_input_tokens", 0) or 0)
        )
        return total or fallback
