S1-retry: a single failed browser call must not stop a full HUDOC run.

**Where:** worktree `~/orca/workspaces/echr-lookup/s1`. Make a **new branch `hutchida/s1-retry` from `origin/main`**; `hutchida/s1-fix` is already merged as #12. DB `echr_s1` (tests use `echr_s1_test`). Read `docs/orchestration/tasks/S1.md` for the common rules (secrets, contract rule, PR report template, learning doc). Model: you are `github-copilot/claude-sonnet-5.5`.

**What happened in the real full run:**
- Request 1279 (`/app/conversion/docx/html/body?library=ECHR&id=001-57425`) is logged in the main checkout's `data/full/hudoc-requests.jsonl` as status `-1`, 0 bytes, 0 s.
- The run stopped with `STOPPED: cannot reach HUDOC through Orca's browser: \`orca eval --expression\` failed: Command '['orca', 'eval', ...` (a `HudocUnavailable` from `_orca_json`, `CalledProcessError`).
- The HUDOC tab was fine; `orca eval --expression document.title` worked straight away, and resuming succeeded. It was a one-off transport hiccup, but it cost a 1-hour run its progress until a human resumed it.

**Change** (only `py/rag/ingest/**` and `docs/learn/S1.md`):
1. **Retry transport-only failures.** That means `orca` exiting non-zero, an `orca` timeout, or unparseable `orca eval` output: the `HudocUnavailable` cases from the browser route.
   - Retry up to **3 times** with backoff (e.g. 5 s, 15 s, 45 s).
   - Before each retry, re-find the HUDOC tab (`find_hudoc_page()`); the page id may have changed. If there is no tab, recreate it as today.
   - After the last retry, stop exactly as now, with the same clear message.
2. **Never retry a block.** `HudocBlocked` (403 / 429 / Cloudflare challenge / non-JSON search answer) stops immediately, as now.
3. **Politeness:**
   - Each retry is a new attempt and goes through the same rate limiter, so ≥ 1 s apart, still ≤ 1 req/s.
   - Log every attempt in `hudoc-requests.jsonl` with its status (`-1` for transport failures) and a `retry` number.
   - Print one line per retry, e.g. `[retry 1/3] orca eval failed (…); waiting 5 s`.
4. **Offline tests** with the fake transport and fake clock:
   - fails once, then succeeds: the run continues, with an exact attempt count and log entries;
   - fails 4 times: stops with `HudocUnavailable` after exactly 4 attempts;
   - a 403 / challenge: no retry;
   - the limiter spacing holds across retries.
5. Add a line to `docs/learn/S1.md` section 5 (Limits): what is retried and what isn't.

**Rules:**
- **Zero HUDOC requests** in this task.
- Don't touch the main checkout's `data/full/`, and don't stop or interfere with the full ingest currently running there.
- Keep CPU use modest.
- Nothing outside the owned paths; `ask` if a seam is wrong.

**Acceptance:** new tests pass; `pnpm check` green; PR from `hutchida/s1-retry` with the standard PR report; CI green; then `worker_done` with `--outcome succeeded|failed`.
