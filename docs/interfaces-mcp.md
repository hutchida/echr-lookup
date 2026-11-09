# MCP slice interfaces (orchestrator-owned; binding for M1, M2, M3)

The zod contract in `packages/contract/src/mcp/` fixes every tool's **arguments and result** (JSON Schema: `packages/contract/schema/Mcp*.json`; real-snapshot fixtures: `packages/contract/fixtures/Mcp*.json`). This file fixes everything else: names, which `py/rag` functions each tool calls, the server text, the `tool_log` table, ports and file ownership. Rules from `docs/interfaces.md` still hold: implement exactly these names; code against a seam with a local fake if it isn't merged yet; if a seam is wrong or missing, `ask`, never work around it.

```
Claude Desktop / Claude Code / M2 harness ──MCP (stdio, or streamable HTTP :8100/mcp)──► py/echr_mcp
                                                                                          │ calls Python directly (no HTTP)
                                                  rag.search · rag.answer.stats · rag.answer.citations · api.queries
                                                                                          │
                                                                        ParadeDB (BM25 + pgvector), tool_log
```

## 1. Package and entry points (M1)

- Python package **`py/echr_mcp/`** (import name `echr_mcp`). Not `py/mcp/`: a package named `mcp` would shadow the official SDK's own `mcp` import.
- SDK: the official Python MCP SDK, **`mcp` 2.3.x** (already in `py/pyproject.toml` + `uv.lock`; v2 differs from v1: read its current docs/README, don't code from memory).
- `python -m echr_mcp --transport stdio` and `python -m echr_mcp --transport http --port <port>` (streamable HTTP at `http://127.0.0.1:<port>/mcp`, default port 8100). Root scripts: `pnpm run mcp:stdio`, `pnpm run mcp:http` (`cd py && uv run --group ml python -m echr_mcp …`).
- `echr_mcp.server.build_server(conn_factory=None, *, embedder=None, reranker=None)` returns the configured server object (tests inject fakes). Models load **once at startup** and are warmed (one dummy embed + rerank), so the first search is not a cold start.
- Each tool is a plain function `echr_mcp.tools.<tool_name>(conn, args: dict, …) -> dict` that returns the contract result dict. The MCP layer only validates, times, logs and serialises.
- Advertised schemas come **from the contract files**: `inputSchema` = `$defs[<Name>]` of `schema/Mcp<Tool>Input.json`, `outputSchema` = `$defs[<Name>]` of `schema/Mcp<Tool>Result.json` (each file has exactly one `$ref`; a contract test guarantees it). Results go out as `structuredContent` **and** one text block with the same JSON (older clients read the text).
- Every tool is annotated `readOnlyHint: true, destructiveHint: false, idempotentHint: true, openWorldHint: false`. No LLM calls anywhere in the server.
- Bad arguments or unknown ids → an MCP tool error (`isError: true`) with one plain sentence, e.g. "No case 001-99999 in this corpus (snapshot: 98 UK documents)." `get_paragraphs` instead lists unknown ids in `not_found`.

## 2. Tools

Every result has `corpus` = `{documents, data_source, scope, sample_note}`: `documents` from `SELECT count(*) FROM documents WHERE data_source = rag.config.data_source()`, `scope` = `"UK cases only (plus the Convention and the Human Rights Act 1998)"`, `sample_note` = `"Small committed sample, not the full HUDOC download."` in snapshot mode, else `null`. Results are **≤ 25,000 bytes** as compact UTF-8 JSON (`MCP_LIMITS.resultMaxBytes`); where the schema limits allow more, the tool trims (rules below).

Shared helpers (M1, in `echr_mcp`): `display_case_name()` (HUDOC upper-case → `Chahal v. the United Kingdom`, `McCann and Others v. the United Kingdom`, `Othman (Abu Qatada) v. …`; already-mixed-case names unchanged), `DOC_TYPE_LABELS` (as in the contract), `cite(case_name, doc_type, paragraph_id)` → `[<display name>, <label>, §<ref>]`, `hudoc_url` = `documents.source_url`.

| Tool | Contract (Input / Result) | Calls | Budget (warm) |
|---|---|---|---|
| `search_case_law` | `McpSearchCaseLaw*` | `rag.search.search(conn, {…rag.answer.context.search_request(query, {}), "k": 30, "filters": …})`, then `rag.answer.citations.best_quote(paragraph_text, query, max_chars=600)` | < 3 s |
| `get_paragraphs` | `McpGetParagraphs*` | SQL on `paragraphs` (by `position`) + `documents` | < 1 s |
| `get_case` | `McpGetCase*` | `api.queries.get_case(conn, case_id)` (or equivalent SQL) | < 1 s |
| `count_cases` | `McpCountCases*` | `rag.answer.stats`: `sanitize_params`, `build_query`, `execute_readonly`, `wants_total_and_subset`, `_top_group`, `_scope_phrase`, `_explain`, `_compose` | < 1 s |
| `corpus_info` | `McpCorpusInfo*` | `api.queries` bucket SQL / `corpus_stats` helpers; `missing` from the last full ingest run where known, else the documented figures | < 1 s |
| `check_quote` | `McpCheckQuote*` | `rag.answer.citations._sentence_spans` + `difflib` (deterministic) | < 1 s |

**`search_case_law`**: the existing best setup (the mode and chunking `/ask` uses, i.e. `search_request` defaults, hybrid + rerank), over-fetching `k = 30` chunks. Filters map to `SearchFilters`: `article`, `doc_types: [doc_type]`, `outcomes: [outcome]`, `date_from: <year_from>-01-01`, `date_to: <year_to>-12-31`. **`data_source`**: `rag.search` has no such filter and is read-only in this slice, so drop hits whose document's `data_source` ≠ `rag.config.data_source()` (each DB holds one source, so this is a guard, not a ranking change). For each chunk hit, pick the one paragraph among its `paragraph_ids` whose `best_quote` matches the query best (most distinctive query words; ties → first). One paragraph per hit, no duplicate `paragraph_id`, best first, at most `limit` (default 8, max 10). `filters` = the filters in plain words (`"Article 3; judgments; 2000–2020"`, `""` if none).

**`get_paragraphs`**: for each requested id, that paragraph plus `neighbours` (0–2) before and after it in the same document (by `position`), each paragraph once, grouped by document in document order, `requested` true/false. Unknown ids → `not_found`. Size rule: if the result would exceed 25 KB, cut neighbours' text first, then requested texts, at a sentence boundary where possible, append `…`, set `truncated: true`.

**`get_case`**: metadata, `outcome_label` (plain words, same meanings as `packages/contract/src/shared.ts`), `outcome_raw` cut at 2000 chars, all operative provisions (`§op…`) with text cut at 1500 chars, `outline` = consecutive runs of paragraphs by section (max 12; merge the tail into the last run if more). Ids that are not documents → tool error.

**`count_cases`**: the model fills the template; it never writes SQL. Run the same template the `/ask` stats path runs, **without editing `stats.py`**: `params = sanitize_params(args)` (defaults filled), `query = build_query(conn, params)`, the count, the main grouped query, the scope total when `wants_total_and_subset(params, "")` (i.e. `count_of = "total_and_subset"`), `_top_group`. Return:
- `answer`: one or two plain sentences with **every number asked for** and every filter in words (`_compose`'s text with the trailing `Examples: […]` markers removed: **no paragraph citations for the count**);
- `filters` (`_scope_phrase`), `definitions` (what each outcome / topic / chamber / default doc-type filter used means; see the fixtures), `sql` (the exact SQL run, ≤ 4000 chars; if longer, cut and say so), `columns`/`rows`;
- `matching_cases`: up to 20 counted documents, most recent first, **no quotes** (for `top_group` with `group_by = reason`: only documents in the top group), via `execute_readonly` over `matched`;
- `params` (after validation), `count`, `scope_total`, `top_group` (`label` in plain words).
Parity test: for at least 3 parameter sets (the two fixtures + one per-year breakdown), `count`, `scope_total` and `rows` equal what `run_stats_full` returns when its `extract_params` is monkeypatched to return the same params (`LLM_MODE=fake`).

**`corpus_info`**: totals, `by_doc_type`, `by_outcome` (with plain labels), `by_article` (top 25, `8-1` counts as 8), `year_range`, and `missing`: what's not here and why (the snapshot sample, other states' cases, 307 Commission reports, 212 scanned older decisions with no text, 45 communicated cases without numbered paragraphs; counts from the full ingest, see `docs/orchestration/status-build1.md`). Fixture: `McpCorpusInfoResult.json`.

**`check_quote`**: deterministic, no model. Normalise both texts (Unicode NFKC; curly quotes → straight; `–`/`—`/`‑` → `-`; whitespace runs → one space; trim). Split the quote on `…` or `...` into segments; `verbatim` = every non-empty segment occurs in the normalised paragraph, in order. `closest_match` = the paragraph window of 1–3 consecutive sentences (use `_sentence_spans`) with the highest `difflib.SequenceMatcher` ratio against the quote, returned verbatim from the paragraph and cut to 600 chars; `similarity` = that ratio (1.0 when `verbatim`). Unknown paragraph → `paragraph_found: false`, `verbatim: false`, `closest_match: null`, `similarity: 0`.

## 3. Server text (M1 implements verbatim; small wording fixes allowed, the rules are not optional)

> **Superseded by F1 (2026-11-05):** the instructions and tool descriptions below are the original M1 text. The current text, which adds the cite-every-sentence, no-outside-cases and 8–10-claims rules, lives in `INSTRUCTIONS` and `TOOL_SPECS` in `py/echr_mcp/server.py`; `para_label` and text-fragment `hudoc_url`s are described in `docs/learn/mcp.md`.

**Server `instructions`:**
> echr-lookup supplies evidence from the European Court of Human Rights' case law against the United Kingdom, plus the Convention and the Human Rights Act 1998. You write the answer; these tools give you citable paragraphs.
> - Cite after every claim: the hit's `cite` string, or its `paragraph_id`. Quote only text copied from a tool result; if unsure, call `check_quote`.
> - Answer first, in one sentence that matches the reach of the holding. No bare "Yes"/"No" unless a cited paragraph states the general rule; otherwise lead with the holding, "Not as a general rule: …" or "It depends on …".
> - For any "how many" question, call `count_cases`; never count search results. Report every number it returns, with its definitions. The SQL is the evidence for a count; example cases only illustrate it.
> - Say what the corpus covers (see `corpus` in every result): UK cases only and, in snapshot mode, a small sample. "Not found here" does not mean the Court never decided it.
> - A "Legal summary" is the Court's digest of a case, not the judgment: say so when you cite one.
> - Stay neutral: no view on UK membership of the Convention or on whether a law or judgment is good. For value questions, give the strongest sourced points on each side.

**Tool descriptions** (first line, then one rule each):
- `search_case_law`: "Find the paragraphs that best match a question (hybrid keyword + meaning search, reranked). Each hit has a verbatim quote and a ready-to-paste `cite`. Use filters to narrow by Article, document type, outcome or years. Fetch more context with get_paragraphs before relying on a hit."
- `get_paragraphs`: "Full text of paragraphs by id, optionally with neighbouring paragraphs, with section labels. Use it to read the reasoning around a search hit."
- `get_case`: "One document's metadata, outcome, operative provisions (what the Court decided) and an outline of its sections with paragraph ranges."
- `count_cases`: "Answer any 'how many' question by filling a fixed, validated template; the server runs read-only SQL and returns every number, the definitions used, the exact SQL and up to 20 matching cases. Never count search results instead."
- `corpus_info`: "What the corpus contains (counts by document type, Article, outcome, years) and what it lacks and why. Call it before saying something is not in the case law."
- `check_quote`: "Check that a quote appears word for word in a paragraph; returns true/false and the closest matching passage. Use it before quoting when unsure."

## 4. `tool_log` (M1: `infra/migrations/mcp_0001_tool_log.sql`)

```sql
CREATE TABLE IF NOT EXISTS tool_log (
  id bigserial PRIMARY KEY,
  called_at timestamptz NOT NULL DEFAULT now(),
  tool text NOT NULL,
  args jsonb NOT NULL,
  ok boolean NOT NULL,
  error text,
  latency_ms numeric NOT NULL,
  result_bytes int NOT NULL,
  data_source text NOT NULL,
  transport text NOT NULL            -- 'stdio' | 'http'
);
CREATE INDEX IF NOT EXISTS tool_log_called_at ON tool_log (called_at);
```
`rag.index.migrate` applies `infra/migrations/*.sql` in name order (`mcp_0001_…` sorts after `0001_schema.sql`). `reset()` drops only its fixed `APP_TABLES` list, so `tool_log` survives a reset (M1 adds a test that proves it). Logging must never fail a tool call (log errors are swallowed and counted).

## 5. Ports, databases, environment

| Who | DB | Ports |
|---|---|---|
| Dan's app / orchestrator | `echr` | API 8000, web 3100, **MCP HTTP 8100** |
| M1 | `echr_m1` | MCP HTTP **8101** |
| M2 | `echr_m2` | MCP over stdio (no port); 8102 if it needs HTTP |
| M3 | `echr_m3` (host DB, for comparison) + its own compose DB | container API → host **8003**, container MCP → host **8103**, compose DB → host **5434**; compose project name `echr-deploy` |

Each worktree's `.env` sets `DATABASE_URL` to its DB and `DATA_SOURCE=snapshot`. Only M2's `.env` has `ANTHROPIC_API_KEY`. Never use another task's DB or port; never `docker compose down -v` on the `echr-lookup` project.

## 6. File ownership (Gate 1)

| Task | Owns (may create/edit) |
|---|---|
| **M1** MCP server | `py/echr_mcp/**` (tests in `py/echr_mcp/tests/`), `infra/migrations/mcp_*.sql`, `scripts/mcp*`, `docs/mcp-setup.md`, `docs/learn/M1.md`; in root `package.json` only the two scripts `mcp:stdio`, `mcp:http` |
| **M2** comparison eval | `py/rag/eval/agentic/**` (incl. its fake MCP server and tests), `data/eval/agentic/**` (run outputs), `docs/mcp-comparison.md`, `docs/learn/M2.md`; in root `package.json` only the script `eval:agentic` |
| **M3** hosting spike | `infra/deploy/**` (Dockerfile, `Dockerfile.dockerignore`, compose file, scripts), `docs/hosting-options.md`, `docs/learn/M3.md` |

Read-only for everyone: `packages/contract/**` (ask for changes), `py/rag/**` outside your folder, `py/api/**`, `apps/web/**`, `data/eval/questions.jsonl`, `data/eval/owner-review.jsonl`, `py/pyproject.toml` / `uv.lock` (`mcp` is already added; ask before any other dependency), `py/conftest.py`, `.github/**`, `infra/docker-compose.yml`, `infra/migrations/0001_schema.sql`.

## 7. M2 seams

- **Owner-review set:** `data/eval/owner-review.jsonl` (10 items, `status: draft`): `question`, `follow_up_of` (or-10 is asked as a second turn after or-01 in the same conversation), `expected_shape` (prose) and `checks` (machine-checkable hints: `no_bare_yes_no`, `cites_min`, `distinct_cases_min`, `mentions`, `tool_used`, `contains_numbers`, `cites_doc`, `cites_paragraph`, `quotes_contain`, `quotes_verbatim`, `new_tool_calls`, and `judge` for prose checks).
- **Retrieval subset:** 30 items drawn with `random.Random(20261104)` from `data/eval/questions.jsonl` items whose `expected_paragraph_ids` is non-empty; the chosen ids are committed in `data/eval/agentic/subset.json`.
- **Host model:** `claude-sonnet-5-5` via the Messages API, client built as `anthropic.Anthropic(api_key=rag.config.anthropic_api_key(), base_url=rag.config.anthropic_base_url())`. Tools = the server's `list_tools()` (name, description, `inputSchema`) passed as tool definitions; system prompt = the server's `instructions`. Use prompt caching on the system prompt and tool definitions. At most 8 tool calls per question (per turn for or-10). Log every call with `rag.index.log_cost` (purpose `agentic`) so spend shows in `cost_log`.
- **Server under test:** the fake (`py/rag/eval/agentic/fake_server.py`, serving the contract fixtures over stdio with the same tool names, schemas and instructions) until M1 merges; then `python -m echr_mcp --transport stdio` against `echr_m2`.
- **Baseline:** the existing pipeline in-process, `rag.answer.answer(conn, {"question": …})` (no HTTP, no changes). "Fetched" for `/ask` recall = the paragraph ids it put in the model's context (from `rag.answer.context.retrieve`, called read-only, or the Answer's steps if they expose them).
- **Judge:** `rag.eval.judge.judge_support` unchanged. The host answer is split into claims (sentences or bullets), each with the `paragraph_id`s / `cite`s it contains. Report citation accuracy **with each claim scored on all its citations together** (the claim-level verdict) as the headline, and the per-citation figure second, for both systems.

## 8. Merge order and switching

M1 → M3 → M2. M3 builds its image against `python -m echr_mcp` from the start and verifies MCP in the container after M1 merges (rebase). M2 switches from the fake server to the real one after M1 merges, then runs the live comparison.
