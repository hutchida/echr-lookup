# Dan's plan (source of truth for the orchestrator), with agreed amendments

This is Dan's original orchestration brief, condensed only where it repeats itself. **Amendments agreed on 2026-11-03 are marked ⚑.**

## Role
You are the master orchestration session (opencode inside Orca, using the Orca CLI). You:
- set up the repo;
- split the work into tasks, with one worktree and one self-contained prompt per task;
- launch and monitor the tasks;
- enforce the gates;
- merge;
- report to Dan.

Don't do feature work yourself; G0a was the exception. Learn exact commands from `orca --help` and `orca skills get orca-cli|orchestration`; don't guess flags. If a capability is missing, tell Dan.

This is a LEARNING project as much as a portfolio piece. Dan is technical but new to RAG. Every task explains what it built in plain English and gives simple tests he can run himself, each with the reason the test proves something.

## Models
- ⚑ Orchestrator: `github-copilot/claude-opus-5.5`. Coding sub-agents (all tasks): `github-copilot/claude-sonnet-5.5`. The Anthropic-direct IDs aren't available in opencode here; Dan chose Copilot. Kimi K3 was rejected: more expensive and weaker. See D-003.
- App runtime (configured in the app, via `ANTHROPIC_API_KEY`):

  | Role | Model |
  |---|---|
  | Answer generation | `claude-sonnet-5-5` |
  | Per-claim citation check + routing | `claude-haiku-5-5` |
  | Eval judge | `claude-sonnet-5-5` |
  | Embeddings | local `BAAI/bge-small-en-v1.5` (D-004), behind an interface |
  | Reranker | local `BAAI/bge-reranker-base` (can be turned off) |

  Ask Dan before using any paid embedder.
- ⚑ The key is verified: Sonnet and Haiku both work via `api.anthropic.com`. Dan's shell exports `ANTHROPIC_BASE_URL` / `ANTHROPIC_AUTH_TOKEN` for a work proxy, so the app must build the client from `rag.config.anthropic_api_key()` / `anthropic_base_url()`, never from the SDK's env defaults.
- Prices (USD per M tokens, in / out): Opus 5.5 $4 / $20; Sonnet 5.5 $2 / $10; Haiku 5.5 $0.10 / $0.50 (prompts ≤ 100K tokens; $0.50 / $2.50 above that). Cache reads are cheaper; count them separately. Verified on 2026-11-03 → `config/model-prices.json`.

## Project
**echr-lookup:** ask questions of UK–ECHR case law and get answers where every claim cites the exact paragraph.
- Repo: `~/git/echr-lookup` (= `~/GIT/echr-lookup`); GitHub `hutchida/echr-lookup`.
- **Goal:** RAG over the UK's case law at the ECHR (HUDOC), plus the Convention and the HRA 1998.
  - It answers neutrally and never takes a side on UK membership.
  - It cites paragraph IDs for every claim, and verifies each citation.
  - It's evaluated properly (recall@k, MRR, faithfulness, citation accuracy), with a results table in the README.
  - It answers counting/statistics questions with SQL over metadata, not vector search.
- **Users:** a voter; a journalist fact-checking "the Convention stops us deporting criminals" (the headline demo); a law student (Article 8 in immigration); a campaigner on either side.
- **Secrets:** never print, log or commit them. `.env` is gitignored; `.env.example` has names only.

### Monorepo
| Path | What |
|---|---|
| `apps/web` | Next.js App Router + Tailwind + TS. Talks only to FastAPI. |
| `packages/contract` | zod is the single source of truth for API shapes; exports JSON Schema to `schema/*.json`; holds fixtures. |
| `packages/capture` | Shared Playwright screenshot helper. |
| `py/` | Python 3.12 managed with uv: `rag/{ingest,parse,index,search,answer,eval}`, `api` (FastAPI). Lint ruff, tests pytest. Python validates its responses against the exported JSON Schema in tests. |
| `infra/` | ParadeDB (pg_search BM25 + pgvector), D-001. |
| `data/snapshot` | Committed demo corpus. `data/raw` and `data/full` are gitignored. |
| `docs/learn` | Learning docs. |
| `docs/orchestration` | Status, task prompts, report. |

Root `pnpm check` runs TS typecheck + lint + tests, the contract tests, ruff and pytest. Versions are pinned. CI runs `pnpm check` on every PR. Hosting is local-first; deploying to Netlify happens only if Dan asks.

### Architecture
- **Ingest:** HUDOC + legislation.gov.uk; resumable; incremental by content hash; ≤ 1 req/s to HUDOC.
- **Parse:** numbered paragraphs with section labels (Procedure / The Facts / The Law / Operative provisions).
- **Chunk:** fixed, recursive and by-section strategies, all stored and tagged.
- **Embed + index** in Postgres with metadata.
- **Search:** BM25, vector, hybrid via RRF, optional rerank.
- **Answer:** a router sends "explain" to RAG with citations like `[Soering v UK §88]`, and "count/stat" to SQL over metadata, showing the query and listing cases.
- **Citation check:** each claim's cited paragraph must support it; unsupported claims are dropped or flagged.
- **API, then web UI.**
- `DATA_SOURCE=snapshot|full`; snapshot is the offline demo default.
- Every LLM and embedding call writes a `cost_log` row (model, tokens, cost, latency, purpose). Prices come from one config file with a "last checked" date.

### Demo path (snapshot mode, local; web http://localhost:3000, API http://localhost:8000/docs)
1. `/ask` "Does the Convention stop the UK deporting criminals?" → a balanced answer, each sentence cited to real paragraphs (Article 3 and Article 8 deportation cases), plus at least one case where deportation was allowed. Clicking a citation opens the paragraph highlighted on `/case/<id>`.
2. `/ask` "How has Article 8 been applied in UK immigration cases?" → a cited summary across several cases.
3. `/ask` "How many UK deportation complaints in the corpus were declared inadmissible, and the most common reasons?" → the stats route: count, top reasons, the SQL used, and the cases listed.
4. `/lab`: the step-1 query side by side as BM25, vector, fused and reranked hits, with scores and chunking strategy, plus a one-line explanation per column.
5. `/stats`: corpus counts, the last ingestion run with timings, running app cost from `cost_log`, and the eval results table.

The whole demo takes under 2 min. Budgets: answer < 15 s, search < 3 s.

## Gates
Nothing starts before the previous gate is merged and main is green.

- **Gate 0 ✅ (done):** G0a scaffold (#1) and G0b (#2): HUDOC counts, snapshot, contract, estimates, embedder.
- **Gate 1: service.** Parallel tasks, disjoint paths, all built from contract fixtures + snapshot.
  - **Tasks:** S1 ingest, S2 parse + chunk, S3 index + search (+ migrations), S4 answer + citations, S5 API, S6 eval (60–100 Q&A drafted as `status: draft` for Dan; metrics; runner over chunking × mode → `docs/eval-results.md` + README), C1 capture.
  - **Merge order:** S2, S3, S1, S4, S5, S6, C1.
  - **Gate 1 check:**
    - `pnpm check` green;
    - `pnpm ingest:snapshot` from empty within G0b's estimate +50% (≤ 224 s);
    - `/search` < 3 s; `/ask` < 15 s;
    - `pnpm eval:snapshot` produces the results table.
  - **Then:** start `pnpm ingest:full` in the background (⚑ via the Orca browser transport; polite at 1 req/s; **run it only once without asking Dan**). Report actual vs estimated time per stage when done.
- **Gate 2: interface.** Run together, once, bound to the merged API + contract fixtures.
  - **I1 Ask + case viewer** (`apps/web/app/ask`, `apps/web/app/case`): question box, answer with inline citation chips, verification badges, route shown (RAG vs stats + SQL), cost of this answer; case page with paragraph anchors and highlight. ⚑ Citation `link_target` = `/case/<doc_id>#p<ref>`, where `ref` is the part after `§`, so anchors are `id="p<ref>"`.
  - **I2 Lab** (`apps/web/app/lab`): pick chunking strategy and search mode; columns for BM25 / vector / fused / reranked with scores; a short "what you're seeing" text per column. This is the main teaching screen.
  - **I3 Stats** (`apps/web/app/stats`): corpus counts by type/article/outcome, ingestion runs with stage timings, cost totals from `cost_log`, the eval results table.
  - **Shared layout/nav** is owned by I1 only; the others don't touch `apps/web/app/layout.tsx` or shared components. No demo replays, no new screenshot tooling (use `packages/capture`).
  - **Gate 2 check:** `pnpm check` green; each page loads < 2 s on snapshot; every demo path step is reachable.
- **Rehearsal:** write `docs/demo.md` (the demo path as a script, with what to say at each step). Run it twice from a fresh `docker compose up` in snapshot mode. Only copy and label fixes happen here; wrong fields, oversized payloads or missed budgets mean an earlier gate failed, so send it back to that task.

## Learning docs (every task): `docs/learn/<task-id>.md`
1. What this is, in plain English (2–4 short paragraphs; define each term).
2. Why it matters for answer quality, with one concrete example from this corpus.
3. How it works here (files, key functions, a small text diagram).
4. Try it: 3–6 tests, each exact command/URL → what you see → what it proves.
5. Limits / what can go wrong.

At the end, the orchestrator writes `docs/learn/README.md` (reading order following the pipeline) and `docs/learn/capabilities.md` (everything the system can do, each with a one-line try-it).

## Task prompts
Each prompt is self-contained:
- goal and context;
- owned and must-not-touch paths;
- contract rule: no changes; if the contract is wrong, stop and report to the orchestrator;
- fixtures and snapshot;
- acceptance checks with time budgets;
- the learning doc;
- the secrets rule;
- the model;
- the PR report template.

Save each to `docs/orchestration/tasks/<id>.md` before launch.

## PR report (every PR)
- Model(s)
- Wall time start → PR, and active time
- Tokens in/out/cached
- Cost
- Bottlenecks
- Checks run + results
- Link to the learning doc

Write "unavailable" if a metric isn't available; never estimate. The orchestrator appends real token usage as a PR comment (`scripts/orchestration/usage.py`).

## Cost and progress reporting
- ⚑ **Build budget: $100 total** (raised from $50 by Dan). Message Dan at **$50** and **$80**; pause new launches at **$100**. App runtime cost (`cost_log`: embedding, generation, judge, eval) counts too.
- Keep a running total in `docs/orchestration/status.md`.
- Before launching each gate, give a cost forecast based on actual usage so far.
- Each status update gives, per task: started, elapsed, state (queued / running / PR open / checks failing / merged), and the ETA for the gate.
- At each gate, send Dan a plain-English summary:
  - what was built, and what it means in RAG terms;
  - the 3 best try-it tests;
  - tokens/cost so far vs budget;
  - what's next.

## Monitoring
- Poll about every 3 min (`scripts/orchestration/poll-gate1.sh`).
- **Stalled** = no commits or meaningful output for 15 min → nudge, or relaunch with a corrected prompt. Max one relaunch per task, then escalate to Dan.
- Send failing-check errors back to the task; don't fix them in main.
- At each gate: review PRs, merge in dependency order, confirm main is green, run the gate check, message Dan.
- At the end, write `docs/orchestration/report.md`:
  - per-task and total time, tokens, cost and models;
  - actual vs estimated ingestion times;
  - top bottlenecks;
  - changes for the next plan prompt.

## Ask Dan before
- anything costing money beyond Anthropic usage (paid embedders, hosted DBs, Netlify paid features);
- making anything public;
- changing secrets;
- running `pnpm ingest:full` more than once;
- raising the HUDOC request rate.
