"""Download both embedders once (timed separately from inference). HF cache lives under
data/raw/g0b/hf (gitignored)."""

import json
import os
import time
from pathlib import Path

HF = Path(__file__).resolve().parents[2] / "data" / "raw" / "g0b" / "hf"
os.environ["HF_HOME"] = str(HF)

from sentence_transformers import SentenceTransformer  # noqa: E402

out = {}
for name in ("BAAI/bge-small-en-v1.5", "BAAI/bge-base-en-v1.5"):
    t0 = time.perf_counter()
    m = SentenceTransformer(name, device="cpu")  # downloads on first call
    out[name] = {
        "download_and_load_s": round(time.perf_counter() - t0, 2),
        "dim": m.get_sentence_embedding_dimension(),
        "max_seq_length": m.max_seq_length,
    }
    print(name, out[name], flush=True)
    t0 = time.perf_counter()
    SentenceTransformer(name, device="cpu")
    out[name]["warm_load_s"] = round(time.perf_counter() - t0, 2)
(HF.parent / "bench").mkdir(parents=True, exist_ok=True)
(HF.parent / "bench" / "models.json").write_text(json.dumps(out, indent=1))
print(out)
