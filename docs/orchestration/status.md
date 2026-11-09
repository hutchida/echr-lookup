# Orchestration status: follow-up slice (F1, F3)

_Orchestrator: `github-copilot/claude-sonnet-5.5` (session `ses_e529b769dffek0Gq502nVntPe4`) · Orca run `run_494e211670d1` · previous slice: [`status-mcp.md`](status-mcp.md), [`handoff-mcp.md`](handoff-mcp.md)_

Briefs: [`tasks/F-common.md`](tasks/F-common.md), [`tasks/F1.md`](tasks/F1.md), [`tasks/F3.md`](tasks/F3.md). Budget **$10 all-in** (agents + app runtime); live-call cap **$5**, only F3's re-run makes paid model calls. Tell Dan at **$6** and **$8**; stop launching at $10.

## Step 0 checks (read-only, 2026-11-05 20:30 UTC)
- Model test: `opencode run -m github-copilot/claude-sonnet-5.5` → "OK sonnet".
- **Refactor A–G merged before M2 ran:** #23 merged 2026-11-04 21:26:47Z; M2 `results.jsonl` runs finished 22:09–22:41Z (`/ask` rows 22:20–22:41). So `/ask`'s or-01 and or-08 failures are **not** stale.
- **Judging:** `docs/eval-judging.md` and `data/eval/judgments/qrels-v2.jsonl` existed **only on open PR #28** (`hutchida/relevance-judging`, not merged) when F3 started. #28 was merged before F1 and F3 landed (`6d15cda`), so both are on `main` now. F3 reads them via `git show origin/hutchida/relevance-judging:<path>`, skips politely if absent, and never merges #28.
- **Risk:** M2's last `/ask` calls hit "Anthropic API usage limit, access regained 2026-12-01". F3 must ping the key with one 1-token call before any paid run.
- Package is `py/echr_mcp/`, not `py/mcp/`.
- Worktrees `~/orca/workspaces/echr-lookup/{f1,f3}`, DBs `echr_f1`, `echr_f3` (copies of `echr`); only F3's `.env` has the API key.

## Tasks

| Task | Started | State | PR | Dispatch | opencode session |
|---|---|---|---|---|---|
| F1 citations + instructions | 20:30 | ✅ merged 20:56 (#30, `e29a33a`); released | #30 | `ctx_ad59764d5501` | `ses_e5298d788ffeVL90Ps79k7vXgY` |
| F3 fair measurement | 20:30 | ✅ Part 1 merged 20:47 (#29); Part 2 paid re-run **not run** (key at usage limit); offline prep merged (#31); released | #29, #31 | `ctx_3d725cef3fce` | `ses_e5298d053ffee04ToBKTx9NrhA` |

## Budget

| Checkpoint (UTC) | Agents | App runtime | Total |
|---|---|---|---|
| 21:35 (all merged) | $6.67 (orch 0.97, F1 1.58, F3 4.12) | $0 | $6.67 of $10 |
| 21:00 (F1 merged) | $4.10 | $0 | $4.10 |

## Decisions log
- 20:30 Briefs written from Dan's prompt; F3's paid part gated on F1 merge and a 1-token API-key ping (usage limit risk).
- 20:50 Merged F1 (#30), then wrote the superseded-note in interfaces-mcp §3 and the learn README rows myself (doc edits).
- 21:10 F3's key ping failed twice (usage limit until 2026-12-01; Dan said he'd raise the limit, it had not taken effect). Dan chose to skip the re-run; F3 finished with offline prep (#31).
