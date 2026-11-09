S6 integration follow-up (same worktree `~/orca/workspaces/echr-lookup/s6`, branch `hutchida/s6`, PR #7, DB `echr_s6`, which has the API key). Your original brief `docs/orchestration/tasks/S6.md` still applies (owned paths, contract rule, secrets, PR report, learning doc, live allowance ≤ $2 during development).

**Context:** S2 (`rag.parse`, #9), S3 (`rag.index`, `rag.search`, migrations, #10) and S1 (`rag.ingest`, #5) are merged to `main`, and CI is green. S4 (`rag.answer`, PR #8) is finishing its integration run and merges next. This runs in two phases.

**Database:** don't run an ingest yourself; four agents embedding at once slow the machine for everyone. The orchestrator is replacing your empty `echr_s6` with a copy of a real `pnpm ingest:snapshot` (98 documents, all 3 chunking strategies), ready by about 21:00 UTC. Before you need it, check with `cd py && uv run python -c "import rag.index as i; print(i.connect().execute('select count(*) from documents').fetchone())"`. If it isn't 98 yet, wait 60 s and retry, for at most 20 min; after that, `ask`.

**Phase A (now; no Anthropic calls):**
1. Rebase `hutchida/s6` onto `origin/main`. Switch the expected-paragraph-ID check from its fallback to the real `rag.parse` (every expected ID must exist; fix any question whose IDs don't). Use the real `rag.search` / `rag.index`, and keep `rag.answer` faked until S4 merges.
2. Once `echr_s6` is ready, run the **retrieval-only** part over all 12 configs (3 chunking × 4 modes) on the full question set: **< 5 min**, $0. Check that the numbers make sense (e.g. hybrid ≥ bm25 or vector on most configs; say so if not).
3. Push and keep CI green. Then **block** with `orca orchestration ask` (from your preamble): "S6 phase A done (<retrieval time, headline recall@10/MRR>). Ready for phase B once S4 merges?" Don't send `worker_done` yet.

**Phase B (after my reply says S4 is merged):**
1. Rebase onto `origin/main` again, and switch to the real `rag.answer`.
2. Run the full `pnpm eval:snapshot` with the judge, once (`--max-cost 3.00`): **< 15 min** and **< $3**. Store its `EvalRun`s. Write the real `docs/eval-results.md` and the README eval section (only between the markers), with stat accuracy in markdown as agreed.
3. Update `docs/learn/S6.md` and the PR #7 description with the real numbers, the results table and the total live spend from `cost_log`. Push, get CI green, then send `worker_done`.

**Constraints:** only S6's owned paths. Don't edit other tasks' modules, migrations, the contract or `config.py`. If a merged module misbehaves or a seam is wrong, `ask`; don't patch around it. Leave the questions as `status: draft` for Dan.

**Acceptance:** PR #7 rebased, CI green, the retrieval time, the full-run time and cost, and the results table in the PR report, `worker_done` with `--outcome succeeded|failed`.
