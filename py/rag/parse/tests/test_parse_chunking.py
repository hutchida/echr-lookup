import importlib.util
import os
import time
from pathlib import Path

import pytest

from rag.contract import contract_errors
from rag.parse import STRATEGIES, approx_count_tokens, chunk_paragraphs

HF_CACHE = Path(__file__).resolve().parents[5] / "g0b" / "data" / "raw" / "g0b" / "hf"


def para(n: int, words: int, section: str = "The Law", doc: str = "d-1") -> dict:
    text = " ".join(f"w{n}x{k}" for k in range(words))
    return {"id": f"{doc}§{n}", "doc_id": doc, "number": n, "section": section, "text": text}


def count(text: str) -> int:
    return len(text.split())


# --------------------------------------------------------------------------- unit tests -----


def test_strategies_constant():
    assert STRATEGIES == ("fixed", "recursive", "by_section")


def test_unknown_strategy_and_empty_input():
    with pytest.raises(ValueError):
        chunk_paragraphs([para(1, 3)], "nope")
    assert chunk_paragraphs([], "fixed") == []


def test_recursive_packs_whole_paragraphs():
    paras = [para(n, 40) for n in range(1, 8)]
    chunks = chunk_paragraphs(paras, "recursive", count_tokens=count, max_tokens=100)
    assert [c["paragraph_ids"] for c in chunks] == [
        ["d-1§1", "d-1§2"],
        ["d-1§3", "d-1§4"],
        ["d-1§5", "d-1§6"],
        ["d-1§7"],
    ]
    assert [c["id"] for c in chunks] == [f"d-1:recursive:{i}" for i in range(4)]
    assert chunks[0]["text"] == paras[0]["text"] + "\n" + paras[1]["text"]
    assert all(c["token_count"] <= 100 for c in chunks)


def test_recursive_splits_an_overlong_paragraph_on_sentences_then_tokens():
    sentences = " ".join(f"Sentence {k} has exactly six words." for k in range(10))
    long_para = {**para(1, 1), "text": sentences}  # 70 words
    chunks = chunk_paragraphs(
        [long_para, para(2, 5)], "recursive", count_tokens=count, max_tokens=20
    )
    assert len(chunks) >= 4
    assert all(c["token_count"] <= 20 for c in chunks)
    assert all(c["text"].split(" ")[0] == "Sentence" for c in chunks[:-1])  # cut at sentence starts
    assert chunks[-1]["paragraph_ids"] == ["d-1§2"]
    assert all(c["paragraph_ids"] == ["d-1§1"] for c in chunks[:-1])

    one_sentence = {**para(1, 1), "text": " ".join(f"tok{k}" for k in range(55))}  # no full stops
    chunks = chunk_paragraphs([one_sentence], "recursive", count_tokens=count, max_tokens=20)
    assert [c["token_count"] for c in chunks] == [20, 20, 15]
    assert " ".join(c["text"] for c in chunks) == one_sentence["text"]


def test_a_single_huge_word_is_still_split():
    """Counts characters / 10, so one 5000-character "word" is 500 tokens: over every limit."""

    def by_chars(text: str) -> int:
        return -(-len(text) // 10)

    p = {**para(1, 1), "text": "x" * 5000}
    for strategy, limit in (("fixed", 64), ("recursive", 64), ("by_section", 480)):
        chunks = chunk_paragraphs([p], strategy, count_tokens=by_chars, max_tokens=64)
        assert len(chunks) > 1, strategy
        assert all(c["token_count"] <= limit for c in chunks), strategy
        assert "".join(c["text"].replace(" ", "") for c in chunks).count("x") >= 5000


def test_fixed_window_and_overlap_ignore_paragraph_boundaries():
    paras = [para(n, 30) for n in range(1, 6)]  # 150 words
    chunks = chunk_paragraphs(paras, "fixed", count_tokens=count, max_tokens=64)
    assert all(c["token_count"] <= 64 for c in chunks)
    assert chunks[0]["token_count"] == 64
    # window 0 spans paragraphs 1-3 (words 0..63), so it touches all three
    assert chunks[0]["paragraph_ids"] == ["d-1§1", "d-1§2", "d-1§3"]
    # consecutive windows overlap by 32 words
    first, second = chunks[0]["text"].split(), chunks[1]["text"].split()
    assert first[-32:] == second[:32]
    # every word of the document appears in some chunk
    seen = {w for c in chunks for w in c["text"].split()}
    assert seen == {w for p in paras for w in p["text"].split()}
    # a window starting mid-paragraph lists that paragraph too
    assert chunks[1]["paragraph_ids"][0] == "d-1§2"


def test_fixed_default_overlap_is_32_tokens_at_256():
    paras = [para(n, 100) for n in range(1, 11)]
    chunks = chunk_paragraphs(paras, "fixed", count_tokens=count)
    assert chunks[0]["token_count"] == 256
    assert chunks[0]["text"].split()[-32:] == chunks[1]["text"].split()[:32]


def test_by_section_never_crosses_a_section_boundary():
    paras = (
        [para(n, 20, "Procedure") for n in range(1, 3)]
        + [para(n, 20, "The Facts") for n in range(3, 6)]
        + [para(n, 20, "The Law") for n in range(6, 9)]
    )
    chunks = chunk_paragraphs(paras, "by_section", count_tokens=count)
    sections = {p["id"]: p["section"] for p in paras}
    assert [c["paragraph_ids"] for c in chunks] == [
        ["d-1§1", "d-1§2"],
        ["d-1§3", "d-1§4", "d-1§5"],
        ["d-1§6", "d-1§7", "d-1§8"],
    ]
    assert [c["id"] for c in chunks] == [f"d-1:by_section:{i}" for i in range(3)]
    for c in chunks:
        assert len({sections[i] for i in c["paragraph_ids"]}) == 1


def test_by_section_limit_is_480():
    paras = [para(n, 100) for n in range(1, 13)]
    chunks = chunk_paragraphs(paras, "by_section", count_tokens=count, max_tokens=256)
    assert max(c["token_count"] for c in chunks) == 400
    assert all(c["token_count"] <= 480 for c in chunks)


def test_counter_with_special_tokens_is_respected():
    """A tokenizer-like counter charges 2 extra tokens per call (CLS/SEP)."""

    def counted(text: str) -> int:
        return len(text.split()) + 2

    paras = [para(n, 37) for n in range(1, 30)]
    for strategy, limit in (("fixed", 256), ("recursive", 256), ("by_section", 480)):
        chunks = chunk_paragraphs(paras, strategy, count_tokens=counted)
        assert all(c["token_count"] <= limit for c in chunks), strategy
        assert all(c["token_count"] == counted(c["text"]) for c in chunks)


def test_approximate_counter_is_monotone_and_conservative():
    assert approx_count_tokens("") == 0
    assert approx_count_tokens("Article 3 (art. 3)") >= 8  # 8 words + punctuation marks
    a, b = "The applicant complained.", "He was deported."
    assert approx_count_tokens(a + "\n" + b) <= approx_count_tokens(a) + approx_count_tokens(b)


def test_chunks_are_deterministic():
    paras = [para(n, 60) for n in range(1, 20)]
    for s in STRATEGIES:
        assert chunk_paragraphs(paras, s) == chunk_paragraphs(paras, s)


# ------------------------------------------------------------------------ snapshot tests -----

LIMITS = {"fixed": 256, "recursive": 256, "by_section": 480}


def _chunk_everything(parsed, counter=None):
    out = {}
    for item_id, doc in parsed.items():
        for s in STRATEGIES:
            out[(item_id, s)] = chunk_paragraphs(doc["paragraphs"], s, count_tokens=counter)
    return out


def test_snapshot_chunks_validate_and_respect_limits(parsed):
    chunks = _chunk_everything(parsed)
    for (item_id, strategy), cs in chunks.items():
        ids = {p["id"]: i for i, p in enumerate(parsed[item_id]["paragraphs"])}
        assert cs, (item_id, strategy)
        assert [c["id"] for c in cs] == [f"{item_id}:{strategy}:{i}" for i in range(len(cs))]
        for c in cs:
            assert contract_errors("Chunk", c) == [], c["id"]
            assert c["token_count"] <= LIMITS[strategy], c["id"]
            assert c["token_count"] == approx_count_tokens(c["text"])
            pos = [ids[i] for i in c["paragraph_ids"]]  # raises if a paragraph id is unknown
            assert pos == sorted(pos) and len(pos) == len(set(pos))


def test_snapshot_chunks_cover_every_paragraph(parsed):
    chunks = _chunk_everything(parsed)
    for (item_id, strategy), cs in chunks.items():
        covered = {i for c in cs for i in c["paragraph_ids"]}
        assert covered == {p["id"] for p in parsed[item_id]["paragraphs"]}, (item_id, strategy)


def test_snapshot_by_section_chunks_stay_inside_a_section(parsed):
    for doc in parsed.values():
        sections = {p["id"]: p["section"] for p in doc["paragraphs"]}
        for c in chunk_paragraphs(doc["paragraphs"], "by_section"):
            assert len({sections[i] for i in c["paragraph_ids"]}) == 1, c["id"]


def test_parse_and_chunk_whole_snapshot_within_budget(manifest, raw_files, capsys):
    from rag.parse import parse_document

    t0 = time.perf_counter()
    n = 0
    for e in manifest:
        paras = parse_document(e, raw_files[e["item_id"]])["paragraphs"]
        for s in STRATEGIES:
            n += len(chunk_paragraphs(paras, s))
    elapsed = time.perf_counter() - t0
    with capsys.disabled():
        print(
            f"\nparse + 3 chunkers, {len(manifest)} documents, approximate counter: "
            f"{elapsed:.2f}s, {n} chunks"
        )
    assert elapsed < 15


def test_soering_para_88_is_in_a_chunk_of_every_strategy(parsed):
    paras = parsed["001-57619"]["paragraphs"]
    for s in STRATEGIES:
        hits = [c for c in chunk_paragraphs(paras, s) if "001-57619§88" in c["paragraph_ids"]]
        assert hits, s
        assert any(
            "Article 3 (art. 3) makes no provision for exceptions" in c["text"] for c in hits
        )


# ------------------------------------------------------------------------------- ml ---------


def _bge_tokenizer():
    if importlib.util.find_spec("transformers") is None:
        pytest.skip("transformers not installed")
    from transformers import AutoTokenizer

    if HF_CACHE.exists():
        os.environ.setdefault("HF_HOME", str(HF_CACHE))
    try:
        return AutoTokenizer.from_pretrained("BAAI/bge-small-en-v1.5")
    except OSError:
        pytest.skip("bge-small tokenizer is not cached and cannot be downloaded")


@pytest.mark.ml
def test_no_chunk_exceeds_512_real_bge_tokens_and_time_budget(manifest, raw_files, capsys):
    from rag.parse import parse_document

    tok = _bge_tokenizer()

    def real(text: str) -> int:
        return len(tok.encode(text, add_special_tokens=True, truncation=False))

    t0 = time.perf_counter()
    worst = {s: 0 for s in STRATEGIES}
    for e in manifest:
        paras = parse_document(e, raw_files[e["item_id"]])["paragraphs"]
        for s in STRATEGIES:
            for c in chunk_paragraphs(paras, s, count_tokens=real):
                assert contract_errors("Chunk", c) == []
                n = real(c["text"])
                assert n == c["token_count"]
                worst[s] = max(worst[s], n)
                assert n <= 512, (c["id"], n)
    elapsed = time.perf_counter() - t0
    with capsys.disabled():
        print(
            f"\nreal bge-small tokenizer: parse + 3 chunkers in {elapsed:.1f}s; "
            f"largest chunk per strategy: {worst}"
        )
    assert elapsed < 45


@pytest.mark.ml
def test_approximate_counter_also_fits_the_real_tokenizer(parsed):
    """Chunks built with the cheap counter stay within 512 real tokens too."""
    tok = _bge_tokenizer()
    worst = 0
    for doc in parsed.values():
        for s in STRATEGIES:
            for c in chunk_paragraphs(doc["paragraphs"], s):
                worst = max(worst, len(tok.encode(c["text"], add_special_tokens=True)))
    assert worst <= 512, worst
