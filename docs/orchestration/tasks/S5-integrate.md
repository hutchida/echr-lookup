S5 integration follow-up (same worktree `~/orca/workspaces/echr-lookup/s5`, branch `hutchida/s5`, PR #6, DB `echr_s5`). Your original brief `docs/orchestration/tasks/S5.md` still applies (owned paths, contract rule, secrets, PR report, learning doc). You have no API key.

**Context:** S2 (`rag.parse`, #9), S3 (`rag.index`, `rag.search`, migrations, #10) and S1 (`rag.ingest`, #5) are merged to `main`, and CI is green. S4 (`rag.answer`, PR #8) is finishing its integration run and merges next. This runs in two phases.

**Database:** don't run an ingest yourself; four agents embedding at once slow the machine for everyone. The orchestrator is replacing your empty `echr_s5` with a copy of a real `pnpm ingest:snapshot` (98 documents, all 3 chunking strategies), ready by about 21:00 UTC. Before you need it, check with `cd py && uv run python -c "import rag.index as i; print(i.connect().execute('select count(*) from documents').fetchone())"`. If it isn't 98 yet, wait 60 s and retry, for at most 20 min; after that, `ask`.

**Phase A (now):**
1. Rebase `hutchida/s5` onto `origin/main`. Use `rag.index.migrate` and the real `rag.search` / `rag.index`. Add integration tests on a small real corpus (fake embedder, fake LLM). Keep `rag.answer` faked until S4 merges.
2. Once `echr_s5` is ready, start `uv run --group ml uvicorn api.main:app --port 8000`. If 8000 is busy, use 8005; port 3000 is someone else's. Then measure, warm: `/stats` < 500 ms, `/case/001-57619` < 300 ms, `/search` < 3 s (hybrid_rerank and hybrid). The machine is loaded (macOS Spotlight), so re-time once if a number is borderline.
3. Push and keep CI green. Then **block** with `orca orchestration ask` (from your preamble): "S5 phase A done (<numbers>). Ready for phase B once S4 merges?" Don't send `worker_done` yet.

**Phase B (after my reply says S4 is merged):** rebase onto `origin/main` again and switch `/ask` to the real `rag.answer`. Measure `/ask` with `LLM_MODE=fake` (the orchestrator measures live `/ask`). Run the integration tests, update `docs/learn/S5.md` and the PR #6 description with the real numbers, push, get CI green, then send `worker_done`.

**Constraints:** only S5's owned paths. Don't edit other tasks' modules, migrations, the contract or `config.py`. If a merged module misbehaves or a seam is wrong, `ask`; don't patch around it. Stop the uvicorn server when you're done.

**Acceptance:** PR #6 rebased, CI green, the latency numbers in the PR report, `worker_done` with `--outcome succeeded|failed`.
