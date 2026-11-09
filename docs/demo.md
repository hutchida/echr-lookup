# Demo script (snapshot mode, ~2 minutes)

The headline: a journalist fact-checks "the Convention stops us deporting criminals". Every claim on screen links to the paragraph it came from, and the system shows its working: which route answered, what it cost, and how retrieval ranked the evidence.

## Before the audience arrives (once, ~5 min)

```sh
docker compose up -d --wait          # ParadeDB (BM25 + pgvector) on :5433
WEB_PORT=3100 pnpm dev               # web :3100, API :8000 (port 3000 is taken on Dan's Mac); ready in ~15 s
```

- **Corpus:** `/stats` should show 98 documents. Only on a new clone or empty DB run `pnpm ingest:snapshot` (~4 min). Skip it otherwise: each run is recorded, and a no-change run (~5 s, 98 skipped) becomes the "last ingestion run" that `/stats` shows, which is less interesting than the full load's stage timings.
- **Eval table:** `/stats` shows the runs stored in `eval_runs`. `pnpm ingest:snapshot --reset` empties that table (and `cost_log`), so after a reset run `pnpm eval:snapshot --retrieval-only` (~4 min, free) or the judged run (~8 min, ~$2) before demoing.
- **Warm up** (dev mode compiles each page on first visit, and the API loads its models at start): open `/`, `/ask`, `/lab`, `/stats` and `/case/001-57619` once, and ask Q1 once (~$0.02).
- Tabs to have open: `http://localhost:3100/ask` and `http://localhost:8000/docs` (the API, if anyone asks "what's behind it?").
- Budgets to quote if asked: answers < 15 s (typically 6–7 s), search < 3 s (the Lab runs four searches in ~1 s), every page < 2 s.

## 1. The headline question (~35 s)

Click **"Does the Convention stop the UK deporting criminals?"** under *Try one of these* (or open `/ask?q=Does the Convention stop the UK deporting criminals?`).

**Say while it thinks (~7 s):** "It searches 98 documents (UK judgments, decisions and case summaries from the Strasbourg court, plus the Convention and the Human Rights Act), writes a short answer and grouped evidence, then a second model checks every claim against the paragraph it cites."

**Point at:**
- the route badge **"RAG: retrieved + cited"**;
- the **short answer** at the top (an answer-first sentence such as "Not as a general rule: the Court has blocked some UK deportations, such as Chahal v UK (Article 3) and A.A. v UK (Article 8), while it held in Balogun v UK that deporting to Nigeria would not violate Article 8"); the exact wording varies from run to run;
- the grouped evidence under it (e.g. *Article 3: an absolute bar where there is a real risk of ill-treatment*, *Article 8: where the Court allowed deportation*), with a chip after each sentence naming the case and paragraph;
- the green **Supported** badges: "each one means the checker found that claim in the cited paragraph; anything it can't verify is flagged, not hidden";
- **Cost of this answer** (~$0.02) and its per-step breakdown.

**Say:** "So the honest answer is: not as a general rule. The Court has allowed some deportations and blocked others; it depends on the facts, and you can check each one yourself. A claim the checker could not support is listed as left out, not hidden."

**Click a chip** (e.g. *Balogun v UK §30*) → `/case/001-110271#p30` opens with that paragraph highlighted and labelled **Cited paragraph**. "That's the Court's own words; nothing is paraphrased without a source."

## 2. Article 8 in immigration (~20 s)

Back, then click **"How has Article 8 been applied in UK immigration cases?"** (~7 s).

**Say:** "Article 8 is the right to private and family life. The answer pulls together several cases, again with a chip on every sentence, so a law student can go straight to the reasoning."

## 3. A counting question goes to SQL, not the language model (~20 s)

Click **"How many UK deportation complaints in the corpus were declared inadmissible, and the most common reasons?"** (~2 s).

**Point at:** the badge **"Stats: SQL over metadata"**, the count (27), the top reasons (manifestly ill-founded, domestic remedies not exhausted, outside the Convention's scope), the **SQL used** and the **matching cases** list.

**Say:** "Language models are bad at counting. A small router spotted this is a numbers question and sent it to a database query instead, and it shows you the exact query so you can audit the number."

## 4. Lab: how retrieval found the evidence (~25 s)

Open **Lab** in the nav (it defaults to the step-1 question; `/lab?q=…&chunking=recursive`).

**Point at the four columns, left to right:**
- **BM25 (keyword):** matches exact words; great for names and terms, blind to synonyms.
- **Vector (meaning):** matches meaning, so "deport" also finds "expulsion" and "removal".
- **Fused (RRF):** merges the two rankings, rewarding passages both methods like.
- **Reranked:** a second model reads each question–passage pair and reorders the top 30; the arrows show how far each passage moved.

**Say:** "The lettered badges follow the same passage across columns. No single method is best, which is why the system combines them." Optionally switch **Chunking** to `by_section` and run again: the hits change, because the text was cut into different pieces.

## 5. Stats: what's in it and how good it is (~15 s)

Open **Stats**.

**Point at:** corpus counts (98 documents, ~9.4k paragraphs; by type, outcome, article and year), the **last ingestion run** with its per-stage timings (embedding dominates), the **running app cost** from `cost_log`, and the **evaluation table** (recall@k, MRR, faithfulness, citation accuracy, neutrality per chunking × search mode).

**Say:** "This is how we know it works rather than hoping: 71 test questions, scored on whether the right paragraphs were found and whether the answers stayed faithful to them and neutral."

## If something goes wrong

| Symptom | Fix |
|---|---|
| Home page says the API is unreachable | Is `pnpm dev` running? `curl localhost:8000/health` |
| `/ask` shows an error after ~1 s | Check `ANTHROPIC_API_KEY` in `.env`; the app ignores the shell's `ANTHROPIC_BASE_URL` on purpose |
| `/stats` eval table is empty | Run `pnpm eval:snapshot --retrieval-only` (see *Before the audience arrives*) |
| First page visit is slow | Dev-mode compile; warm up first |
| Port 3000 in use | Use `WEB_PORT=3100` (Dan's other dev server owns 3000) |

## Rehearsal log (2026-11-04, snapshot mode, fresh `docker compose down && up`, live Anthropic)

| Step | Run 1 (main @ `1676572`) | Run 2 (main @ `2f8251b`, after #20) | Budget |
|---|---|---|---|
| Stack ready after `pnpm dev` | 13 s | 13 s | — |
| 1. `/ask` Q1 (streamed; shell first byte < 0.2 s) | 7.8 s, 7 chips | 7.8 s, 10 chips | < 15 s |
| 1. Chip → `/case/…#p…` highlighted | 0.10 s | 0.15 s | < 2 s |
| 2. `/ask` Q2 | 6.3 s | 6.5 s, 9 chips | < 15 s |
| 3. `/ask` Q3 (stats route) | 1.3 s | 1.2 s | < 15 s |
| 4. `/lab` (default) / `by_section` | 1.07 s / 1.89 s | 1.08 s / 1.92 s | < 2 s |
| 5. `/stats` | 0.16 s | 0.16 s | < 2 s |
| Browser capture specs (`I1-*`, `I2-lab`, `I3-stats`, `home`) | all pass | all pass | — |

First `/lab` after a restart takes ~2.2 s (the search models warm up on the first query): covered by the warm-up. Copy/label fixes from run 1, merged in #20 before run 2: the stats count sentence (natural wording, every SQL filter named, chips at the sentence end), plain labels for inadmissibility grounds, and HTTP 404 for unknown case ids.
