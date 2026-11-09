from .pool import build_pool, collect_runs, pool_for_question, pool_sizes

ITEM = {
    "id": "q1",
    "question": "Q one?",
    "type": "explain",
    "expected_paragraph_ids": ["a§1", "a§2"],
}
STAT = {"id": "s1", "question": "How many?", "type": "stat", "expected_paragraph_ids": []}


def test_collect_runs_skips_stat_and_uses_runner_request_shape():
    seen = []

    def search(request):
        seen.append(request)
        return {"hits": [{"paragraph_ids": ["a§1", "b§9"]}, {"paragraph_ids": ["c§3"]}]}

    rows = collect_runs(search, [ITEM, STAT], configs=[("fixed", "bm25"), ("recursive", "vector")])
    assert [r["question_id"] for r in rows] == ["q1"]
    assert set(rows[0]["runs"]) == {"fixed/bm25", "recursive/vector"}
    assert rows[0]["runs"]["fixed/bm25"] == [["a§1", "b§9"], ["c§3"]]
    assert seen[0] == {"query": "Q one?", "mode": "bm25", "chunking": "fixed", "k": 10}


def test_pool_is_union_of_hits_and_gold_with_provenance():
    runs = {
        "fixed/bm25": [["b§9", "a§1"], ["c§3"]],
        "fixed/vector": [["c§3"], ["b§9"]],
        "by_section/hybrid": [["d§4"]],
    }
    entries = {e["id"]: e for e in pool_for_question(ITEM, runs)}
    assert set(entries) == {"a§1", "a§2", "b§9", "c§3", "d§4"}  # a§2 only via gold
    assert entries["a§1"]["gold"] and entries["a§2"]["gold"] and not entries["b§9"]["gold"]
    assert entries["b§9"]["found_by"] == {"fixed/bm25": 1, "fixed/vector": 2}
    assert entries["b§9"]["n_configs"] == 2 and entries["b§9"]["best_rank"] == 1
    assert entries["c§3"]["found_by"] == {"fixed/bm25": 2, "fixed/vector": 1}
    assert entries["a§2"]["found_by"] == {} and entries["a§2"]["best_rank"] is None


def test_pool_best_rank_is_the_first_hit_that_contains_the_paragraph():
    runs = {"fixed/bm25": [["x§1"], ["y§1", "x§1"]]}
    (x,) = [e for e in pool_for_question(ITEM, runs) if e["id"] == "x§1"]
    assert x["best_rank"] == 1


def test_pool_order_most_configs_first_and_gold_not_found_last():
    runs = {"fixed/bm25": [["p"], ["q"]], "fixed/vector": [["q"]]}
    ids = [e["id"] for e in pool_for_question(ITEM, runs)]
    assert ids == ["q", "p", "a§1", "a§2"]


def test_build_pool_attaches_text_and_flags_missing():
    rows = [{"question_id": "q1", "runs": {"fixed/bm25": [["a§1", "zz§1"]]}}]
    paragraphs = {
        "a§1": {
            "text": "Verbatim.",
            "case_name": "A v UK",
            "doc_type": "judgment",
            "section": "The Law",
        },
    }
    (q,) = build_pool([ITEM], rows, paragraphs)
    assert q["gold_ids"] == ["a§1", "a§2"] and q["type"] == "explain"
    by_id = {p["id"]: p for p in q["paragraphs"]}
    assert by_id["a§1"]["text"] == "Verbatim." and by_id["a§1"]["case_name"] == "A v UK"
    assert by_id["zz§1"]["text"] is None


def test_pool_sizes():
    pool = [{"paragraphs": [0] * n} for n in (3, 5, 10, 20)]
    assert pool_sizes(pool) == {"questions": 4, "min": 3, "median": 7.5, "max": 20, "total": 38}
    assert pool_sizes([])["questions"] == 0
