# Contract fixtures

One fixture per schema, `fixtures/<Name>.json`; extra branches in `fixtures/<Name>.<variant>.json`
(`Answer.stats.json`, `Answer.refused.json`, `EvalItem.stat.json`). Tests (`pnpm --filter @echr/contract test`
and `py/tests/test_contract_fixtures.py`) check that every fixture validates, that every schema property
(optional ones included) appears in at least one fixture, and that nothing appears only in a fixture.

Built by `scripts/g0b/make_fixtures.py` from the demo snapshot in `data/snapshot/`.

**Real** (copied from the snapshot or measured): item ids, case names, paragraph text and quotes, chunk ids and
text, `sha256`, hybrid-search scores and ranks (BM25 + bge-small vector via pgvector, reciprocal rank fusion k=60,
run on the prototype index), snapshot counts in the stats answer, ingest timings and the embed `CostLogEntry`
(measured in G0b), `EvalRun` recall/MRR (computed from the real retrieval).

**Illustrative** (hand-written, no model was called): the prose in `Answer*.json` (`answer_text`, claim wording,
claim `status`/`reason`), the stats SQL (it shows the intended shape against a `documents`/`chunks` schema that
Gate 1 will define; the counts in `rows` are real for the snapshot), token counts and step latencies in
`steps`; costs in `steps` are computed from `config/model-prices.json`. `EvalRun.json` is a retrieval-only run
(`generator_model` null, so faithfulness/citation/neutrality are null).

## Added after the PR #2 review (`make_fixtures_fix.py`)

- `SourceDocument.json` is **Miah v UK (2010), `001-98645`**, a real inadmissible decision. Its
  `inadmissibility_grounds` (`manifestly_ill_founded`, `incompatible_ratione_materiae`) with source `"text"` are
  **prototype-derived**: HUDOC's `conclusion` for it is the bare word "Inadmissible", so the values come from the
  regex prototype `scripts/g0b/grounds_regex.py`, whose evidence sentences were read by the author. They are not
  in `manifest.json` (the manifest carries grounds only where HUDOC's metadata states them; `ManifestEntry.json`
  is Soering, whose grounds are `null`).
- `CaseDetail.json`: the same decision with all 25 paragraphs as parsed by the prototype parser.
- `CorpusStats.json`: counts computed from the manifest for the 96 HTML documents the prototype ingested
  (legislation was not parsed), paragraph and chunk totals from the benchmark, embedded `last_ingest_run`,
  `costs` and `latest_eval` (the same real objects as the other fixtures). Breakdowns sum to `totals.documents`
  (a test checks it); `by_article` is the top 25.
- `CostSummary.json`: the four real embedding runs of the benchmark (local models, so $0 and `purpose: embed` only).
- `IngestRunList.json`, `EvalRunSummary.json`, `EvalRunList.json`: wrap the single real run of each kind.
- `ApiError.json`: the body `GET /case/001-99999` would return (that id is not in the snapshot; checked by the script).
