"""Time parse + the three chunkers over the whole snapshot; write chunks for later stages."""

import json
import os
import statistics as st
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
os.environ["HF_HOME"] = str(ROOT / "data" / "raw" / "g0b" / "hf")
os.environ["HF_HUB_OFFLINE"] = "1"
sys.path.insert(0, str(Path(__file__).parent))
from proto_chunk import STRATEGIES  # noqa: E402
from proto_parse import completeness, parse_html  # noqa: E402
from transformers import AutoTokenizer  # noqa: E402

SNAP = ROOT / "data" / "snapshot"
BENCH = ROOT / "data" / "raw" / "g0b" / "bench"
BENCH.mkdir(parents=True, exist_ok=True)
manifest = json.loads((SNAP / "manifest.json").read_text())
tok = AutoTokenizer.from_pretrained("BAAI/bge-small-en-v1.5")
tok_base = AutoTokenizer.from_pretrained("BAAI/bge-base-en-v1.5")
assert tok.get_vocab() == tok_base.get_vocab(), "tokenizers differ"

docs, parse_times, parse_stats = {}, [], {}
for e in manifest:
    if e["format"] != "html":
        continue
    t0 = time.perf_counter()
    paras = parse_html(SNAP / e["path"])
    parse_times.append(time.perf_counter() - t0)
    docs[e["item_id"]] = paras
    parse_stats[e["item_id"]] = {"type": e["doc_type"], "n": len(paras), **completeness(paras)}
print(
    "parse: docs",
    len(docs),
    "total s",
    round(sum(parse_times), 2),
    "median ms",
    round(st.median(parse_times) * 1000, 1),
)

results = {
    "parse": {
        "docs": len(docs),
        "total_s": sum(parse_times),
        "mean_ms": 1000 * st.mean(parse_times),
        "p95_ms": 1000 * sorted(parse_times)[int(0.95 * len(parse_times)) - 1],
        "paragraphs_total": sum(len(p) for p in docs.values()),
    }
}
bad = {
    k: v
    for k, v in parse_stats.items()
    if v["type"] in ("judgment", "decision") and (v["gaps"] or v["dups"] or v["n_numbered"] == 0)
}
results["parse"]["docs_with_gaps_or_dups_or_zero_numbered"] = bad
results["parse"]["stats"] = parse_stats
(BENCH / "paragraphs.json").write_text(json.dumps(docs))

for name, fn in STRATEGIES.items():
    t0 = time.perf_counter()
    chunks = []
    for did, paras in docs.items():
        for i, c in enumerate(fn(paras, tok)):
            chunks.append({"id": f"{did}:{name}:{i}", "doc_id": did, "strategy": name, **c})
    dt = time.perf_counter() - t0
    toks = [c["token_count"] for c in chunks]
    results[name] = {
        "chunks": len(chunks),
        "total_s": dt,
        "ms_per_doc": 1000 * dt / len(docs),
        "tokens_total": sum(toks),
        "tokens_mean": st.mean(toks),
        "tokens_max": max(toks),
        "over_512": sum(t > 512 for t in toks),
    }
    (BENCH / f"chunks_{name}.json").write_text(json.dumps(chunks))
    print(
        name,
        {k: (round(v, 3) if isinstance(v, float) else v) for k, v in results[name].items()},
        flush=True,
    )
(BENCH / "parse_chunk.json").write_text(json.dumps(results, indent=1))
print("bad docs:", json.dumps(bad))
