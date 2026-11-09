"""Every tool against the seeded corpus (fake embedder, no reranker): contract-valid and small."""

import json
from types import SimpleNamespace

import pytest

from echr_mcp import tools
from echr_mcp.common import RESULT_MAX_BYTES, ToolError, cite, json_bytes
from echr_mcp.tests import seed
from rag.contract import contract_errors, load_fixture
from rag.index import get_embedder


def valid(name: str, result: dict) -> dict:
    assert contract_errors(name, result) == []
    assert json_bytes(result) <= RESULT_MAX_BYTES
    return result


def search(conn, **args):
    return tools.search_case_law(conn, args, embedder=get_embedder("fake"), reranker=None)


# --- search_case_law -------------------------------------------------------------------------


def test_search_fixture_arguments(seeded):
    result = valid(
        "McpSearchCaseLawResult", search(seeded, **load_fixture("McpSearchCaseLawInput"))
    )
    assert result["filters"] == "Article 3"
    assert 1 <= len(result["hits"]) <= 3
    assert [h["rank"] for h in result["hits"]] == list(range(1, len(result["hits"]) + 1))


def test_search_all_filters_in_words_and_hits_obey_them(seeded):
    result = valid(
        "McpSearchCaseLawResult",
        search(seeded, **load_fixture("McpSearchCaseLawInput.all-filters")),
    )
    assert result["filters"] == "Article 8; judgments; outcome: violation; 2000–2020"
    for hit in result["hits"]:
        assert hit["doc_type"] == "judgment" and hit["outcome"] == "violation"


def test_search_hits_are_distinct_cited_and_verbatim(seeded):
    result = valid(
        "McpSearchCaseLawResult",
        search(seeded, query="deportation national security risk of ill-treatment", limit=10),
    )
    ids = [h["paragraph_id"] for h in result["hits"]]
    assert ids and len(ids) == len(set(ids))
    for hit in result["hits"]:
        text = seeded.execute(
            "SELECT text FROM paragraphs WHERE id = %s", (hit["paragraph_id"],)
        ).fetchone()[0]
        assert hit["quote"].strip("…") in text
        assert hit["cite"].startswith("[") and hit["cite"].endswith("]")
        assert hit["cite"] == cite(hit["case_name"], hit["doc_type"], hit["para_label"])
        assert hit["para_label"] in hit["cite"] and "#:~:text=" in hit["hudoc_url"]


def test_search_default_limit_is_eight_and_limit_is_respected(seeded):
    many = search(seeded, query="deportation Article 3 applicant")
    assert len(many["hits"]) <= 8
    assert len(search(seeded, query="deportation Article 3 applicant", limit=2)["hits"]) <= 2


def test_search_no_match_is_an_empty_list(seeded):
    result = valid(
        "McpSearchCaseLawResult", search(seeded, query="zzzqqq", year_from=2090, year_to=2091)
    )
    assert result["hits"] == []
    assert result["filters"] == "2090–2091"


def test_search_drops_documents_of_another_data_source(seeded):
    seeded.execute("UPDATE documents SET data_source = 'full' WHERE item_id = %s", (seed.MCCANN,))
    seeded.commit()
    try:
        hits = search(seeded, query="use of lethal force submission", limit=10)["hits"]
        assert all(h["doc_id"] != seed.MCCANN for h in hits)
    finally:
        seeded.execute(
            "UPDATE documents SET data_source = 'snapshot' WHERE item_id = %s", (seed.MCCANN,)
        )
        seeded.commit()


# --- get_paragraphs --------------------------------------------------------------------------


def test_get_paragraphs_fixture_arguments(seeded):
    result = valid(
        "McpGetParagraphsResult",
        tools.get_paragraphs(seeded, load_fixture("McpGetParagraphsInput")),
    )
    assert [p["paragraph_id"] for p in result["paragraphs"]] == [
        "001-58004§78",
        "001-58004§79",
        "001-58004§80",
    ]
    assert [p["requested"] for p in result["paragraphs"]] == [False, True, False]
    assert result["not_found"] == []
    assert result["paragraphs"][1]["cite"] == "[Chahal v. the United Kingdom, Judgment, §79]"


def test_get_paragraphs_not_found_and_grouping(seeded):
    result = valid(
        "McpGetParagraphsResult",
        tools.get_paragraphs(
            seeded,
            {
                "paragraph_ids": [
                    "001-58004§80",
                    "001-99999§1",
                    "001-57943§2",
                    "001-58004§79",
                    "001-58004§80",
                ],
                "neighbours": 1,
            },
        ),
    )
    assert result["not_found"] == ["001-99999§1"]
    ids = [p["paragraph_id"] for p in result["paragraphs"]]
    assert len(ids) == len(set(ids))
    docs = [p["doc_id"] for p in result["paragraphs"]]
    assert docs == sorted(docs, key=docs.index)  # a document's paragraphs are contiguous
    assert docs[0] == "001-58004" and docs[-1] == "001-57943"
    chahal = [p for p in result["paragraphs"] if p["doc_id"] == "001-58004"]
    assert [p["paragraph_id"] for p in chahal] == [f"001-58004§{n}" for n in (78, 79, 80, 81)]
    assert [p["requested"] for p in chahal] == [False, True, True, False]


def test_get_paragraphs_operative_neighbour_numbers_are_null(seeded):
    result = tools.get_paragraphs(seeded, {"paragraph_ids": ["001-58004§op2"]})
    assert result["paragraphs"][0]["number"] is None
    assert result["paragraphs"][0]["section"] == "Operative provisions"


# --- get_case --------------------------------------------------------------------------------


def test_get_case_chahal(seeded):
    result = valid("McpGetCaseResult", tools.get_case(seeded, load_fixture("McpGetCaseInput")))
    assert result["case_name"] == "Chahal v. the United Kingdom"
    assert result["outcome_label"].startswith("Mixed")
    assert result["paragraph_count"] == len(seed.chahal_paragraphs())
    assert [o["paragraph_id"] for o in result["operative_provisions"]][:2] == [
        "001-58004§op1",
        "001-58004§op2",
    ]
    assert [s["section"] for s in result["outline"]] == [
        "Procedure",
        "The Facts",
        "The Law",
        "Operative provisions",
        "Other",
    ]
    assert sum(s["paragraph_count"] for s in result["outline"]) == result["paragraph_count"]


def test_get_case_unknown_id_is_a_plain_sentence(seeded):
    with pytest.raises(ToolError) as error:
        tools.get_case(seeded, {"case_id": "001-99999"})
    assert str(error.value) == "No case 001-99999 in this corpus (snapshot: 7 UK documents)."


def test_outline_merges_the_tail_after_twelve_runs():
    paragraphs = [
        {"id": f"d§{i}", "section": "The Law" if i % 2 else "Other"} for i in range(1, 41)
    ]
    outline = tools._outline(paragraphs)
    assert len(outline) == 12
    assert outline[-1]["last_paragraph_id"] == "d§40"
    assert sum(r["paragraph_count"] for r in outline) == 40
    assert outline[-1]["first_paragraph_id"] == "d§12"


# --- corpus_info -----------------------------------------------------------------------------


def test_corpus_info(seeded):
    result = valid("McpCorpusInfoResult", tools.corpus_info(seeded, {}))
    assert result["totals"]["documents"] == 7
    assert sum(b["count"] for b in result["by_doc_type"]) == 7
    assert result["year_range"] == {"from": 1995, "to": 2012}
    assert {b["key"]: b["count"] for b in result["by_article"]}["3"] == 6
    assert [m["count"] for m in result["missing"]][2:] == [307, 212, 45]
    assert result["by_outcome"][0]["key"] == "inadmissible"


# --- check_quote -----------------------------------------------------------------------------


def test_check_quote_fixture_is_verbatim(seeded):
    expected = load_fixture("McpCheckQuoteResult")
    result = valid(
        "McpCheckQuoteResult", tools.check_quote(seeded, load_fixture("McpCheckQuoteInput"))
    )
    assert result["verbatim"] is True and result["similarity"] == 1.0
    assert result["closest_match"] == expected["closest_match"]
    assert result["cite"] == expected["cite"]


def test_check_quote_unknown_paragraph(seeded):
    result = valid(
        "McpCheckQuoteResult",
        tools.check_quote(seeded, {"paragraph_id": "001-58004§9999", "quote": "anything"}),
    )
    assert result == {
        "paragraph_id": "001-58004§9999",
        "paragraph_found": False,
        "verbatim": False,
        "closest_match": None,
        "similarity": 0,
        "para_label": None,
        "cite": None,
        "corpus": result["corpus"],
    }


# --- count_cases -----------------------------------------------------------------------------


def test_count_cases_fixture_arguments(seeded):
    result = valid(
        "McpCountCasesResult", tools.count_cases(seeded, load_fixture("McpCountCasesInput"))
    )
    # seeded: Grand Chamber judgments are Chahal (mixed) and McCann (violation)
    assert (result["count"], result["scope_total"]) == (2, 2)
    assert result["filters"] == "Grand Chamber judgments that found at least one violation"
    assert "2" in result["answer"] and "all 2" in result["answer"]
    assert result["rows"][0][1] == 2
    assert [c["doc_id"] for c in result["matching_cases"]] == ["001-58004", "001-57943"]
    assert "Examples" not in result["answer"]
    assert result["params"]["count_of"] == "total_and_subset"


def test_count_cases_top_group_lists_only_the_top_group(seeded):
    result = valid(
        "McpCountCasesResult", tools.count_cases(seeded, load_fixture("McpCountCasesInput.reasons"))
    )
    assert result["top_group"] == {
        "key": "manifestly_ill_founded",
        "label": "manifestly ill-founded",
        "count": 2,
    }
    assert result["count"] == 2 and result["scope_total"] is None
    assert [c["doc_id"] for c in result["matching_cases"]] == ["001-90002", "001-90001"]
    assert any("deportation" in d for d in result["definitions"])
    assert result["sql"].startswith("WITH matched AS")


def test_count_cases_defaults_when_nothing_is_given(seeded):
    result = valid("McpCountCasesResult", tools.count_cases(seeded, {}))
    assert result["count"] == 6  # default document types exclude the legal summary
    assert result["params"]["group_by"] == "none"


def test_count_cases_long_sql_is_cut_and_says_so(seeded):
    args = {
        "articles": ["3", "5", "8", "13", "P1-1"],
        "keywords": ["deport", "removal"],
        "topic": "deportation",
    }
    result = valid("McpCountCasesResult", tools.count_cases(seeded, args))
    assert len(result["sql"]) <= 4000


@pytest.mark.parametrize(
    "params",
    [
        json.loads(json.dumps(load_fixture("McpCountCasesInput"))),
        load_fixture("McpCountCasesInput.reasons"),
        {"group_by": "year", "doc_types": ["judgment"], "date_from": "1990-01-01"},
        {"group_by": "article", "count_of": "top_group", "doc_types": ["decision"]},
        {"outcomes": ["inadmissible"], "count_of": "total"},
    ],
)
def test_count_cases_matches_the_ask_stats_path(seeded, monkeypatch, params):
    """The same numbers /ask's stats path gets from the same parameters (LLM_MODE=fake)."""
    from rag.answer import stats

    monkeypatch.setenv("LLM_MODE", "fake")
    mine = tools.count_cases(seeded, params)
    no_llm = SimpleNamespace(model="none", tokens_in=0, tokens_out=0, tokens_cached=0, cost_usd=0)
    monkeypatch.setattr(stats, "extract_params", lambda conn, q, rid: (mine["params"], no_llm))
    ours = stats.run_stats_full(seeded, "", "parity")
    assert mine["count"] == ours.result["count"]
    assert mine["scope_total"] == ours.result["scope_total"]
    assert mine["rows"] == ours.result["rows"]
    assert mine["columns"] == ours.result["columns"]
