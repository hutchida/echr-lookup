# Decisions

Short records of choices that shape the project. Newest at the bottom. Each says what we chose, what we tried, and why.

## D-001 — Database: ParadeDB image (pg_search + pgvector in one container)

- **Date:** 2026-11-03 (G0a)
- **Choice:** `paradedb/paradedb:0.26.4-pg17` (Postgres 17.11, pgvector, pg_search).
- **Why:** one container gives us a *real* BM25 index (pg_search, built on Tantivy) next to vector search (pgvector), so hybrid search is two SQL queries against the same rows — no second search engine to keep in sync.
- **Tested:** created both extensions, built a `bm25` index, ran `body @@@ 'deportation'` with `paradedb.score(id)` and a `<=>` cosine query on a `vector(3)` column. Both returned the expected rows.
- **Gotchas found:**
  - `pg_search` depends on `vector`; create `vector` first (`infra/init/01-extensions.sql`).
  - BM25 indexes on **TEMP tables** produce hundreds of `resource was not closed` warnings. Regular tables produce none. Tests should use regular tables (e.g. in a throwaway schema), not temp tables.
  - Image is ~1.5 GB; first pull took ~6 min on this connection. Later `docker compose up -d --wait` takes ~3 s.
- **Fallback (not needed):** `pgvector/pgvector` + the `bm25s` Python library.
- **Port:** host `5433` → container `5432`, to avoid clashing with any local Postgres.

## D-002 — Pinned toolchain

- Node **22.22.0** (`.node-version`, `engines`), pnpm **10.34.7** (`packageManager`, `engine-strict`), Python **3.12** via uv (`py/.python-version`, `requires-python`), uv **0.9.x** (`[tool.uv] required-version`; CI pins 0.9.0).
- **TypeScript 6.0.3, not 7.0.2.** TS 7 is the new native compiler; `typescript-eslint` 8.72 supports only `<6.1`, so 6.0.3 is the newest version the lint stack accepts.
- **ESLint 9.39.5, not 10.** `eslint-config-next` 16.4.4 pulls in `eslint-plugin-import`, `-react` and `-jsx-a11y`, which don't declare ESLint 10 support yet.
- FastAPI's `TestClient` wants `httpx2` (Starlette deprecated `httpx` for it), so the dev group uses `httpx2`.

## D-003 — Models for build agents (not the app)

- Anthropic-direct model IDs (`anthropic/claude-*-5-5`) are not available in opencode on this machine; Dan chose GitHub Copilot's equivalents.
- Orchestrator: `github-copilot/claude-opus-5.5`. Coding sub-agents: `github-copilot/claude-sonnet-5.5`.
- Kimi K3 was considered and rejected: list price $3 / $15 per M tokens (vs Sonnet 5.5's $2 / $10) and clearly weaker on agentic-coding benchmarks (e.g. Terminal-Bench 4.0 ~17% vs ~64%).
- Costs in `docs/orchestration/status.md` are **list-price equivalents** computed from opencode's token counts; GitHub actually bills Copilot via plan premium requests.
- The **app's** runtime models (answer generation, citation check, eval judge) still call Anthropic directly with `ANTHROPIC_API_KEY`.

## D-004 — Embedder: `BAAI/bge-small-en-v1.5`, 384 dimensions, behind an interface

- **Date:** 2026-11-03 (G0b)
- **Choice:** `BAAI/bge-small-en-v1.5` via `sentence-transformers`, **vector dimension 384** (`vector(384)` in pgvector, HNSW with `vector_cosine_ops`). Gate 1 must use exactly this unless this decision is superseded.
- **Compared:** bge-small vs `BAAI/bge-base-en-v1.5` (768 dims), CPU, batch 32, on the 96 HUDOC documents of the snapshot (98 with the Convention and the Human Rights Act, which G0b had not yet added; 1,070,616 tokens, 5,901 recursive chunks) on an Apple M4 Pro.

  | | bge-small | bge-base |
  |---|---:|---:|
  | Embed the snapshot | **41.3 s** (25,900 tokens/s) | 127.4 s (8,400 tokens/s) |
  | Embed full UK corpus (extrapolated, 35.5 M tokens) | **23 min** | 70 min |
  | Table + BM25 + HNSW size (snapshot) | **31.9 MB** | 58.0 MB |
  | Index build (snapshot) | **1.5 s** | 2.5 s |
  | Quality check, 10 hand-written queries, expected case in top 5 chunks | 10/10 (vector, hybrid and BM25) | 10/10 |
  | Quality check, expected case at rank 1 (vector / hybrid) | 10/10, 10/10 | 9/10, 8/10 |

- **Why small:** on a 96-document corpus (the HUDOC part of the snapshot) the two models are indistinguishable on quality (both find the expected case in the top 5 for all 10 queries; small even edged ahead at rank 1, which is noise at n=10), while small is 3x faster, half the size, and keeps embedding cheaper than the 1 request/second download (72 min), so the download stays the bottleneck instead of the CPU (`docs/learn/ingestion-estimates.md`). The check is deliberately small and the corpus tiny: **revisit at full-corpus scale** with the real eval set (S6); the interface below makes that a re-embed of 23-70 minutes, not a rewrite. Retrieval quality will be decided by chunking and hybrid search more than by the model size here.
- **Interface (required):** embedding goes through one small class so a paid embedder (e.g. `voyage-law-2`, 1024 dims) can be added later without touching callers:
  `Embedder` with `name: str`, `dim: int`, `embed_documents(list[str]) -> np.ndarray` and `embed_query(str) -> np.ndarray` (float32, L2-normalised). The bge implementation prepends `"Represent this sentence for searching relevant passages: "` to **queries only** (documents get no prefix). Chunks must be sized with the model's own tokenizer (max 512 tokens; our chunkers target 256). The model name and dimension are recorded in `IngestRun.embedder_model` / `embedding_dim`; the chunk table stores the dimension in its column type, so a model change = new table + re-embed. **No paid embedder was called** in G0b.
- **Where torch comes from:** `sentence-transformers` and `torch` sit in the uv dependency group **`ml`** so the default `uv sync` (and CI) stays small; run embedding with `uv run --group ml ...`. On Linux torch comes from the CPU-only wheel index.
- **Also found (affects Gate 1):** HUDOC is behind a Cloudflare challenge (plain HTTP gets 403); HTML is the right stored format (DOCX loses paragraph numbers); inadmissibility grounds are not in the metadata. Details in `docs/hudoc-measurement.md`.
