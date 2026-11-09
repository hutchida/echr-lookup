# Orchestrator handoff: MCP slice

_Written 2026-11-04 21:40 UTC by orchestrator #4 (`ses_e579d1058ffe7fiiTqo0k7lgWX`, retired at Gate 0 → Gate 1, context ~120K)._

Read this, then [`plan-mcp.md`](plan-mcp.md) (Dan's brief, verbatim), [`status.md`](status.md), [`../interfaces-mcp.md`](../interfaces-mcp.md). Gotchas from the first build: [`handoff-build1.md`](handoff-build1.md) §5 and [`retrospective.md`](retrospective.md) §6. Task briefs: [`tasks/mcp-common.md`](tasks/mcp-common.md), [`tasks/M1.md`](tasks/M1.md), [`tasks/M2.md`](tasks/M2.md), [`tasks/M3.md`](tasks/M3.md). **Don't re-read code you don't need: the briefs and interfaces doc are the spec.**

## 1. Resume
```sh
cd ~/GIT/echr-lookup
orca status --json
orca orchestration run-use --id run_aeba880d36a2 --json
orca orchestration check --json            # process + ack anything waiting
```
Add your session ID (`opencode session list`, top entry in this repo) to `scripts/orchestration/usage-mcp.sh` as `orchestrator5=…`; `./scripts/orchestration/usage-mcp.sh` prints every session's tokens and cost.

## 2. State at handoff
- **Gate 0 done.** #23 (W0, refactor A–G) and #24 (prep: MCP contract, fixtures, `interfaces-mcp.md`, owner-review set, `mcp` SDK) merged; main CI green at `0432dc2`; briefs committed at `939108f`.
- **Gate 1 running since 21:34**, three Sonnet workers (Orca run `run_aeba880d36a2`):

| Task | Dispatch | Worktree / DB | Expect |
|---|---|---|---|
| M1 MCP server | `ctx_f213806ba640` | `~/orca/workspaces/echr-lookup/m1`, `echr_m1`, port 8101 | `worker_done` with PR |
| M2 comparison eval | `ctx_684eb12b75e1` | `…/m2`, `echr_m2` (only `.env` with the API key) | draft PR, then `ask` "ready to switch" |
| M3 hosting spike | `ctx_570856be40ad` | `…/m3`, `echr_m3`, ports 8003/8103/5434 | draft PR, then `ask` "ready for MCP check" |

- Budget: **$7.37 of $25** at 21:38 (agents only; app runtime $0). Orchestrator share so far 83%: Gate 0 prep was orchestrator work. **Keep your context lean** (polls only print deltas; don't open worker diffs whole).

## 3. Next actions
1. **Poll:** `python3 scripts/orchestration/poll.py 240 M1=ctx_f213806ba640 M2=ctx_684eb12b75e1 M3=ctx_570856be40ad` (waits up to 4 min; prints mail + per-worker status). It doesn't ack: ack each delivery after deciding the worker's next owner (`orca orchestration check --ack <delivery_id> --json`; an ack can return the next delivery).
2. **M2/M3 asks before M1 merges:** don't answer "ready to switch / ready for MCP check" until M1 is merged; other questions: answer from the briefs and `interfaces-mcp.md`. Never approve extra live spend step by step: M2's cap is $8 total with a fixed plan (≤ $0.25 before the switch; pilot; full run ≤ $6; ≥ $1.50 kept for the owner-review re-run). Over that → refuse or escalate to Dan with the new total.
3. **Review M1's PR** against `tasks/M1.md` acceptance: owned paths only (`gh pr view N --json files`), `py/rag/answer/stats.py` untouched, CI green, the latency table (search < 3 s, others < 1 s, warm, over stdio), result sizes ≤ 25 KB, count fixture → 9/10, `check_quote` verbatim true. Append the usage row as a PR comment, `gh pr merge N --squash`, `git push origin --delete hutchida/m1`, check `gh run list --branch main --limit 2`. Release the M1 worker after acceptance (or keep it for owner-review fixes: `worker-retain`).
4. **After M1 merges:** reply to M3's ask ("M1 merged at <sha>: rebase on main and verify MCP in the container") and M2's ask ("M1 merged at <sha>: rebase, switch to `python -m echr_mcp --transport stdio` on echr_m2, run the pilot, then the full run within the plan"). Merge **M3** next, then **M2**.
5. **Gate 1 check:** `pnpm check` green on main; M1 acceptance passed; M2 table produced within cap (spend from `cost_log` in `echr_m2`: `select round(sum(cost_usd),2) from cost_log where timestamp > '2026-11-04 21:30'`); M3 image runs locally. Budget messages to Dan at **$12** and **$20**; pause launches at **$25**.
6. **Owner review (async):** start the MCP HTTP server for Dan only if he wants HTTP; Claude Desktop uses stdio. Put in `status.md` and message Dan: the Claude Desktop snippet (`scripts/mcp-desktop-config.sh` output; DB `echr`), the 10 questions (`data/eval/owner-review.jsonl`, with expected shapes), the M2 table. Then **end the session**. A fresh session resumes when Dan replies pass/fail per question: failures go to the right worker; M2 re-runs the failed questions only, within its cap.
7. **Finish:** `docs/learn/mcp.md`, the decision memo in `docs/mcp-comparison.md` (both via a worker: they're over 20 lines), and `docs/orchestration/report.md` (per-task time, tokens, cost, models, orchestrator share).

## 4. Launch recipe (for follow-up tasks)
1. `orca worktree create --name <t> --repo path:~/GIT/echr-lookup --branch hutchida/<t> --no-parent --json` from a clean, green main.
2. `.env`: copy the root `.env`, set the DB to `echr_<t>` (`create database echr_<t> template echr` needs no open connections to `echr`), drop `ANTHROPIC_API_KEY` unless the task makes live calls.
3. `orca orchestration worker-start --task-title "<t> …" --spec "<pointer to docs/orchestration/tasks/<t>.md>" --worktree path:<worktree> --agent opencode --model github-copilot/claude-sonnet-5.5 --json`. For a follow-up to a live worker, reuse its terminal (see `orca skills get orchestration --reference references/coordinator-loop.md`).
4. Record dispatch, opencode session and start time in `status.md`; add the session to `usage-mcp.sh`.

## 5. Gotchas seen this session
- `orca status --json` shows no `caller` here: the coordinator handle is the Run's `coordinator_handle` (`term_95cb3e34-…`).
- The first `search` in a fresh process takes ~30 s (model loading): every server and harness must load and warm models once at startup.
- `rag.answer.stats._compose` appends `Examples: [Case §op1] …` to the count sentence; MCP `count_cases` must drop it (no paragraph citations for a count).
- CI on a PR takes ~2 min 15 s; `gh pr checks N --watch` right after a push can report "no checks" (wait ~15 s).
