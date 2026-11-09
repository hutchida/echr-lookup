"""data/snapshot is the offline corpus for everything in Gate 1. Offline test: no network, no DB."""

import hashlib
import json
import re
from collections import Counter

import pytest

from rag.config import REPO_ROOT
from rag.contract import contract_errors

SNAP = REPO_ROOT / "data" / "snapshot"
MANIFEST = json.loads((SNAP / "manifest.json").read_text())
MAX_BYTES = 30 * 1024 * 1024


def test_manifest_entries_match_the_contract():
    for entry in MANIFEST:
        assert contract_errors("ManifestEntry", entry) == [], entry["item_id"]


@pytest.mark.parametrize("entry", MANIFEST, ids=[e["item_id"] for e in MANIFEST])
def test_file_exists_and_sha256_matches(entry):
    path = SNAP / entry["path"]
    assert path.is_file(), f"{entry['path']} is listed in the manifest but missing"
    assert hashlib.sha256(path.read_bytes()).hexdigest() == entry["sha256"]


def test_no_untracked_files_in_snapshot():
    listed = {e["path"] for e in MANIFEST}
    on_disk = {
        str(p.relative_to(SNAP))
        for sub in ("hudoc", "legislation")
        for p in (SNAP / sub).rglob("*")
        if p.is_file()
    }
    assert on_disk == listed


def test_snapshot_size_and_counts():
    total = sum(p.stat().st_size for p in SNAP.rglob("*") if p.is_file())
    assert total <= MAX_BYTES, f"snapshot is {total / 2**20:.1f} MB (limit 30 MB)"
    counts = Counter(e["doc_type"] for e in MANIFEST)
    assert 35 <= counts["judgment"] <= 45
    assert 35 <= counts["decision"] <= 45
    assert 12 <= counts["legal_summary"] <= 18
    assert counts["legislation"] == 2
    assert {e["item_id"] for e in MANIFEST if e["doc_type"] == "legislation"} == {
        "echr-convention",
        "ukpga-1998-42",
    }


def test_at_least_15_inadmissible_deportation_or_expulsion_decisions():
    topic = re.compile(r"deport|expuls|expel|extradit", re.I)
    hits = [
        e["item_id"]
        for e in MANIFEST
        if e["doc_type"] == "decision"
        and e["outcome"] == "inadmissible"
        and len(topic.findall((SNAP / e["path"]).read_text(encoding="utf-8"))) >= 10
        and {"3", "8"} & {a.split("-")[0] for a in e["articles"]}
    ]
    assert len(hits) >= 15, hits


def test_must_have_cases_are_present_with_expected_outcomes():
    by_id = {e["item_id"]: e for e in MANIFEST}
    assert by_id["001-57619"]["case_name"].startswith("SOERING")  # violation of Art 3 (possible)
    assert by_id["001-176931"]["outcome"] == "no_violation"  # Ndidi: criminal's deportation allowed
    assert by_id["001-70442"]["chamber"] == "Grand Chamber"  # Hirst (No. 2)
    outcomes = Counter(e["outcome"] for e in MANIFEST if e["doc_type"] == "judgment")
    assert outcomes["violation"] >= 5
    assert outcomes["no_violation"] >= 5


def test_inadmissibility_grounds_fields_are_consistent():
    for e in MANIFEST:
        grounds, source = e["inadmissibility_grounds"], e["inadmissibility_grounds_source"]
        assert (grounds is None) == (source is None)
        # only what HUDOC's metadata states; text-extracted grounds come from Gate 1's parser
        assert source in (None, "metadata")
    by_id = {e["item_id"]: e for e in MANIFEST}
    assert by_id["001-182755"]["inadmissibility_grounds"] == ["non_exhaustion"]  # Khaksar (dec.)
    assert by_id["001-98645"]["inadmissibility_grounds"] is None  # Miah: "Inadmissible" only
