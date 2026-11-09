"""Retrieval and answer metrics. Pure functions, no I/O.

A search hit is a SearchResult hit dict; its `paragraph_ids` are the paragraphs to cite.
A hit is *relevant* if any of its paragraph_ids is in the item's expected paragraph ids.
"""

from collections.abc import Iterable, Sequence


def covered_ids(hits: Sequence[dict], k: int) -> set[str]:
    return {pid for hit in hits[:k] for pid in hit["paragraph_ids"]}


def recall_at_k(hits: Sequence[dict], expected: Iterable[str], k: int) -> float | None:
    """Share of the expected paragraphs found in the paragraph_ids of the top-k hits.
    None when the item has no expected paragraphs."""
    expected = set(expected)
    if not expected:
        return None
    return len(expected & covered_ids(hits, k)) / len(expected)


def reciprocal_rank(hits: Sequence[dict], expected: Iterable[str], k: int = 10) -> float | None:
    """1 / rank of the first relevant hit within the top k, 0 if none. None without expectations."""
    expected = set(expected)
    if not expected:
        return None
    for rank, hit in enumerate(hits[:k], start=1):
        if expected & set(hit["paragraph_ids"]):
            return 1 / rank
    return 0.0


def doc_hit_at_k(hits: Sequence[dict], expected: Iterable[str], k: int) -> float | None:
    """1.0 if any top-k hit comes from a document that holds an expected paragraph (right case,
    maybe wrong paragraph), else 0.0. Looser than recall@k; not part of the EvalRun contract."""
    docs = {pid.split("§")[0] for pid in expected}
    if not docs:
        return None
    found = {pid.split("§")[0] for hit in hits[:k] for pid in hit["paragraph_ids"]}
    return 1.0 if docs & found else 0.0


def retrieved_paragraph_ids(hits: Sequence[dict], limit: int = 10) -> list[str]:
    """Paragraph ids of the top hits, best first, de-duplicated, at most `limit`."""
    out: list[str] = []
    for hit in hits[:limit]:
        for pid in hit["paragraph_ids"]:
            if pid not in out:
                out.append(pid)
    return out[:limit]


def mean(values: Iterable[float | None]) -> float | None:
    vals = [v for v in values if v is not None]
    return sum(vals) / len(vals) if vals else None


def stat_correct(answer: dict, expected: int) -> bool:
    """The stats route was taken and its count equals the expected value."""
    stats = answer.get("stats")
    return answer.get("route") == "stats" and stats is not None and stats["count"] == expected
