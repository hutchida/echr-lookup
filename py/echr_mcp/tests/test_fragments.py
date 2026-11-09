"""Text fragments on hudoc_url: encoding and where they are added."""

import re
from urllib.parse import unquote

import pytest

from echr_mcp import tools
from echr_mcp.common import (
    FRAGMENT_MAX_CHARS,
    encode_fragment_text,
    text_fragment,
    with_text_fragment,
)
from rag.contract import contract_errors, load_fixture
from rag.index import get_embedder

BASE = "https://hudoc.echr.coe.int/eng?i=001-58004"


@pytest.mark.parametrize(
    ("text", "encoded"),
    [
        ("plain words", "plain%20words"),
        ("well-established", "well%2Destablished"),
        ("Smith & Jones", "Smith%20%26%20Jones"),
        ("a, b", "a%2C%20b"),
        ("“quoted”", "%E2%80%9Cquoted%E2%80%9D"),
        ("it’s", "it%E2%80%99s"),
        ("it's (see)", "it's%20(see)"),
        ("café déjà", "caf%C3%A9%20d%C3%A9j%C3%A0"),
        ("Article 3 § 1", "Article%203%20%C2%A7%201"),
        ("100% sure; #1 = x?", "100%25%20sure%3B%20%231%20%3D%20x%3F"),
        ("snake_case.dot!tilde~star*", "snake_case.dot!tilde~star*"),
        ("en–dash em—dash", "en%E2%80%93dash%20em%E2%80%94dash"),
    ],
)
def test_encoding(text, encoded):
    assert encode_fragment_text(text) == encoded
    assert unquote(encoded) == text


def test_encoding_never_leaves_the_three_reserved_characters():
    out = encode_fragment_text("a-b&c,d e")
    assert not re.search(r"[-&, ]", out)


def test_fragment_takes_the_first_eight_words_of_the_quote_as_written():
    quote = (
        "The Court reiterates that, in the well-established case-law, expulsion engages Article 3."
    )
    assert text_fragment(quote) == (
        ":~:text=The%20Court%20reiterates%20that%2C%20in%20the%20well%2Destablished%20case%2Dlaw%2C"
    )
    assert text_fragment("  The   Court\nreiterates ") == ":~:text=The%20Court%20reiterates"


def test_fragment_skips_a_leading_cut_marker_and_drops_a_trailing_one():
    assert (
        text_fragment("…the applicant was deported") == ":~:text=the%20applicant%20was%20deported"
    )
    assert (
        text_fragment("the applicant was deported…") == ":~:text=the%20applicant%20was%20deported"
    )
    assert text_fragment("one two three four five six seven eight nine…").endswith("seven%20eight")


def test_fragment_stays_short_even_for_long_words():
    quote = " ".join(["Pneumonoultramicroscopicsilicovolcanoconiosis"] * 8)
    fragment = text_fragment(quote)
    assert fragment is not None and len(fragment) - len(":~:text=") <= FRAGMENT_MAX_CHARS
    assert text_fragment("x" * 500) is None
    accented = " ".join(["ééééééééééé"] * 8)
    assert len(text_fragment(accented)) - len(":~:text=") <= FRAGMENT_MAX_CHARS


def test_url_gets_a_hash_only_when_it_has_none():
    assert with_text_fragment(BASE, "two words") == f"{BASE}#:~:text=two%20words"
    hudoc = 'https://hudoc.echr.coe.int/eng#{"itemid":["001-58004"]}'
    assert with_text_fragment(hudoc, "two words") == f"{hudoc}:~:text=two%20words"
    assert with_text_fragment(hudoc, "two words").count("#") == 1


def test_no_quote_no_fragment():
    assert with_text_fragment(BASE, "") == BASE
    assert with_text_fragment(BASE, " … ") == BASE


def test_search_urls_are_fragments_of_each_hits_quote(seeded):
    result = tools.search_case_law(
        seeded,
        {"query": "deportation national security risk of ill-treatment", "limit": 10},
        embedder=get_embedder("fake"),
    )
    assert result["hits"]
    for hit in result["hits"]:
        assert hit["hudoc_url"] == with_text_fragment(
            f"https://hudoc.echr.coe.int/eng?i={hit['doc_id']}", hit["quote"]
        )
        words = unquote(hit["hudoc_url"].split(":~:text=")[1]).split(" ")
        assert hit["quote"].lstrip("…").startswith(" ".join(words))
        assert hit["hudoc_url"].count("#") == 1 and len(hit["hudoc_url"]) <= 400
    assert contract_errors("McpSearchCaseLawResult", result) == []


def test_get_paragraphs_urls_use_the_paragraph_text(seeded):
    result = tools.get_paragraphs(seeded, load_fixture("McpGetParagraphsInput"))
    for p in result["paragraphs"]:
        fragment = p["hudoc_url"].split("#:~:text=")[1]
        assert p["text"].startswith(" ".join(unquote(fragment).split(" ")))
    assert contract_errors("McpGetParagraphsResult", result) == []


def test_case_level_urls_have_no_fragment(seeded):
    case = tools.get_case(seeded, load_fixture("McpGetCaseInput"))
    assert case["hudoc_url"] == BASE
    counted = tools.count_cases(seeded, load_fixture("McpCountCasesInput"))
    assert all("#" not in c["hudoc_url"] for c in counted["matching_cases"])
