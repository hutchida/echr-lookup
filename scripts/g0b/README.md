# scripts/g0b (throwaway)

Prototype and measurement code for task G0b. **Gate 1 writes the real implementations; do not import from here.**
Run everything from `py/` with `uv run` (`uv run --group ml ...` when torch/sentence-transformers are needed).

| Script | Does |
|---|---|
| `hudoc.py` | HUDOC client: fetch() inside Orca's browser tab (Cloudflare), shared >=1.05 s rate limiter, 1,500 hard cap, request log |
| `measure_counts.py`, `verify_counts.py` | exact UK counts per type + full metadata dump to `data/raw/g0b/` |
| `measure_timing.py`, `analyse_hudoc.py` | response-time, rate and empty-field statistics |
| `measure_formats.py`, `analyse_formats.py` | HTML vs DOCX vs PDF |
| `snapshot_ids.py`, `download_pool.py`, `analyse_pool.py`, `grounds.py` | choosing and downloading the snapshot documents |
| `clean_convention.py`, `build_snapshot.py`, `make_snapshot_readme.py` | assemble `data/snapshot/` |
| `proto_parse.py`, `proto_chunk.py` | prototype parser (HTML/DOCX) and the three chunkers |
| `bench_models.py`, `bench_parse_chunk.py`, `bench_embed.py`, `bench_index.py`, `queries.py` | stage timings, embedder benchmark, `g0b_bench` index, 10-query quality check |
| `make_fixtures.py` | builds `packages/contract/fixtures/` from real data |

`data/raw/g0b/` (gitignored) holds downloads, dumps, the Hugging Face cache and benchmark outputs.
