# MCP slice brief (Dan, 2026-11-04; verbatim copy for resuming sessions)

## Role
Orchestration session for a new slice of an EXISTING project, in opencode inside Orca with the Orca CLI. Prepare interfaces, split the work into tasks (one worktree and one self-contained brief each), launch and monitor workers, review and merge, report to Dan. Learn exact commands from `orca --help` and `orca skills get orca-cli|orchestration`; never guess flags.

Read first (targeted): `docs/orchestration/retrospective.md` §4–7, `docs/interfaces.md`, `packages/contract/`, `py/rag/search/`, `py/rag/answer/` (the stats template), `py/api/`.

## Operating rules
- **The orchestrator doesn't write feature code.** Exceptions: per-gate prep (interfaces doc, contract additions, fixtures) and doc/copy edits under ~20 lines. Everything else goes to a worker.
- **Keep context small.** Poll with a script that prints only deltas. Waits under 5 minutes while context is large, or end the session and resume fresh from `handoff.md` + `status.md`. Hand off at ~120K tokens or at each gate.
- **Owner reviews are asynchronous.** Write what to check in `status.md`, message Dan, end the session. A fresh session resumes when he replies.
- Long jobs (servers, evals) run in Orca terminals, never opencode background shells.
- Every task writes `docs/learn/<task>.md` (plain English, why, how, 3–6 try-its with command → expected → what it proves, limits).

## Models and budget
- Orchestrator `github-copilot/claude-opus-5.5`; workers `github-copilot/claude-sonnet-5.5` (confirmed 21:05 with one-line calls).
- App runtime for the comparison eval: `claude-sonnet-5-5` (host model with tools) and the existing Sonnet judge, via `ANTHROPIC_API_KEY`. Build the client explicitly from config, never from SDK env defaults.
- **Budget $25 all-in** (agents + app runtime). Message Dan at $12 and $20; pause launches at $25. Report the orchestrator's share at each gate; aim under 35%.
- **Live-call caps:** M2 $8 total. No other task makes live LLM calls. A worker asks before exceeding its cap; refuse or escalate to Dan with the new total, never approve step by step.

## Slice: echr-lookup as an MCP server
**Goal:** expose the retrieval layer (hybrid search, paragraphs, cases, the safe stats template, corpus scope) as MCP tools, so Claude or ChatGPT does the reading and writing while echr-lookup supplies cited evidence. Then measure whether "Claude + tools" beats our `/ask` pipeline on the same questions. The Next.js app stays as is.

**Already in place (don't recreate or change):** repo, ParadeDB, local embedder + reranker, FastAPI 8000, web 3100, snapshot (98 docs) and full corpus, the contract, `cost_log`, the 71-question eval set (draft), the 10 owner-review questions. The `/ask` pipeline is the baseline: don't change it. Secret names only: `ANTHROPIC_API_KEY`.

### Gate 0: land and prep (no workers before this is merged and main is green)
- **W0 (worker):** the uncommitted refactor A–G. Review, PR, `pnpm check`, free retrieval eval, refresh S4 and I1 learning docs. Merge. Main clean before any worktree.
- **Prep (orchestrator):** contract additions in `packages/contract/src/mcp/` for every tool's input and output, fixtures from the real snapshot, exported to JSON Schema; contract tests (fixtures validate; search results ≤ 10; each tool result ≤ 25 KB). `docs/interfaces-mcp.md`: tool names, signatures, which `py/rag` functions each calls, ports (MCP HTTP 8100; workers 810N), file ownership. Environment check: free ports, scrubbed `ANTHROPIC_BASE_URL`/`ANTHROPIC_AUTH_TOKEN`, git push works.

### The tools (read-only; no LLM calls inside the server)
Every result includes a small `corpus` block: document count, `data_source`, "UK cases only", and in snapshot mode "small committed sample, not the full HUDOC download".
1. `search_case_law(query, article?, doc_type?, outcome?, year_from?, year_to?, limit=8)`: hybrid + rerank, filtered by `data_source`. Each hit: `paragraph_id`, case name, `doc_type` + plain label, date, Articles, section; a verbatim quote containing the matching sentence, at sentence boundaries (A–G quote-window code); `hudoc_url`; a `cite` string like `[Chahal v. the United Kingdom, Judgment, §79]`.
2. `get_paragraphs(paragraph_ids, neighbours=0..2)`: full text plus neighbours, with section labels.
3. `get_case(case_id)`: metadata, outcome, operative provisions, section outline with paragraph ranges.
4. `count_cases(...)`: the validated parameter template; the model never writes SQL. Returns every number asked for (scope total + subset), filters in plain words, definitions, the exact SQL, up to 20 matching cases. No paragraph citations for the count.
5. `corpus_info()`: counts by doc type, Article, outcome, year range; what's missing (scanned decisions, Commission reports) and why.
6. `check_quote(paragraph_id, quote)`: deterministic verbatim check; true/false and the closest match.

Server `instructions` and tool descriptions carry, briefly: cite a `paragraph_id`/`cite` after every claim, quote only verbatim (use `check_quote`); answer first, matching the reach of the holding (no bare Yes/No unless a cited paragraph states the general rule); `count_cases` for any how-many question; say what the corpus covers ("not found here" ≠ never decided); neutral (no view on UK membership or whether a law/judgment is good; value questions get the strongest sourced points on each side). Annotate every tool read-only. Official Python MCP SDK.

### Gate 1: build (parallel, disjoint paths)
- **M1 MCP server.** Owns `py/mcp/`, `scripts/mcp*`, `infra/migrations/mcp_*` (`tool_log`: tool, args, latency, result size, data_source; never wiped by `reset()`). Calls `py/rag` directly, not HTTP. stdio + streamable HTTP on 8100; `pnpm run mcp:stdio`, `pnpm run mcp:http`. Setup docs for Claude Desktop (absolute paths) and Claude Code (`claude mcp add`); note what ChatGPT and claude.ai need (public HTTPS URL + auth) so they wait for M3; check current docs. Acceptance: pytest with an MCP client over stdio lists all six tools and calls each with fixtures; every result validates against the contract; search < 3 s, others < 1 s, each result ≤ 25 KB.
- **M2 Comparison eval.** Owns `py/rag/eval/agentic/`, `docs/mcp-comparison.md`. Harness runs Claude Sonnet 5.5 over the API with the MCP tools (MCP client over stdio, list tools, pass as tool definitions, tool loop, ≤ 8 tool calls per question). Build against M1's contract/fixtures with a fake server, switch to the real one after M1 merges. Runs the 10 owner-review questions ×3 and a fixed random 30 retrieval questions ×1, then the same through `/ask`. Per question: answer and tool calls; agentic recall (gold paragraphs among everything fetched); citation accuracy (existing judge, multi-citation answers scored together); verbatim-quote rate (`check_quote`); owner-review shape check; tokens, cost, latency. Side-by-side table + 10 transcripts in `docs/mcp-comparison.md`. Hard cap $8.
- **M3 Hosting spike (research + local build, no spending).** Owns `infra/deploy/`, `docs/hosting-options.md`. Dan knows Netlify and would like to stay in that ecosystem if possible. Dockerfile for API + MCP (models baked or cached), runnable locally with compose; measure RAM and cold start. Compare 3 hosts that can run it next to Postgres with pgvector + BM25: monthly cost, RAM, ParadeDB or a BM25 fallback. Auth for claude.ai custom connectors and ChatGPT from current docs. Recommend one. No accounts or resources.

Merge order: M1, M3, then M2 (switched to the real server). Gate 1 check: `pnpm check` green; M1 acceptance passes; M2 table within cap; M3 image runs locally.

### Owner review (async)
Message Dan with the Claude Desktop setup snippet, the 10 owner-review questions and the M2 table. He tries them in Claude Desktop and replies pass/fail per question. Failures go back to the right worker; re-run M2 for failed questions only, within its cap.

### Finish
- `docs/learn/mcp.md`: what MCP is, tools vs `/ask`, what moved to the host model, try-its.
- Decision memo in `docs/mcp-comparison.md`: does Claude + tools beat `/ask` on usefulness, citation accuracy, recall? Is remote hosting worth it, at what monthly cost?
- `docs/orchestration/report.md`: per-task time, tokens, cost, models, plus the orchestrator's share.

### PR report (every PR)
Model; wall time; tokens and cost ("unavailable" if unknown, never estimate); live spend against cap; bottlenecks; checks with numbers; learning doc link.

### Ask Dan before
Spending money or creating hosted resources; making anything public or changing secrets; changing `/ask` or the eval set; exceeding a cap or the $25 budget.
