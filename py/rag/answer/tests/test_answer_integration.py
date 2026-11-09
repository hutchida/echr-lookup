# ruff: noqa: E501
"""answer() against the real S3 index and search (S3's `corpus` fixture), with the fake LLM and
fake embedder, so it stays offline."""

import json

from rag.answer import answer
from rag.contract import contract_errors


def test_rag_answer_against_real_index(corpus):
    a = answer(
        corpus,
        {"question": "extradition death row phenomenon", "options": {"mode": "hybrid", "k": 5}},
    )
    assert contract_errors("Answer", a) == []
    assert a["route"] == "rag" and a["citations"] and not a["refused_or_not_in_sources"]
    for c in a["citations"]:
        text = corpus.execute(
            "SELECT text FROM paragraphs WHERE id = %s", (c["paragraph_id"],)
        ).fetchone()[0]
        assert c["quote"] in text and c["link_target"].startswith(f"/case/{c['doc_id']}#p")
    rows = corpus.execute(
        "SELECT purpose, count(*) FROM cost_log WHERE request_id = %s GROUP BY 1",
        (a["request_id"],),
    ).fetchall()
    assert dict(rows)["generate"] == 1 and dict(rows)["verify"] >= 1  # logged by the real log_cost
    assert [s["step"] for s in a["steps"]][:2] == ["route", "retrieve"]
    assert len(json.dumps(a).encode()) < 50_000


def test_all_search_modes_feed_the_answer(corpus):
    for mode in ("bm25", "vector", "hybrid", "hybrid_rerank"):
        a = answer(
            corpus,
            {"question": "deportation family life", "options": {"mode": mode, "route": "rag"}},
        )
        assert contract_errors("Answer", a) == [], mode


def test_stats_answer_against_real_tables(corpus):
    a = answer(
        corpus,
        {"question": "How many decisions were declared inadmissible?", "options": {"route": "rag"}},
    )
    assert a["route"] == "rag"
    a = answer(corpus, {"question": "How many decisions were declared inadmissible?"})
    assert contract_errors("Answer", a) == []
    assert a["route"] == "stats" and a["stats"]["count"] == 1  # BETA v UK
    assert a["stats"]["matching_cases"][0]["doc_id"] == "001-10002"
