"""Paths, the 12 configs and small JSONL helpers shared by the judging steps."""

import json
from pathlib import Path

from rag.config import REPO_ROOT
from rag.eval.runner import CHUNKINGS, MODES

JUDGMENTS_DIR = REPO_ROOT / "data" / "eval" / "judgments"
RETRIEVAL_PATH = JUDGMENTS_DIR / "retrieval.jsonl"
POOL_PATH = JUDGMENTS_DIR / "pool.jsonl"
QRELS_V2_PATH = JUDGMENTS_DIR / "qrels-v2.jsonl"
POOL_K = 10
CONFIGS: list[tuple[str, str]] = [(c, m) for c in CHUNKINGS for m in MODES]


def config_key(chunking: str, mode: str) -> str:
    return f"{chunking}/{mode}"


def run_path(run: int) -> Path:
    return JUDGMENTS_DIR / f"judgments-run{run}.jsonl"


def read_jsonl(path: Path) -> list[dict]:
    if not path.exists():
        return []
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line]


def write_jsonl(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in rows), encoding="utf-8"
    )


def append_jsonl(path: Path, row: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(row, ensure_ascii=False) + "\n")
        fh.flush()
