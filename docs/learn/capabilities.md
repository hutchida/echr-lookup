# What echr-lookup can do

Every capability with a one-line try-it. Start the stack first: `docker compose up -d --wait`, then `WEB_PORT=3100 pnpm dev` (web on :3100, API on :8000). Snapshot mode (98 documents) is the default. Learning doc for each area in brackets.

## Ask questions (web) [I1, S4]

| Capability | Try it |
|---|---|
| Cited answer: every sentence carries a chip naming the case and paragraph | `http://localhost:3100/ask?q=Does the Convention stop the UK deporting criminals?` |
| Per-claim verification: a second model checks each claim against its cited paragraph (Supported / Unsupported / Unverified, with the reason) | Same page → expand **How each claim was checked** |
| Click a citation to read the source paragraph, highlighted | Click any chip → `/case/<id>#p<ref>`, e.g. `http://localhost:3100/case/001-57619#p91` |
| Counting questions answered by SQL, with the query and the matching cases shown | `/ask?q=How many UK deportation complaints in the corpus were declared inadmissible, and the most common reasons?` |
| Router: decides "explain" (RAG) vs "count" (SQL) and shows which it chose | Compare the route badge on the two questions above |
| Cost and latency of every answer, per step (route, retrieve, rerank, generate, verify) | **Cost of this answer** box under any answer |
| Neutral on contested questions: it sets out what the sources show on each side, without a verdict | `/ask?q=Should the UK leave the ECHR?` |
| Shareable answers (the question is in the URL) | Copy any `/ask?q=…` link |

## See how retrieval works [I2, S3]

| Capability | Try it |
|---|---|
| BM25, vector, fused (RRF) and reranked results side by side, with scores, timings and rank movement | `http://localhost:3100/lab` |
| Compare chunking strategies (fixed / recursive / by_section) | `/lab?q=Does the Convention stop the UK deporting criminals?&chunking=by_section` |
| Keyword vs meaning: an exact name vs a paraphrase | `/lab?q=Soering` vs `/lab?q=extradition to face death row` |
| Filter by article or document type | Fill **Article** (e.g. `8`) or **Document type** on `/lab` |

## Measure it [I3, S6]

| Capability | Try it |
|---|---|
| Corpus counts by type, outcome, chamber, article and year | `http://localhost:3100/stats` |
| Last ingestion run with per-stage timings | `/stats` → Ingestion |
| Running app cost from `cost_log` (every LLM and embedding call logged with model, tokens, cost, latency) | `/stats` → Cost, or `curl localhost:8000/costs` |
| Eval table across chunking × search mode: recall@5/10, MRR, faithfulness, citation accuracy, neutrality | `/stats` → Evaluation; per-question results via **per question** |
| Re-run the retrieval eval (free, ~4 min) | `pnpm eval:snapshot --retrieval-only` |
| Full judged eval (answers + judge, ~8 min, ~$2; aborts if the estimate exceeds `--max-cost`, default $3) | `pnpm eval:snapshot` |

## Command line [S1–S4]

| Capability | Try it |
|---|---|
| Load the snapshot (incremental by content hash; `--reset` starts from empty and clears eval runs and cost log) | `pnpm ingest:snapshot` |
| Search from the terminal with any mode, chunking and filters | `pnpm run search "Soering" --mode bm25` (not `pnpm search`: that's pnpm's own command) |
| Filtered search | `pnpm run search "family life" --mode hybrid --article 8 --doc-type judgment -k 5` |
| Ask from the terminal, optionally forcing a route | `pnpm ask "How has Article 8 been applied in UK immigration cases?"` · `--route stats` · `--json` |
| Full HUDOC corpus (3,527 UK documents) in its own DB | `DATABASE_URL=postgresql://echr:echr@localhost:5433/echr_full DATA_SOURCE=full pnpm dev:api` |

## API [S5]

| Capability | Try it |
|---|---|
| Interactive OpenAPI docs with contract-based examples | `http://localhost:8000/docs` |
| Health, including DB extensions and data source | `curl localhost:8000/health` |
| Search / ask over HTTP | `curl -s localhost:8000/search -H 'content-type: application/json' -d '{"query":"Soering","mode":"bm25","chunking":"recursive","k":5}'` |
| Case with all paragraphs | `curl localhost:8000/case/001-57619` |
| Stats, ingest runs, eval runs, costs | `curl localhost:8000/stats` · `/ingest-runs` · `/eval-runs` · `/costs` |
| Every response carries `X-Request-ID` and `Server-Timing`; every error is a contract `ApiError` | `curl -i localhost:8000/case/001-99999` |

## Engineering [G0b, C1]

| Capability | Try it |
|---|---|
| One contract (zod) for every API shape, exported as JSON Schema and checked on both sides | `pnpm --filter @echr/contract test` |
| Whole-repo check: TS typecheck + lint + tests, ruff, pytest (offline, ~1 min) | `pnpm check` |
| Screenshots of any page from a small JSON spec | `pnpm capture packages/capture/specs/I2-lab.json` |
