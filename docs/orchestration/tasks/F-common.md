# Common rules for the follow-up slice (F1, F3): binding, part of your brief

Read `docs/orchestration/tasks/mcp-common.md` first (project context, git over HTTPS via gh, quality bar, learning-doc format, PR report, finishing). This file overrides or adds to it.

## Overrides
- The MCP server package is `py/echr_mcp/` (not `py/mcp/`: that name would shadow the SDK's `mcp`). Contract: `packages/contract/src/mcp/`, schemas `packages/contract/schema/Mcp*.json`, fixtures `packages/contract/fixtures/Mcp*.json`.
- Your worktree: `~/orca/workspaces/echr-lookup/<task>`; DB `echr_<task>` (copy of `echr`; `.env` already points at it). F1 port: MCP HTTP 8101 if needed. F3 port: 8102 if needed. Never 3000, 3100, 8000, 8100.
- Only **F3** has `ANTHROPIC_API_KEY` in its `.env`, and only for the paid re-run. F1 makes no live calls at all.
- Models: you run as `github-copilot/claude-sonnet-5.5`.

## Hard rules (Dan's)
- **Never change paragraph IDs**: the eval answer keys depend on them. Labels are display-only.
- Don't change the `/ask` pipeline (`py/rag/answer/**`, `py/api/**`), the search code (`py/rag/search/**`) or the eval question files (`data/eval/questions.jsonl`, `data/eval/owner-review.jsonl`).
- Every task writes or updates `docs/learn/<task>.md` with try-its (exact command → expected output → what it proves).
- Anthropic clients are built from `rag.config` (`anthropic_api_key()`, `anthropic_base_url()`), never from SDK environment defaults (the shell exports a work-proxy base URL).
- Ask the orchestrator (`ask`) before exceeding your cap or touching anything outside your ownership.

## Budget (all-in $10 for the whole slice, including the orchestrator and the live re-run)
Be token-efficient: grep and targeted reads, no whole-directory dumps, don't re-read files you've already read, keep command output short (`| tail`, `| head`). Soft targets for your own agent cost: F1 ≈ $2.50, F3 ≈ $2.00 (excluding F3's live calls, hard cap $5).

## Paid-vs-free
Everything except F3's M2 re-run is free and offline (`EMBEDDER`/models are local; `LLM_MODE=fake` for tests).
