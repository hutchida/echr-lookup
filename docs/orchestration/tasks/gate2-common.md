# Common rules for every Gate 2 task (I1, I2, I3) — binding, part of your brief

## Project context
`echr-lookup` is a learning and portfolio RAG (Retrieval-Augmented Generation) system over the UK's case law at the European Court of Human Rights (HUDOC), plus the Convention and the Human Rights Act 1998. It answers questions neutrally and never takes a side on UK membership. Every claim cites a paragraph ID like `001-57619§88`, and every citation is verified. Counting questions are answered with SQL over metadata. Dan (the owner) is technical but new to RAG; the web UI is where he and his audience *see* how RAG works.

Gate 1 is merged: ingest → parse + chunk → embed + index → search → answer + citation check + stats SQL → **FastAPI** (`py/api`). Gate 2 builds the Next.js UI on top, three tasks in parallel: **I1** Ask + case viewer (+ shared layout), **I2** Lab, **I3** Stats.

Demo path (snapshot mode; must work end to end after Gate 2; whole demo < 2 min):
1. `/ask` "Does the Convention stop the UK deporting criminals?" → a balanced answer, each sentence cited to real paragraphs (Article 3 and Article 8 deportation cases), plus at least one case where deportation was allowed. Clicking a citation opens the paragraph highlighted on `/case/<id>`.
2. `/ask` "How has Article 8 been applied in UK immigration cases?" → a cited summary across several cases.
3. `/ask` "How many UK deportation complaints in the corpus were declared inadmissible, and the most common reasons?" → the stats route: count, top reasons, the SQL used, and the cases listed.
4. `/lab`: the step-1 query side by side as BM25, vector, fused and reranked hits, with scores and chunking strategy, plus a one-line explanation per column.
5. `/stats`: corpus counts, the last ingestion run with timings, running app cost from `cost_log`, and the eval results table.

Budgets: **every page loads < 2 s** on the snapshot (warm API); an answer < 15 s; a search < 3 s.

## Read first (targeted; don't re-read big files)
- `docs/interfaces.md` **§8–10 (Gate 2: ownership, web conventions, your ports/DB). Binding.**
- `apps/web/lib/api.ts` (the typed client you must use) and `apps/web/lib/api.test.ts` (test style).
- `apps/web/AGENTS.md`: this is Next.js 16 / React 19; check `apps/web/node_modules/next/dist/docs/` before using an API you're unsure of.
- The contract types you render: `packages/contract/src/*.ts` and their fixtures `packages/contract/fixtures/*.json`.
- `docs/learn/C1.md` §3–4 (the screenshot helper `pnpm capture`) and `packages/capture/specs/home.json`.
- The learning docs of the Gate 1 tasks you surface (`docs/learn/S3.md` search, `S4.md` answer/citations, `S5.md` API, `S6.md` eval): skim sections 1 and 3 only.

## Contract rule
**No contract or API changes.** `packages/contract/**`, `py/**` and `apps/web/lib/api.ts` are read-only. If a shape is wrong or something you need is missing, stop and `ask` the orchestrator (your Orca preamble's ask command). Don't work around it.

## Ownership
Only edit the paths `docs/interfaces.md` §8 gives your task. No new dependencies; no edits to any `package.json`, the lockfile, Next/TS/ESLint config. `next dev` may touch `apps/web/next-env.d.ts` or `apps/web/AGENTS.md`: don't commit those (`git checkout -- <file>`).

## Your environment
- Your worktree `.env` already has `DATABASE_URL` → **your own DB** (`echr_i1|i2|i3`, a copy of the integration DB with the snapshot corpus loaded and 12 eval runs), `DATA_SOURCE=snapshot`, `EMBEDDER`/`RERANK_ENABLED` for real search, and your `API_PORT` / `WEB_PORT` / `API_URL` (§10). Never touch other `echr_*` databases; never `docker compose down -v`. If the DB container is down: `docker compose up -d --wait`.
- **Ports:** only your own (§10). **Never 3000 or 8000.**
- Setup: `pnpm i` at the root; `cd py && uv sync --group ml` (models are cached locally).
- Run the API in an Orca terminal or background shell: `API_PORT=800N pnpm dev:api` (first start loads the embedder/reranker, ~10–20 s). Run the web: `API_URL=http://localhost:800N WEB_PORT=310N pnpm dev:web`. Stop both before `worker_done`.
- Measure page loads with `curl -s -o /dev/null -w '%{time_total}\n' 'http://localhost:310N/<page>'` (warm: run twice, report the second) and with your capture specs.

## Git (SSH is broken on this machine; use HTTPS via gh)
Push: `git -c credential.helper= -c credential.helper='!gh auth git-credential' push https://github.com/hutchida/echr-lookup.git HEAD:<your-branch>`, then `gh pr create --base main --head <your-branch> …`. Fetch the same way. `gh` itself works normally.

## Secrets and money
- Never print, log or commit secret values. `.env` is gitignored.
- Only I1 has `ANTHROPIC_API_KEY` (live `/ask`), with a **$1.00 live-call allowance** (one RAG answer ≈ $0.05–0.10; check `cost_log` in your DB). I2 and I3 make no LLM calls.
- No paid services.

## Quality bar
- `pnpm check` green locally and on the PR's GitHub Actions run (offline, fast).
- Unit-test display logic as pure functions on the contract fixtures (vitest `node` env, see §9). Every error state (`ApiResult.ok === false`) renders a readable message.
- Accessible basics: labelled inputs, real links (`<a>`/`<Link>`) for navigation, visible focus, no information carried by colour alone.
- Commit in logical steps at least every ~45 minutes. Keep the PR to your owned paths.
- Be token-efficient: grep and targeted reads. The build budget is shared.

## Screenshots
Write 1–3 capture specs `packages/capture/specs/<id>-*.json` (baseUrl `http://localhost:3100`, the demo port; run them with `--base-url http://localhost:310N`) that wait for real content, then screenshot into `docs/learn/img/<id>-*.png`. Embed them in your learning doc. If Chromium is missing: `pnpm --filter @echr/capture exec playwright install chromium`.

## Learning doc: `docs/learn/<id>.md` (required)
Dan is technical but new to RAG. Define every term the first time you use it.
1. **What this is, in plain English:** 2–4 short paragraphs.
2. **Why it matters for answer quality:** one concrete example from this corpus.
3. **How it works here:** files, key functions, a small text diagram (browser → Next server → FastAPI → Postgres).
4. **Try it:** 3–6 tests Dan can run himself. Each is an exact URL or command → what he should see → what it proves.
5. **Limits / what can go wrong.**

## PR report (put it in the PR description)
```
## PR report — <id>
- Model(s): github-copilot/claude-sonnet-5.5
- Wall time: <start> → <PR opened> (UTC, from `date -u`); active time: <value or "unavailable">
- Tokens in/out/cached: unavailable to agent — orchestrator appends from `opencode session export`
- Cost: unavailable to agent — orchestrator appends. Live Anthropic spend during development (from cost_log): <$ or "none">
- Bottlenecks: <waits, retries, flaky checks, unclear instructions, contract gaps>
- Checks run + results: <each acceptance check, pass/fail with key numbers and timings>
- Screenshots: <paths>
- Learning doc: docs/learn/<id>.md
```
Never estimate a metric. Write "unavailable" instead.

## Finishing
1. Push your branch (HTTPS, above) and open one PR to `main` with `gh pr create`.
2. Make sure CI is green (`gh pr checks <n> --watch`).
3. Stop your dev servers. Send `worker_done` once, with a three-sentence summary and the PR URL.

Keep your context afterwards: the orchestrator may send review follow-ups. If you're blocked for more than 15 minutes on something only the orchestrator can decide, use `ask`.
