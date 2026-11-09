# ruff: noqa: E501
"""Fixtures for the S4 tests: an isolated schema (`answer_db`) with the interfaces §3 tables, and a
fake `rag.search.search` for unit tests. The real S3 `log_cost` writes to that schema's cost_log.
Integration tests use S3's own `corpus` fixture (real tables, real search)."""

import importlib

import psycopg
import pytest

from rag.index.testing import corpus, empty_db  # noqa: F401

SCHEMA = "s4_unit"

DDL = f"""
DROP SCHEMA IF EXISTS {SCHEMA} CASCADE;
CREATE SCHEMA {SCHEMA};
SET search_path TO {SCHEMA};
CREATE TABLE documents (
  item_id text PRIMARY KEY, case_name text NOT NULL, application_numbers text[] NOT NULL DEFAULT '{{}}',
  ecli text, doc_type text NOT NULL, chamber text, date date NOT NULL, articles text[] NOT NULL,
  outcome_raw text, outcome text NOT NULL, importance int, language text NOT NULL DEFAULT 'en',
  source_url text NOT NULL DEFAULT 'x', sha256 text NOT NULL DEFAULT 'x',
  data_source text NOT NULL DEFAULT 'snapshot',
  inadmissibility_grounds text[], inadmissibility_grounds_source text);
CREATE TABLE paragraphs (
  id text PRIMARY KEY, doc_id text NOT NULL REFERENCES documents(item_id) ON DELETE CASCADE,
  position int NOT NULL, number int, section text NOT NULL, text text NOT NULL);
CREATE TABLE chunks (id text PRIMARY KEY, doc_id text NOT NULL, text text NOT NULL);
CREATE TABLE cost_log (
  id text PRIMARY KEY, timestamp timestamptz NOT NULL, model text NOT NULL, purpose text NOT NULL,
  tokens_in int NOT NULL, tokens_out int NOT NULL, tokens_cached int NOT NULL,
  cost_usd numeric NOT NULL, latency_ms numeric NOT NULL, request_id text NOT NULL);
"""

SOERING_88 = (
    "Article 3 makes no provision for exceptions. It follows from this that the decision by a "
    "Contracting State to extradite a fugitive may give rise to an issue under Article 3, where "
    "substantial grounds have been shown for believing that the person would face a real risk of "
    "being subjected to torture or to inhuman or degrading treatment in the requesting country."
)
N_UK_42 = (
    "The Court considers that the applicant's removal to Uganda would not breach Article 3. "
    "Her deportation was therefore allowed, as the high threshold of exceptional circumstances "
    "was not met."
)

# (item_id, case_name, doc_type, date, articles, outcome, grounds, paragraphs[(ref, section, text)])
DOCS = [
    (
        "001-57619",
        "SOERING v. THE UNITED KINGDOM",
        "judgment",
        "1989-07-07",
        ["3"],
        "violation",
        None,
        [
            ("88", "The Law", SOERING_88),
            (
                "91",
                "The Law",
                "The extradition of the applicant would expose him to the death row phenomenon.",
            ),
            (
                "111",
                "The Law",
                "There would be a breach of Article 3 if the applicant were extradited.",
            ),
        ],
    ),
    (
        "001-100001",
        "N. v. THE UNITED KINGDOM",
        "judgment",
        "2008-05-27",
        ["3"],
        "no_violation",
        None,
        [("42", "The Law", N_UK_42)],
    ),
    (
        "001-200001",
        "Horne v. The United Kingdom",
        "decision",
        "2022-01-11",
        ["3", "8-1"],
        "inadmissible",
        ["manifestly_ill_founded"],
        [
            (
                "60",
                "The Law",
                "The applicant's deportation to Jamaica was lawful. The complaint is inadmissible as manifestly ill-founded.",
            ),
            ("61", "The Law", "Expulsion of a settled migrant engages Article 8."),
        ],
    ),
    (
        "001-200002",
        "Osagiede v. The United Kingdom",
        "decision",
        "2021-03-02",
        ["8"],
        "inadmissible",
        ["non_exhaustion"],
        [
            (
                "16",
                "The Law",
                "The complaint about removal is inadmissible as domestic remedies have not been exhausted.",
            ),
            ("17", "The Law", "The deportation order had not yet been enforced."),
        ],
    ),
    (
        "001-200003",
        "Khaksar v. The United Kingdom",
        "decision",
        "2017-06-20",
        ["8"],
        "partly_inadmissible",
        None,
        [
            (
                "u1",
                "Other",
                "The applicant faced deportation and expulsion; the application is rejected.",
            ),
            ("u2", "Other", "The expulsion was lawful."),
        ],
    ),
    (
        "001-200004",
        "Smith v. The United Kingdom",
        "decision",
        "2019-02-02",
        ["6"],
        "inadmissible",
        ["out_of_time"],
        [
            ("5", "The Law", "The applicant complained about a fair trial in a civil dispute."),
            ("6", "The Law", "The application was lodged out of time."),
        ],
    ),
    (
        "001-200005",
        "Jones v. The United Kingdom",
        "judgment",
        "2015-04-04",
        ["8"],
        "violation",
        None,
        [
            (
                "9",
                "The Law",
                "The deportation of the applicant violated Article 8; the expulsion was disproportionate.",
            )
        ],
    ),
]


DOCS += [
    (
        "001-200006",
        "Zeta v. The United Kingdom",
        "decision",
        "2018-05-05",
        ["6"],
        "inadmissible",
        ["manifestly_ill_founded"],
        [("3", "The Law", "The complaint is manifestly ill-founded.")],
    ),
    (
        "001-200007",
        "Field and Others v. The United Kingdom",
        "decision",
        "2023-05-16",
        ["14", "P1-3"],
        "inadmissible",
        ["incompatible_ratione_materiae"],
        [
            ("8", "The Law", "Seats fall vacant on death, resignation or expulsion of the holder."),
            ("9", "The Law", "By-elections follow the expulsion from the House of a peer."),
        ],
    ),
    (
        "001-300001",
        "Gamma v. The United Kingdom",
        "judgment",
        "2012-01-01",
        ["8"],
        "mixed",
        None,
        [("1", "The Law", "Mixed findings on private life.")],
        "Grand Chamber",
    ),
    (
        "001-300002",
        "Delta v. The United Kingdom",
        "judgment",
        "2013-01-01",
        ["6"],
        "violation",
        None,
        [("1", "The Law", "A fair trial violation.")],
        "Grand Chamber",
    ),
    (
        "001-300003",
        "Epsilon v. The United Kingdom",
        "judgment",
        "2014-01-01",
        ["6"],
        "no_violation",
        None,
        [("1", "The Law", "No violation of the fair trial guarantee.")],
        "Chamber",
    ),
]


@pytest.fixture
def answer_db(test_database_url):
    conn = psycopg.connect(test_database_url)
    try:
        conn.execute(DDL)
        for item_id, name, doc_type, date, arts, outcome, grounds, paras, *chamber in DOCS:
            conn.execute(
                "INSERT INTO documents (item_id, case_name, doc_type, date, articles, outcome, "
                "inadmissibility_grounds, chamber) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)",
                (item_id, name, doc_type, date, arts, outcome, grounds, (chamber or [None])[0]),
            )
            for pos, (ref, section, text) in enumerate(paras, 1):
                conn.execute(
                    "INSERT INTO paragraphs (id, doc_id, position, section, text) VALUES (%s,%s,%s,%s,%s)",
                    (f"{item_id}§{ref}", item_id, pos, section, text),
                )
        conn.commit()
        yield conn
    finally:
        conn.rollback()
        conn.execute(f"DROP SCHEMA IF EXISTS {SCHEMA} CASCADE")
        conn.commit()
        conn.close()


@pytest.fixture
def fake_search(monkeypatch):
    """Patch rag.search.search to return hits for the paragraph ids set in `fake_search.ids`."""
    search = importlib.import_module("rag.search")
    state = {"ids": [], "requests": []}

    def _search(conn, request, *, embedder=None, reranker=None):
        state["requests"].append(request)
        hits = [
            {
                "rank": i + 1,
                "case_name": "x",
                "chunk": {"doc_id": pid.split("§")[0]},
                "paragraph_ids": [pid],
                "scores": {},
            }
            for i, pid in enumerate(state["ids"])
        ]
        return {
            "query": request["query"],
            "hits": hits,
            "timings_ms": {"rerank": None, "total": 1.0},
        }

    monkeypatch.setattr(search, "search", _search, raising=False)
    monkeypatch.setattr(search, "get_reranker", lambda name=None: None, raising=False)
    return state


@pytest.fixture(autouse=True)
def small_topic_threshold(monkeypatch):
    """The seeded test documents are tiny (2 matching paragraphs), so lower the topic threshold."""
    from rag.answer import stats

    monkeypatch.setattr(stats, "TOPIC_MIN_PARAGRAPHS", 2)
