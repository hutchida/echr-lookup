import json
from pathlib import Path

import pytest

from rag.config import REPO_ROOT

SNAPSHOT = REPO_ROOT / "data" / "snapshot"


@pytest.fixture(scope="session")
def manifest() -> list[dict]:
    return json.loads((SNAPSHOT / "manifest.json").read_text())


@pytest.fixture(scope="session")
def raw_files(manifest) -> dict[str, bytes]:
    return {e["item_id"]: (SNAPSHOT / e["path"]).read_bytes() for e in manifest}


@pytest.fixture(scope="session")
def parsed(manifest, raw_files) -> dict[str, dict]:
    from rag.parse import parse_document

    return {e["item_id"]: parse_document(e, raw_files[e["item_id"]]) for e in manifest}


@pytest.fixture(scope="session")
def by_id(parsed) -> dict[str, dict[str, dict]]:
    """item_id -> {paragraph id -> paragraph}"""
    return {k: {p["id"]: p for p in v["paragraphs"]} for k, v in parsed.items()}


@pytest.fixture(scope="session")
def oracle() -> dict[str, list[str]]:
    return json.loads((Path(__file__).parent / "grounds_oracle.json").read_text())
