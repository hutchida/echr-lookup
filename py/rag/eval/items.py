"""Load and validate the evaluation question set (data/eval/questions.jsonl)."""

import json
import re
from pathlib import Path

from rag.config import REPO_ROOT
from rag.contract import contract_errors

QUESTIONS_PATH = REPO_ROOT / "data" / "eval" / "questions.jsonl"
SNAPSHOT_DIR = REPO_ROOT / "data" / "snapshot"


def load_questions(path: Path = QUESTIONS_PATH) -> list[dict]:
    items = []
    for line in path.read_text(encoding="utf-8").splitlines():
        if line.strip():
            items.append(json.loads(line))
    return items


def validate_items(items: list[dict]) -> list[str]:
    """Contract violations plus duplicate ids, as readable strings (empty = fine)."""
    errors = []
    seen = set()
    for item in items:
        errors += [f"{item.get('id')}: {e}" for e in contract_errors("EvalItem", item)]
        if item.get("id") in seen:
            errors.append(f"duplicate id {item.get('id')}")
        seen.add(item.get("id"))
    return errors


def expected_count(item: dict) -> int | None:
    """The expected answer of a stat item, from its `expected_count:<n>` tag."""
    for tag in item.get("tags", []):
        m = re.fullmatch(r"expected_count:(\d+)", tag)
        if m:
            return int(m.group(1))
    return None


def snapshot_paragraph_ids() -> set[str]:
    """Every paragraph id that rag.parse (S2) produces from the snapshot."""
    from rag.parse import parse_document

    manifest = json.loads((SNAPSHOT_DIR / "manifest.json").read_text())
    ids: set[str] = set()
    for entry in manifest:
        raw = (SNAPSHOT_DIR / entry["path"]).read_bytes()
        ids |= {p["id"] for p in parse_document(entry, raw)["paragraphs"]}
    return ids
