# One-shot brief v2: echr-lookup (rewritten from the first build's retrospective)

_For the planning agent. This replaces [`plan.md`](plan.md) (v1 brief plus amendments). Every rule marked **[L]** comes from a lesson in [`retrospective.md`](retrospective.md). The first build met every gate and still needed two rounds of fixes after the owner used the app, so the product rules (section 4) now come first and are checked by a person, not only by metrics._

## 1. Role and operating rules (orchestrator)

You are the master orchestration session (opencode inside Orca, using the Orca CLI). You set up the repo, split work into tasks (one worktree and one self-contained brief each), launch and monitor workers, enforce gates, review and merge, and report to Dan. Learn exact commands from `orca --help` and `orca skills get orca-cli|orchestration`; never guess flags.

- **You never write feature code, fixes included [L].** Every change goes to a Sonnet worker, however small; that includes copy fixes, prompt edits and refactors after owner feedback. Your job is briefs, interfaces, prep, review and merge. (Exception: the G0a scaffold and per-gate prep, i.e. interfaces, typed client and fixtures.)
- **Keep your context small [L].** Targeted reads only. Hand off to a fresh orchestrator session (`handoff.md` + `status.md`) at about 120K tokens of context, or at each gate, whichever comes first. Keep waits for worker mail under 5 minutes while your context is large; prompt-cache expiry re-writes your whole context on the next turn. **Orchestrator spend is capped at 35% of the build budget**; report your share at each gate.
- Poll with a script that prints only deltas. Ack every delivery after deciding the worker's next owner.
- This is a learning project: every task explains what it built in plain English, with tests Dan can run.

## 2. Models and budget

- Orchestrator: `github-copilot/claude-opus-5.5`. All coding workers: `github-copilot/claude-sonnet-5.5`.
- App runtime (via `ANTHROPIC_API_KEY`, client built explicitly from config, never from SDK env defaults, because Dan's shell exports a work-proxy `ANTHROPIC_BASE_URL` [L]):

  | Role | Model |
  |---|---|
  | Answers | `claude-sonnet-5-5` |
  | Router, verifier, stats parameters | `claude-haiku-5-5` |
  | Eval judge | `claude-sonnet-5-5` |
  | Embeddings | local `BAAI/bge-small-en-v1.5` |
  | Reranker | local `BAAI/bge-reranker-base` |

- Prices live in `config/model-prices.json` with a "last checked" date.
- **Budget: $100 all-in** (agents plus app runtime). Message Dan at $50 and $80; pause launches at $100.
- **Every task brief has a hard live-call cap** [L]. A worker asks before exceeding it; you either refuse or escalate to Dan with the new total. Never approve overruns step by step.
- Before each gate, forecast cost as a range from measured usage, including your own share.

## 3. Project

**echr-lookup:** ask questions of the UK's case law at the European Court of Human Rights (HUDOC), plus the Convention and the Human Rights Act 1998, and get answers in which every claim cites the exact paragraph and is verified.
- Neutral: it never takes a side on UK membership, and never says whether a law, policy or judgment is good or bad. A direct answer about **what the law does** is neutral and wanted.
- Counting/statistics questions are answered with SQL over metadata, never by the model.
- **Users:** a voter; a journalist fact-checking "the Convention stops us deporting criminals" (the headline demo); a law student (Article 8 in immigration); a campaigner on either side.
- **Repo:** `~/git/echr-lookup`, GitHub `hutchida/echr-lookup` (private). Local-first; Netlify only if asked.
- **Secrets:** never printed, logged or committed. `.env` is gitignored; `.env.example` has names only.

## 4. Product rules (binding on every task; checked at every gate) [L]

**Answers (RAG route)**
1. **Answer first.** An explain answer opens with ONE sentence that answers the question directly, in terms of what the Court has held or done, citing 1–3 paragraphs that together support it. It is verified like any other claim. The evidence follows as 3–6 points, grouped under short neutral headings when the question has two sides or several grounds.
2. **Reach of the holding.** The short answer opens with "Yes" or "No" only when a cited paragraph states that general rule. When the holdings cover particular applicants, people, places or circumstances, it leads with the holding ("In <case> the Court held that <these applicants>…"). When holdings go both ways it uses "Not as a general rule: …" / "It depends on …". If the stated rule is itself limited, it leads with the limit ("Only in exceptional circumstances: …").
3. **Evidence quality.** Plan the context by legal ground and by outcome both ways; prefer the Court's reasoning and operative provisions over recited legislation (demote statute boilerplate); cap paragraphs per document. Cite the paragraph that states the result for "the Court held".
4. **Citations.** Each citation carries `doc_type` (judgment, decision, communicated, legal_summary, legislation), shown on the chip and in the sources list. A legal summary is visibly not the judgment.
5. **Quotes.** Verbatim; contain the sentence that supports the claim; start and end at sentence boundaries when one exists (`;` and `:` are not sentence ends; abbreviations such as "v.", "art.", "no." and initials are not either; a line break is). Prefer the sentence with the claim's distinctive tokens (Article numbers). Mark a necessary cut with "…".
6. **Verification never fails silently.** A parse failure retries once; the remaining failures are counted and shown as "Unverified (error)".
7. **Corpus honesty.** The Ask page always states the live corpus (document count from `GET /stats`, UK cases only, and "the small committed sample, not the full HUDOC download" in snapshot mode), linking to Stats. A refusal says that "not in these sources" does not mean the Court never decided it.
8. **Value questions** ("should…", "is it right…") get no verdict: a one-line note, then the strongest sourced points on each side.
9. **Follow-ups.** Under each answer: a question field and 2–3 standalone follow-up questions built from the cited cases and Articles, as plain `GET /ask?q=` links. No threads, memory or previous-question field.

**Counting answers (stats route)**
10. The model only fills a validated parameter template; SQL runs read-only with a timeout; the SQL shown is the SQL run.
11. State **every number the question asks for**: "how many X, and how many of them Y" runs the template twice (scope total + subset) and reports both. Name every filter in plain words; no HUDOC jargon ("in formation"), no raw enum keys, no implied filter the user did not ask for.
12. The count's evidence is the SQL, so the count claim cites no paragraph. Examples are illustrations: when the count is about an outcome, quote the operative clause that states that outcome, or list the case without a quote. Never a clause that contradicts the count (preliminary objection, join to merits, admissibility, "no violation" for a violation count).
13. Definitions that decide counts ("deportation case", "found a violation" includes `mixed`, "declared inadmissible" excludes `partly_inadmissible`) are written down with the eval set and shown in the explanation.

## 5. Monorepo and architecture

| Path | What |
|---|---|
| `apps/web` | Next.js 16 App Router + Tailwind v4 + TS. Talks only to FastAPI, server-side only, through a typed client generated from the contract. Read `node_modules/next/dist/docs/` first: Next 16 differs from training data [L]. |
| `packages/contract` | zod is the single source of truth; exports JSON Schema to `schema/*.json`; fixtures for every shape. |
| `packages/capture` | Playwright screenshot helper; capture specs double as browser smoke tests. |
| `py/` | Python 3.12 + uv: `rag/{ingest,parse,index,search,answer,eval}`, `api` (FastAPI). ruff + pytest; responses validated against the exported JSON Schema in tests. |
| `infra/` | ParadeDB (pg_search BM25 + pgvector). Never `docker compose down -v`. |
| `data/snapshot` | Committed demo corpus; `data/raw`, `data/full` gitignored. |
| `docs/learn`, `docs/orchestration` | Learning docs; status, briefs, report, retrospective. |

- **Pipeline:** ingest (HUDOC + legislation.gov.uk; resumable; incremental by content hash; ≤ 1 req/s) → parse (numbered paragraphs with section labels) → chunk (fixed / recursive / by_section, all stored) → embed + index → search (BM25, vector, RRF, optional rerank) → route (explain → RAG; count → SQL) → generate → verify each claim → API → UI.
- **Every LLM and embedding call writes a `cost_log` row.**
- **Design rules [L]:**
  - search filters by `data_source`, so snapshot and full can share one database;
  - `reset()` keeps `cost_log` and `eval_runs`;
  - the contract must cover every HUDOC doc type (including Commission reports), the eval metrics shown in the README (including stat accuracy), `Citation.doc_type`, nullable example paragraphs, and the stats scope total.
- **Budgets:** answer < 15 s; search < 3 s; every page < 2 s on the snapshot.

## 6. Environment check (G0, before any feature work) [L]

- **Git:** push works (SSH or HTTPS via `gh auth git-credential`).
- **Ports:** 3000 is Dan's other app. Use `WEB_PORT`/`API_PORT` from day one (demo 3100/8000; workers 310N/800N).
- **Shell:** scrub `ANTHROPIC_BASE_URL`/`ANTHROPIC_AUTH_TOKEN`. zsh: no variable named `path`, no word-splitting tricks.
- **Script names:** `pnpm search` is pnpm's own command (use `pnpm run search`); `pnpm dev` runs both servers.
- **Long jobs** (ingest, eval, servers) run in Orca terminals; opencode background shells die when the session idles.
- **Measurement:** estimate ingestion and eval on a **random sample of the full corpus**, under realistic load, with real tokenizer chunk counts. Report ranges.

## 7. Gates

Nothing starts before the previous gate is merged and main is green. Every gate ends with an **owner review** [L]: Dan (or you, with transcripts sent to Dan) runs the 10 review questions (section 8) against the live app and marks each answer's shape against the expectations. A failed review sends the work back before the gate closes.

- **G0:**
  - **G0a** scaffold plus environment check (section 6);
  - **G0b** HUDOC measurement, snapshot (98 documents chosen for the demo questions), contract (section 5 rules), estimates (section 6), embedder choice;
  - **G0c eval set first [L]:** 60–100 questions with expected paragraphs, expected counts and SQL oracles, written definitions, the 10 owner-review questions with expected answer shapes, all `status: draft` for Dan.
- **Gate 1 (service).** Parallel workers, disjoint paths, an orchestrator-owned `docs/interfaces.md` (signatures, tables, ports, ownership), one database per worker template-copied from a single orchestrator ingest (never parallel embedding [L]).
  - **Tasks:** S1 ingest, S2 parse/chunk, S3 index/search, S4 answer/citations/stats (section 4 rules 1–13; the eval set is its acceptance test), S5 API, S6 eval runner, C1 capture.
  - **Ingest acceptance [L]:**
    - the listing pager terminates (test on a recorded last page);
    - transient failures retry 3× (5/15/45 s), blocks never;
    - a `--limit` dry run precedes any full run.
  - **Check:**
    - `pnpm check`;
    - snapshot ingest within the estimate range;
    - search < 3 s, answer < 15 s;
    - eval table produced, stat accuracy ≥ 11/12;
    - owner review passes.
  - **Then:** the full ingest, once, at 1 req/s via the Orca browser transport.
- **Gate 2 (interface).** Prep first: typed client, nav shell, ownership table, test IDs, per-worker ports/databases.
  - **Tasks:** I1 Ask + case viewer (corpus line, answer-first layout, doc-type chips, follow-ups), I2 Lab, I3 Stats.
  - **Check:**
    - `pnpm check`;
    - each page < 2 s;
    - every demo step reachable;
    - capture specs pass;
    - owner review passes.
- **Rehearsal:** `docs/demo.md` (script plus what to say), run twice from a fresh `docker compose up`, timings logged. Only copy and label fixes, done by a worker.

## 8. Owner review set (Dan's 10 questions, expected shapes)

Draft these in G0c from the demo and the defects in `retrospective.md` §7; for example:
1. "Does the Convention stop the UK deporting criminals?" → "Not as a general rule: …"; Article 3 and Article 8 holdings, both outcomes.
2. "How has Article 8 been applied in UK immigration cases?" → a short answer plus grouped holdings.
3. "Does the Convention apply to British troops in Iraq?" → leads with the holding's reach (who was within jurisdiction), not "Yes".
4. "How many UK deportation complaints were declared inadmissible, and the most common reasons?" → count, reasons, SQL, example cases.
5. "How many Grand Chamber judgments are in the corpus, and how many of them found a violation?" → both numbers; violation clauses only.
6. "Does a ban on full-face veils breach Article 9?" → refusal that names the corpus limits.
7. "Should the UK leave the ECHR?" → no verdict, both sides sourced.
8. A question whose best source is a legal summary → chip labelled "Legal summary".
9. A question whose support sits in a paragraph's 2nd or 3rd sentence → the source card shows that sentence whole.
10. A follow-up link from any answer → a fresh, standalone answer.

## 9. Eval

recall@k and MRR (retrieval, free), plus faithfulness, citation accuracy, neutrality and stat accuracy (judged, capped cost).
- **Judge rules [L]:**
  - a multi-citation short answer is scored on its citations together;
  - neutrality items are sampled at least 3× and reported as pass rates;
  - unscored items are reported, never silently dropped.
- Results go to `docs/eval-results.md` and the README table. The metrics do not replace the owner review.

## 10. Learning docs, PR report, monitoring

- **`docs/learn/<task>.md`:** what it is (plain English); why it matters (one corpus example); how it works (files, small diagram); try it (3–6 exact commands → what you see → what it proves); limits. At the end: `docs/learn/README.md` (reading order) and `capabilities.md`.
- **PR report:**
  - model;
  - wall time;
  - tokens and cost ("unavailable" if unknown; the orchestrator appends real usage);
  - live spend against the cap;
  - bottlenecks;
  - checks with numbers;
  - learning doc link.
- **Monitoring:** stalled = 15 min with no progress → nudge, or relaunch once with a corrected brief, then escalate. Failing checks go back to the worker; never fixed in main by you.
- **Commits:** `docs/orchestration/**` and `scripts/orchestration/**` go straight to main; code goes through PRs (CI green, owned paths only, squash, delete branch).
- **At the end:** `docs/orchestration/report.md` (per-task time/tokens/cost/models, estimates vs actuals, bottlenecks) and `retrospective.md` (what went well, what went wrong, pitfalls by stage, requirements for the next brief).

## 11. Ask Dan before

- Anything costing money beyond Anthropic usage.
- Making anything public; changing secrets.
- Running the full ingest more than once; raising the HUDOC request rate.
- Exceeding a task's live-call cap or the gate forecast by more than 25%.
