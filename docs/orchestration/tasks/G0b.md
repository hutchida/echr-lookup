# Task G0b — HUDOC measurement, demo snapshot, API contract, ingestion estimates, embedder choice

- **Model:** `github-copilot/claude-sonnet-5.5` (opencode). One agent.
- **Branch / worktree:** your own Orca worktree, branched from `main`. Open one PR to `main`.
- **Coordinator:** the orchestrator (Opus). For blocking questions, use the `ask` command from your Orca preamble. Never stop and wait on a local prompt.

## 1. Context

`echr-lookup` is a learning and portfolio RAG (Retrieval-Augmented Generation) system over the UK's case law at the European Court of Human Rights (ECHR), using HUDOC (https://hudoc.echr.coe.int), plus the Convention and the Human Rights Act 1998. It answers questions neutrally and never takes a side on UK membership of the Convention. Every claim cites a paragraph ID like `001-57619§88`, and each citation is verified. It also answers counting questions ("how many UK deportation complaints were declared inadmissible, and why?") with SQL over metadata, not vector search.

Pipeline: ingest → parse (numbered paragraphs + section labels: Procedure / The Facts / The Law / Operative provisions) → chunk (three strategies: fixed, recursive, by-section) → embed + index in Postgres (pgvector + BM25 via ParadeDB `pg_search`) → search (BM25, vector, hybrid via reciprocal rank fusion, optional rerank) → answer (router: explain vs count/stat) → citation check → FastAPI → Next.js.

Read first: `README.md`, `docs/learn/00-overview.md`, `docs/decisions.md`, `packages/contract/**`, `py/rag/contract.py`, `py/api/tests/test_health.py`.

Gate 0a (merged) gives you:
- the monorepo;
- ParadeDB on `localhost:5433` (user/pass/db `echr`);
- a FastAPI `/health`;
- the contract package with one `Health` schema;
- the root `pnpm check`.

**You are Gate 0b.** Gate 1 starts after you merge, with seven parallel tasks built entirely on your contract, fixtures and snapshot:

| Task | Builds |
|---|---|
| S1 | ingest |
| S2 | parse + chunk |
| S3 | index + search |
| S4 | answer + citation check |
| S5 | API |
| S6 | eval |
| C1 | screenshot helper |

Get the contract right. Gate 1 tasks are forbidden from changing it.

## 2. Deliverables

### A. HUDOC measurement → `docs/hudoc-measurement.md`

1. **Work out how the HUDOC site queries its results.** Use Orca's built-in browser, which is available to you:
   - `orca tab create --url https://hudoc.echr.coe.int/eng ...`
   - `orca eval --expression "performance.getEntriesByType('resource').map(e => e.name)"`
   - or read the site's JS.

   Document the search endpoint (expected: `/app/query/results`), its query syntax, `select` fields, paging (`start`/`length`) and sort. Also document the document-conversion endpoints for HTML, DOCX and PDF. Do not commit a reusable browser harness; task C1 owns `packages/capture`.
2. **Get exact counts for respondent = United Kingdom (`GBR`) by document type:**
   - judgments, split by Grand Chamber / Chamber / Committee;
   - decisions;
   - communicated cases;
   - legal summaries / Case-law Information Notes;
   - Commission decisions and reports.

   Give the exact query string used for each count, so anyone can reproduce it. English-language documents are the main target; note French-only counts separately.
3. **Record:**
   - response times (p50 and p95 over at least 20 requests);
   - any rate limiting or blocking you observe;
   - which metadata fields come back empty or unreliable, and how often (sample of at least 100 records): e.g. `conclusion`, `article`, `importance`, `ecli`, `appno`, `kpdate`, `doctypebranch`, `separateopinion`;
   - which download formats work (HTML vs DOCX vs PDF): success rate, size and parse-friendliness.
4. **Check HUDOC's reuse terms** (copyright / disclaimer / terms of use on hudoc.echr.coe.int and echr.coe.int). Quote the relevant text with its URL, and say plainly what it allows for a public portfolio repo. Do the same for legislation.gov.uk (Open Government Licence) and the source of the Convention text.
5. **Politeness:**
   - **at most 1 request per second to HUDOC**, enforced in code (a shared rate limiter), not by hope;
   - send a descriptive `User-Agent` with a contact URL (`https://github.com/hutchida/echr-lookup`);
   - keep total HUDOC requests for this whole task **under 1,500**, and log the actual number.

### B. Demo snapshot → `data/snapshot/` (committed, ≤ 30 MB total)

1. **Choose about 40 UK judgments, about 40 UK decisions and about 15 legal summaries** (English), so that the demo path and eval questions have real answers. Must include:
   - well-known UK **Article 3** expulsion/extradition cases, with both violation and no-violation outcomes. Candidates to verify on HUDOC (don't trust this list; confirm each case's ID, application number and outcome from HUDOC metadata): Soering, Chahal, Vilvarajah, D v UK, N v UK (GC), Bensaid, NA v UK, Sufi and Elmi, Othman (Abu Qatada), Babar Ahmad and Others, Aswat, S.H.H. v UK, Harkins and Edwards;
   - UK **Article 8** deportation/expulsion cases, both violation and no-violation (candidates: A.A. v UK, Omojudi, Nnyanzi, Ndidi, Abdulaziz Cabales and Balkandali, Hode and Abdi);
   - **at least one case where deportation of a criminal was allowed** (no violation);
   - **at least 15 inadmissible UK deportation/expulsion decisions**, so the count/stats demo has something to count, with varied reasons (manifestly ill-founded, non-exhaustion, out of time, etc.);
   - a handful of well-known contested non-immigration UK cases for neutrality questions (e.g. Hirst (No. 2), Al-Skeini, Saadi v UK).
2. **Add the Convention text** (from the Council of Europe / ECHR site; record the source) and **the Human Rights Act 1998** from legislation.gov.uk, in the most parseable format available (legislation.gov.uk offers XML).
3. **Layout:** this layout is an interface Gate 1 depends on, so document it exactly in `data/snapshot/README.md`.
   - `data/snapshot/manifest.json`: one entry per document with:
     - every metadata field the contract's `SourceDocument` needs;
     - `source_url`, `retrieved_at`, `sha256` of the stored file, `format`, `path`.
   - `data/snapshot/hudoc/<itemid>.<ext>`: one stored body per document, in whichever format you found best for parsing (prefer HTML if it keeps paragraph numbers). Don't store several formats per document unless needed.
   - `data/snapshot/legislation/…`
4. **`data/snapshot/README.md`:** every chosen case with name, item ID, application number, date, articles, outcome and *why it's in the snapshot* (which demo step or eval theme it serves). Also include the counts per type and total size.
5. **The snapshot must work fully offline.** Nothing in Gate 1 may need the network in snapshot mode.

### C. Contract → `packages/contract/**`

This is the single source of truth for API shapes. Use zod, export JSON Schema with `pnpm contract:export`, and add one fixture per schema in `packages/contract/fixtures/<Name>.json`, **built from real snapshot data** (real item IDs, real paragraph text). Schemas:

- **`SourceDocument`**: item ID, case name, application number(s), ECLI, doc type (judgment / decision / communicated / legal summary / legislation), chamber (Grand Chamber / Chamber / Committee / null), date, articles, outcome/conclusion (raw text and a normalised form), importance level, language, source URL, sha256, `data_source`.
- **`Paragraph`**: stable ID `<doc-id>§<n>`, doc ID, number, section label (Procedure / The Facts / The Law / Operative provisions / Other), text, character offsets if useful.
- **`Chunk`**: chunk ID, doc ID, strategy (`fixed` | `recursive` | `by_section`), text, `paragraph_ids[]` (non-empty), token count.
- **`IngestRun`**: run ID, data source, started/finished, per-stage timings (download, parse, chunk, embed, index), counts (seen, new, changed, unchanged-skipped, failed), embedder model.
- **`SearchRequest` / `SearchResult`**:
  - request: query, mode (`bm25` | `vector` | `hybrid` | `hybrid_rerank`), chunking strategy, `k`, filters (article, doc type, outcome, date range);
  - result: hits with **per-method scores and ranks** (bm25, vector, fused/RRF, rerank, each nullable), chunk, paragraph IDs, case name, timings. **Results capped at 50** (`.max(50)`).
- **`AnswerRequest` / `Answer`**:
  - request: question, options;
  - answer: route used (`rag` | `stats`), answer text; `claims[]`, each with text, `citation_ids[]` and verification status (`supported` | `unsupported` | `unverified`) with a short reason; `citations[]` (paragraph ID, case name, quote/snippet, link target); for the stats route, SQL used + result rows + matching cases; `refused_or_not_in_sources` flag; cost (USD) + tokens + latency per step; models used. **Payload < 50 KB** (enforced by a test against the fixture and against a generated worst case).
- **`StatsQueryResult`**: question, SQL, columns, rows, matching cases (as citations), count, explanation.
- **`EvalItem`**: ID, question, type (explain / stat / neutrality), expected paragraph IDs, reference answer notes, `status` (`draft` | `reviewed`), tags. **`EvalRun`**: run ID, config (chunking × mode × rerank × models), metrics (recall@5, recall@10, MRR, faithfulness, citation accuracy, neutrality), per-item results, cost, timings.
- **`CostLogEntry`**: ID, timestamp, model, purpose (`embed` | `generate` | `verify` | `route` | `judge` | `rerank`), tokens in/out/cached, cost USD, latency ms, request ID.
- Keep `Health` as is.

**Contract tests** (in `packages/contract/test/`, run by `pnpm check`):

1. Every fixture validates against its schema.
2. **No field exists only in a fixture or only in a schema.** Schemas are `.strict()`, so a fixture with an unknown field fails. Also walk every schema's object shape and assert every property, optional ones included, appears in at least one fixture. Add extra fixture files such as `Answer.stats.json` if one fixture can't cover every branch; keep a clear naming rule and update the existing "every fixture has a schema" test accordingly.
3. The `Answer` fixture and a generated worst case are < 50 KB.
4. `SearchResult` with 51 hits fails.
5. `schema/*.json` is up to date.

Add a Python test in `py/tests/test_contract_fixtures.py` (add `"tests"` to pytest `testpaths`). It validates every fixture against the exported JSON Schema with `rag.contract.contract_errors`, proving the zod → JSON Schema export works from Python too.

### D. Ingestion time estimate → `docs/learn/ingestion-estimates.md`

Time each stage on the snapshot with **throwaway prototype code in `scripts/g0b/`**. Gate 1 writes the real implementations; yours only need to be realistic.

- **download**: real HUDOC, at ≤1 req/s;
- **parse**: HTML/DOCX → paragraphs;
- **chunk**: all three strategies;
- **embed**: **both** `BAAI/bge-small-en-v1.5` and `BAAI/bge-base-en-v1.5` via `sentence-transformers` on CPU. Record the batch size, the hardware (`sysctl -n machdep.cpu.brand_string`, cores) and the one-off model download time separately;
- **index**: insert rows plus the BM25 index plus a vector index into a **scratch schema `g0b_bench`**. Drop it when done.

Write a table of per-document cost per stage. Then extrapolate the time for:

- (a) the snapshot;
- (b) the **full UK corpus**, using your real HUDOC counts;
- (c) adding 100 new documents later.

Name the bottleneck stage and explain *why* in plain English. The 1 req/s download limit is likely the answer for the full corpus; show the arithmetic. Show your measured numbers, not guesses. Where you extrapolate, say so.

### E. Embedder choice → `docs/decisions.md` (append **D-004** only)

- Pick bge-small or bge-base from the benchmark: speed, plus a tiny sanity check of quality (for example, 10 hand-written queries against the snapshot, comparing whether the expected case appears in the top 5).
- State the vector dimension Gate 1 must use.
- The provider must sit behind an interface so that a paid embedder (e.g. voyage-law-2) could be added later. **Do not call any paid embedder.**

### F. Model price check → `config/model-prices.json`

Create this single price file. Gate 1 reads it for `cost_log`. For each model it holds `input_per_mtok`, `output_per_mtok`, `cache_read_per_mtok`, `cache_write_per_mtok` (if published), and a top-level `last_checked` date and `source_url`. Re-verify these against Anthropic's official pricing page (webfetch):

| Model | Input | Output | Note |
|---|---|---|---|
| `claude-sonnet-5-5` | $2 | $10 | |
| `claude-haiku-5-5` | $0.10 | $0.50 | prompts up to 100K tokens |
| `claude-opus-5-5` | $4 | $20 | |

Record any difference prominently in your PR, and also any long-context price tier.

## 3. Ownership

**You own (create or edit):**
- `packages/contract/**`
- `data/snapshot/**`
- `scripts/g0b/**`
- `config/model-prices.json`
- `docs/hudoc-measurement.md`
- `docs/learn/G0b.md`
- `docs/learn/ingestion-estimates.md`
- `py/tests/**`

**Shared files, narrow edits only:**
- `docs/decisions.md`: append D-004 only.
- `py/pyproject.toml` and `py/uv.lock`: add dependencies and `"tests"` to `testpaths` only. Add now **every** dependency Gate 1 will obviously need, so seven parallel tasks don't fight over the lockfile:
  - `httpx`
  - `beautifulsoup4`
  - `lxml`
  - `python-docx`
  - `sentence-transformers`
  - `torch`
  - `numpy`
  - `anthropic`
  - `tenacity`

  Install torch **CPU-only on Linux** (CI), via a `[[tool.uv.index]]` for `https://download.pytorch.org/whl/cpu` with `explicit = true` and a `[tool.uv.sources]` marker for Linux. Put the heavy ML packages (`sentence-transformers`, `torch`) in a uv **dependency group `ml`**, so the default `uv sync` used by CI stays fast. Explain this in your learning doc.
- `.gitignore`: add model-cache paths only, if needed.

**Must not touch:**
- `apps/**`
- `packages/capture/**`
- `py/api/**`
- `py/rag/{ingest,parse,index,search,answer,eval}/**` (these belong to Gate 1 tasks)
- `py/rag/config.py`, `py/rag/contract.py`
- `infra/**`
- `.github/**`
- root `package.json`, `compose.yaml`
- `docs/orchestration/**`, `docs/learn/00-overview.md`, `README.md`

If you believe one of these must change, `ask` the orchestrator first.

## 4. Rules

- **Database:** one shared ParadeDB container serves every worktree (compose project `echr-lookup`, port 5433). Start it with `docker compose up -d --wait` if it isn't running. **Never run `docker compose down -v`.** Use only your scratch schema `g0b_bench`, and use regular tables, not TEMP tables (TEMP tables with BM25 indexes spew warnings; see D-001).
- **Secrets:** never print, log or commit secret values. `.env` is gitignored. This task needs **no** LLM API calls; don't make any. `ANTHROPIC_API_KEY` is not needed.
- **Large files:** never commit `data/raw/` or `data/full/`. The snapshot is capped at 30 MB.
- **Ask before** raising the HUDOC rate above 1 req/s, exceeding 1,500 HUDOC requests, or spending money on anything.
- **Python:** run everything with `uv run` from `py/` (e.g. `uv run --group ml python ../scripts/g0b/bench_embed.py`). Lint with `uv run ruff check` and `uv run ruff format`.
- Keep the PR focused. Commit in logical steps with clear messages.

## 5. Acceptance checks (all must pass before you open the PR)

1. `pnpm check` is green locally, and the PR's GitHub Actions `check` is green. Fix any failures on your branch.
2. `pnpm contract:export && git diff --exit-code packages/contract/schema` shows no diff.
3. Snapshot contents:
   - `du -sh data/snapshot` ≤ 30 MB;
   - judgments 35–45, decisions 35–45 (of which ≥ 15 are inadmissible deportation/expulsion decisions), legal summaries 12–18;
   - the Convention and the HRA 1998 are present.
4. A test (in `py/tests/`) checks every `manifest.json` entry: the file exists and its sha256 matches. It runs offline.
5. Every contract test listed in section C exists and passes.
6. `docs/hudoc-measurement.md` has exact counts with reproducible queries, timings, empty-field stats, format findings, reuse terms (quoted, with URLs), and the total HUDOC request count.
7. `docs/learn/ingestion-estimates.md` has the measured per-stage table, extrapolations (a), (b) and (c), and the bottleneck explanation.
8. D-004 is appended to `docs/decisions.md`, and `config/model-prices.json` exists with `last_checked`.
9. `docs/learn/G0b.md` is written (see section 6).
10. Time budgets: the snapshot build itself (its download portion) should take under 10 minutes at 1 req/s. Running the contract tests must take under 10 s.

## 6. Learning doc → `docs/learn/G0b.md`

Dan is technical but new to RAG. Write plainly, and define every term the first time you use it.

1. **What this is, in plain English** (2–4 short paragraphs): what HUDOC is, what a demo snapshot is, what an API contract is and why it's written once, and what an embedding model is and what you benchmarked.
2. **Why it matters for answer quality**, with one concrete example from this corpus: for instance, why keeping paragraph numbers in the snapshot format makes `[Soering v UK §88]` citations possible, or why picking the embedder matters.
3. **How it works here**: files, key functions, and a small text diagram if useful.
4. **Try it:** 3–6 tests Dan can run himself. Each one is an exact command or URL → what he should see → what this proves. Example of the style: "Run `jq '.[] | select(.doc_type=="decision") | .outcome' data/snapshot/manifest.json | sort | uniq -c` → about 15+ 'inadmissible' → shows the stats demo has real data to count."
5. **Limits / what can go wrong.**

## 7. PR report (put this in the PR description; required)

```
## PR report — G0b
- Model(s): github-copilot/claude-sonnet-5.5
- Wall time: <start> → <PR opened> (UTC); active time: <value or "unavailable">
- Tokens in/out/cached: unavailable to agent — orchestrator appends from `opencode session export`
- Cost: unavailable to agent — orchestrator appends
- HUDOC requests made: <n> (max observed rate: <x> req/s)
- Bottlenecks: <waits, retries, flaky checks, unclear instructions, contract gaps>
- Checks run + results: <each acceptance check, pass/fail with key numbers>
- Price check: <same as plan | differences>
- Plan-changing findings: <anything that changes Gate 1, e.g. empty fields, formats, counts much larger than expected>
- Learning doc: docs/learn/G0b.md
```

Never estimate a metric. Write "unavailable" instead.

## 8. When done

Open the PR. Then send `worker_done` per your Orca preamble, with a three-sentence summary and the PR URL.

- If you're blocked for more than 15 minutes on something only the orchestrator can decide, use `ask`.
- If the contract plan above is wrong or missing something, say so in the PR and in `worker_done`. Don't silently work around it.
