S1 integration follow-up (same worktree `~/orca/workspaces/echr-lookup/s1`, branch `hutchida/s1`, PR #5, DB `echr_s1`). Your original brief `docs/orchestration/tasks/S1.md` still applies (owned paths, contract rule, secrets, PR report, learning doc).

**Context:** S2 (`rag.parse`, PR #9) and S3 (`rag.index`, `rag.search`, `infra/migrations`, PR #10) are merged to `main`, and main CI is green.

**Change:**
1. Rebase `hutchida/s1` onto `origin/main`. Switch from your fakes to the real `rag.parse` / `rag.index` modules. CI tests keep using the defaults (`EMBEDDER=fake`, no ML, no network). Turn the skip-if-missing integration tests into real ones where the modules now exist.
2. **HEREP (Commission reports): skip them; don't map them to `decision`.** This is the answer to your 19:47 question, which apparently never reached you. In full mode, don't download or parse them. `IngestRun` is a strict contract object, so **don't add fields**. Print `skipped_commission_reports=<n>` in the CLI summary and the log, keep them out of the `IngestRun` counts, and mention it in `docs/learn/S1.md`. You may get `<n>` from the HUDOC result count (at most 1 extra request). The orchestrator records the contract gap.
3. Run these for real against `echr_s1`. bge-small is already in the default HF cache (`~/.cache/huggingface`).
   - `pnpm ingest:snapshot --reset` from empty: **≤ 224 s**. Report per-stage seconds against `docs/learn/ingestion-estimates.md`.
   - A second `pnpm ingest:snapshot`: every document `unchanged_skipped`, in **< 15 s**.
   - Sanity check: `pnpm search "Soering" --mode bm25 -k 3` returns Soering first, and `pnpm search "extradition to face death row" --mode vector -k 3` does too.
   - `pnpm ingest:full --limit 5` via the Orca browser. Stay within your task cap of ≤ 30 HUDOC requests in total, and report the request count and observed rate. If the cap is already used up, `ask` before running it.
4. Update `docs/learn/S1.md` with the real timings. Update the PR #5 description (report with real numbers). Push, get CI green, then send `worker_done`.

**Constraints:** only S1's owned paths. Don't edit `rag.parse`, `rag.index`, `rag.search`, migrations, the contract or `config.py`. If a merged module misbehaves or a seam is wrong, `ask`; don't patch around it. No full ingest.

**Acceptance:** PR #5 rebased, CI green, the numbers above in the PR report, `worker_done` with `--outcome succeeded|failed`.
