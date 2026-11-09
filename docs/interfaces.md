# Gate 1 interfaces (orchestrator-owned)

The zod contract (`packages/contract`) fixes the **API shapes**. This file fixes the **internal seams** between the Gate 1 tasks: Python function signatures, database tables, configuration and test conventions. The tasks build in parallel, so each one codes against this file, not against another task's unfinished code.

**Rules**
- If you own a module below, implement **exactly** these names and signatures. You may add more; you may not rename or remove anything.
- If you depend on a module that isn't merged yet, code against the signature and use a small local fake in your tests.
- After your dependency merges, the orchestrator will ask you to rebase and switch to the real thing.
- If a seam is wrong or missing, `ask` the orchestrator. Never work around it silently.

## 1. Data shapes in Python

Plain `dict`s shaped exactly like the contract types: `SourceDocument`, `Paragraph`, `Chunk`, `SearchRequest`, `SearchResult`, `AnswerRequest`, `Answer`, `IngestRun`, `CostLogEntry`, `EvalItem`, `EvalRun`, and so on. Validate them in tests with `rag.contract.contract_errors("<Name>", obj)`. Snapshot entries are `ManifestEntry` dicts read from `data/snapshot/manifest.json`. Don't create parallel pydantic models of the contract unless you also test them against the JSON Schema.

## 2. Module seams

### `rag.parse` (owner: S2)
```python
STRATEGIES: tuple[str, ...] = ("fixed", "recursive", "by_section")

def parse_document(entry: dict, raw: bytes) -> dict:
    """ManifestEntry-shaped metadata + stored file bytes (HTML/XML/txt) ->
    {"document": SourceDocument dict, "paragraphs": list[Paragraph dict] in document order}.
    Paragraph ids follow data/snapshot/README.md (<doc>§<n>, §op<n>, §u<n>, §art<n>).
    For inadmissible / partly_inadmissible decisions whose inadmissibility_grounds is null,
    extract the grounds from the text and set inadmissibility_grounds_source = "text"."""

def chunk_paragraphs(paragraphs: list[dict], strategy: str, *,
                     count_tokens: Callable[[str], int] | None = None,
                     max_tokens: int = 256) -> list[dict]:
    """-> list[Chunk dict]. ids '<doc>:<strategy>:<index>'. paragraph_ids non-empty, in order.
    count_tokens comes from the embedder (rag.index.Embedder.count_tokens). If None, use a cheap
    approximation so tests need no ML packages."""
```

### `rag.index` (owner: S3)
```python
def connect(url: str | None = None) -> psycopg.Connection        # default rag.config.database_url()
def migrate(conn) -> None          # idempotent; applies infra/migrations/*.sql in order
def reset(conn) -> None            # drop all app tables, then migrate(): "start from empty"

class Embedder(Protocol):
    model_name: str
    dim: int                       # 384 for bge-small (D-004)
    def embed(self, texts: list[str]) -> list[list[float]]   # L2-normalised
    def count_tokens(self, text: str) -> int

def get_embedder(name: str | None = None) -> Embedder
    # name defaults to rag.config.embedder_name(). "fake" = deterministic hash-based vectors,
    # dim 384, no ML packages (tests and CI). Real models load once per process (cache).

def upsert_document(conn, document: dict, paragraphs: list[dict]) -> None   # replaces paragraphs
def replace_chunks(conn, doc_id: str, strategy: str, chunks: list[dict],
                   vectors: list[list[float]], embedder_model: str) -> None
def stored_hashes(conn) -> dict[str, str]          # item_id -> sha256 (incremental ingest)
def record_ingest_run(conn, run: dict) -> None     # IngestRun dict
def log_cost(conn, *, model: str, purpose: str, tokens_in: int, tokens_out: int,
             tokens_cached: int, latency_ms: float, request_id: str) -> dict
    # computes cost_usd from config/model-prices.json (local models cost 0; Haiku's
    # >100K-token tier applies per request), inserts into cost_log, returns CostLogEntry dict
def price_usd(model: str, tokens_in: int, tokens_out: int, tokens_cached: int) -> float
```

### `rag.search` (owner: S3)
```python
def search(conn, request: dict, *, embedder: Embedder | None = None, reranker=None) -> dict
    # SearchRequest dict -> SearchResult dict. Fills every per-method score/rank the mode ran,
    # null otherwise. Logs the query embedding (purpose "embed") and any rerank ("rerank")
    # via log_cost. Hits capped at 50.
def get_reranker(name: str | None = None)   # cross-encoder; "fake" for tests
```
CLI: `python -m rag.search "<query>" --mode bm25|vector|hybrid|hybrid_rerank --chunking recursive -k 10 [--article 8] [--doc-type decision] …` prints a readable table. This is `pnpm search`.

### `rag.answer` (owner: S4)
```python
def answer(conn, request: dict) -> dict              # AnswerRequest dict -> Answer dict
def route(conn, question: str, request_id: str) -> str          # "rag" | "stats"
def run_stats(conn, question: str, request_id: str) -> dict     # -> StatsQueryResult dict

# rag.answer.llm: the ONLY place the app calls Anthropic. S6's judge uses it too.
@dataclass
class LLMResult:
    text: str; model: str; tokens_in: int; tokens_out: int; tokens_cached: int; latency_ms: float
def complete(conn, *, model: str, system: str, messages: list[dict], purpose: str,
             request_id: str, max_tokens: int = 1024, temperature: float = 0.0) -> LLMResult
    # Builds anthropic.Anthropic(api_key=rag.config.anthropic_api_key(),
    #                            base_url=rag.config.anthropic_base_url())
    # explicitly; NEVER relies on SDK env defaults (the shell may point ANTHROPIC_BASE_URL at
    # a work proxy). Logs every call via rag.index.log_cost.
    # rag.config.llm_mode() == "fake" -> deterministic canned output, no network.
```
CLI: `python -m rag.answer "<question>"` prints the answer with citations, route, SQL (stats) and cost. This is `pnpm ask`.

### `rag.ingest` (owner: S1)
```python
def run_ingest(conn, source: str, *, limit: int | None = None, reset: bool = False) -> dict  # -> IngestRun
```
CLI: `python -m rag.ingest --source snapshot|full [--limit N] [--reset]`. These are `pnpm ingest:snapshot` / `pnpm ingest:full`.

### `rag.eval` (owner: S6)
CLI: `python -m rag.eval --source snapshot [--quick] [--no-judge]`, which is `pnpm eval:snapshot`. It stores `EvalRun` rows in `eval_runs`, writes `docs/eval-results.md`, and replaces the README section between `<!-- eval:start -->` and `<!-- eval:end -->`.

### `api` (owner: S5)
FastAPI app `api.main:app`. Endpoints and contract types:

| Endpoint | Request | Response |
|---|---|---|
| `POST /search` | `SearchRequest` | `SearchResult` |
| `POST /ask` | `AnswerRequest` | `Answer` |
| `GET /stats` | — | `CorpusStats` |
| `GET /case/{id}` | — | `CaseDetail` |
| `GET /ingest-runs` | — | `IngestRunList` |
| `GET /eval-runs` | — | `EvalRunList` |
| `GET /eval-runs/{id}` | — | `EvalRun` |
| `GET /costs` | — | `CostSummary` |
| `GET /health` | — | `Health` |
| any error | — | `ApiError` |

Load the embedder and reranker **once at startup** (lifespan), not per request.

## 3. Database (owner: S3, `infra/migrations/*.sql`; everyone else reads these names)

```sql
documents (
  item_id text PRIMARY KEY, case_name text NOT NULL, application_numbers text[] NOT NULL,
  ecli text, doc_type text NOT NULL, chamber text, date date NOT NULL, articles text[] NOT NULL,
  outcome_raw text, outcome text NOT NULL, importance int, language text NOT NULL,
  source_url text NOT NULL, sha256 text NOT NULL, data_source text NOT NULL,
  inadmissibility_grounds text[], inadmissibility_grounds_source text,
  ingested_at timestamptz NOT NULL DEFAULT now())
paragraphs (
  id text PRIMARY KEY, doc_id text NOT NULL REFERENCES documents(item_id) ON DELETE CASCADE,
  position int NOT NULL, number int, section text NOT NULL, text text NOT NULL)
chunks (
  id text PRIMARY KEY, doc_id text NOT NULL REFERENCES documents(item_id) ON DELETE CASCADE,
  strategy text NOT NULL, position int NOT NULL, text text NOT NULL,
  paragraph_ids text[] NOT NULL, token_count int NOT NULL,
  embedding vector(384), embedder_model text NOT NULL)
  -- BM25 (pg_search) index over chunks.text (plus whatever S3 needs to filter by strategy);
  -- HNSW (vector_cosine_ops) on embedding. BM25 over paragraphs.text is allowed too
  -- (S4's stats route may use it to find deportation-related decisions).
ingest_runs (run_id text PRIMARY KEY, started_at timestamptz NOT NULL, payload jsonb NOT NULL)  -- IngestRun
cost_log (id text PRIMARY KEY, timestamp timestamptz NOT NULL, model text NOT NULL,
  purpose text NOT NULL, tokens_in int NOT NULL, tokens_out int NOT NULL,
  tokens_cached int NOT NULL, cost_usd numeric NOT NULL, latency_ms numeric NOT NULL,
  request_id text NOT NULL)
eval_runs (run_id text PRIMARY KEY, created_at timestamptz NOT NULL, payload jsonb NOT NULL)  -- EvalRun
schema_migrations (version text PRIMARY KEY, applied_at timestamptz NOT NULL DEFAULT now())
```
Column names equal the contract field names, so rows map 1:1 to contract dicts. S3 may add indexes and helper columns, but must not rename these.

## 4. Configuration (`py/rag/config.py`, orchestrator-owned; read-only for tasks)

| Function | Default |
|---|---|
| `database_url()` | — |
| `data_source()` | — |
| `data_dir()` | — |
| `answer_model()` | `claude-sonnet-5-5` |
| `router_model()` | `claude-haiku-5-5` |
| `verify_model()` | `claude-haiku-5-5` |
| `judge_model()` | `claude-sonnet-5-5` |
| `embedder_name()` | `BAAI/bge-small-en-v1.5`, or `fake` |
| `reranker_name()` | `BAAI/bge-reranker-base` |
| `rerank_enabled()` | — |
| `llm_mode()` | `live`, or `fake` |
| `model_prices_path()` | — |
| `anthropic_api_key()` | — |
| `anthropic_base_url()` | — |

If you need a new knob, `ask`; don't edit `config.py`.

## 5. Tests and CI (`py/conftest.py`, orchestrator-owned)

- Tests default to `EMBEDDER=fake`, `LLM_MODE=fake` and `RERANK_ENABLED=0`, so CI needs no ML packages, no network and no API key.
- **Database tests use the `test_database_url` / `db_conn` fixtures.** They point at `<your DATABASE_URL db>_test`, created on demand with both extensions. Never run destructive operations against `DATABASE_URL` itself in tests.
- `@pytest.mark.ml`: needs `uv sync --group ml` (real embedder or reranker); auto-skipped if missing. CI does not install `ml`.
- `@pytest.mark.live`: real network or paid API; runs only with `RUN_LIVE=1`. **Never** in CI.
- `pnpm check` must stay under ~2 minutes in CI and must pass offline.

## 6. Databases, one per worktree

One shared ParadeDB container (`localhost:5433`, compose project `echr-lookup`). Each Gate 1 worktree gets its own database, `echr_<task>` (e.g. `echr_s3`), already created with both extensions, and its `.env` sets `DATABASE_URL` to it. Tests then use `echr_<task>_test`. The orchestrator's integration database is `echr`. **Never** run `docker compose down -v`.

## 7. Merge order and rebasing

Merge order is S2 → S3 → S1 → S4 → S5 → S6 → C1. A task whose dependencies aren't merged ships with fakes and skip-if-missing integration tests. When the dependencies land, the orchestrator dispatches a follow-up: "rebase on main, switch to the real modules, run the integration acceptance checks".

---

# Gate 2 interfaces (web UI; orchestrator-owned)

The API is merged and fixed: talk to it **only** through `apps/web/lib/api.ts`. The contract and every `py/**` file are read-only in Gate 2.

## 8. Path ownership

| Task | Owns (may create/edit) |
|---|---|
| I1 Ask + case viewer | `apps/web/app/ask/**`, `apps/web/app/case/**`, `apps/web/app/layout.tsx`, `apps/web/app/page.tsx`, `apps/web/app/globals.css`, `apps/web/components/**` (shared components, the only shared UI folder) |
| I2 Lab | `apps/web/app/lab/**` (route-local components in `apps/web/app/lab/_components/`) |
| I3 Stats | `apps/web/app/stats/**` (route-local components in `apps/web/app/stats/_components/`) |

Each task also owns `docs/learn/<id>.md`, `docs/learn/img/<id>-*.png` and `packages/capture/specs/<id>-*.json`.
**Read-only for all three:** `apps/web/lib/api.ts` (ask the orchestrator if it lacks something), `packages/**` except your capture specs, `py/**`, every `package.json`, `pnpm-lock.yaml`, `apps/web/next.config.ts`, `apps/web/tsconfig.json`, `apps/web/eslint.config.mjs`. **No new dependencies.** I2/I3 must not import from `apps/web/components/**` (it's I1's and isn't merged yet); keep their UI route-local.

## 9. Web conventions

- **Server-side API calls only.** Call `@/lib/api` from Server Components, Server Actions or Route Handlers, never from the browser: `API_URL` is server-only and the API's CORS allows only ports 3000/3100. Interactive pages use URL search params (e.g. `/lab?q=…&chunking=recursive`) or Server Actions.
- **Every result is an `ApiResult<T>`** (`{ok:true,data,ms}` or `{ok:false,error,status,apiError,ms}`). Render the error state readably (API down, 404, contract mismatch); never crash the page.
- **Layout:** `layout.tsx` renders only the top nav (`data-testid="site-nav"`: echr-lookup / Ask / Lab / Stats). Each page renders its own `<main>` (`mx-auto max-w-6xl px-6 py-10`; reading pages may use `max-w-3xl`). Tailwind v4 with the stone palette already in use; no other CSS framework.
- **Next.js 16 / React 19:** read `apps/web/AGENTS.md` and the guides in `apps/web/node_modules/next/dist/docs/` before using an API you're unsure of (e.g. async `params` / `searchParams`).
- **Tests:** vitest in `node` (no jsdom, no testing-library: no new deps). Put display logic in pure functions (`*.test.ts` next to them) and test them on the contract fixtures; optionally render a component with `react-dom/server`'s `renderToString`.
- **Stable `data-testid`s** for capture specs and the demo script: I1 `ask-input`, `ask-submit`, `answer`, `citation` (one per chip), `claim-status`, `answer-route`, `stats-sql`, `answer-cost`, `case-paragraph` (with `id="p<ref>"`), highlighted paragraph `data-highlighted="true"`; I2 `lab-query`, `lab-column-bm25`, `lab-column-vector`, `lab-column-fused`, `lab-column-reranked`; I3 `stats-counts`, `stats-ingest`, `stats-costs`, `stats-eval`.
- **Citation links:** `Citation.link_target` is `/case/<doc_id>#p<ref>` (`ref` = the part after `§`, e.g. `88`, `op1`, `u3`, `art8`). The case page puts `id="p<ref>"` on each paragraph and highlights the hash target.

## 10. Per-worker environment

| Task | DB | API (`API_PORT`) | Web (`WEB_PORT`) |
|---|---|---|---|
| I1 | `echr_i1` | 8001 | 3101 |
| I2 | `echr_i2` | 8002 | 3102 |
| I3 | `echr_i3` | 8003 | 3103 |

Each DB is a copy of the integration DB `echr` (snapshot corpus loaded, 12 eval runs). **Never use ports 3000 or 8000** (Dan's other dev server and the orchestrator). Start the API with `API_PORT=800N pnpm dev:api` and the web app with `API_URL=http://localhost:800N WEB_PORT=310N pnpm dev:web` (Next does not read the root `.env`). Capture with `pnpm capture <spec> --base-url http://localhost:310N`.
