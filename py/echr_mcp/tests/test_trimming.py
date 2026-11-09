"""get_paragraphs keeps every result under 25 KB: neighbours are cut first, then requested texts."""

import psycopg
import pytest

from echr_mcp import tools
from echr_mcp.common import RESULT_MAX_BYTES, json_bytes
from echr_mcp.tests import seed
from rag.contract import contract_errors
from rag.index import reset, upsert_document

BODY = ". ".join(f"Sentence {i} of a very long paragraph" for i in range(500)) + "."


def valid(result: dict) -> dict:
    assert contract_errors("McpGetParagraphsResult", result) == []
    assert json_bytes(result) <= RESULT_MAX_BYTES
    return result


@pytest.fixture
def long_paragraphs(test_database_url):
    """One document with 12 paragraphs of ~20,000 characters each."""
    with psycopg.connect(test_database_url) as conn:
        reset(conn)
        doc = seed._doc("001-70001", "LONGCASE v. THE UNITED KINGDOM", doc_type="judgment")
        paragraphs = [seed._para("001-70001", str(n), BODY[:19_000]) for n in range(1, 13)]
        upsert_document(conn, doc, paragraphs)
        yield conn


def test_get_paragraphs_trims_neighbours_first_then_requested(long_paragraphs):
    conn = long_paragraphs
    neighbours = tools.get_paragraphs(conn, {"paragraph_ids": ["001-70001§5"], "neighbours": 2})
    valid(neighbours)
    requested = [p for p in neighbours["paragraphs"] if p["requested"]]
    others = [p for p in neighbours["paragraphs"] if not p["requested"]]
    assert len(requested) == 1 and len(others) == 4
    assert not requested[0]["truncated"] and len(requested[0]["text"]) == 19_000
    assert all(p["truncated"] and p["text"].endswith("…") for p in others)

    everything = tools.get_paragraphs(
        conn,
        {"paragraph_ids": [f"001-70001§{n}" for n in (1, 3, 5, 7, 9, 11)], "neighbours": 1},
    )
    valid(everything)
    assert all(p["truncated"] for p in everything["paragraphs"] if not p["requested"])
    cut = [p for p in everything["paragraphs"] if p["requested"] and p["truncated"]]
    assert cut and all(p["text"].endswith("…") for p in cut)
    # what is kept is still the start of the real paragraph
    assert all(BODY.startswith(p["text"].rstrip("…")) for p in everything["paragraphs"])


def test_get_paragraphs_worst_case_fits(long_paragraphs):
    ids = [f"001-70001§{n}" for n in range(1, 11)]
    result = tools.get_paragraphs(long_paragraphs, {"paragraph_ids": ids, "neighbours": 2})
    valid(result)
    assert len(result["paragraphs"]) == 12
