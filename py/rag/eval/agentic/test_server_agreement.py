# ruff: noqa: E501
"""The harness's own check_quote must agree with the server's, on the server's own seeded corpus."""

import psycopg
import pytest

from echr_mcp import tools
from echr_mcp.tests import seed
from rag.eval.agentic.quotes import check_text, local_checker, server_checker

QUOTES = [
    "the Convention prohibits in absolute terms torture or inhuman or degrading treatment or punishment",
    "irrespective of the victim's conduct",  # straight apostrophe
    "However, even in these circumstances … irrespective of the victim's conduct.",
    "irrespective of the victim's conduct … even in these circumstances",  # gaps out of order
    "the Convention permits deportation in absolute terms",  # not in the paragraph
]


@pytest.fixture
def conn(test_database_url):
    with psycopg.connect(test_database_url) as c:
        seed.seed(c)
        yield c


def text_of(conn, pid):
    row = conn.execute("SELECT text FROM paragraphs WHERE id = %s", (pid,)).fetchone()
    return row[0] if row else None


@pytest.mark.parametrize("quote", QUOTES)
def test_local_check_quote_agrees_with_the_servers(conn, quote):
    pid = f"{seed.CHAHAL}§79"
    server = tools.check_quote(conn, {"paragraph_id": pid, "quote": quote})
    local = check_text(text_of(conn, pid), quote)
    assert local["verbatim"] == server["verbatim"]
    assert local["paragraph_found"] == server["paragraph_found"]
    if server["verbatim"]:
        assert local["similarity"] == server["similarity"] == 1.0
    else:  # the closeness score is a display figure; the two may weigh a gapped quote differently
        assert 0 < local["similarity"] < 1 and 0 < server["similarity"] < 1


def test_the_server_checker_adapter_and_unknown_paragraphs(conn):
    check = server_checker(conn)
    assert check(f"{seed.CHAHAL}§79", "irrespective of the victim's conduct")["verbatim"] is True
    unknown = check("001-00000§1", "anything at all")
    assert unknown["paragraph_found"] is False and unknown["verbatim"] is False
    assert (
        local_checker(lambda pid: text_of(conn, pid))("001-00000§1", "x")["paragraph_found"]
        is False
    )
