"""Validate Python payloads against the JSON Schema exported from packages/contract (zod)."""

import json
from functools import cache
from typing import Any

from jsonschema import Draft202012Validator

from rag.config import REPO_ROOT

SCHEMA_DIR = REPO_ROOT / "packages" / "contract" / "schema"
FIXTURE_DIR = REPO_ROOT / "packages" / "contract" / "fixtures"


@cache
def validator(name: str) -> Draft202012Validator:
    schema = json.loads((SCHEMA_DIR / f"{name}.json").read_text())
    return Draft202012Validator(schema)


def contract_errors(name: str, payload: Any) -> list[str]:
    """Return a list of human-readable violations (empty list = valid)."""
    return [
        f"{'/'.join(map(str, e.absolute_path)) or '<root>'}: {e.message}"
        for e in validator(name).iter_errors(payload)
    ]


def load_fixture(name: str) -> Any:
    return json.loads((FIXTURE_DIR / f"{name}.json").read_text())
