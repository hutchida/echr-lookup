import json

import pytest

from rag.contract import contract_errors
from rag.ingest import run_ingest
from rag.ingest.progress import Progress, fmt_duration

from .fakes import FakeConn, FakeDb, make_snapshot


@pytest.fixture
def snap(tmp_path):
    root = tmp_path / "snapshot"
    entries = make_snapshot(root, 4)
    return root, entries


def run(db, snap_root, conn=None, **kw):
    lines: list[str] = []
    result = run_ingest(
        conn or FakeConn(),
        "snapshot",
        deps=kw.pop("deps", None) or db.deps(),
        snapshot_root=snap_root,
        out=lines.append,
        **kw,
    )
    return result, lines


def test_manifest_fixture_entries_are_valid(snap):
    _, entries = snap
    assert all(contract_errors("ManifestEntry", e) == [] for e in entries)


def test_first_run_ingests_everything_and_ingest_run_validates(snap):
    root, entries = snap
    db = FakeDb()
    result, _ = run(db, root)
    assert contract_errors("IngestRun", result) == []
    assert result["counts"] == {
        "seen": 4,
        "new": 4,
        "changed": 0,
        "unchanged_skipped": 0,
        "failed": 0,
    }
    assert set(result["stage_seconds"]) == {"download", "parse", "chunk", "embed", "index"}
    assert result["embedder_model"] == "fake-embedder" and result["embedding_dim"] == 384
    assert db.runs == [result]
    assert {s for (_, s) in db.chunks} == {"fixed", "recursive", "by_section"}
    assert len(db.hashes) == 4


def test_second_run_skips_every_document(snap):
    root, _ = snap
    db = FakeDb()
    run(db, root)
    deps = db.deps()
    result, _ = run(db, root, deps=deps)
    assert result["counts"]["unchanged_skipped"] == 4
    assert result["counts"]["new"] == result["counts"]["changed"] == 0
    assert deps.embedder.batches == []  # nothing was embedded


def test_changed_file_is_reingested_and_others_skipped(snap):
    root, entries = snap
    db = FakeDb()
    run(db, root)
    body = b"<p>1. Corrected text.</p>" * 50
    (root / entries[1]["path"]).write_bytes(body)
    import hashlib

    entries[1]["sha256"] = hashlib.sha256(body).hexdigest()
    (root / "manifest.json").write_text(json.dumps(entries))
    result, _ = run(db, root)
    assert result["counts"] == {
        "seen": 4,
        "new": 0,
        "changed": 1,
        "unchanged_skipped": 3,
        "failed": 0,
    }


def test_new_document_added_later_is_picked_up(snap):
    root, entries = snap
    db = FakeDb()
    run(db, root, limit=3)
    result, _ = run(db, root)
    assert result["counts"]["new"] == 1 and result["counts"]["unchanged_skipped"] == 3


def test_failure_is_counted_and_does_not_abort(snap):
    root, entries = snap
    db = FakeDb()
    conn = FakeConn()
    bad = entries[1]["item_id"]
    result, lines = run(db, root, conn=conn, deps=db.deps(fail_on={bad}))
    assert result["counts"]["failed"] == 1
    assert result["counts"]["new"] == 3
    assert bad not in db.hashes
    assert conn.rollbacks == 1
    assert any("FAILED" in line and bad in line for line in lines)
    assert contract_errors("IngestRun", result) == []


def test_sha_mismatch_is_a_failure_not_a_crash(snap):
    root, entries = snap
    (root / entries[0]["path"]).write_bytes(b"tampered" * 200)
    db = FakeDb()
    result, _ = run(db, root)
    assert result["counts"]["failed"] == 1 and result["counts"]["new"] == 3


def test_reset_empties_first_and_limit_applies(snap):
    root, _ = snap
    db = FakeDb()
    run(db, root)
    result, _ = run(db, root, reset=True, limit=2)
    assert db.resets == 1
    assert result["counts"]["seen"] == 2 and result["counts"]["new"] == 2


def test_embeds_in_batches_of_at_most_32(snap):
    root, _ = snap
    db = FakeDb()
    deps = db.deps()
    run(db, root, deps=deps)
    assert deps.embedder.batches and max(deps.embedder.batches) <= 32


def test_progress_line_per_document_with_eta(snap):
    root, _ = snap
    _, lines = run(FakeDb(), root)
    doc_lines = [line for line in lines if line.startswith("[ingest")]
    assert len(doc_lines) == 4 and all("ETA" in line for line in doc_lines)
    assert "Ingest summary" in "\n".join(lines)


def test_eta_is_mean_time_per_document_times_remaining():
    now = [0.0]
    out: list[str] = []
    p = Progress(10, out=out.append, clock=lambda: now[0])
    now[0] = 20.0
    p.step("a", "new")
    now[0] = 40.0
    p.step("b", "new")  # 2 done in 40 s -> 20 s each -> 8 left = 160 s
    assert p.eta_seconds() == pytest.approx(160)
    assert "ETA 2:40" in out[-1]
    assert fmt_duration(3725) == "1:02:05"


def test_snapshot_must_not_touch_network_modules(snap):
    """run_ingest in snapshot mode needs no HudocClient."""
    root, _ = snap
    result, _ = run(FakeDb(), root)
    assert result["data_source"] == "snapshot"


def test_half_ingested_document_is_discarded_so_it_is_retried(snap):
    """If chunks fail to store after the document row was written, the stored hash must not make
    the next run skip the document."""
    root, entries = snap
    db = FakeDb()
    deps = db.deps()
    original = deps.replace_chunks
    calls = {"n": 0}

    def flaky(*a, **kw):
        calls["n"] += 1
        if calls["n"] == 2:
            raise RuntimeError("disk full")
        return original(*a, **kw)

    deps.replace_chunks = flaky
    deps.discard_document = lambda conn, item_id: db.hashes.pop(item_id, None)
    result, _ = run(db, root, deps=deps)
    assert result["counts"]["failed"] == 1 and len(db.hashes) == 3
    again, _ = run(db, root)
    assert again["counts"]["new"] == 1 and again["counts"]["unchanged_skipped"] == 3


def test_embed_all_keeps_original_order_while_batching_by_length():
    from rag.ingest.pipeline import embed_all

    class Echo:
        def embed(self, texts):
            assert len(texts) <= 32
            return [[float(len(t))] for t in texts]

    texts = ["x" * n for n in (50, 3, 700, 12, 1, 40) * 11]
    assert embed_all(Echo(), texts) == [[float(len(t))] for t in texts]


def test_embedding_failure_in_worker_thread_is_counted_and_run_continues(snap):
    root, entries = snap
    db = FakeDb()
    deps = db.deps()
    real_embed = deps.embedder.embed
    state = {"calls": 0}

    def flaky(texts):
        state["calls"] += 1
        if state["calls"] == 1:
            raise RuntimeError("model fell over")
        return real_embed(texts)

    deps.embedder.embed = flaky
    result, lines = run(db, root, deps=deps)
    assert result["counts"]["failed"] == 1 and result["counts"]["new"] == 3
    assert len(db.hashes) == 3
    assert len([line for line in lines if line.startswith("[ingest")]) == 4
