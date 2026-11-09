# Common rules for every task in the MCP slice (W0, M1, M2, M3): binding, part of your brief

## Project context
`echr-lookup` is a learning and portfolio RAG system over the UK's case law at the European Court of Human Rights (HUDOC), plus the Convention and the Human Rights Act 1998. ParadeDB (BM25 + pgvector) on `localhost:5433`, a local bge-small embedder and bge-reranker-base, FastAPI (`py/api`), a Next.js app (`apps/web`). Every claim cites a paragraph ID like `001-57619§88`. Counting questions are answered by a validated SQL parameter template; the model never writes SQL. Dan (the owner) is technical but new to RAG and MCP.

This slice exposes the retrieval layer as **MCP tools** (Model Context Protocol), so Claude or ChatGPT does the reading and writing while echr-lookup supplies cited evidence, then measures "Claude + tools" against our own `/ask` pipeline. Interfaces: `docs/interfaces-mcp.md` (binding). Contract: `packages/contract/src/mcp/` (zod → JSON Schema in `packages/contract/schema/Mcp*.json`, fixtures in `packages/contract/fixtures/Mcp*.json`).

## Hard boundaries
- **The `/ask` pipeline is the baseline: don't change its behaviour.** `py/rag/answer/**`, `py/rag/search/**` (except what `docs/interfaces-mcp.md` §6 grants M1), `py/api/**`, `apps/web/**` and the eval set `data/eval/questions.jsonl` are read-only in Gate 1.
- Only edit the paths your brief's **Ownership** gives you. No contract edits: if a shape is wrong or missing, `ask` the orchestrator.
- **No new dependencies** unless your brief names them. Never edit another task's files.
- Never print, log or commit secret values. `.env` is gitignored. Never create accounts, cloud resources or anything public. No paid services.
- Build any Anthropic client explicitly from `rag.config` (`anthropic_api_key()`, `anthropic_base_url()`); never from SDK environment defaults (the shell exports a work-proxy `ANTHROPIC_BASE_URL`). Only M2 makes live LLM calls.

## Your environment
- Your worktree `.env` has `DATABASE_URL` → **your own DB** (`echr_<task>`, a copy of the integration DB `echr`: the 98-document snapshot, 36 eval runs), `DATA_SOURCE=snapshot`. Tests use `<your db>_test` via the `db_conn` fixture. Never touch other `echr_*` databases; never `docker compose down -v`.
- **Ports:** only your own (`docs/interfaces-mcp.md` §5). **Never 3000, 3100, 8000 or 8100** (Dan's apps and the orchestrator).
- Setup: `pnpm i` at the root; `cd py && uv sync --group ml` (models are cached locally).
- Long-running processes (servers) in a background shell you stop before `worker_done`, or an Orca terminal.
- zsh: never name a variable `path`; use `pnpm run search`, not `pnpm search`.

## Git (SSH is unreliable here; use HTTPS via gh)
Push: `git -c credential.helper= -c credential.helper='!gh auth git-credential' push https://github.com/hutchida/echr-lookup.git HEAD:<your-branch>`, then `gh pr create --base main --head <your-branch> …`. Commit in logical steps. Keep the PR to your owned paths.

## Quality bar
- `pnpm check` green locally and on the PR's GitHub Actions run (offline: `EMBEDDER=fake`, `LLM_MODE=fake`, no network, under ~2 minutes).
- Tests that need real models are `@pytest.mark.ml`; tests that need network or a paid API are `@pytest.mark.live` (run only with `RUN_LIVE=1`, never in CI).
- Be token-efficient: grep and targeted reads; don't read whole directories. The budget is shared.

## Learning doc: `docs/learn/<task>.md` (required)
Define every term the first time you use it.
1. **What this is, in plain English** (2–4 short paragraphs).
2. **Why it matters**, with one concrete example from this corpus.
3. **How it works here:** files, key functions, a small text diagram.
4. **Try it:** 3–6 try-its, each **exact command → expected output → what it proves**.
5. **Limits / what can go wrong.**

## PR report (in the PR description)
```
## PR report — <task>
- Model: github-copilot/claude-sonnet-5.5
- Wall time: <start> → <PR opened> (UTC, from `date -u`)
- Tokens and cost: unavailable to agent (the orchestrator appends them from `opencode session export`)
- Live spend against cap: <$ from cost_log, or "none (no live calls)"> / <cap>
- Bottlenecks: <waits, retries, flaky checks, unclear instructions, contract gaps>
- Checks run + results: <each acceptance check, pass/fail, with numbers and timings>
- Learning doc: docs/learn/<task>.md
```
Never estimate a metric: write "unavailable".

## Finishing
1. Push your branch and open one PR to `main`. Make sure CI is green (`gh pr checks <n> --watch`).
2. Stop your servers. Send `worker_done` once, with a three-sentence summary and the PR URL.
3. Keep your context: the orchestrator may send review follow-ups. If you're blocked for more than 15 minutes on something only the orchestrator can decide, use `ask`.
