"""DEV ONLY: load the snapshot's HTML documents into DATABASE_URL until S2 (rag.parse) merges.

Uses G0b's throwaway prototypes (scripts/g0b/proto_parse.py, proto_chunk.py) for parsing and
chunking, and rag.index for everything else. py/rag/** never imports those prototypes.
Legislation is skipped (the prototypes only parse HUDOC HTML).

Usage (from py/):  uv run --group ml python ../scripts/s3/load_snapshot_dev.py [--reset]
                   [--strategies recursive fixed by_section] [--limit N]
Set HF_HOME if the Hugging Face cache is not in the default place.
"""

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "scripts" / "g0b"))
sys.path.insert(0, str(ROOT / "py"))

from proto_chunk import STRATEGIES  # noqa: E402
from proto_parse import parse_html  # noqa: E402

from rag import config  # noqa: E402
from rag.index import (  # noqa: E402
    connect,
    get_embedder,
    migrate,
    replace_chunks,
    reset,
    upsert_document,
)

DOC_KEYS = (
    "item_id case_name application_numbers ecli doc_type chamber date articles outcome_raw outcome "
    "inadmissibility_grounds inadmissibility_grounds_source importance language source_url sha256 "
    "data_source"
).split()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--reset", action="store_true")
    ap.add_argument("--strategies", nargs="+", default=list(STRATEGIES))
    ap.add_argument("--limit", type=int)
    args = ap.parse_args()

    from transformers import AutoTokenizer

    embedder = get_embedder()
    tok = AutoTokenizer.from_pretrained(embedder.model_name)
    snap = ROOT / "data" / "snapshot"
    manifest = [e for e in json.loads((snap / "manifest.json").read_text()) if e["format"] == "html"]
    manifest = manifest[: args.limit]

    conn = connect()
    reset(conn) if args.reset else migrate(conn)
    t_all = time.perf_counter()
    n_chunks = 0
    for e in manifest:
        doc = {k: e[k] for k in DOC_KEYS}
        raw = parse_html(snap / e["path"])
        paras = [
            {
                "id": f"{doc['item_id']}§{p['ref']}",
                "doc_id": doc["item_id"],
                "number": p["number"],
                "section": p["section"],
                "text": p["text"],
            }
            for p in raw
        ]
        if not paras:
            print("no paragraphs:", doc["item_id"])
            continue
        upsert_document(conn, doc, paras)
        for strategy in args.strategies:
            chunks = [
                {
                    "id": f"{doc['item_id']}:{strategy}:{i}",
                    "doc_id": doc["item_id"],
                    "strategy": strategy,
                    "text": c["text"],
                    "paragraph_ids": [f"{doc['item_id']}§{r}" for r in c["paragraph_ids"]],
                    "token_count": c["token_count"],
                }
                for i, c in enumerate(STRATEGIES[strategy](raw, tok))
            ]
            replace_chunks(
                conn,
                doc["item_id"],
                strategy,
                chunks,
                embedder.embed([c["text"] for c in chunks]),
                embedder.model_name,
            )
            n_chunks += len(chunks)
        print(f"{doc['item_id']} {len(paras)} paragraphs", flush=True)
    conn.execute("ANALYZE")
    conn.commit()
    print(f"done: {len(manifest)} docs, {n_chunks} chunks in {time.perf_counter() - t_all:.0f}s")
    print("database:", config.database_url().rsplit("/", 1)[-1])


if __name__ == "__main__":
    main()
