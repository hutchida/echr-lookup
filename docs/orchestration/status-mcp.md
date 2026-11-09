# Orchestration status: MCP slice

_Last updated: 2026-11-04 22:38 UTC · **BUDGET EXCEEDED ($32.9 of $25): launches paused, waiting for Dan** · Gate 1 merged (M1 #26, M3 #27, M2 #25); no workers running_ · Orchestrator #4: `github-copilot/claude-opus-5.5` (session `ses_e579d1058ffe7fiiTqo0k7lgWX`) · Orca run `run_aeba880d36a2` · Previous build: [`status-build1.md`](status-build1.md), [`handoff-build1.md`](handoff-build1.md)

Brief: Dan's MCP-slice prompt (goal, tools, gates, budget), summarised in [`handoff.md`](handoff.md). Interfaces: [`../interfaces-mcp.md`](../interfaces-mcp.md) (Gate 0 prep).

## Budget ($25 all-in: agents + app runtime)
Tell Dan at **$12** and **$20**; pause launches at **$25**. Orchestrator share target < 35% (≈ $8.75). Live-call caps: **M2 $8**; no other task makes live LLM calls.

| Checkpoint (UTC) | Agents (budget figure) | App runtime | Total | Orchestrator share |
|---|---|---|---|---|
| 21:14 | $1.60 (orch $1.54, W0 $0.06) | $0 | $1.60 | 96% (setup) |
| 22:45 (Gate 1 merged; no workers) | **$27.62** (orch #4 $15.51, M2 $5.43, others as below) | **$5.27** (M2, cap $8) | **$32.89 (over $25)** | 56% |
| 22:36 (M1, M3 merged; M2 mid-run) | **$25.06** (orch #4 $14.06, W0 $0.57, M1 $3.63, M2 $4.32 so far, M3 $2.45, model checks $0.03); opencode figure $16.26 | **$4.42** (M2, `echr_m2` cost_log) | **$29.48 (over $25)** | **48%** |
| 21:38 (Gate 0 done, Gate 1 launched) | $7.37 (orch $6.14 + model checks $0.03, W0 $0.57, M1–M3 ≈ $0.4 so far) | $0 | $7.37 | 83% (Gate 0 prep was orchestrator work; Gate 1 should pull it down) |

## Environment check (21:05)
- Models: `github-copilot/claude-opus-5.5` → "OK opus"; `github-copilot/claude-sonnet-5.5` → "OK sonnet" (one-line `opencode run` each).
- Ports: 8100–8104 free; 8000 (API) and 3100 (web) in use by Dan's running app (leave them). DB container `echr-lookup-db-1` healthy on 5433.
- Shell exports a work-proxy `ANTHROPIC_BASE_URL` and an `ANTHROPIC_AUTH_TOKEN`; `rag.config.anthropic_base_url()` ignores them (uses `ECHR_ANTHROPIC_BASE_URL` or api.anthropic.com). The app key comes from the repo `.env` only.
- Git: SSH push works (`git push --dry-run`), `gh` logged in with `repo` scope.
- Per-worker DBs `echr_w0`, `echr_m1`, `echr_m2`, `echr_m3` copied from `echr` (98 snapshot docs, 36 eval runs). Worker `.env`s have no `ANTHROPIC_API_KEY` except M2's.
- The uncommitted refactor A–G was committed to branch `wip/refactor-a-g` (`6b786fb`), so main is clean.

## Gates

| Gate | State | Notes |
|---|---|---|
| G0: W0 land A–G | ✅ merged 21:28 (#23, `f999386`) | A–G all OK on review, no code fixes; pnpm check green (py 552/4 skipped); retrieval eval unchanged (recursive hybrid_rerank R@5 0.17, R@10 0.28, MRR 0.16, case hit@10 0.90); S4/I1 docs refreshed, `docs/learn/W0.md`; $0.57; worker released |
| G0: prep | ✅ merged 21:33 (#24, `0432dc2`), main CI green | `packages/contract/src/mcp/` (12 schemas, 16 real-snapshot fixtures, `test/mcp.test.ts`), `docs/interfaces-mcp.md`, `data/eval/owner-review.jsonl` (draft), `mcp` 2.3.0 SDK dependency. pnpm check: contract 124, web 111, capture 21, pytest 568/4 skipped |
| G1: M1, M2, M3 | ✅ all merged by 22:45 (#26, #27, #25) | Gate 1 check pending main CI on `6deacf7`; owner review needs Dan (budget decision first) |
| Owner review (async) | ⏳ | |
| Finish (learn/mcp.md, memo, report) | ⏳ | |

## Tasks

| Task | Started | State | PR | Dispatch | opencode session |
|---|---|---|---|---|---|
| W0 refactor A–G | 21:12 | ✅ merged 21:28; released | #23 | `ctx_4f45bcfbd96a` | `ses_e5798b534ffePddhFoTxDNayCB` |
| M1 MCP server | 21:34 | ✅ merged 22:01 (`8898617`). Low-level SDK v2 server, contract schemas, stdio + HTTP; 82 offline tests; ml acceptance: count 9/10, check_quote verbatim, Othman hits; warm medians search 1.07 s (1.70 s under load), others ≈ 0.015 s; results 0.5–9 KB; $3.63; worker released | #26 | `ctx_f213806ba640` | `ses_e57844073ffe6vVkmMQK22dTuN` |
| M2 comparison eval (live cap $8) | 21:34 | ✅ merged 22:45 (`6deacf7`): live $5.27 of $8, no cuts; owner-review shape pass 22/30 tools vs 16/30 /ask; recall 60% vs 23%; per-claim citation accuracy 91–94% vs 95–96% but 58–65% of tool-answer claims uncited; ≈ 2× cost and latency; 3 of 30 /ask subset answers missing (Anthropic API usage limit hit at the end); agent $5.43; released. Earlier: | phase 1 done 21:52: draft PR, CI green, scope OK (22 files, owned paths); live $0.048 of $0.25 pre-merge. 22:02 told to switch (reply to `msg_289e26615054`): rebase, pilot, full run per plan | #25 | `ctx_684eb12b75e1` | `ses_e5784396cffeEFPljyY4An4lH9` |
| M3 hosting spike | 21:34 | ✅ merged 22:36 (`86b9d45`): image 2.8 GB, RAM 0.8–1.1 GiB/process, MCP first search 2.8 s; CPU-bound reranker (15.2/8.0/4.5 s at 1/2/4 vCPU); Netlify can't host the container or pg_search; recommends web on Netlify + compose on Hetzner CPX32 ≈ €36/month; six MCP tools verified at :8103; $2.45; released. Earlier: phase 1 done 22:26; told to rebase + phase 2. **Grant:** one edit in `py/echr_mcp/__main__.py` (+1 test): `--host`/`MCP_HOST` (default 127.0.0.1) and `MCP_ALLOWED_HOSTS` for the container; protection stays on | #27 | `ctx_570856be40ad` | `ses_e57843262ffeJjp8xr6w0gUWRm` |

## Decisions log
- 21:10 Main was dirty with the A–G refactor; committed it to `wip/refactor-a-g` and based W0's worktree on it (no worktree from a dirty main).
- 21:10 `count_cases` will compose `rag.answer.stats` helpers from `py/mcp` without editing `stats.py` (the `/ask` baseline stays untouched); a parity test against `run_stats` guards drift.
- 21:10 The "10 owner-review questions" existed only as examples in `one-shot-prompt.md` §8 (items 8–10 not concrete, 8–10 UI-specific). Prep writes a concrete MCP version to `data/eval/owner-review.jsonl` (status: draft) for Dan.

- 21:20 M1's package is `py/echr_mcp/`, not `py/mcp/`: a package named `mcp` would shadow the SDK's own `import mcp`.
- 21:20 `search_case_law` filters by `data_source` by dropping hits from other sources after over-fetching (k=30), because `rag.search` has no such filter and stays read-only (each DB holds one source anyway).
- 21:20 `count_cases` answers drop the template's trailing `Examples: [… §op1]` markers: the count must cite no paragraph.
- 21:20 The `mcp` SDK dependency was added once in prep so M1 and M2 don't both edit `pyproject.toml`/`uv.lock`.
- 21:41 M1 asked: `py/pyproject.toml` testpaths miss `echr_mcp`. Approved M1 adding `"echr_mcp"` to `[tool.pytest.ini_options] testpaths` (that line only).
- 21:30 M2 cap plan: ≤ $0.25 live before M1 merges; pilot; full run planned ≤ $6.00 with a fixed degrade order; ≥ $1.50 kept for the owner-review re-run.

## For Dan
- **22:38 Budget exceeded: $29.48 all-in vs $25** (agents $25.06 budget figure, app runtime $4.42). I missed the $12 and $20 messages: I processed heartbeats without re-checking the total. Main cause: orchestrator #4's own cost ($14.06, 48%), since every heartbeat woke a ~140K-token context after > 5 min, re-writing the prompt cache (1.48M cache-write tokens). **No new launches.** M2 is mid-run inside its own $8 cap ($4.42 spent, projected ≈ $5 for the run) and was told to finish this run, write the doc and PR, and start nothing else. **Decide:** (a) let M2 finish (≈ +$1.5–2.5 all-in), or stop it now; (b) whether to go on to the owner review, the re-run of failures and the Finish docs (each needs a worker), and with what new ceiling.
- **Draft to approve (no rush, needed before the owner review):** `data/eval/owner-review.jsonl`. The 10 questions existed only as examples in `one-shot-prompt.md` §8; items 8–10 were UI-specific, so I made them concrete for MCP: or-08 a question answered only by a legal summary (Harkins (dec.) [GC], 002-11569), or-09 support in the 3rd sentence of Chahal §79, or-10 a follow-up turn after or-01.
