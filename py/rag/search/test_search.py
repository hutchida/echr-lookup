import pytest

from rag import config
from rag.contract import contract_errors, load_fixture
from rag.index import get_embedder
from rag.search import get_reranker, search
from rag.search.fusion import rrf
from rag.search.retrieval import bm25_query_string, bm25_search, vector_search

MODES = ("bm25", "vector", "hybrid", "hybrid_rerank")
QUERY = "death row phenomenon extradition"


def req(mode="hybrid", **over):
    return {"query": QUERY, "mode": mode, "chunking": "recursive", "k": 5, **over}


def run(conn, request):
    return search(conn, request, embedder=get_embedder("fake"), reranker=get_reranker("fake"))


def doc_ids(result):
    return {h["chunk"]["doc_id"] for h in result["hits"]}


# --- fusion -------------------------------------------------------------------------------------


def test_rrf_hand_computed():
    # list 1: a, b, c   list 2: b, c, d     k = 60
    # a = 1/61                 = 0.016393
    # b = 1/62 + 1/61          = 0.032522  (rank 2 in list 1, rank 1 in list 2)
    # c = 1/63 + 1/62          = 0.032002
    # d = 1/63                 = 0.015873
    out = rrf([["a", "b", "c"], ["b", "c", "d"]], k=60)
    assert [i for i, _ in out] == ["b", "c", "a", "d"]
    scores = dict(out)
    assert scores["a"] == pytest.approx(0.0163934, abs=1e-6)
    assert scores["b"] == pytest.approx(0.0325224, abs=1e-6)
    assert scores["c"] == pytest.approx(0.0320020, abs=1e-6)
    assert scores["d"] == pytest.approx(0.0158730, abs=1e-6)


def test_rrf_matches_contract_fixture_numbers():
    # SearchResult.json: vector rank 1 + bm25 rank 3 -> 1/61 + 1/63 = 0.032266...
    assert dict(rrf([["x", "y", "z"], ["z", "q", "x"]]))["x"] == pytest.approx(1 / 61 + 1 / 63)
    fixture = load_fixture("SearchResult")["hits"][0]["scores"]
    assert fixture["rrf_score"] == pytest.approx(1 / 61 + 1 / 63)


def test_rrf_ties_are_deterministic():
    out = rrf([["a"], ["b"]])
    assert [i for i, _ in out] == ["a", "b"]


# --- query string ---------------------------------------------------------------------------------


def test_bm25_query_string_is_safe():
    assert bm25_query_string("Soering") == "soering"
    assert bm25_query_string('Is "death row" AND (torture)?') == "death OR row OR torture"
    assert bm25_query_string("the of") == "the OR of"
    assert bm25_query_string("?!") is None


# --- every mode ---------------------------------------------------------------------------------


@pytest.mark.parametrize("mode", MODES)
def test_every_mode_validates_against_the_contract(corpus, mode):
    request = req(mode)
    assert contract_errors("SearchRequest", request) == []
    result = run(corpus, request)
    assert contract_errors("SearchResult", result) == []
    assert result["hits"], mode
    assert result["hits"][0]["case_name"].startswith("SOERING")
    assert [h["rank"] for h in result["hits"]] == list(range(1, len(result["hits"]) + 1))


def test_scores_filled_exactly_for_the_methods_that_ran(corpus):
    def filled(result):
        keys = set()
        for h in result["hits"]:
            keys |= {k.rsplit("_", 1)[0] for k, v in h["scores"].items() if v is not None}
        return keys

    assert filled(run(corpus, req("bm25"))) == {"bm25"}
    assert filled(run(corpus, req("vector"))) == {"vector"}
    assert filled(run(corpus, req("hybrid"))) == {"bm25", "vector", "rrf"}
    assert filled(run(corpus, req("hybrid_rerank"))) == {"bm25", "vector", "rrf", "rerank"}

    t = run(corpus, req("hybrid_rerank"))["timings_ms"]
    assert all(t[k] is not None for k in ("bm25", "vector", "fuse", "rerank", "total"))
    t = run(corpus, req("bm25"))["timings_ms"]
    assert t["vector"] is None and t["fuse"] is None and t["rerank"] is None


def test_hybrid_ranks_follow_rrf_and_rerank_reorders(corpus):
    hybrid = run(corpus, req("hybrid", k=10))
    assert [h["scores"]["rrf_rank"] for h in hybrid["hits"]] == list(range(1, 11))
    rrf_scores = [h["scores"]["rrf_score"] for h in hybrid["hits"]]
    assert rrf_scores == sorted(rrf_scores, reverse=True)

    reranked = run(corpus, req("hybrid_rerank", k=10))
    values = [h["scores"]["rerank_score"] for h in reranked["hits"]]
    assert values == sorted(values, reverse=True)
    assert [h["scores"]["rerank_rank"] for h in reranked["hits"]] == list(range(1, 11))


def test_hybrid_rerank_without_reranker_degrades_to_hybrid_when_disabled(corpus, monkeypatch):
    monkeypatch.setenv("RERANK_ENABLED", "0")
    assert not config.rerank_enabled()
    result = search(corpus, req("hybrid_rerank"), embedder=get_embedder("fake"))
    assert contract_errors("SearchResult", result) == []
    assert all(h["scores"]["rerank_score"] is None for h in result["hits"])
    assert result["timings_ms"]["rerank"] is None


def test_chunking_filter(corpus):
    fixed = run(corpus, req("bm25", chunking="fixed", k=10))
    assert fixed["hits"] and {h["chunk"]["strategy"] for h in fixed["hits"]} == {"fixed"}
    rec = run(corpus, req("vector", chunking="recursive", k=10))
    assert {h["chunk"]["strategy"] for h in rec["hits"]} == {"recursive"}


def test_paragraph_ids_are_a_nonempty_subset_of_the_chunk(corpus):
    for mode in MODES:
        for h in run(corpus, req(mode, k=10))["hits"]:
            assert h["paragraph_ids"]
            assert set(h["paragraph_ids"]) <= set(h["chunk"]["paragraph_ids"])


def test_k_is_capped_at_50_and_51_is_invalid(corpus):
    for mode in MODES:
        result = run(corpus, req(mode, k=50))
        assert len(result["hits"]) <= 50
        assert contract_errors("SearchResult", result) == []
    with pytest.raises(ValueError):
        run(corpus, req(k=51))
    assert contract_errors("SearchRequest", req(k=51)) != []
    for bad in (req(k=0), req(mode="nope"), req(chunking="nope"), req(query="  ")):
        with pytest.raises(ValueError):
            run(corpus, bad)


def test_search_logs_embed_and_rerank_costs(corpus):
    corpus.execute("DELETE FROM cost_log")
    run(corpus, req("bm25"))
    assert corpus.execute("SELECT count(*) FROM cost_log").fetchone()[0] == 0
    run(corpus, req("hybrid"))
    run(corpus, req("hybrid_rerank"))
    rows = corpus.execute("SELECT purpose, cost_usd FROM cost_log ORDER BY purpose").fetchall()
    assert [r[0] for r in rows] == ["embed", "embed", "rerank"]
    assert all(r[1] == 0 for r in rows)


def test_empty_bm25_query_returns_no_hits(corpus):
    result = run(corpus, req("bm25", query="?!"))
    assert result["hits"] == []
    assert contract_errors("SearchResult", result) == []


# --- filters are applied inside both retrievers -----------------------------------------

FILTERS = [
    ({"article": "8"}, {"001-10001", "001-10002"}),  # '8' and '8-1'
    ({"article": "8-1"}, {"001-10001"}),
    ({"article": "3"}, {"001-57619"}),
    ({"doc_types": ["decision"]}, {"001-10002"}),
    ({"outcomes": ["violation"]}, {"001-57619", "001-10003"}),
    ({"outcomes": ["inadmissible", "no_violation"]}, {"001-10001", "001-10002"}),
    ({"date_from": "2005-01-01"}, {"001-10001", "001-10002"}),
    ({"date_to": "1999-12-31"}, {"001-57619", "001-10003"}),
    ({"date_from": "1990-01-01", "date_to": "2006-01-01"}, {"001-10002", "001-10003"}),
    ({"article": "8", "doc_types": ["judgment"], "date_from": "2000-01-01"}, {"001-10001"}),
]


@pytest.mark.parametrize(("filters", "allowed"), FILTERS)
@pytest.mark.parametrize("mode", MODES)
def test_filters_are_honoured(corpus, mode, filters, allowed):
    query = "deportation life family death row freedom expression prisoners voting extradition"
    result = run(corpus, req(mode, query=query, k=50, filters=filters))
    assert contract_errors("SearchRequest", req(mode, filters=filters)) == []
    assert contract_errors("SearchResult", result) == []
    assert result["hits"]
    assert doc_ids(result) <= allowed


def test_filter_matching_nothing_gives_no_hits(corpus):
    result = run(corpus, req("hybrid", filters={"article": "P1-3"}))
    assert result["hits"] == []


def test_filters_apply_before_the_top_50_cut(empty_db):
    """60 'noise' chunks match the query better than the one target chunk. After a filter that only
    the target passes, a retriever that filtered AFTER taking its top 50 would return nothing."""
    from rag.index.testing import load_doc, make_doc

    emb = get_embedder("fake")
    noise = make_doc("001-90000", "NOISE v. THE UNITED KINGDOM", doc_type="judgment")
    target = make_doc("001-90001", "TARGET v. THE UNITED KINGDOM", doc_type="decision")
    load_doc(empty_db, emb, noise, ["death row phenomenon extradition"] * 60)
    load_doc(
        empty_db,
        emb,
        target,
        ["extradition was mentioned once in a long passage about something else entirely " * 3],
    )
    empty_db.execute("ANALYZE")
    empty_db.commit()
    filters = {"doc_types": ["decision"]}
    unfiltered = bm25_search(empty_db, QUERY, "recursive", None)
    assert "001-90001" not in {r["doc_id"] for r in unfiltered}
    assert [r["doc_id"] for r in bm25_search(empty_db, QUERY, "recursive", filters)] == [
        "001-90001"
    ]
    qvec = emb.embed_query(QUERY)
    unfiltered = vector_search(empty_db, qvec, "recursive", None)
    assert "001-90001" not in {r["doc_id"] for r in unfiltered}
    assert [r["doc_id"] for r in vector_search(empty_db, qvec, "recursive", filters)] == [
        "001-90001"
    ]
