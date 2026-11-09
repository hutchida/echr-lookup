# ruff: noqa: E501
import json

import pytest

from rag.answer import answer, generate, llm, pipeline
from rag.answer.llm_fake import UNSUPPORTED_MARKER
from rag.contract import contract_errors, load_fixture

SOERING = ["001-57619§88", "001-57619§91", "001-57619§111"]


def ask(conn, question="Can the UK extradite someone at risk of ill-treatment?", **options):
    return answer(
        conn, {"question": question, "options": options} if options else {"question": question}
    )


def test_rag_path_end_to_end_with_fake_llm(answer_db, fake_search):
    fake_search["ids"] = [*SOERING, "001-100001§42"]
    a = ask(answer_db)
    assert contract_errors("Answer", a) == []
    assert a["route"] == "rag" and not a["refused_or_not_in_sources"]
    assert [c["status"] for c in a["claims"]] == ["supported"] * 3
    assert "[Soering v UK §88]" in a["answer_text"]
    assert len(json.dumps(a).encode()) < 50_000
    assert {c["link_target"] for c in a["citations"]} == {
        "/case/001-57619#p88",
        "/case/001-57619#p91",
        "/case/001-57619#p111",
    }
    steps = [s["step"] for s in a["steps"]]
    assert steps == ["route", "retrieve", "generate", "verify"]
    assert a["steps"][0]["model"] == "claude-haiku-5-5"  # the route step includes query planning
    assert a["total_cost_usd"] == pytest.approx(sum(s["cost_usd"] for s in a["steps"]))
    assert a["total_cost_usd"] > 0
    assert set(a["models_used"]) == {"claude-sonnet-5-5", "claude-haiku-5-5"}


def test_every_call_is_logged_to_cost_log(answer_db, fake_search):
    fake_search["ids"] = SOERING
    ask(answer_db)
    rows = answer_db.execute("SELECT purpose, count(*) FROM cost_log GROUP BY 1").fetchall()
    assert dict(rows) == {"route": 1, "generate": 1, "verify": 3}  # route = query planning


def test_citations_quote_the_paragraph_verbatim(answer_db, fake_search):
    fake_search["ids"] = SOERING
    a = ask(answer_db)
    for c in a["citations"]:
        text = answer_db.execute(
            "SELECT text FROM paragraphs WHERE id = %s", (c["paragraph_id"],)
        ).fetchone()[0]
        assert c["quote"] in text and len(c["quote"]) <= 300


def test_unsupported_claims_removed_from_text_but_kept_in_claims(
    answer_db, fake_search, monkeypatch
):
    fake_search["ids"] = SOERING
    real = llm.complete

    def tamper(conn, **kw):
        if kw["purpose"] == "generate":
            r = real(conn, **kw)
            data = json.loads(r.text)
            data["claims"][0]["text"] += f" {UNSUPPORTED_MARKER}"
            r.text = json.dumps(data)
            return r
        return real(conn, **kw)

    monkeypatch.setattr(llm, "complete", tamper)
    a = ask(answer_db)
    statuses = [c["status"] for c in a["claims"]]
    assert statuses == ["supported", "unsupported", "supported"]
    assert UNSUPPORTED_MARKER not in a["answer_text"]
    assert "§91" not in a["answer_text"]  # the dropped claim's marker is gone too
    assert "§88" in a["answer_text"] and "§111" in a["answer_text"]
    assert "001-57619§91" not in {c["paragraph_id"] for c in a["citations"]}
    assert contract_errors("Answer", a) == []


def test_invented_citation_id_is_rejected(answer_db, fake_search, monkeypatch):
    fake_search["ids"] = SOERING
    real = llm.complete

    def tamper(conn, **kw):
        r = real(conn, **kw)
        if kw["purpose"] == "generate":
            data = json.loads(r.text)
            data["short_answer"]["citation_ids"] = ["001-57619§999"]
            r.text = json.dumps(data)
        return r

    monkeypatch.setattr(llm, "complete", tamper)
    monkeypatch.setattr(generate, "rewrite_short_answer", lambda *a, **k: (None, None))
    a = ask(answer_db)
    assert a["claims"][0]["status"] == "unsupported" and a["claims"][0]["citation_ids"] == []
    assert "§999" not in a["answer_text"]
    assert all(c["paragraph_id"] != "001-57619§999" for c in a["citations"])


def test_all_claims_unsupported_gives_no_answer(answer_db, fake_search, monkeypatch):
    fake_search["ids"] = SOERING[:1]
    real = llm.complete

    def tamper(conn, **kw):
        r = real(conn, **kw)
        if kw["purpose"] == "generate":
            data = json.loads(r.text)
            data["short_answer"]["text"] += f" {UNSUPPORTED_MARKER}"
            data["claims"][0]["text"] += f" {UNSUPPORTED_MARKER}"
            r.text = json.dumps(data)
        return r

    monkeypatch.setattr(llm, "complete", tamper)
    a = ask(answer_db)
    assert a["refused_or_not_in_sources"] and a["citations"] == []
    assert a["claims"][0]["status"] == "unsupported"
    assert contract_errors("Answer", a) == []


def test_verification_failure_leaves_claim_unverified(answer_db, fake_search, monkeypatch):
    fake_search["ids"] = SOERING[:1]
    real = llm.complete

    def flaky(conn, **kw):
        if kw["purpose"] == "verify":
            raise RuntimeError("verifier down")
        return real(conn, **kw)

    monkeypatch.setattr(llm, "complete", flaky)
    a = ask(answer_db)
    assert a["claims"][0]["status"] == "unverified"
    assert "§88" in a["answer_text"]  # unverified claims are kept
    assert contract_errors("Answer", a) == []


def test_nothing_retrieved_says_not_in_sources(answer_db, fake_search):
    fake_search["ids"] = []
    a = ask(answer_db, "Should the UK leave the ECHR?")
    assert a["refused_or_not_in_sources"] is True
    assert "don't answer" in a["answer_text"]
    assert a["claims"] == [] and a["citations"] == []
    assert contract_errors("Answer", a) == []


def test_search_options_are_forwarded(answer_db, fake_search):
    fake_search["ids"] = SOERING[:1]
    ask(answer_db, mode="bm25", chunking="by_section", k=5)
    req = fake_search["requests"][0]
    assert (req["mode"], req["chunking"], req["k"]) == ("bm25", "by_section", 5)
    fake_search["requests"].clear()
    ask(answer_db)
    req = fake_search["requests"][0]
    assert (req["mode"], req["chunking"], req["k"]) == ("hybrid_rerank", "recursive", 12)


def test_stats_route_end_to_end(answer_db, fake_search):
    q = (
        "How many UK deportation complaints in the corpus were declared inadmissible, "
        "and the most common reasons?"
    )
    a = answer(answer_db, {"question": q})
    assert contract_errors("Answer", a) == []
    assert a["route"] == "stats" and a["stats"]["count"] == 2
    assert "SELECT" in a["stats"]["sql"]
    assert (
        a["answer_text"].startswith("The indexed corpus has 2 ")
        and "manifestly ill-founded" in a["answer_text"]
    )
    assert a["citations"] == a["stats"]["matching_cases"]
    assert [s["step"] for s in a["steps"]] == ["route", "generate", "retrieve"]
    assert fake_search["requests"] == []  # no vector search on the stats path


def test_forced_route_option(answer_db, fake_search):
    fake_search["ids"] = SOERING[:1]
    a = ask(answer_db, "How many cases are there?", route="rag")
    assert a["route"] == "rag"
    a = ask(answer_db, "Explain Article 3.", route="stats")
    assert a["route"] == "stats" and a["stats"] is not None


def test_stats_failure_falls_back_to_rag_when_auto(answer_db, fake_search, monkeypatch):
    fake_search["ids"] = SOERING[:1]
    monkeypatch.setattr(
        pipeline.stats,
        "run_stats_full",
        lambda *a, **k: (_ for _ in ()).throw(pipeline.stats.StatsError("boom")),
    )
    a = ask(answer_db, "How many cases mention Article 3?")
    assert a["route"] == "rag" and a["claims"]
    a = ask(answer_db, "How many cases mention Article 3?", route="stats")
    assert a["route"] == "stats" and a["refused_or_not_in_sources"] and a["stats"] is None
    assert contract_errors("Answer", a) == []


def test_size_cap_trims_quotes_and_claims():
    a = load_fixture("Answer")
    a["citations"] = [dict(a["citations"][0], quote="q" * 300) for _ in range(10)]
    a["claims"] = [dict(a["claims"][0], id=f"c{i}") for i in range(10)]
    out = pipeline.enforce_size(a, max_bytes=2500)
    assert len(json.dumps(out, ensure_ascii=False).encode()) <= 2500 or len(out["claims"]) == 1


def test_assemble_caps_citations_and_text_length():
    from rag.answer.context import Source

    sources = [
        Source(
            f"d{i}§1",
            f"d{i}",
            f"Case {i} v. The United Kingdom",
            "judgment",
            "2000-01-01",
            "violation",
            f"Paragraph {i} text. " * 5,
        )
        for i in range(15)
    ]
    claims = [
        {
            "id": f"c{i}",
            "text": f"Claim {i} " + "x" * 200,
            "citation_ids": [f"d{i}§1"],
            "status": "supported",
            "reason": "",
        }
        for i in range(15)
    ]
    text, kept, cites, refused = pipeline.assemble_rag(claims, sources, "")
    assert len(cites) <= 10 and len(text) <= 3000 and not refused
    assert len(kept) == len(cites)


def test_contract_fixtures_still_valid():
    for name in ("Answer", "Answer.stats", "Answer.refused"):
        assert contract_errors("Answer", load_fixture(name)) == []


def test_markers_are_grouped_per_case():
    names = {
        "d1§1": "A v. The United Kingdom",
        "d1§2": "A v. The United Kingdom",
        "d2§9": "B v. The United Kingdom",
    }
    out = pipeline._sentence("The Court held X.", ["d1§1", "d1§2", "d2§9"], names)
    assert out == "The Court held X [A v UK §1, §2] [B v UK §9]."


def test_operative_provisions_of_retrieved_cases_join_the_context(answer_db, fake_search):
    answer_db.execute(
        "INSERT INTO paragraphs (id, doc_id, position, section, text) VALUES "
        "('001-100001§op1', '001-100001', 9, 'Operative provisions', 'Holds that there has been no violation of Article 3;')"
    )
    answer_db.commit()
    fake_search["ids"] = ["001-100001§42"]
    a = ask(answer_db)
    cited = {c["paragraph_id"] for c in a["citations"]}
    assert "001-100001§42" in cited and "001-100001§op1" in cited
    assert "[N. v UK §42, §op1]" in a["answer_text"] or "§op1" in a["answer_text"]
