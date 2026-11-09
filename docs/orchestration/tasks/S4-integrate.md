S4 integration follow-up (same worktree `~/orca/workspaces/echr-lookup/s4`, branch `hutchida/s4`, PR #8, DB `echr_s4`, which has the API key). Your original brief `docs/orchestration/tasks/S4.md` still applies (owned paths, contract rule, secrets, PR report, learning doc, live-spend allowance $1.50 in total).

**Context:** S2 (`rag.parse`, #9) and S3 (`rag.index`, `rag.search`, migrations, #10) are merged to `main`, and CI is green. S1 (`rag.ingest`) is in its own integration follow-up and merges next. This work runs in two phases so you aren't idle while S1 finishes.

**Phase A (now):**
1. Rebase `hutchida/s4` onto `origin/main`. Switch from your fakes to the real `rag.index.log_cost` and `rag.search.search` / `get_reranker`, keeping fakes only where the tests need them offline (CI defaults: `EMBEDDER=fake`, `LLM_MODE=fake`, `RERANK_ENABLED=0`). Turn the skip-if-missing integration tests into real ones where possible.
2. Fill `echr_s4` for development with S3's dev loader: `cd py && uv run --group ml python ../scripts/s3/load_snapshot_dev.py --reset --strategies recursive fixed by_section`. It loads the HTML documents (no legislation) using the G0b prototype parser. bge-small and the reranker are in the default HF cache.
3. Do a **dry run** of the three demo questions against it with `pnpm ask "<q>"`, and tune the "deportation" text-match definition for Q3. Keep live spend small: at most one run of each question in phase A.
4. Push the rebased branch, and keep CI green.
5. Then **block** with `orca orchestration ask` (from your preamble): "S4 phase A done (<one line>). Ready for phase B once S1 merges?" Wait for the reply. Don't poll, and don't send `worker_done` yet.

**Phase B (after my reply says S1 is merged):**
1. Rebase onto `origin/main` again. Then `pnpm ingest:snapshot --reset`, the real ingest into `echr_s4` (it replaces the dev-loader data).
2. Run the three demo questions end to end with `pnpm ask` (Q1 deportation, Q2 Article 8 immigration, Q3 inadmissible-deportation stats; exact wording in your brief). Save the transcripts to `docs/learn/S4-demo.md`. Requirements:
   - Q1 is balanced and cites at least one case where deportation was allowed.
   - Q3 takes the stats route and shows its SQL.
   - Each call takes **< 15 s**; include the per-step latency and the cost per question.
3. Update `docs/learn/S4.md` if anything changed. Update the PR #8 description with real numbers (and total live spend from `cost_log`). Push, get CI green, then send `worker_done`.

**Constraints:** only S4's owned paths (`py/rag/answer/**`, `docs/learn/S4.md`, `docs/learn/S4-demo.md`). Don't edit `rag.parse`, `rag.index`, `rag.search`, `rag.ingest`, migrations, the contract or `config.py`. If a merged module misbehaves or a seam is wrong, `ask`; don't patch around it.

**Acceptance:** PR #8 rebased, CI green, demo transcripts with latency < 15 s each, `worker_done` with `--outcome succeeded|failed`.
