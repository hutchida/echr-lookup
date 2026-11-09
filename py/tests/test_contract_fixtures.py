"""Every contract fixture validates against the JSON Schema exported from zod."""

import json
import re

import pytest

from rag.contract import FIXTURE_DIR, SCHEMA_DIR, contract_errors

FIXTURE_FILE = re.compile(r"^([A-Za-z]+)(?:\.([a-z0-9-]+))?\.json$")
FIXTURES = sorted(p.name for p in FIXTURE_DIR.glob("*.json"))


def schema_name(fixture_file: str) -> str:
    m = FIXTURE_FILE.match(fixture_file)
    assert m, f"{fixture_file} does not follow <Name>.json / <Name>.<variant>.json"
    return m.group(1)


def test_there_are_fixtures_for_every_exported_schema():
    schemas = {p.stem for p in SCHEMA_DIR.glob("*.json")}
    primary = {schema_name(f) for f in FIXTURES if FIXTURE_FILE.match(f).group(2) is None}
    assert schemas == primary


@pytest.mark.parametrize("fixture_file", FIXTURES)
def test_fixture_validates_against_exported_json_schema(fixture_file):
    payload = json.loads((FIXTURE_DIR / fixture_file).read_text())
    assert contract_errors(schema_name(fixture_file), payload) == []


def test_exported_schema_rejects_unknown_fields_and_over_limit_values():
    paragraph = json.loads((FIXTURE_DIR / "Paragraph.json").read_text())
    assert contract_errors("Paragraph", {**paragraph, "extra": 1}) != []
    result = json.loads((FIXTURE_DIR / "SearchResult.json").read_text())
    hit = result["hits"][0]
    assert contract_errors("SearchResult", {**result, "hits": [hit] * 51}) != []
    assert contract_errors("SearchResult", {**result, "hits": [hit] * 50}) == []
