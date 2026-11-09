"""Embed the snapshot chunks with bge-small and bge-base on CPU (sentence-transformers).

Usage: uv run --group ml python ../scripts/g0b/bench_embed.py
Writes timings to data/raw/g0b/bench/embed.json and vectors to bench/emb_<model>_<strategy>.npy.
"""

import json
import os
import platform
import subprocess
import time
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[2]
os.environ["HF_HOME"] = str(ROOT / "data" / "raw" / "g0b" / "hf")
os.environ["HF_HUB_OFFLINE"] = "1"
import torch  # noqa: E402
from sentence_transformers import SentenceTransformer  # noqa: E402

BENCH = ROOT / "data" / "raw" / "g0b" / "bench"
BATCH = 32
MODELS = {
    "BAAI/bge-small-en-v1.5": ["recursive", "fixed", "by_section"],
    "BAAI/bge-base-en-v1.5": ["recursive"],
}

hw = {
    "cpu": subprocess.run(
        ["sysctl", "-n", "machdep.cpu.brand_string"], capture_output=True, text=True
    ).stdout.strip(),
    "logical_cores": os.cpu_count(),
    "ram_gb": int(
        subprocess.run(["sysctl", "-n", "hw.memsize"], capture_output=True, text=True).stdout
    )
    // 2**30,
    "platform": platform.platform(),
    "torch": torch.__version__,
    "torch_threads": torch.get_num_threads(),
    "device": "cpu",
}
out = {"hardware": hw, "batch_size": BATCH, "runs": []}
for model_name, strategies in MODELS.items():
    model = SentenceTransformer(model_name, device="cpu")
    short = model_name.split("/")[1]
    model.encode(["warm up"], batch_size=1)  # exclude one-off lazy init from the timings
    for strat in strategies:
        chunks = json.loads((BENCH / f"chunks_{strat}.json").read_text())
        texts = [c["text"] for c in chunks]
        t0 = time.perf_counter()
        emb = model.encode(
            texts, batch_size=BATCH, normalize_embeddings=True, show_progress_bar=False
        )
        dt = time.perf_counter() - t0
        np.save(BENCH / f"emb_{short}_{strat}.npy", emb.astype(np.float32))
        n_docs = len({c["doc_id"] for c in chunks})
        run = {
            "model": model_name,
            "strategy": strat,
            "chunks": len(chunks),
            "docs": n_docs,
            "tokens": sum(c["token_count"] for c in chunks),
            "seconds": dt,
            "ms_per_chunk": 1000 * dt / len(chunks),
            "chunks_per_s": len(chunks) / dt,
            "s_per_doc": dt / n_docs,
            "dim": int(emb.shape[1]),
        }
        out["runs"].append(run)
        print({k: (round(v, 3) if isinstance(v, float) else v) for k, v in run.items()}, flush=True)
(BENCH / "embed.json").write_text(json.dumps(out, indent=1))
print(hw)
