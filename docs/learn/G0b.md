# G0b: measuring HUDOC, the demo snapshot, the API contract, ingestion estimates and the embedder

## 1. What this is, in plain English

**HUDOC** is the European Court of Human Rights' public case-law database (https://hudoc.echr.coe.int). For the
United Kingdom it holds about 4,500 English documents: 586 judgments, 2,532 decisions (about half of them old
European Commission decisions), 230 communicated cases (cases sent to the government for comment), 444 legal
summaries and more. This task measured it: how many of each, how fast it answers, how complete its metadata is, in
which download format the text is easiest to use, and what its terms of use allow. One surprise: HUDOC sits behind
a Cloudflare "are you a human?" challenge, so ordinary scripts get a 403 error and we had to go through a real
browser.

A **demo snapshot** is a small, frozen copy of the corpus that is committed to the repository (`data/snapshot/`,
10 MB): 41 judgments, 40 decisions, 15 legal summaries, the Convention and the Human Rights Act 1998, picked so
the demo and the evaluation questions have real answers (Soering, Chahal, Ndidi, Hirst, 27 inadmissible
deportation decisions to count...). Because it is on disk, everything downstream works offline, deterministically,
and fast.

An **API contract** is a written-down agreement about the shape of the data that moves between the parts of the
system: what a "search result", an "answer" or a "paragraph" looks like. We write it **once**, as zod schemas
(`packages/contract/`), and everything else is generated or checked against it: JSON Schema files, Python
validation, test fixtures. Seven Gate 1 tasks will now be built in parallel; if each invented its own shapes they
would not fit together, so they are not allowed to change the contract. The fixtures are real data (real item IDs,
real paragraph text), and tests make sure no field exists only in a schema or only in an example.

An **embedding model** turns a piece of text into a list of numbers (a "vector"; here 384 of them) such that
passages with similar *meaning* get similar numbers. That is how "can we send a man to a country that
executes people?" can find Soering without sharing its words. We timed two such models, `bge-small` (fast, 384
numbers) and `bge-base` (3x slower, 768 numbers), on the snapshot and picked bge-small (decision D-004).

## 2. Why it matters for answer quality

**Paragraph numbers are what make a citation checkable.** The answer will say
`[Soering v UK §88]` and a checker must be able to open paragraph 88 and see that it supports the sentence. That
only works if the stored text keeps the paragraph numbers. We tested three download formats: HTML, DOCX and PDF.
In the 2017 judgment *Ndidi v UK* the DOCX version silently lost 31 of the 86 numbered paragraphs (Word's
automatic numbering is not stored as text), so a claim citing, say, `001-176931§45` could never be verified from
it. HTML kept all 86. That one measurement decided the storage format for the whole project.

The same care applies to **chunks**: Soering's key sentence ("...the applicant's extradition ... would expose him to
a real risk of treatment going beyond the threshold set by Article 3") is not in paragraph 111's first
`<p>` but in an unnumbered continuation block that follows it. A parser that only keeps lines starting with a
number would never index that sentence, and no search could find it.

**Counting questions need metadata you can trust.** "How many UK deportation complaints were declared
inadmissible, and why?" is answered with SQL, not vector search. We found HUDOC's own `conclusion` field says
*why* for only 18 of 671 inadmissible Court decisions. So "how many" can come from metadata, but "why" must be read
from the text. Better to learn that now than after building the stats route.

## 3. How it works here

```
HUDOC (behind Cloudflare)                             data/snapshot/  (committed, offline)
   |  fetch() inside Orca's browser tab,                 manifest.json   one ManifestEntry per document
   |  our limiter: >= 1.05 s between requests    --->    hudoc/<itemid>.html
   v                                                     legislation/{ukpga-1998-42.xml, echr-convention.txt}
scripts/g0b/  (throwaway, Gate 1 rewrites)                     |
   hudoc.py            rate limiter + request counter          v
   measure_*.py        counts, timings, formats      packages/contract/   zod schemas (source of truth)
   download_pool.py    fetch candidates                  src/*.ts  -->  schema/*.json  (pnpm contract:export)
   build_snapshot.py   copy, hash, manifest              fixtures/*.json  built from the snapshot
   bench_*.py          parse, chunk, embed, index        test/*.test.ts, py/tests/*.py  (pnpm check)
   make_fixtures.py    real hybrid search for fixtures
```

Key pieces:

- `packages/contract/src/` has one file per schema family (`source-document.ts`, `paragraph.ts`, `chunk.ts`,
  `search.ts`, `answer.ts`, `stats.ts`, `eval.ts`, `ingest-run.ts`, `cost-log.ts`), shared enums in `shared.ts`
  and the size limits in `limits.ts`. `registry.ts` lists everything that is exported and tested. Schemas are
  `.strict()`, so an unknown field is an error.
- A paragraph id is `<doc-id>§<ref>`: `001-57619§88`, `001-57619§op3` (operative provisions), `002-14484§u2`
  (an unnumbered paragraph in a legal summary).
- Fixtures: `fixtures/<Name>.json` plus `fixtures/<Name>.<variant>.json` for extra branches (a stats answer, a
  refusal). `fixtures/README.md` says which parts are real and which are illustrative.
- **One schema per API response** (added after review): `POST /search` returns `SearchResult`, `POST /ask`
  returns `Answer`, `GET /case/{id}` returns `CaseDetail` (the document plus all its paragraphs, so the viewer can
  scroll to and highlight `§88`), `GET /stats` returns `CorpusStats` (totals, breakdowns by type, outcome, chamber,
  article and year, the last ingest run, costs and the latest eval), `GET /costs` returns `CostSummary`,
  `GET /ingest-runs` returns `IngestRunList`, `GET /eval-runs` returns `EvalRunList` (summaries without per-item
  results) and `GET /eval-runs/{id}` the full `EvalRun`. Every error is an `ApiError`. All are strict and
  size-capped, so a front end can rely on the shapes.
- **Why a decision was inadmissible** now has a home: `SourceDocument.inadmissibility_grounds` (a list such as
  `manifestly_ill_founded`, `non_exhaustion`) and `inadmissibility_grounds_source` (`metadata` if HUDOC states it,
  `text` if extracted from the decision). The manifest fills only the six cases where HUDOC states it; the rest is
  `null` until Gate 1's parser reads the text. `scripts/g0b/grounds_regex.py` is a quick prototype of that reader,
  and `data/snapshot/README.md` lists what it finds for all 35 inadmissible decisions as a test oracle.
- `config/model-prices.json` is the single price file that Gate 1's cost log reads.
- `data/snapshot/README.md` lists every case and why it is there.
- `docs/hudoc-measurement.md` and `docs/learn/ingestion-estimates.md` hold the measurements.

## 4. Try it

Run these from the repository root unless a `cd` is shown.

1. **The stats demo has real data to count.**
   `jq -r '.[] | select(.doc_type=="decision") | .outcome' data/snapshot/manifest.json | sort | uniq -c`
   -> `33 inadmissible`, `4 struck_out`, `2 partly_inadmissible`, `1 admissible`. Of the 33 inadmissible,
   27 are deportation/expulsion/extradition cases (listed in `data/snapshot/README.md`). *Proves:* the
   "how many were declared inadmissible?" question has an answer to find.
2. **Paragraph numbers survived, so citations are possible.**
   `cd py && uv run python -c "import sys; sys.path.insert(0,'../scripts/g0b'); from pathlib import Path; from proto_parse import parse_html; p={x['ref']:x for x in parse_html(Path('../data/snapshot/hudoc/001-57619.html'))}; print('001-57619§88:', p['88']['text'][:140])"`
   -> `001-57619§88: Article 3 (art. 3) makes no provision for exceptions and no derogation from it is permissible...`.
   *Proves:* the stored HTML can be turned into addressable paragraphs.
3. **The snapshot is intact and works offline.**
   `cd py && uv run pytest tests -q` -> everything passes in about a second (one test per stored file checking its
   sha256, plus size, count and "at least 15 inadmissible deportation decisions" checks). Switch Wi-Fi off first if
   you like. *Proves:* the committed files are exactly what the manifest says and no network is needed.
4. **The contract is checked from both languages.**
   `pnpm --filter @echr/contract test` -> 43 tests pass; then
   `cd py && uv run python -c "from rag.contract import *; r=load_fixture('SearchResult'); r['hits']=r['hits'][:1]*51; print([e[-30:] for e in contract_errors('SearchResult', r)])"`
   -> a one-item list ending in `is too long`: 51 hits is over the cap of 50. *Proves:* the 50-result
   cap is enforced by the JSON Schema exported from zod, which Python reads.
5. **HUDOC's own numbers agree with ours.** Open
   `https://hudoc.echr.coe.int/eng#{"respondent":["GBR"],"languageisocode":["ENG"]}` and press reload. The left
   column shows Judgments (586), Grand Chamber (69), Chamber (507), Decisions (2532), Communicated Cases (230),
   Legal Summaries (444). *Proves:* the counts in `docs/hudoc-measurement.md` are not our invention. (If you
   see a different number next month, new cases were published.)
6. **Why bge-small.** Read the table in `docs/learn/ingestion-estimates.md`: embedding the snapshot takes 41 s with
   bge-small and 127 s with bge-base, and both found the expected case in the top 5 for all 10 test questions
   (`docs/decisions.md`, D-004). To rerun the benchmark yourself (about 6 minutes, downloads ~550 MB of models):
   `cd py && uv run --group ml python ../scripts/g0b/bench_models.py && uv run --group ml python ../scripts/g0b/bench_parse_chunk.py && uv run --group ml python ../scripts/g0b/bench_embed.py`
   -> three lines like `{'model': 'BAAI/bge-small-en-v1.5', 'strategy': 'recursive', 'chunks': 5901, ... 'seconds': ~41}` and
   one for bge-base about 3x slower. *Proves:* the speed gap is real on your machine too (absolute times will differ).

## 5. Limits / what can go wrong

- **HUDOC and Cloudflare.** Full-corpus downloading needs a browser-class client and may stop working if the Court
  tightens its challenge. We have no agreement for bulk access; the reuse terms allow free non-commercial reuse
  with attribution, not commercial use. Snapshot mode is unaffected.
- **The snapshot is a sample**, not the corpus: 96 documents out of ~4,100. Retrieval quality measured on it
  (10/10 for both models) overstates what a full-corpus search will do. The eval set (S6) is the real test.
- **"Outcome" is our normalisation** of HUDOC's free-text `conclusion` (e.g. `mixed` = both violation and no
  violation findings). A judgment can be `mixed` and still be a "violation" case to a reader; the raw text is kept
  next to it.
- **The inadmissibility "Ground" column in the snapshot README is a keyword guess** on the last two paragraphs,
  not verified by a lawyer, and some decisions rest on several grounds.
- **The grounds prototype is regex, not law.** It reports the grounds the Court states in a concluding sentence;
  it can miss a ground mentioned only in passing and was checked by reading its evidence sentences, not by a lawyer.
- **Fixtures mix real and illustrative data.** Paragraph text, ids, scores and counts are real; the answer prose,
  claim statuses and token/cost numbers in `Answer*.json` were written by hand (no LLM was called).
- **Quality check is tiny** (10 queries, 96 documents, hand-written by the author who also picked the
  documents). It supports "no visible difference", not "bge-small is as good as bge-base".
- **HUDOC served the files through a browser, so no custom User-Agent was sent for HUDOC.**
- The HUDOC HTML has quirks (glued paragraphs, missing full stops, continuation blocks, restart numbering,
  unnumbered documents) and our prototype parser handles the ones we saw in 96 documents; Gate 1's parser must be
  tested on more.
