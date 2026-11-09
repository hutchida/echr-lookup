import json

from . import common, report


def test_report_end_to_end_on_synthetic_data(tmp_path, monkeypatch):
    items = [
        {"id": "q1", "question": "Q1?", "type": "explain", "expected_paragraph_ids": ["a", "b"]}
    ]
    paras = [
        {"id": pid, "gold": pid in ("a", "b"), "found_by": {"fixed/bm25": i + 1}, "n_configs": 1,
         "best_rank": i + 1, "case_name": "C v UK", "doc_type": "judgment", "section": "The Law",
         "text": f"Text of {pid}."}
        for i, pid in enumerate("abc")
    ]  # fmt: skip
    pool = [{"question_id": "q1", "question": "Q1?", "type": "explain", "gold_ids": ["a", "b"],
             "paragraphs": paras}]  # fmt: skip
    hit_lists = {f"{c}/{m}": [["a"], ["c"]] for c, m in common.CONFIGS}
    runs = [{"question_id": "q1", "runs": hit_lists}]

    def rec(run, grades):
        return {
            "question_id": "q1",
            "run": run,
            "seed": 1,
            "model": "claude-opus-5-5",
            "n_pooled": 3,
            "ok": True,
            "order": [],
            "errors": [],
            "attempts": [{"cost_usd": 0.1}],
            "grades": {p: {"grade": g, "reason": f"why {p}"} for p, g in grades.items()},
        }

    monkeypatch.setattr(common, "JUDGMENTS_DIR", tmp_path)
    for mod in (report,):
        monkeypatch.setattr(mod, "JUDGMENTS_DIR", tmp_path)
        monkeypatch.setattr(mod, "POOL_PATH", tmp_path / "pool.jsonl")
        monkeypatch.setattr(mod, "RETRIEVAL_PATH", tmp_path / "retrieval.jsonl")
        monkeypatch.setattr(mod, "META_PATH", tmp_path / "meta.json")
        monkeypatch.setattr(mod, "DOC_PATH", tmp_path / "doc.md")
    monkeypatch.setattr("rag.eval.judging.qrels.QRELS_V2_PATH", tmp_path / "qrels-v2.jsonl")
    monkeypatch.setattr(report, "load_questions", lambda: items)
    monkeypatch.setattr(
        report, "spend_from_db",
        lambda: {"usd": 0.2, "calls": 2, "tokens_in": 10, "tokens_out": 5, "tokens_cached": 0},
    )  # fmt: skip
    common.write_jsonl(tmp_path / "pool.jsonl", pool)
    common.write_jsonl(tmp_path / "retrieval.jsonl", runs)
    common.write_jsonl(common.run_path(1), [rec(1, {"a": 2, "b": 0, "c": 2})])
    common.write_jsonl(common.run_path(2), [rec(2, {"a": 2, "b": 1, "c": 2})])
    qrels_path = tmp_path / "qrels-v2.jsonl"
    monkeypatch.setattr(report, "write_qrels", lambda rows: common.write_jsonl(qrels_path, rows))
    monkeypatch.setattr(report, "load_qrels", lambda: {r["question_id"]: r["qrels"] for r in
                        common.read_jsonl(qrels_path)})  # fmt: skip

    assert report.write_report() == 0
    doc = (tmp_path / "doc.md").read_text()
    assert "Did the scores move?" in doc and "fixed/hybrid_rerank" in doc
    assert "$0.20" in doc and "Gold added" in doc and "`b`" in doc
    assert json.loads((tmp_path / "meta.json").read_text())["spend"]["calls"] == 2
