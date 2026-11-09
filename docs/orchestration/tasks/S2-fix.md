S2-fix: inadmissibility grounds must also come from the text when HUDOC's metadata lists only some of them.

**Where:** worktree `~/orca/workspaces/echr-lookup/s2`. Make a **new branch `hutchida/s2-fix` from `origin/main`**; `hutchida/s2` is already merged. DB `echr_s2` (tests use `echr_s2_test`). Read `docs/orchestration/tasks/S2.md` for the common rules (secrets, contract rule, PR report template, learning doc). Model: you are `github-copilot/claude-sonnet-5.5`.

**The gap:**
- `parse_document()` extracts grounds from the text **only when the metadata grounds are null**.
- K2 v. the United Kingdom (`001-172143`, decision, inadmissible) has metadata `['manifestly_ill_founded']` (`outcome_raw`: "Inadmissible (Art. 35) Admissibility criteria;(Art. 35-3-a) Manifestly ill-founded"). The G0b oracle `py/rag/parse/tests/grounds_oracle.json` says `['manifestly_ill_founded', 'non_exhaustion']`: the decision text also rejects a complaint for non-exhaustion of domestic remedies.
- Across all 35 oracle entries, K2 is the **only** disagreement. Your earlier 35/35 figure covered only the decisions without metadata grounds.

**Change** (only `py/rag/parse/**` and `docs/learn/S2.md`):
1. For inadmissible / partly_inadmissible decisions that **do** have metadata grounds, also run the text extraction. If the text **clearly** states extra grounds, return the union.
   - The contract is fixed: `inadmissibility_grounds_source` is `"metadata" | "text"`, so don't change it.
   - Use `"text"` when the text adds grounds, i.e. when the stored set is no longer only what the metadata said. Keep `"metadata"` otherwise. Document this rule in `docs/learn/S2.md` (section 3 or 5).
2. Be conservative: no new false positives. Only treat a ground as stated when the decision's own reasoning or operative part rejects a complaint on that ground, not a mere mention or quotation.
3. Tests:
   - Compare against **all 35** oracle entries, whether they have metadata or not: **35/35 exact**.
   - Add a K2-specific test.
   - Add a test that no other snapshot decision with metadata grounds changes, unless the text clearly supports the extra ground. List any that change in the PR, with the sentence that justifies each.
   - Determinism and the existing parse tests stay green.

**Rules:**
- Don't run any ingest against `echr` or the main checkout. The orchestrator re-ingests after merge.
- Keep CPU use modest: a full ingest is running on this machine. Parse-only checks are fine.
- Nothing outside the owned paths; `ask` if a seam is wrong.

**Acceptance:** 35/35 oracle agreement over all entries; K2 gets `['manifestly_ill_founded', 'non_exhaustion']` with source `text`; `pnpm check` green; PR from `hutchida/s2-fix` with the standard PR report; CI green; then `worker_done` with `--outcome succeeded|failed`.
