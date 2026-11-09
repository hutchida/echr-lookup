S4-fix: stats-route accuracy and answer neutrality (Dan approved this before Gate 2).

**Where:** same worktree `~/orca/workspaces/echr-lookup/s4`, DB `echr_s4` (real snapshot ingest; has the API key). Make a **new branch `hutchida/s4-fix` from `origin/main`**; `hutchida/s4` is already squash-merged. Your original brief `docs/orchestration/tasks/S4.md` still applies (secrets, contract rule, PR report, learning doc).

**Why:** S6's judged eval on main (`docs/eval-results.md`) shows stat accuracy 6/12 and neutrality 0.55 (6/11) for the default config. Faithfulness 0.96 and citation accuracy 0.98 are good, so keep them.

**1. Stats route.** Mismatches as `expected → got`:
- **Grand Chamber judgments:** 10 → 41. The chamber filter looks unapplied.
- **UK judgments with at least one violation:** 24 → 16. Probably `mixed` outcomes are missing; check the `outcome` values.
- **Most common inadmissibility ground, and how many decisions rest on it:** 26 → 35. It seems to return the total, not that ground's count.
- **Decisions declared inadmissible:** 33 → 35. Check whether `partly_inadmissible` belongs, and what the question means.
- **Deportation complaints declared inadmissible:** 27 → 30. This is your text-match definition (known false positive: Field and Others).
- **Deportation/expulsion inadmissible for non-exhaustion:** 5 → 6.

Fix real SQL or extraction bugs in `py/rag/answer/**`, with an offline (fake LLM) test for each. When the disagreement is about **definitions**, the answer must state its definition. You may correct a stat item's expected count / `reference_notes` / `expected_count:<n>` tag in `data/eval/questions.jsonl`, but **only** with the SQL over `documents` that justifies the new value, quoted in the PR. I'll review each change. Keep items `status: draft`.

**2. Neutrality.** Items failing in the default config: `neutrality-003` (soldiers abroad), `-006` (whole-life sentences), `-007` (assisted suicide), `-010` (following Strasbourg), `-011` ("Is the Human Rights Act good for the UK?": 3.2 s with no faithfulness score, so it was probably refused or routed oddly).
- Re-run just these items through S6's judge, in a small script or REPL, to read the judge's reasons. Then fix the answer side: system prompt / framing in `rag.answer` for "should…" / value questions. The answer should give the Court's reasoning and the main positions on each side, cited, with no verdict.
- Opinion questions should get a sourced, neutral answer, not a refusal.
- **Don't edit `py/rag/eval/**`** (judge or metrics). If the judge itself looks wrong for an item, `ask` me with the evidence.
- Explain answers mustn't become vague.

**3. Final check, once, at the end:** a full `pnpm eval:snapshot --max-cost 3.00` in `echr_s4`. It regenerates `docs/eval-results.md` and the README eval section; commit them as the runner writes them, without hand edits. Re-run the 3 demo questions and update `docs/learn/S4-demo.md`; Q3's numbers may change.

**Ownership:** `py/rag/answer/**`, `docs/learn/S4.md`, `docs/learn/S4-demo.md`, the stat items in `data/eval/questions.jsonl` (rules above), and the runner-generated `docs/eval-results.md` / README eval section. Nothing else. Don't change the contract, `config.py` or other modules; `ask` if a seam is wrong.

**Budget:** live Anthropic spend **≤ $3.00 in total**, including the final run (~$2.10). So iterate cheaply: single `pnpm ask` calls and the 5-item judge script, not repeated full evals.

**Acceptance (report all in the PR):**
- Stat accuracy ≥ 10/12 in the final run. Any remaining miss is explained as definitional, with both SQLs.
- Neutrality ≥ 9/11 in the final run, with the judge unchanged.
- No regression: faithfulness ≥ 0.95 and citation accuracy ≥ 0.94 (default config).
- The 3 demo questions are still balanced/correct and each < 15 s.
- `pnpm check` green; PR opened from `hutchida/s4-fix` with the standard PR report (+ live spend from `cost_log`); CI green; then `worker_done` with `--outcome succeeded|failed`.
