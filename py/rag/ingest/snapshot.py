"""Snapshot mode: read data/snapshot/manifest.json and the stored files (offline)."""

from __future__ import annotations

import json
from pathlib import Path

from .pipeline import Item


def load_manifest(root: Path) -> list[dict]:
    return json.loads((Path(root) / "manifest.json").read_text())


def items_from_manifest(root: Path, entries: list[dict]) -> list[Item]:
    root = Path(root)
    return [
        Item(entry=e, read=lambda p=root / e["path"]: p.read_bytes())  # type: ignore[misc]
        for e in entries
    ]
