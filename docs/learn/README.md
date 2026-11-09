# Learning docs: reading order

Each task in the build wrote a learning doc with the same five sections (what it is, why it matters, how it works here, try it, limits). Read them in pipeline order: the same order a question's evidence travels, from HUDOC to the screen.

| # | Doc | What you learn | Time |
|---|---|---|---|
| 0 | [00-overview.md](00-overview.md) | The whole pipeline in plain English, with the library analogy the other docs build on | 10 min |
| 1 | [G0b.md](G0b.md) | Measuring HUDOC before building: how many UK cases exist, the 98-document demo snapshot, the API contract, choosing the embedder | 10 min |
| 2 | [ingestion-estimates.md](ingestion-estimates.md) | How long downloading and embedding take, and why embedding dominates (estimate vs actual in `docs/orchestration/report.md`) | 5 min |
| 3 | [S1.md](S1.md) | **Ingest:** polite fetching (1 request/s), content hashes for incremental reloads, what an ingest run records | 10 min |
| 4 | [S2.md](S2.md) | **Parse + chunk:** numbered paragraphs and paragraph IDs (`001-57619§88`), sections, and three chunking strategies | 15 min |
| 5 | [S3.md](S3.md) | **Index + search:** BM25, embeddings and vector search, Reciprocal Rank Fusion, cross-encoder reranking | 20 min |
| 6 | [I2.md](I2.md) | **The Lab:** the same four methods side by side on real queries. Read straight after S3 and keep `/lab` open | 15 min |
| 7 | [S4.md](S4.md) | **Answer + citations:** the router (explain vs count), prompting for cited claims, per-claim verification, stats SQL, neutrality | 20 min |
| 8 | [S4-demo.md](S4-demo.md) | Real transcripts of the three demo questions, with costs and timings | 5 min |
| 9 | [S5.md](S5.md) | **The API:** what a contract buys you, validation, request IDs and timing headers | 10 min |
| 10 | [I1.md](I1.md) | **Ask + case viewer:** reading citation chips and verification badges, and checking an answer against the paragraph yourself | 10 min |
| 11 | [S6.md](S6.md) | **Eval:** recall@k, MRR, faithfulness, citation accuracy, neutrality, stat accuracy; the chunking × mode grid | 20 min |
| 12 | [I3.md](I3.md) | **Stats page:** reading the corpus counts, ingestion timings, cost log and eval table | 10 min |
| 13 | [C1.md](C1.md) | The screenshot helper used for every image in these docs | 5 min |

Then:
- [mcp.md](mcp.md): the MCP server's tools, `cite` / `para_label` / text-fragment links, and the server instructions (F1).
- [F3.md](F3.md): fair measurement of Claude + tools against `/ask` (recall at k, new answer key, or-09 diagnosis).
- [capabilities.md](capabilities.md): everything the system can do, each with a one-line try-it.
- [../demo.md](../demo.md): the two-minute demo script.
- [../eval-results.md](../eval-results.md): the full eval tables.
- [../decisions.md](../decisions.md): why ParadeDB (D-001), why a local embedder (D-004), and the other design decisions.

**If you only have 30 minutes:** 00-overview, then S3 with `/lab` open (I2's try-its), then S4, then S6's section 1.
