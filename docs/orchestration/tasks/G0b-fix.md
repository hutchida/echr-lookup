# Task G0b-fix — contract additions found in orchestrator review of PR #2

- **Model:** `github-copilot/claude-sonnet-5.5`, reusing the G0b agent and terminal.
- **Branch:** same branch, same PR (#2).

Gate 1 and 2 tasks are forbidden from changing the contract. The review of PR #2 found shapes they will need that don't exist yet. Add them now, on the same branch, so they land in PR #2. Same rules, ownership and acceptance checks as `docs/orchestration/tasks/G0b.md`.

1. **Endpoint names in `.meta` descriptions.** The API is: `POST /search`, `POST /ask` (not `/answer`), `GET /stats`, `GET /case/{id}`, `GET /ingest-runs`, `GET /eval-runs`, `GET /eval-runs/{id}`, `GET /costs`, `GET /health`. Fix every description to match.
2. **Response schemas for the remaining endpoints.** Each must be strict, size-capped, registered, exported to `schema/*.json`, and have a fixture built from real snapshot data. All must be covered by the existing "every property appears in some fixture" test.
   - **`CaseDetail`** (`GET /case/{id}`): `document: SourceDocument`, plus `paragraphs: Paragraph[]` in document order (all of them; cap generously, e.g. 3,000). Used by the case viewer to anchor and highlight `§` paragraphs.
   - **`CorpusStats`** (`GET /stats`):
     - totals: documents, paragraphs, and chunks per strategy;
     - counts by `doc_type`, by `outcome`, by `chamber`, by article (top N, capped) and by year;
     - `last_ingest_run: IngestRun | null`;
     - `costs: CostSummary`;
     - `latest_eval: EvalRunSummary | null`.
   - **`CostSummary`** (`GET /costs`, also embedded in `CorpusStats`):
     - `total_usd`;
     - `by_purpose[]` and `by_model[]`, each with calls, tokens in, out and cached, and `cost_usd`;
     - `recent: CostLogEntry[]` (capped, e.g. 100);
     - `since` timestamp.
   - **`IngestRunList`** (`GET /ingest-runs`): `{ runs: IngestRun[] }`, capped at 50, newest first.
   - **`EvalRunSummary`**: an `EvalRun` without per-item results. This is what the stats page and the list need.
   - **`EvalRunList`** (`GET /eval-runs`): `{ runs: EvalRunSummary[] }`, capped at 50. `GET /eval-runs/{id}` returns the full `EvalRun`.
   - **`ApiError`**: the error body for every endpoint: `{ error: string, detail: string | null, request_id: string | null }`.
3. **Inadmissibility grounds.** Your finding: metadata states the ground for only 18 of 671 decisions. Demo step 3 asks for "the most common reasons", so the grounds need a home in the contract:
   - Add an `InadmissibilityGround` enum: `manifestly_ill_founded`, `non_exhaustion`, `out_of_time`, `incompatible_ratione_materiae`, `incompatible_ratione_personae`, `incompatible_ratione_temporis`, `incompatible_ratione_loci`, `abuse_of_right`, `no_significant_disadvantage`, `substantially_same`, `not_a_victim`, `other`. Adjust it if your data says otherwise, and explain any change.
   - Add two fields to `SourceDocument` (and therefore to `ManifestEntry`):
     - `inadmissibility_grounds: InadmissibilityGround[] | null`. `null` means not applicable, or not extracted yet.
     - `inadmissibility_grounds_source: "metadata" | "text" | null`.
   - In `manifest.json`, fill these from HUDOC metadata where it states the ground (source `metadata`); otherwise leave them `null`. Gate 1's S2 will extract them from the decision text at parse time (source `text`).
   - Make the `SourceDocument` fixture show a real snapshot decision with text-extracted grounds. Write a quick regex prototype in `scripts/g0b/`, and say in `fixtures/README.md` that the value is prototype-derived.
   - Add a section to `data/snapshot/README.md` listing, for the snapshot's inadmissible decisions, the grounds your prototype finds. Gate 1's S2 will use it as a test oracle.
4. **Docs.** Re-run `pnpm contract:export`. Update `fixtures/README.md` and add a short paragraph on the new schemas to `docs/learn/G0b.md`. Append a "G0b-fix" section to the PR description listing these changes.
5. **Acceptance.**
   - `pnpm check` green locally and the PR's CI green;
   - `git diff --exit-code packages/contract/schema` clean after export;
   - the `Answer` worst case is still < 50 KB.

   Then send `worker_done` once, with a three-sentence summary.
