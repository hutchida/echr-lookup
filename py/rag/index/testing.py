"""Test helpers and fixtures for S3 (imported by the conftest files next to the tests).

A small corpus: contract-fixture Soering chunks + synthetic cases, in `<db>_test`."""

import json

import pytest

from rag.config import REPO_ROOT
from rag.index import get_embedder, replace_chunks, reset, upsert_document

FIXTURES = REPO_ROOT / "packages" / "contract" / "fixtures"

DOC_BASE = json.loads((FIXTURES / "SourceDocument.json").read_text())


def make_doc(item_id: str, case_name: str, **over) -> dict:
    return {**DOC_BASE, "item_id": item_id, "case_name": case_name, **over}


def make_paragraphs(doc_id: str, texts: list[str]) -> list[dict]:
    return [
        {
            "id": f"{doc_id}§{i}",
            "doc_id": doc_id,
            "number": i,
            "section": "The Law",
            "text": t,
        }
        for i, t in enumerate(texts, start=1)
    ]


def make_chunks(doc_id: str, strategy: str, texts: list[str]) -> list[dict]:
    return [
        {
            "id": f"{doc_id}:{strategy}:{i}",
            "doc_id": doc_id,
            "strategy": strategy,
            "text": t,
            "paragraph_ids": [f"{doc_id}§{i + 1}"],
            "token_count": len(t.split()),
        }
        for i, t in enumerate(texts)
    ]


def load_doc(conn, embedder, doc: dict, texts: list[str], strategy: str = "recursive") -> None:
    upsert_document(conn, doc, make_paragraphs(doc["item_id"], texts))
    chunks = make_chunks(doc["item_id"], strategy, texts)
    vectors = embedder.embed([c["text"] for c in chunks])
    replace_chunks(conn, doc["item_id"], strategy, chunks, vectors, embedder.model_name)


_RESULT = json.loads((FIXTURES / "SearchResult.json").read_text())
SOERING = [h["chunk"]["text"] for h in _RESULT["hits"]]

SYNTHETIC = [
    (
        make_doc(
            "001-57619",
            "SOERING v. THE UNITED KINGDOM",
            doc_type="judgment",
            outcome="violation",
            articles=["3", "6", "13"],
            date="1989-07-07",
        ),
        SOERING,
    ),
    (
        make_doc(
            "001-10001",
            "ALPHA v. THE UNITED KINGDOM",
            doc_type="judgment",
            outcome="no_violation",
            articles=["8", "8-1"],
            date="2011-03-15",
        ),
        [
            "The applicant, a foreign national convicted of drug offences, challenged the "
            "deportation order and relied on his private and family life in the United Kingdom.",
            "Interference with family life is justified where deportation is necessary in a "
            "democratic society for the prevention of disorder or crime.",
        ],
    ),
    (
        make_doc(
            "001-10002",
            "BETA v. THE UNITED KINGDOM",
            doc_type="decision",
            outcome="inadmissible",
            articles=["8"],
            date="2005-09-01",
        ),
        [
            "The complaint under Article 8 about the refusal of leave to remain is manifestly "
            "ill-founded and the application is declared inadmissible.",
            "Prisoners voting rights were not raised by the applicant in this decision.",
        ],
    ),
    (
        make_doc(
            "001-10003",
            "GAMMA v. THE UNITED KINGDOM",
            doc_type="judgment",
            outcome="violation",
            articles=["10"],
            date="1999-12-20",
        ),
        [
            "Freedom of expression includes the right of journalists to protect their sources "
            "and the press plays an essential role in a democratic society.",
        ],
    ),
]


@pytest.fixture
def corpus(db_conn):
    """Fresh schema + the small corpus above (fake embedder). Returns the connection."""
    embedder = get_embedder("fake")
    reset(db_conn)
    for doc, texts in SYNTHETIC:
        load_doc(db_conn, embedder, doc, texts)
    # the same Soering text under a second strategy, to test the chunking filter
    load_doc(db_conn, embedder, SYNTHETIC[0][0], SOERING[:2], strategy="fixed")
    db_conn.execute("ANALYZE")
    db_conn.commit()
    yield db_conn
    db_conn.rollback()


@pytest.fixture
def empty_db(db_conn):
    reset(db_conn)
    yield db_conn
    db_conn.rollback()
