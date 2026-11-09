# ruff: noqa: E501
"""check_quote is deterministic: normalisation, '…' gaps, paraphrases, the closest passage."""

import pytest

from echr_mcp import tools

PARAGRAPH = (
    "Article 3 enshrines one of the most fundamental values of democratic society. "
    "The Court is well aware of the immense difficulties faced by States in modern times in "
    "protecting their communities from terrorist violence. "
    "However, even in these circumstances, the Convention prohibits in absolute terms torture "
    "or inhuman or degrading treatment or punishment, irrespective of the victim’s conduct. "
    "The nature of the offence allegedly committed is therefore irrelevant – the guarantee is "
    "absolute."
)


@pytest.mark.parametrize(
    "quote",
    [
        "the Convention prohibits in absolute terms torture or inhuman or degrading treatment",
        # straight apostrophe for a curly one
        "irrespective of the victim's conduct",
        # odd spacing and a line break
        "the Convention  prohibits in absolute\nterms torture",
        # en dash in the paragraph vs a hyphen, an em dash and a minus in the quote
        "irrelevant - the guarantee is absolute",
        "irrelevant — the guarantee is absolute",
        "irrelevant − the guarantee is absolute",
        # an omission marked with the ellipsis character, three dots, or [...]
        "Article 3 enshrines … democratic society",
        "Article 3 enshrines ... democratic society",
        "Article 3 enshrines [...] democratic society",
        # leading and trailing cut markers, as search quotes carry them
        "…the Convention prohibits in absolute terms torture…",
        # several gaps, in order
        "However, even … prohibits in absolute terms … irrespective of the victim's conduct.",
    ],
)
def test_verbatim_after_normalisation(quote):
    assert tools.is_verbatim(PARAGRAPH, quote)


@pytest.mark.parametrize(
    "quote",
    [
        # a paraphrase
        "The Convention absolutely forbids torture whatever the victim has done",
        # one word changed
        "the Convention prohibits in relative terms torture",
        # right words, wrong order across a gap
        "irrespective of the victim's conduct … Article 3 enshrines",
        # words the paragraph does not have
        "Article 3 enshrines … fundamental freedoms of the individual",
        # case matters
        "article 3 enshrines one of the most fundamental values",
        # quotation marks that are not in the paragraph are not ignored
        "“the Convention prohibits in absolute terms torture”",
        # nothing but a gap
        "…",
        "...",
    ],
)
def test_not_verbatim(quote):
    assert not tools.is_verbatim(PARAGRAPH, quote)


def test_normalise():
    assert tools.normalise("  “a”   ‘b’\n\tc – d — e ‑ f … ") == "\"a\" 'b' c - d - e - f ..."


def test_closest_match_is_verbatim_from_the_paragraph():
    quote = "However, the Convention prohibits in absolute terms torture whatever the victim did."
    closest, ratio = tools.closest_window(PARAGRAPH, quote)
    assert closest in PARAGRAPH
    assert "prohibits in absolute terms" in closest
    assert 0.4 < ratio < 1.0


def test_closest_match_of_an_exact_quote_scores_one_after_normalisation():
    closest, ratio = tools.closest_window(
        PARAGRAPH,
        "The Court is well aware of the immense difficulties faced by States in modern times in protecting their communities from terrorist violence.",
    )
    assert ratio == pytest.approx(1.0)
    assert closest.startswith("The Court is well aware")


def test_closest_match_is_cut_to_600_characters():
    long_paragraph = ("Word " * 400).strip() + "."
    closest, _ = tools.closest_window(long_paragraph, "Word Word Word")
    assert len(closest) <= 600 and closest.endswith("…")
    assert long_paragraph.startswith(closest.rstrip("…"))


def test_check_quote_reports_similarity_for_a_paraphrase(seeded):
    result = tools.check_quote(
        seeded,
        {
            "paragraph_id": "001-58004§79",
            "quote": "Article 3 absolutely prohibits torture and inhuman treatment whatever the victim did.",
        },
    )
    assert result["paragraph_found"] and not result["verbatim"]
    assert 0 < result["similarity"] < 1
    paragraph = seeded.execute("SELECT text FROM paragraphs WHERE id = '001-58004§79'").fetchone()[
        0
    ]
    assert result["closest_match"] in paragraph
