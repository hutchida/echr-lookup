import json
import re
import time

from rag.contract import contract_errors
from rag.parse import parse_document
from rag.parse.grounds import extract_grounds

# HUDOC's HTML sometimes loses the printed number of a paragraph. Those paragraphs are kept (as
# unnumbered §u<n> items, in order) but the numbered sequence has holes. Listed here on purpose:
# a new gap anywhere else is a parser regression.
KNOWN_MISSING_NUMBERS = {
    "001-90402": {17, 18, 19, 23, 24, 25, 26, 27, 28, 29, 31, 32, 33, 34, 35, 36, 38, 39},
}


def test_every_snapshot_document_parses(manifest, parsed):
    assert len(parsed) == len(manifest) == 98
    for e in manifest:
        paras = parsed[e["item_id"]]["paragraphs"]
        assert paras, e["item_id"]


def test_documents_and_paragraphs_validate_against_the_contract(parsed):
    for item_id, doc in parsed.items():
        assert contract_errors("SourceDocument", doc["document"]) == [], item_id
        for p in doc["paragraphs"]:
            assert contract_errors("Paragraph", p) == [], p["id"]


def test_paragraph_ids_are_unique_and_prefixed_by_the_document(parsed):
    for item_id, doc in parsed.items():
        ids = [p["id"] for p in doc["paragraphs"]]
        assert len(ids) == len(set(ids)), item_id
        assert all(
            i.startswith(f"{item_id}§") and p["doc_id"] == item_id
            for i, p in zip(ids, doc["paragraphs"], strict=True)
        )


def test_numbered_paragraphs_have_no_gaps_or_duplicates(parsed):
    checked = 0
    for item_id, doc in parsed.items():
        nums = [p["number"] for p in doc["paragraphs"] if p["number"] is not None]
        if not nums:
            continue
        checked += 1
        assert len(nums) == len(set(nums)), f"duplicate numbers in {item_id}"
        assert nums == sorted(nums), f"numbers out of order in {item_id}"
        missing = set(range(1, max(nums) + 1)) - set(nums)
        assert missing == KNOWN_MISSING_NUMBERS.get(item_id, set()), item_id
    assert checked >= 60


def test_all_judgments_are_numbered_and_have_operative_provisions(manifest, parsed):
    for e in manifest:
        if e["doc_type"] != "judgment":
            continue
        paras = parsed[e["item_id"]]["paragraphs"]
        assert sum(p["number"] is not None for p in paras) >= 10, e["item_id"]
        assert any(p["id"].endswith("§op1") for p in paras), e["item_id"]


def test_sections_are_labelled(parsed):
    soering = {p["id"]: p["section"] for p in parsed["001-57619"]["paragraphs"]}
    assert soering["001-57619§1"] == "Procedure"
    assert soering["001-57619§20"] == "The Facts"
    assert soering["001-57619§88"] == "The Law"
    assert soering["001-57619§op1"] == "Operative provisions"
    assert soering["001-57619§u10"] == "Other"  # concurring opinion of Judge De Meyer


def test_ids_are_deterministic(manifest, raw_files, parsed):
    for e in manifest:
        assert parse_document(e, raw_files[e["item_id"]]) == parsed[e["item_id"]]


# ------------------------------------------------------------------ hand-picked assertions ----


def test_soering_para_88_starts_with_the_key_sentence(by_id):
    text = by_id["001-57619"]["001-57619§88"]["text"]
    assert text.startswith("Article 3 (art. 3) makes no provision for exceptions")
    assert by_id["001-57619"]["001-57619§88"]["number"] == 88


def test_soering_para_111_includes_its_unnumbered_continuation(by_id):
    p = by_id["001-57619"]["001-57619§111"]
    assert p["text"].startswith("Accordingly") or p["number"] == 111
    assert "give rise to a breach of Article 3 (art. 3)" in p["text"]
    assert "This finding in no way puts in question the good faith" in p["text"]
    assert "001-57619§112" in by_id["001-57619"]


def test_old_judgment_with_glued_paragraphs_and_dotless_number(by_id):
    mccann = by_id["001-57943"]
    assert mccann["001-57943§41"]["text"].endswith("away from the control stations.")
    assert mccann["001-57943§42"]["text"].startswith(
        "The suspect was followed for approximately an hour"
    )
    assert mccann["001-57943§131"]["text"].startswith(
        "The applicants also submitted a further opinion of Dr Scott"
    )


def test_operative_provisions_restart_numbering(by_id):
    ndidi = by_id["001-176931"]
    assert ndidi["001-176931§1"]["text"].startswith("The case originated in an application")
    op2 = ndidi["001-176931§op2"]
    assert op2["section"] == "Operative provisions" and op2["number"] is None
    assert op2["text"].startswith("Holds that there has been no violation of Article 8")


def test_modern_judgment_operative_list_items(by_id):
    unuane = by_id["001-205796"]
    assert unuane["001-205796§op1"]["text"].startswith(
        "Declares the complaint concerning Article 8"
    )
    assert sum(1 for i in unuane if "§op" in i) == 6


def test_numbered_decision(by_id):
    miah = by_id["001-98645"]
    assert miah["001-98645§1"]["text"].startswith(
        "The applicant, Mr Jahed Tofur Miah, is a Bangladeshi national"
    )
    assert miah["001-98645§25"]["number"] == 25
    assert miah["001-98645§25"]["text"].endswith("Article 35 §§ 3 and 4 of the Convention.")


def test_unnumbered_decision_uses_running_indexes(by_id):
    alidjah = by_id["001-4596"]
    assert alidjah["001-4596§u1"]["text"].startswith("The applicant is a Ghanaian national")
    assert alidjah["001-4596§u1"]["section"] == "The Facts"
    assert all(p["number"] is None for p in alidjah.values())
    ops = [p for i, p in alidjah.items() if "§op" in i]
    assert len(ops) == 1 and ops[0]["text"] == "DECLARES THE APPLICATION INADMISSIBLE."
    # the cover page (composition of the Chamber) is not a paragraph
    assert not any("Having deliberated" in p["text"] for p in alidjah.values())


def test_legal_summary(by_id):
    hirst = by_id["002-3706"]
    assert hirst["002-3706§u1"]["text"] == "Hirst v. the United Kingdom (no. 2) [GC] - 74025/01"
    law = next(
        p
        for p in hirst.values()
        if p["text"].startswith("Law: The rights guaranteed under Article 3 of Protocol No. 1")
    )
    assert law["section"] == "The Law"
    assert any(
        p["text"].startswith("Conclusion: violation (12 votes to five)") for p in hirst.values()
    )
    assert not any(p["text"].startswith(("Click here", "©")) for p in hirst.values())


def test_convention(by_id):
    conv = by_id["echr-convention"]
    art3 = conv["echr-convention§art3"]
    assert art3["text"] == (
        "Article 3 – Prohibition of torture\n"
        "No one shall be subjected to torture or to inhuman or degrading treatment or punishment."
    )
    art8 = conv["echr-convention§art8"]["text"]
    assert art8.startswith(
        "Article 8 – Right to respect for private and family life\n1. Everyone has the right"
    )
    assert "\n2. There shall be no interference by a public authority" in art8
    assert "echr-convention§art59" in conv and "echr-convention§art60" not in conv
    assert conv["echr-convention§p1-art1"]["text"].startswith(
        "Protocol No. 1, Article 1 – Protection of property"
    )
    assert conv["echr-convention§art26"]["text"].startswith(
        "Article 26 – Single-judge formation, Committees, Chambers and Grand Chamber\n"
        "1. To consider"
    )
    assert conv["echr-convention§p16-art3"]["text"].startswith(
        "Protocol No. 16, Article 3\nThe Council of Europe Commissioner"
    )
    ids = list(conv)
    assert ids.index("echr-convention§p16-art2") < ids.index("echr-convention§p16-art3")
    assert len(ids) == len(set(ids))


def test_human_rights_act(by_id):
    hra = by_id["ukpga-1998-42"]
    s3 = hra["ukpga-1998-42§s3"]["text"]
    assert s3.startswith(
        "Human Rights Act 1998, section 3 – Interpretation of legislation\n"
        "(1) So far as it is possible to do so"
    )
    assert "\n(2) This section—\n(a) applies to primary legislation" in s3
    assert hra["ukpga-1998-42§s7A"]["text"].startswith("Human Rights Act 1998, section 7A")
    assert hra["ukpga-1998-42§s4"]["text"].split("\n")[0].endswith("Declaration of incompatibility")
    art8 = hra["ukpga-1998-42§sch1-art8"]["text"]
    assert (
        "Right to respect for private and family life\n1. Everyone has the right to respect" in art8
    )
    assert "ukpga-1998-42§sch1-p1-art1" in hra and "ukpga-1998-42§sch3-part1" in hra
    assert all(p["section"] == "The Law" and p["number"] is None for p in hra.values())


# --------------------------------------------------------------- inadmissibility grounds ------


def test_grounds_are_extracted_from_text_when_the_manifest_has_none(manifest, parsed):
    n = 0
    for e in manifest:
        doc = parsed[e["item_id"]]["document"]
        if e["doc_type"] == "decision" and e["outcome"] in ("inadmissible", "partly_inadmissible"):
            if e["inadmissibility_grounds"] is None:
                n += 1
                assert doc["inadmissibility_grounds"], e["item_id"]
                assert doc["inadmissibility_grounds_source"] == "text"
            else:  # named by HUDOC: kept (K2 is extended, see the test below)
                assert set(e["inadmissibility_grounds"]) <= set(doc["inadmissibility_grounds"])
        else:
            assert doc["inadmissibility_grounds"] == e["inadmissibility_grounds"], e["item_id"]
            assert doc["inadmissibility_grounds_source"] == e["inadmissibility_grounds_source"]
    assert n == 33


def test_grounds_agree_with_the_g0b_oracle(parsed, oracle, capsys):
    """parse_document over all 35 oracle decisions (with or without metadata), exact sets."""
    agree = 0
    for item_id, expected in oracle.items():
        found = sorted(parsed[item_id]["document"]["inadmissibility_grounds"] or [])
        agree += found == sorted(expected)
        if found != sorted(expected):
            print("DISAGREE", item_id, found, expected)
    with capsys.disabled():
        print(f"\ngrounds oracle agreement: {agree}/{len(oracle)} = {agree / len(oracle):.0%}")
    assert agree == len(oracle) == 35


def test_k2_gets_the_text_ground_on_top_of_the_metadata_one(manifest, parsed):
    entry = next(e for e in manifest if e["item_id"] == "001-172143")
    assert entry["inadmissibility_grounds"] == ["manifestly_ill_founded"]
    doc = parsed["001-172143"]["document"]
    assert doc["inadmissibility_grounds"] == ["manifestly_ill_founded", "non_exhaustion"]
    assert doc["inadmissibility_grounds_source"] == "text"
    assert contract_errors("SourceDocument", doc) == []


def test_only_k2_changes_among_decisions_with_metadata_grounds(manifest, parsed):
    """Metadata grounds are only ever extended, and only where the text clearly supports it.
    K2: "the Article 14 complaint ... must be rejected pursuant to Article 35 § 1 of the Convention
    for failure to exhaust domestic remedies"."""
    changed = {}
    for e in manifest:
        if e["doc_type"] != "decision" or not e["inadmissibility_grounds"]:
            continue
        doc = parsed[e["item_id"]]["document"]
        assert set(e["inadmissibility_grounds"]) <= set(doc["inadmissibility_grounds"])
        if doc["inadmissibility_grounds"] != e["inadmissibility_grounds"]:
            changed[e["item_id"]] = doc["inadmissibility_grounds"]
            assert doc["inadmissibility_grounds_source"] == "text"
        else:
            assert doc["inadmissibility_grounds_source"] == "metadata"
    assert changed == {"001-172143": ["manifestly_ill_founded", "non_exhaustion"]}


def test_merge_grounds_is_a_union_in_enum_order():
    from rag.parse.grounds import merge_grounds

    assert merge_grounds(["non_exhaustion"], ["manifestly_ill_founded"]) == [
        "manifestly_ill_founded",
        "non_exhaustion",
    ]
    assert merge_grounds(["non_exhaustion"], []) == ["non_exhaustion"]


def test_specific_grounds(parsed):
    g = {k: v["document"]["inadmissibility_grounds"] for k, v in parsed.items()}
    assert g["001-98645"] == ["manifestly_ill_founded", "incompatible_ratione_materiae"]
    assert g["001-127061"] == ["non_exhaustion"]
    assert g["001-225312"] == ["incompatible_ratione_materiae"]
    assert g["001-115660"] is None  # struck out, not inadmissible


def test_grounds_ignore_recitals_negations_and_arguments():
    texts = [
        "The Government argued that the applicant had failed to exhaust domestic remedies.",
        "It cannot be considered manifestly ill-founded within the meaning of Article 35 § 3.",
        "The Court need not decide whether the applicant exhausted domestic remedies.",
        "The application was lodged out of time, more than six months after the final decision.",
        "It follows that this complaint must be rejected pursuant to Article 35 §§ 1 and 4.",
    ]
    assert [g for g, _ in extract_grounds(texts)] == ["out_of_time"]


def test_four_month_rule_is_out_of_time():
    texts = [
        "The application was introduced more than four months after the final domestic decision.",
        "It must therefore be rejected as being out of time pursuant to Article 35 § 1.",
    ]
    assert [g for g, _ in extract_grounds(texts)] == ["out_of_time"]


# ---------------------------------------------------------------------------- timing ----------


def test_parsing_the_whole_snapshot_is_fast(manifest, raw_files):
    t = time.perf_counter()
    for e in manifest:
        parse_document(e, raw_files[e["item_id"]])
    assert time.perf_counter() - t < 15


def test_manifest_round_trip_is_json_serialisable(parsed):
    json.dumps(parsed)
    assert re.fullmatch(
        r"[^§]+§[A-Za-z0-9._-]+", next(iter(parsed["001-57619"]["paragraphs"]))["id"]
    )
