# Ingestion time estimates (G0b)

How long does each stage of the pipeline take per document, and so how long will it take to ingest the
demo snapshot, the full UK corpus, or 100 new documents? Measured with throwaway prototypes in `scripts/g0b/`
(Gate 1 writes the real ones, which should be of similar speed). **Measured** numbers come from runs on the
machine below; **extrapolated** numbers are marked as such and show their arithmetic.

> Re-measured during G0b-fix: the first benchmark used a parser that lost most of the text of 7 unnumbered
> decisions (it mistook numbered sub-headings such as "1. The applicant's submissions" for paragraphs). After the
> fix the snapshot is 1,070,616 tokens (was 1,035,112, +3.4%); every number below is from the re-run.

## Setup

| | |
|---|---|
| Machine | Apple M4 Pro (`sysctl -n machdep.cpu.brand_string`), 14 logical cores, 48 GB RAM, macOS 15.6.1 |
| Embedding | `sentence-transformers` + `torch 2.15.0`, **CPU only** (`device="cpu"`, 10 torch threads), batch size **32**, vectors L2-normalised |
| Models | `BAAI/bge-small-en-v1.5` (384 dimensions, 33M parameters) and `BAAI/bge-base-en-v1.5` (768 dimensions, 109M parameters). Max sequence 512 tokens |
| Database | the shared ParadeDB container (Postgres 17, `pg_search` BM25 + `pgvector` HNSW), scratch schema `g0b_bench` (regular tables, dropped afterwards) |
| Corpus | the demo snapshot: **96 HTML documents** (41 judgments, 40 decisions, 15 legal summaries; the two legislation files are not part of this prototype) = 7,422 paragraphs = **1,070,616 tokens** |
| Download | real HUDOC through Orca's browser tab, limiter 1.05 s between requests |

**One-off model download** (not part of per-document cost): bge-small **18.3 s** (first load incl. download),
bge-base **16.5 s**; warm load from the local cache 0.8 s each. The Hugging Face cache for both is about 556 MB.

## Measured: the snapshot, stage by stage

| Stage | What was run | Total for 96 documents | Per document | Per 1,000 tokens |
|---|---|---:|---:|---:|
| **Download** | HUDOC HTML body, 1 request per 1.05 s | **103.4 s** | 1.08 s | 0.097 s |
| **Parse** | HTML to paragraphs (`lxml`) | 0.40 s | 4.1 ms | 0.37 ms |
| **Chunk** | `recursive` (paragraph-packed, 256 tokens) | 2.30 s | 24 ms | 2.1 ms |
| | `fixed` (256-token window, 32 overlap) | 2.15 s | 22 ms | 2.0 ms |
| | `by_section` (<= 480 tokens, never crosses a section) | 1.61 s | 17 ms | 1.5 ms |
| **Embed**, bge-small, `recursive` (5,901 chunks) | CPU, batch 32 | **41.3 s** | 0.43 s | 0.039 s |
| Embed, bge-small, `fixed` (4,811 chunks) | | 45.0 s | 0.47 s | |
| Embed, bge-small, `by_section` (3,012 chunks) | | 61.1 s | 0.64 s | |
| Embed, **bge-base**, `recursive` | CPU, batch 32 | **127.4 s** | 1.33 s | 0.119 s |
| **Index**, bge-small `recursive`: COPY insert 0.49 s + BM25 build 0.13 s + HNSW build 0.91 s | | **1.53 s** | 15.9 ms | 1.4 ms |
| Index, bge-small `fixed` | | 1.26 s | 13.2 ms | |
| Index, bge-small `by_section` | | 0.80 s | 8.3 ms | |
| Index, bge-base `recursive` (insert 0.94 + BM25 0.13 + HNSW 1.40) | | 2.47 s | 25.8 ms | |

Embedding throughput: bge-small ~**25,900 tokens/s** (143 chunks/s of 181 tokens) on `recursive`; bge-base
~**8,400 tokens/s** (46 chunks/s): bge-base is **3.1x slower** and its vectors are twice as large.
`by_section` embeds more slowly per token (17,500 tokens/s) because its chunks are longer (mean 355 vs 181
tokens) and attention cost grows with length.

Table + index size on disk (rows + heap + BM25 + HNSW): bge-small `recursive` 31.9 MB (5,901 rows),
`fixed` 28.4 MB, `by_section` 20.4 MB; bge-base `recursive` 58.0 MB.

**Snapshot total, measured end to end (serial): bge-small 149.0 s (about 2.5 minutes) = 103.4 + 0.4 + 2.3 + 41.3 + 1.5;
bge-base 236.0 s (about 3.9 minutes).** Download is 69% of the small-model total and 44% of the base-model total.

Per-document cost on the snapshot's average document (11,152 tokens, 61 chunks): download 1.08 s, parse 4 ms,
chunk 24 ms, embed 0.43 s (small) or 1.33 s (base), index 16 ms (small).

## Extrapolation (these are computed, not measured)

Per-type average size from the snapshot (recursive chunking): judgment **18,746 tokens** (103 chunks), decision
**7,086 tokens** (39 chunks), legal summary **1,238 tokens** (7 chunks). The snapshot's decisions are the long,
reasoned Article 3/8 ones (median 5,111 tokens), so for the thousands of short Commission and Committee
decisions this **over**-states tokens (conservative). Communicated cases are assumed to be the size of legal
summaries and Commission reports the size of judgments: there is **no snapshot sample** for either, so those
two lines are guesses.

Rates used: download 1.05 s per document (the limiter; the in-browser fetch itself takes 0.2 s, inside that window)
plus one listing request per 500 documents; CPU stages scale with tokens: parse 0.37 us/token, chunk 2.1 us/token,
embed 38.6 us/token (small) or 119 us/token (base), index 1.4 us/token (small) or 2.3 us/token (base). HNSW build
is super-linear in row count, so index time at full size is probably under-estimated (but it starts from 1.5 s,
so even 5x is under a few minutes).

### (a) The snapshot (measured above)

| | bge-small | bge-base |
|---|---:|---:|
| Download / embed / everything else | 103 s / 41 s / 4 s | 103 s / 127 s / 5 s |
| **Total, serial** | **149 s** | **236 s** |

### (b) Full UK corpus

Two definitions, English only, from the counts in `docs/hudoc-measurement.md`:

- **Core** = 586 judgments + 1,326 Court decisions + 444 legal summaries = **2,356 documents**, ~20.9 M tokens.
- **Full text** = 586 judgments + 2,532 decisions (Court + Commission) + 230 communicated + 444 legal summaries +
  307 Commission reports = **4,099 documents**, ~35.5 M tokens ((586 + 307) x 18,746 + 2,532 x 7,086 +
  (230 + 444) x 1,238).

| Stage | Core, small | Core, base | Full text, small | Full text, base |
|---|---:|---:|---:|---:|
| Download: N x 1.05 s + listing | 2,356 x 1.05 + 3 = **41.3 min** | same | 4,099 x 1.05 + 9 = **71.9 min** | same |
| Parse | 8 s | 8 s | 13 s | 13 s |
| Chunk | 45 s | 45 s | 76 s | 76 s |
| Embed: tokens / rate | 20.9 M / 25.9 k/s = **13.5 min** | 20.9 M / 8.4 k/s = **41.5 min** | 35.5 M / 25.9 k/s = **22.9 min** | 35.5 M / 8.4 k/s = **70.5 min** |
| Index | 30 s | 48 s | 51 s | 82 s |
| **Total if run one stage after another** | **56.1 min** | 84.5 min | **97.1 min** | 145.2 min |
| **Total if download and embed overlap** (pipeline: embed document N while downloading N+1) | **41.3 min** | 41.3 min | **71.9 min** | 71.9 min |

Index size at full scale (linear extrapolation from 29.8 MB per million tokens, small): about **1.03 GB**
(base: 1.88 GB); about 196,000 chunks. Raw HTML at full size is roughly 300 MB (not committed; `data/full/`).

### (c) Adding 100 new documents later

100 documents at the full-corpus average mix = 866,474 tokens.

| Stage | bge-small | bge-base |
|---|---:|---:|
| Check what changed: 1 listing request (`length=500`) + sha256 compare | ~1 s | ~1 s |
| Download 100 x 1.05 s | 105 s | 105 s |
| Parse + chunk | 2 s | 2 s |
| Embed | 34 s | 103 s |
| Index (inserts into existing indexes) | about 1 s | about 2 s |
| **Total, serial** | **~2.4 min** | **~3.6 min** |

The 1 req/s limit costs 1 min 45 s of that; the embedder is not the limiting factor for incremental updates.

## The bottleneck, in plain English

**For the full corpus the bottleneck is the download, because of the politeness rule, not because anything is
slow.** HUDOC answers in a quarter of a second, but we promised to ask for only one document per second, so
4,099 documents need 4,099 seconds of waiting however fast our machine is: 72 minutes. A faster computer or a
second CPU does nothing for that, and "going faster" would mean breaking the rule.

The runner-up is embedding, which is **CPU bound**: turning 35 million tokens into vectors takes 23 minutes
with bge-small. With bge-base it takes 70 minutes, about the same as the download, so bge-base would turn
a download-bound job into a roughly 50/50 job and add more than an hour if the two ran one after the other.
Parsing, chunking and indexing are noise (seconds to a minute or two in total).

For the **snapshot** the picture is similar but compressed: 103 of 149 seconds are the 1 request/second wait.
This is why the committed snapshot exists: once a document is on disk, re-running everything else costs 46
seconds.

Practical consequences:

1. Download once, cache the raw files, never re-download unless the document changed (sha256 compare).
2. Overlap download and embed (a queue between them) and the total is the download time alone.
3. Choose **bge-small**: it keeps the embed stage below the download stage (D-004).
4. Switching embedder later means re-embedding every chunk: 23 minutes (small) to 70 minutes (base) for the
   full corpus, or a 3-4 minute re-embed of the snapshot. It never means re-downloading.

## Caveats

- One machine, one run per configuration; embed times vary a few percent between runs (bge-small `recursive`:
  7.0 ms/chunk in both of the last two runs).
- The prototype parser/chunkers are simple; Gate 1's will cost somewhat more per document but not orders of
  magnitude (chunk and parse are 1-2% of the total).
- Extrapolations assume the full corpus looks like the snapshot per document type; the Commission decisions
  and reports are the least certain lines.
- On the Linux CI runner torch is installed CPU-only; embedding there will be slower than on an M4 Pro (we do not
  embed in CI: the default `uv sync` does not install the `ml` group).
- Download timings use the in-browser path forced by Cloudflare (`docs/hudoc-measurement.md`); a different
  transport would not change the 1 req/s floor.
