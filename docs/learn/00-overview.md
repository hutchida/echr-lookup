# 00 — The whole pipeline in plain English

This is the map. Every other doc in `docs/learn/` zooms into one box on it.

## What we're building

You type a question like *"Does the Convention stop the UK deporting criminals?"* The system finds the exact paragraphs in European Court of Human Rights (ECHR) judgments that bear on it. It writes a short, neutral answer where **every sentence points to the paragraph it came from**, and then checks each of those pointers before showing you the answer.

That pattern is called **RAG — Retrieval-Augmented Generation**:

- **Retrieval:** find the relevant pieces of text first (a search problem).
- **Augmented:** paste those pieces into the prompt you send to a language model.
- **Generation:** the model writes an answer *using only those pieces*.

**Analogy.** A research assistant in a law library. Instead of answering from memory, which can be wrong or made up (*hallucination*), they first pull the right volumes off the shelf. Then they bookmark the exact paragraphs and write a memo that cites each bookmark. Finally, a second person checks every citation before the memo goes out.

## The stages

```
 HUDOC + legislation.gov.uk
          │
   1. INGEST     download documents + metadata, politely, skipping what hasn't changed
          │
   2. PARSE      turn HTML/DOCX into numbered paragraphs with section labels
          │
   3. CHUNK      group paragraphs into search-sized pieces (3 strategies, compared)
          │
   4. EMBED +    store each chunk twice: as words (BM25 index) and as meaning (vectors)
      INDEX
          │
   5. SEARCH     keyword search + meaning search → merge (RRF) → optional rerank
          │
   6. ANSWER     router: "explain" → cited answer;  "count/stats" → SQL over metadata
          │
   7. VERIFY     check each claim against the paragraph it cites; drop or flag failures
          │
   8. API + UI   FastAPI serves it; the web app shows answers, citations and the Lab
          │
   9. EVAL       a fixed question set scores every combination, so changes are measured, not guessed
```

### 1. Ingest — *fetch the books*

HUDOC is the court's public database. We download UK cases (judgments, decisions, legal summaries) plus the Convention text and the Human Rights Act 1998. We download at most one request per second, which is polite to a public service. Each document gets a **content hash**, a fingerprint of its text. Re-running ingest skips anything whose fingerprint hasn't changed, so new cases can be added any time without re-downloading everything.

### 2. Parse — *number every paragraph*

ECHR judgments already number their paragraphs (§1, §2…) and group them into sections: *Procedure*, *The Facts*, *The Law*, and the *operative provisions* (the court's actual ruling). We keep those numbers and labels. Each paragraph gets a stable ID like `001-57619§88`, the document ID plus the paragraph number. That ID is what a citation points to, so it must never change.

### 3. Chunk — *decide what one search result is*

A **chunk** is the unit we search over. Too small and it loses context; too big and it's vague, and it wastes the model's attention. We build three versions and measure which works best:

- **fixed:** every N words, regardless of meaning;
- **recursive:** split on paragraph breaks first, then sentences, until each piece fits;
- **by-section:** respect the judgment's own structure.

Every chunk remembers which paragraph IDs it contains, so citations stay exact.

### 4. Embed + index — *two card catalogues*

- **BM25** is a classic keyword-ranking formula. It's great at exact names and phrases ("Soering", "Article 8 § 2"). It rewards rare words appearing often in a chunk.
- An **embedding** is a list of numbers (a *vector*) that captures a text's *meaning*. Texts about similar things get similar vectors, even with no words in common: "extradition to face death row" lands near *Soering v UK*. A small open-source **embedding model** runs on your own CPU to make these, for free.

Both live in one Postgres database: `pg_search` for BM25, `pgvector` for vectors.

### 5. Search — *ask both catalogues, merge, re-check*

We run BM25 and vector search separately, then merge the two ranked lists with **Reciprocal Rank Fusion (RRF)**. RRF gives each result points for ranking high in *either* list, which rewards results that both methods like. Optionally, a **reranker** (a *cross-encoder*, a slower model that reads the question and a chunk together) re-scores the top results more carefully. The **/lab** page shows all four columns side by side, so you can see what each step adds.

### 6. Answer — *write the memo, or count*

A **router** first decides what kind of question this is:

- **Explain** ("how has Article 8 been applied…?") → RAG. The model gets the top chunks and must cite a paragraph ID for each claim, like `[Soering v UK §88]`.
- **Count / statistics** ("how many deportation complaints were declared inadmissible?") → no vector search at all. We run a SQL query over case metadata (outcome, article, document type) and show you the query. Language models are bad at counting things they've only skimmed; databases are perfect at it.

The system prompt keeps answers **neutral**. It presents the strongest sourced points on each side, never gives an opinion on whether the UK should stay in the Convention, and says "not in the sources" when that's the honest answer.

### 7. Verify — *check every citation*

For each claim, a cheap, fast model reads the cited paragraph and answers one question: *does this paragraph actually support this sentence?* Unsupported claims are removed or visibly flagged. This is what makes the citations trustworthy rather than decorative.

### 8. API + UI

FastAPI exposes `/search`, `/ask`, `/stats`, `/case/{id}` and more. The web app is the only consumer. The **contract** (`packages/contract`) defines every request and response shape once, in zod, and exports JSON Schema. Both TypeScript and Python test against it, so the front end and back end can't silently drift apart.

### 9. Eval — *measure, don't guess*

A set of 60–100 questions, each with the paragraph IDs a good answer should cite. We score:

- **recall@k:** did the right paragraphs appear in the top k results?
- **MRR (Mean Reciprocal Rank):** how high did the first right one appear?
- **faithfulness:** does the answer stick to its sources? A judge model scores this.
- **citation accuracy:** do the citations point to paragraphs that support the claim?
- **neutrality:** checked on contested questions.

The runner tries every *chunking strategy × search mode* combination and writes a results table. That table is how we decide, with evidence, which setup to use.

## Cost and speed

Every model call (embedding, generation, verification, judging) writes a row to a `cost_log` table: model, tokens, cost and how long it took. The **/stats** page totals it.

Budgets: search under 3 s, a full answer under 15 s.

## Try it now (Gate 0)

| Run | You should see | What it proves |
|---|---|---|
| `docker compose up -d --wait` | `Container echr-lookup-db-1 Healthy` | The database (ParadeDB) is running. |
| `docker compose exec db psql -U echr -d echr -c "\dx"` | `pg_search` and `vector` listed | Both search engines live in one Postgres: BM25 for words, pgvector for meaning. |
| `pnpm dev`, then open http://localhost:8000/health | `{"status":"ok", … "extensions":["pg_search","vector"]}` | The Python API is up and can see both extensions. |
| Open http://localhost:3000 | "API status: ok" with a round-trip time | The web app talks to the API, and the reply passed the shared contract check. |
| `pnpm check` | everything green, ending with `3 passed` | Types, lint, tests and the contract all agree on both the TypeScript and Python sides. |

> Note: port 3000 must be free for `pnpm dev`. Run `WEB_PORT=3100 pnpm dev` to use another port.
