from .common import read_jsonl
from .qrels import build_qrels, load_qrels, write_qrels

POOL = [{"question_id": "q1"}, {"question_id": "q2"}, {"question_id": "q3"}]
RECORDS = {
    "q1": {"ok": True, "model": "claude-opus-5-5", "run": 1, "seed": 9,
           "grades": {"b§2": {"grade": 1, "reason": "r"}, "a§1": {"grade": 2, "reason": "r"}}},
    "q2": {"ok": False, "model": "claude-opus-5-5", "run": 1, "seed": 9, "grades": {}},
}  # fmt: skip


def test_build_qrels_has_provenance_and_skips_failed_and_missing():
    rows = build_qrels(RECORDS, POOL)
    assert [r["question_id"] for r in rows] == ["q1"]
    r = rows[0]
    assert r["qrels"] == {"a§1": 2, "b§2": 1}
    assert (r["judge_model"], r["run"], r["seed"]) == ("claude-opus-5-5", 1, 9)
    assert r["source"]


def test_write_and_load_round_trip(tmp_path):
    path = tmp_path / "qrels-v2.jsonl"
    write_qrels(build_qrels(RECORDS, POOL), path)
    assert len(read_jsonl(path)) == 1
    assert load_qrels(path) == {"q1": {"a§1": 2, "b§2": 1}}


def test_writer_never_touches_the_original_key(tmp_path):
    from rag.eval.items import QUESTIONS_PATH

    before = QUESTIONS_PATH.read_bytes()
    write_qrels(build_qrels(RECORDS, POOL), tmp_path / "x.jsonl")
    assert QUESTIONS_PATH.read_bytes() == before
