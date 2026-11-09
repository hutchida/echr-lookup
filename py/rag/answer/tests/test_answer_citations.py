# ruff: noqa: E501
from rag.answer import citations as cit
from rag.answer.generate import SYSTEM_PROMPT, build_claims, repair_id


def test_link_target_anchors_match_case_viewer():
    assert cit.link_target("001-57619§88") == "/case/001-57619#p88"
    assert cit.link_target("001-57619§op3") == "/case/001-57619#pop3"
    assert cit.link_target("001-57619§u2") == "/case/001-57619#pu2"
    assert cit.link_target("ukpga-1998-42§s3") == "/case/ukpga-1998-42#ps3"


def test_short_names_and_markers():
    assert cit.short_case_name("SOERING v. THE UNITED KINGDOM") == "Soering v UK"
    assert cit.short_case_name("Horne v. The United Kingdom") == "Horne v UK"
    assert cit.marker("SOERING v. THE UNITED KINGDOM", "001-57619§88") == "[Soering v UK §88]"
    assert cit.short_case_name("A.H. KHAN v. THE UNITED KINGDOM") == "A.H. Khan v UK"
    assert cit.short_case_name("KHAN A.W. v. THE UNITED KINGDOM") == "Khan A.W. v UK"
    assert cit.short_case_name("ABDULAZIZ, CABALES AND BALKANDALI v. THE UNITED KINGDOM") == (
        "Abdulaziz, Cabales and Balkandali v UK"
    )
    assert "[" not in cit.short_case_name("A v. B [GC] (dec.)")


def test_best_quote_is_verbatim_and_short():
    text = " ".join(f"Sentence number {i} talks about nothing." for i in range(40))
    text += " The extradition risk of torture is the key point here."
    quote = cit.best_quote(text, "extradition risk of torture")
    assert quote in text and len(quote) <= 300
    assert "extradition risk of torture" in quote
    short = "Short paragraph."
    assert cit.best_quote(short, "x") == short


# --- the quote shows the supporting sentence, whole -------------------------------------------------------------

FILLER = (
    "The Government submitted that the applicant had been given every opportunity to put his case to the "
    "domestic courts, which had examined his claims with care over several hearings and had given full reasons "
    "for each of their decisions, so that nothing in the domestic proceedings could be criticised."
)


def _is_whole_sentences(quote: str, text: str) -> bool:
    start = text.index(quote)
    opens_ok = start == 0 or text[start - 2 : start] in (". ", "? ", "! ")
    closes_ok = quote.rstrip().endswith((".", "?", "!", '."', ".”"))
    return opens_ok and closes_ok


def test_supporting_sentence_is_the_second_sentence():
    support = (
        "The Court therefore finds that the applicant's removal to Iraq would expose him to a real risk of "
        "the death penalty, in breach of Article 3."
    )
    text = f"{FILLER} {support} {FILLER}"
    claim = "The Court found that removal to Iraq would breach Article 3 because of the death penalty risk."
    quote = cit.best_quote(text, claim)
    assert quote in text and len(quote) <= 300
    assert support in quote
    assert _is_whole_sentences(quote, text)


def test_quote_does_not_stop_before_the_sentence_with_the_article():
    """The Al-Saadoon §120 card: the old window kept the first matching sentence and stopped before the
    following sentence, the one that names Article 3."""
    first = (
        "On 31 December 2008 the applicants, who had been held by the British forces at the detention facility, "
        "were physically transferred out of British custody and handed over to the Iraqi authorities, who then "
        "brought them before the Iraqi High Tribunal."
    )
    second = (
        "That transfer exposed them to a real risk of the death penalty, contrary to Article 3."
    )
    text = f"{FILLER} {first} {second}"
    assert (
        len(first) + len(second) + 1 > 300
    )  # both cannot fit: the quote must keep the Article 3 sentence
    claim = (
        "The transfer of the applicants from British custody to the Iraqi authorities exposed them to the death "
        "penalty, in breach of Article 3."
    )
    quote = cit.best_quote(text, claim)
    assert second in quote and len(quote) <= 300
    assert _is_whole_sentences(quote, text)


def test_quote_never_opens_on_a_clause_after_a_semicolon():
    """The Chagos card opened mid-sentence ("and circumstances where ..."): ";" is not a sentence end."""
    sentence = (
        "The Court reiterates that a State's jurisdiction is primarily territorial; and circumstances where "
        "a State exercises jurisdiction outside its territory are exceptional and require special justification."
    )
    text = f"{FILLER} {sentence} {FILLER}"
    quote = cit.best_quote(
        text, "Jurisdiction outside a State's territory requires exceptional circumstances."
    )
    assert not quote.startswith("and ")
    assert quote == sentence


def test_abbreviations_do_not_end_a_sentence():
    sentence = (
        "In Soering v. the United Kingdom (no. 14038/88) the extradition (art. 3) of the applicant was found to "
        "engage the responsibility of the State."
    )
    text = f"{FILLER} {sentence} {FILLER}"
    quote = cit.best_quote(
        text, "Soering extradition engaged the State's responsibility under Article 3."
    )
    assert quote == sentence


def test_one_overlong_sentence_is_cut_verbatim_within_the_budget():
    long_sentence = (
        "The Court notes, "
        + ", ".join(f"in respect of point {i}" for i in range(40))
        + ", the death row phenomenon."
    )
    quote = cit.best_quote(long_sentence, "death row phenomenon")
    assert quote in long_sentence and len(quote) <= 300
    assert "death row" in quote


def test_repair_id():
    valid = {"001-57619§88", "001-57619§op3", "002-1§88"}
    assert repair_id("001-57619§88", valid) == "001-57619§88"
    assert repair_id(" [001-57619 § 88]. ", valid) == "001-57619§88"
    assert repair_id("001-57619§OP3", valid) == "001-57619§op3"
    assert repair_id("§op3", valid) == "001-57619§op3"
    assert repair_id("88", valid) is None  # ambiguous: two documents have §88
    assert repair_id("001-99999§1", valid) is None


def test_unknown_citation_ids_rejected():
    valid = {"001-57619§88"}
    claims = build_claims(
        [
            {"text": "Good claim.", "citation_ids": ["001-57619§88"]},
            {"text": "Invented source.", "citation_ids": ["001-00000§1"]},
            {"text": "Mixed.", "citation_ids": ["001-57619§88", "nope"]},
        ],
        valid,
        10,
    )
    assert [c["status"] for c in claims] == ["unverified", "unsupported", "unverified"]
    assert claims[1]["citation_ids"] == []
    assert claims[2]["citation_ids"] == ["001-57619§88"]


def test_neutral_prompt_contents():
    low = SYSTEM_PROMPT.lower()
    assert "only the numbered source" in low
    assert "never give your own opinion" in low
    assert "remain in, leave" in low
    assert "don't answer this" in low


def test_a_line_break_ends_a_sentence_so_list_items_are_not_merged():
    """Legal summaries list exceptions as "v. ...", "vi. ..." on separate lines; "v." is not "versus" there."""
    items = [
        f"{FILLER}",
        "iv. There are two principal exceptions to territoriality: State agent authority and control, and effective control over an area;",
        "v. The State agent authority and control exception applies where the State through its agents exercises control and authority over an individual outside its territory, such as by taking a person into custody;",
        "vi. Effective control over an area arises when, as a consequence of military action, a State exercises effective control of an area outside its territory.",
    ]
    text = "\n".join(items)
    quote = cit.best_quote(
        text,
        "State agents exercising control and authority over an individual outside the territory",
    )
    assert quote == items[2]
