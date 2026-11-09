S1-fix: the full-mode listing pager loops forever on duplicate rows (bug found in the one real `pnpm ingest:full` run).

**Where:** worktree `~/orca/workspaces/echr-lookup/s1`. Make a **new branch `hutchida/s1-fix` from `origin/main`**; `hutchida/s1` is already merged. DB `echr_s1` (tests use `echr_s1_test`). Read `docs/orchestration/tasks/S1.md` for the common rules (secrets, contract rule, PR report template, learning doc). Model: you are `github-copilot/claude-sonnet-5.5`.

**Evidence** (orchestrator's main checkout, read-only for you: `~/GIT/echr-lookup/data/full/`):
- `hudoc-requests.jsonl`: request 1 is the judgments listing (258 KB, complete). Request 3 is the decisions listing with `start=0, length=500`-style paging (190 KB). Requests **4–710 are the identical decisions URL**, each answered 200 with **3,680 bytes**: about 10 rows, all item IDs already seen.
- `listing.json`: decisions cached at **2522/2532** with `complete: false`. The log printed `[listing decisions] 2522/2532` ~700 times.

**Cause:** in `py/rag/ingest/full.py` `list_rows()`, the next `start` is `len(cached["rows"])`, the count of **unique** rows. When a page contains only already-seen IDs, `new` is empty and `start` doesn't move. Because `page` isn't empty, `complete` stays False: an infinite loop at 1 req/s.

**Change** (only `py/rag/ingest/**` and `docs/learn/S1.md`):
1. Page by HUDOC offset. Keep a `next_start` that advances by `len(page)` (rows returned, not rows new), and store it in the listing cache. If an old cache has no `next_start`, fall back to `len(rows)`.
2. Stop when any of these holds: the page is empty; `next_start >= resultcount`; or **2 consecutive pages bring no new item IDs**. In that last case, print a warning with the shortfall, e.g. `[listing decisions] 2522 unique of 2532 listed (10 duplicates)`, and mark the listing complete.
3. Hard safety cap per query: at most `ceil(resultcount / PAGE_LENGTH) + 3` listing requests. If it's hit, stop with a clear error instead of looping.
4. Resume behaviour: with the existing cache above (2522 rows, no `next_start`), a resumed run must finish the decisions listing in **≤ 3 requests** and then move on.
5. Offline tests with the fake transport: duplicates across pages, a final page made entirely of duplicates (this bug), a short final page, `resultcount` larger than the unique rows, and resuming from an old-format cache. Each must terminate, and each must assert the **exact number of requests**.
6. Add a line to section 5 (Limits) of `docs/learn/S1.md` about HUDOC listing duplicates.

**Rules:** **zero HUDOC requests** in this task: no `ingest:full`, not even `--limit`. The orchestrator verifies by resuming the real run after merge. Don't touch the main checkout's `data/full/`; copy `listing.json` into a test fixture if useful. Nothing outside the owned paths; `ask` if a seam is wrong.

**Acceptance:** the new tests pass; `pnpm check` green; PR from `hutchida/s1-fix` with the standard PR report; CI green; then `worker_done` with `--outcome succeeded|failed`.
