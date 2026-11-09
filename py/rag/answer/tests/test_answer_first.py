# ruff: noqa: E501
"""Answer first: a short answer, grouped points, better evidence, and a verifier that retries."""

import json

import pytest

from rag.answer import answer, context, generate, llm, pipeline, verify
from rag.answer.context import Source
from rag.contract import contract_errors, load_fixture

SOERING = ["001-57619§88", "001-57619§91", "001-57619§111"]


def ask(conn, question="Can the UK extradite someone at risk of ill-treatment?"):
    return answer(conn, {"question": question})


def src(pid, text, *, doc_type="judgment", doc_id=None):
    doc = doc_id or pid.split("§")[0]
    return Source(pid, doc, "X v. THE UNITED KINGDOM", doc_type, "2001-01-01", "violation", text)


# --- the shape of an answer-first answer -------------------------------------------------------


def test_explain_answer_starts_with_a_short_answer_then_grouped_points(answer_db, fake_search):
    fake_search["ids"] = SOERING
    a = ask(answer_db)
    assert contract_errors("Answer", a) == []
    roles = [c.get("role") for c in a["claims"]]
    assert roles[0] == "short_answer" and roles.count("short_answer") == 1
    assert all(r == "point" for r in roles[1:])
    assert all(c["group"] for c in a["claims"][1:]) and "group" not in a["claims"][0]
    first = a["answer_text"].split("\n\n")[0]
    assert "[Soering v UK §88]" in first  # the short answer leads, with its marker
    assert "Fake group one:\n" in a["answer_text"] and "Fake group two:\n" in a["answer_text"]
    assert [c["status"] for c in a["claims"]] == ["supported"] * 3


def test_value_question_has_no_roles_or_groups(answer_db, fake_search):
    fake_search["ids"] = SOERING
    a = answer(
        answer_db, {"question": "Should the UK leave the ECHR?", "options": {"route": "rag"}}
    )
    assert a["claims"] and all("role" not in c and "group" not in c for c in a["claims"])
    assert "\n" not in a["answer_text"]
    assert contract_errors("Answer", a) == []


def test_unsupported_short_answer_is_flagged_and_left_out_of_the_text(
    answer_db, fake_search, monkeypatch
):
    fake_search["ids"] = SOERING
    real = llm.complete

    def tamper(conn, **kw):
        r = real(conn, **kw)
        if kw["purpose"] == "generate":
            data = json.loads(r.text)
            data["short_answer"]["text"] += " [[unsupported]]"
            r.text = json.dumps(data)
        return r

    monkeypatch.setattr(llm, "complete", tamper)
    monkeypatch.setattr(generate, "rewrite_short_answer", lambda *a, **k: (None, None))
    a = ask(answer_db)
    assert a["claims"][0]["role"] == "short_answer" and a["claims"][0]["status"] == "unsupported"
    assert [c["status"] for c in a["claims"][1:]] == ["supported", "supported"]
    assert "[[unsupported]]" not in a["answer_text"]
    assert contract_errors("Answer", a) == []


def test_rejected_short_answer_is_rewritten_from_the_checked_points_and_reverified(
    answer_db, fake_search, monkeypatch
):
    fake_search["ids"] = SOERING
    real = llm.complete
    purposes = []

    def tamper(conn, **kw):
        r = real(conn, **kw)
        purposes.append(kw["purpose"])
        if kw["purpose"] == "generate" and kw.get("fake_key") is None:
            data = json.loads(r.text)
            data["short_answer"]["text"] += " [[unsupported]]"
            r.text = json.dumps(data)
        return r

    monkeypatch.setattr(llm, "complete", tamper)
    a = ask(answer_db)
    short = a["claims"][0]
    assert (
        short["role"] == "short_answer" and short["status"] == "supported" and short["id"] == "c1"
    )
    assert "[[unsupported]]" not in short["text"]
    assert set(short["citation_ids"]) <= {i for c in a["claims"][1:] for i in c["citation_ids"]}
    assert a["answer_text"].startswith(short["text"].rstrip("."))
    assert (
        purposes.count("generate") == 2 and purposes.count("verify") == 4
    )  # one rewrite, one re-check
    assert a["total_cost_usd"] == pytest.approx(sum(s["cost_usd"] for s in a["steps"]))
    assert contract_errors("Answer", a) == []


def test_short_answer_is_verified_with_the_summarising_rules(answer_db, fake_search, monkeypatch):
    fake_search["ids"] = SOERING
    calls = []
    real = llm.complete

    def spy(conn, **kw):
        calls.append(kw)
        return real(conn, **kw)

    monkeypatch.setattr(llm, "complete", spy)
    ask(answer_db)
    verifies = [c for c in calls if c["purpose"] == "verify"]
    short = [c for c in verifies if "SHORT ANSWER" in c["system"]]
    assert len(verifies) == 3 and len(short) == 1  # only the short answer gets the extra rules


def test_build_claims_parses_roles_and_groups():
    valid = {"d1§1", "d1§2"}
    claims = generate.build_claims(
        [
            {
                "text": "Point one.",
                "citation_ids": ["d1§2"],
                "group": "  Where the Court found a breach: ",
            },
            {"text": "Point two.", "citation_ids": ["d1§2"], "group": ""},
            {"text": "Point three.", "citation_ids": ["d1§2"], "group": "g" * 200},
        ],
        valid,
        10,
        short_answer={"text": "Not as a rule.", "citation_ids": ["d1§1"], "group": "ignored"},
        answer_first=True,
    )
    assert [c["role"] for c in claims] == ["short_answer", "point", "point", "point"]
    assert "group" not in claims[0] and "group" not in claims[2]
    assert claims[1]["group"] == "Where the Court found a breach"
    assert len(claims[3]["group"]) <= 80
    assert [c["id"] for c in claims] == ["c1", "c2", "c3", "c4"]


def test_build_claims_without_answer_first_adds_no_fields():
    claims = generate.build_claims(
        [{"text": "A.", "citation_ids": ["d1§1"], "group": "x"}],
        {"d1§1"},
        5,
        short_answer={"text": "S.", "citation_ids": ["d1§1"]},
    )
    assert len(claims) == 1 and "role" not in claims[0] and "group" not in claims[0]


def test_assemble_keeps_going_when_one_claim_is_over_the_citation_cap():
    sources = [src(f"d{i}§1", f"Paragraph {i}.") for i in range(12)]
    claims = [
        {
            "id": f"c{i + 1}",
            "text": f"Claim {i}",
            "citation_ids": [f"d{i}§1"],
            "status": "supported",
            "reason": "ok",
            "role": "point",
        }
        for i in range(12)
    ]
    claims.append({**claims[0], "id": "c13"})  # reuses an already-cited paragraph
    text, kept, citations, refused = pipeline.assemble_rag(claims, sources, "")
    assert len(citations) == 10 and not refused
    assert kept[-1]["id"] == "c13"  # the later claim that fits is still shown


def test_compose_text_without_roles_joins_with_spaces():
    placed = [({"id": "c1"}, "One."), ({"id": "c2"}, "Two.")]
    assert pipeline.compose_text("Msg.", placed) == "Msg. One. Two."


def test_compose_text_with_roles_and_groups():
    placed = [
        ({"role": "short_answer"}, "Short."),
        ({"role": "point", "group": "A"}, "One."),
        ({"role": "point", "group": "A"}, "Two."),
        ({"role": "point", "group": "B"}, "Three."),
        ({"role": "point"}, "Four."),
    ]
    assert pipeline.compose_text("", placed) == "Short.\n\nA:\nOne. Two.\n\nB:\nThree.\n\nFour."


def test_old_fixture_still_validates_and_has_no_new_fields():
    old = load_fixture("Answer")
    assert contract_errors("Answer", old) == []
    assert all("role" not in c and "group" not in c for c in old["claims"])
    new = load_fixture("Answer.answer-first")
    assert contract_errors("Answer", new) == []
    assert new["claims"][0]["role"] == "short_answer"


# --- the verifier ----------------------------------------------------------------------------


def test_verifier_retries_once_when_the_first_reply_is_cut_off(answer_db, monkeypatch):
    replies = [
        '{"status": "supported", "reason": "The paragraph says that the',
        '{"status": "supported", "reason": "Stated in 88."}',
    ]
    seen = []

    def complete(conn, **kw):
        seen.append(kw["max_tokens"])
        return llm.LLMResult(replies[len(seen) - 1], "m", 10, 5, 0, 1.0, 0.001)

    monkeypatch.setattr(llm, "complete", complete)
    claim = {
        "id": "c1",
        "text": "T.",
        "citation_ids": ["d§1"],
        "status": "unverified",
        "reason": "",
    }
    out, results = verify._verify_one(answer_db, claim, {"d§1": src("d§1", "Text.")}, "rid")
    assert out["status"] == "supported" and out["reason"] == "Stated in 88."
    assert len(seen) == 2 and seen[0] >= 600 and seen[1] >= seen[0]
    assert len(results) == 2  # both calls are accounted for in the step cost


def test_verifier_gives_up_after_one_retry(answer_db, monkeypatch):
    calls = []

    def complete(conn, **kw):
        calls.append(1)
        return llm.LLMResult("not json at all", "m", 10, 5, 0, 1.0, 0.001)

    monkeypatch.setattr(llm, "complete", complete)
    claim = {
        "id": "c1",
        "text": "T.",
        "citation_ids": ["d§1"],
        "status": "unverified",
        "reason": "",
    }
    out, results = verify._verify_one(answer_db, claim, {"d§1": src("d§1", "Text.")}, "rid")
    assert out["status"] == "unverified" and len(calls) == 2 and len(results) == 2


# --- better evidence: diversify the context --------------------------------------------------


def test_diversify_caps_paragraphs_per_document_and_total():
    ordered = [src(f"a§{i}", "x") for i in range(6)] + [src("b§1", "x"), src("c§1", "x")]
    kept = context.diversify(ordered, cap=10, per_doc=3)
    assert [s.id for s in kept] == ["a§0", "a§1", "a§2", "b§1", "c§1"]
    assert len(context.diversify(ordered, cap=2, per_doc=3)) == 2


def test_recited_domestic_legislation_is_moved_behind_the_courts_reasoning():
    statute = src(
        "m§10",
        "Section 3(5)(a) of the Immigration Act 1971 (as amended) provides that a person is liable to deportation.",
    )
    rules = src(
        "m§11",
        "Paragraph 398 of the Immigration Rules provides that deportation is conducive to the public good.",
    )
    reasoning = src(
        "n§80", "The Court considers that the applicant's deportation would not breach Article 8."
    )
    convention = src(
        "n§81",
        "Article 8 of the Convention provides that everyone has the right to respect for private life.",
    )
    law = src(
        "ukpga-1998-42§s3",
        "Section 3 of the Human Rights Act 1998 requires legislation to be read compatibly.",
        doc_type="legislation",
    )
    assert context.quotes_statute(statute) and context.quotes_statute(rules)
    assert not context.quotes_statute(reasoning) and not context.quotes_statute(convention)
    assert not context.quotes_statute(
        law
    )  # the legislation document itself is a source, not a quote
    ordered = context.demote_statute_quotes([statute, reasoning, rules, convention, law])
    assert [s.id for s in ordered] == ["n§80", "n§81", "ukpga-1998-42§s3", "m§10", "m§11"]


def test_operative_provisions_keep_outcomes_and_skip_boilerplate(answer_db, fake_search):
    fake_search["ids"] = SOERING[:1]
    ops = context.operative_sources(answer_db, ["001-57619"], set())
    assert all(context.OUTCOME_WORDS.search(s.text) for s in ops)


def test_generation_is_retried_once_when_no_claim_cites_a_listed_source(
    answer_db, fake_search, monkeypatch
):
    fake_search["ids"] = SOERING
    real = llm.complete
    seen = []

    def bad_then_good(conn, **kw):
        r = real(conn, **kw)
        if kw["purpose"] == "generate" and kw.get("fake_key") is None:
            seen.append(kw["messages"])
            if len(seen) == 1:
                data = json.loads(r.text)
                data["short_answer"]["citation_ids"] = ["nope§1"]
                for c in data["claims"]:
                    c["citation_ids"] = ["nope§2"]
                r.text = json.dumps(data)
        return r

    monkeypatch.setattr(llm, "complete", bad_then_good)
    a = ask(answer_db)
    assert len(seen) == 2 and "citation_ids matched" not in seen[0][-1]["content"]
    assert "None of your citation_ids matched" in seen[1][-1]["content"]
    assert [c["status"] for c in a["claims"]] == ["supported"] * 3


def test_a_rejected_rewrite_gets_one_more_try_then_the_original_stays_flagged(
    answer_db, fake_search, monkeypatch
):
    fake_search["ids"] = SOERING
    real = llm.complete
    attempts = []

    def tamper(conn, **kw):
        r = real(conn, **kw)
        if kw["purpose"] == "generate" and kw.get("fake_key") is None:
            data = json.loads(r.text)
            data["short_answer"]["text"] += " [[unsupported]]"
            r.text = json.dumps(data)
        return r

    def bad_rewrite(conn, question, points, failed, request_id):
        attempts.append(failed["reason"])
        claim = {**failed, "text": "Still wrong [[unsupported]]", "status": "unverified"}
        return claim, None

    monkeypatch.setattr(llm, "complete", tamper)
    monkeypatch.setattr(generate, "rewrite_short_answer", bad_rewrite)
    a = ask(answer_db)
    assert len(attempts) == 2 and a["claims"][0]["status"] == "unsupported"
    assert "[[unsupported]]" not in a["answer_text"]
    assert contract_errors("Answer", a) == []


def test_cli_render_keeps_the_short_answer_and_group_headings_on_their_own_lines():
    from rag.answer.__main__ import render

    a = load_fixture("Answer.answer-first")
    out = render(a)
    assert (
        "\n\n  Yes, but only within limits" in out or "ANSWER\n  Yes, but only within limits" in out
    )
    assert "\n  The test:\n" in out and "\n  How the Court applied it:\n" in out
    assert "(short answer)" in out and "[The test]" in out


def test_short_answer_rule_matches_the_reach_of_the_holding():
    """A holding about particular applicants must not be turned into a general "Yes" (no new model call, just
    the rule in the existing prompt)."""
    rules = generate.ANSWER_FIRST_RULES
    assert (
        "The opening words of the short answer must match the reach of the cited holdings" in rules
    )
    assert "begin with the holding itself" in rules
    assert 'Never open with "Yes" or "No" in any form' in rules
    for opening in (
        '"Yes, where ..."',
        '"Yes, in some circumstances"',
        '"Yes, in the circumstances"',
    ):
        assert (
            opening in rules
        )  # named as forbidden openings when the holding is narrower than the question
    assert '"Only in exceptional circumstances: ..."' in rules
    assert '"Yes, but ..."' not in rules  # no longer offered as an opening
    assert 'do not open with "Yes" or "No" in any form' in generate.REWRITE_SYSTEM
    assert "Not as a general rule" in rules and "It depends on" in rules
