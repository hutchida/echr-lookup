# Orchestrator handoff (written 2026-11-04 ~10:30 UTC by orchestrator #2, `ses_e5cfd3c23ffee1W6h4E7UXcj50`, retired)

Read this, then `docs/orchestration/plan.md` (Dan's brief + amendments), `docs/orchestration/status.md` and `docs/interfaces.md`. Include **all** earlier orchestrator sessions in cost totals (`scripts/orchestration/usage-all.sh` already lists them; add yours).

## 1. Resume
```sh
cd ~/GIT/echr-lookup
orca status --json
orca orchestration run-use --id run_5aad27308746 --json
orca orchestration check --json            # should be count 0
```
Find your own session ID with `opencode session list`, then add it to `scripts/orchestration/usage-all.sh`.

## 2. State
- **Gate 1 is merged and checked** (#4–#11). Post-gate fixes are merged: #12 (listing loop), #13 (stats 11/12, neutrality 11/11), #14 (K2 grounds from text), #15 (retry transient `orca eval` failures). Main is green at `514bdad`.
- **No workers are running.** S4's terminal is retained by Orca (`user_takeover`; Dan's). All others are released.
- **Dan gave the Gate 2 go-ahead on 2026-11-04 (~10:30 UTC)** and opened a new orchestrator session for it. He has seen the $15–24 forecast; record it in status.md and launch.
- Not requested (optional, ask Dan only if relevant): metadata-only rows for the 212 scanned decisions in `echr_full`.
- **Full ingest: done 09:07** (DB `echr_full`): 3,527 loaded, 257 failed (212 scanned old decisions, 45 communicated cases, 2 empty). Embed took 44.6 min vs the 22 min estimate. Details in status.md. Optional fix later: store metadata-only rows for the scanned decisions, and parse communicated cases' unnumbered paragraphs.
- **Demo DB `echr`** was reloaded at 08:50 with K2's new grounds.
- **Budget:** ≈ $69.50 of $100 at 10:28 (build $64.18 incl. orchestrator #1 $17.38 and #2 $15.47; app $5.30). Tell Dan at **$80**; pause at $100. Keep your own context small: the orchestrator is the biggest single cost.

## 3. Next actions
1. If `git status -sb` shows main ahead of origin, push. The last push failed with SSH/GitHub errors; if it still fails, tell Dan (`ssh-add`).
2. Gate 2 (`plan.md`): forecast, then write `docs/orchestration/tasks/I1.md`, `I2.md`, `I3.md` following the Gate 1 task-brief structure (`tasks/S*.md`). Launch with `worker-start --spec … --worktree id:ec679419-44e6-4fb3-9ba0-d27b5dfa3b3d::<path> --agent opencode --model github-copilot/claude-sonnet-5.5`. Create the worktrees first; `opencode` model selection needs an existing worktree.
   - **Prep first (orchestrator, like Gate 1 prep #3), if needed:**
     - a typed web API client generated from `packages/contract` (e.g. `apps/web/lib/api.ts`) and the shared layout/nav ownership rule (I1 owns `apps/web/app/layout.tsx` and shared components; I2/I3 only their routes);
     - per-worker ports: web 3101/3102/3103, API 8001/8002/8003. Never 3000 (another local dev server) or 8000.
   - **Per-worker DBs:** `create database echr_i1 template echr` (and i2, i3). This needs no open connections to `echr`, and avoids 3 parallel embeddings.
   - **Poll script:** copy `scripts/orchestration/poll-gate1.sh` to `poll-gate2.sh` with the new dispatch IDs.
   - **Each PR:** CI green, owned paths only, learning doc (5 sections), usage comment, squash merge, then `git push origin --delete <branch>`.
   - **Gate 2 check:** `pnpm check`; each page loads < 2 s on snapshot; every demo step (`plan.md`) is reachable.
3. Rehearsal, `docs/demo.md`, `docs/learn/README.md`, `docs/learn/capabilities.md`, `docs/orchestration/report.md`.

## 4. Open items for Dan (also in status.md)
- **stat-003:** expected 5, we get 4. K2 (citizenship deprivation + exclusion) is not a deportation case under S4's definition. Recommend expected = 4 when Dan reviews the draft question set.
- **Wording:** the stats answer sentence omits its ground filter ("…inadmissible" instead of "…inadmissible for non-exhaustion"). The SQL is right. This is a copy fix for the rehearsal or S4.
- **Search ignores `data_source`**, hence the separate `echr_full` DB.
- **`reset()` empties `cost_log`.** Incremental ingest skips by file hash, so parser changes need `--reset` to take effect.

## 5. Gotchas learned the hard way
- **zsh:**
  - never name a variable `path`;
  - variables aren't word-split (use a function, not `P="docker exec …"; $P`).
- **Background shells of an opencode session die when the session goes idle or the Mac sleeps.** Run anything long in an Orca terminal (`orca terminal create --worktree path:… --command …`).
- **`gh pr merge --delete-branch`** fails while a worktree has the branch checked out. Use `gh pr merge N --squash`, then `git push origin --delete <branch>`.
- **`gh run watch $(gh run list --limit 1 …)`** right after a merge can catch the previous run. Confirm with `gh run list --branch main --limit 2`.
- **`poll.py` doesn't ack.** Ack each delivery after deciding the worker's next owner. An ack can return the next delivery, so read its count.
- **Agents' self-reported clock times** are sometimes off by ~30 min. Use `date -u` and the PR/commit timestamps.
- **Copying a database:** `create database X template Y` needs no connections on Y.
- **Port 3000** belongs to another local dev server. Use `WEB_PORT=3100 pnpm dev` (fixed in #11).
- **`pnpm search`** runs pnpm's own built-in command; use `pnpm run search`.
- **Never** `docker compose down -v`. Commit `docs/orchestration/**` and `scripts/orchestration/**` straight to main; code goes through PRs.
