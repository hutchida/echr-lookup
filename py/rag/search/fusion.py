"""Reciprocal Rank Fusion (Cormack et al. 2009): score(d) = sum over lists of 1 / (k + rank(d))."""

RRF_K = 60


def rrf(rankings: list[list[str]], k: int = RRF_K) -> list[tuple[str, float]]:
    """`rankings` = best-first id lists. Returns (id, score) best-first. An id missing from a list
    gets nothing from it. Ties break on the best rank any list gave the id, then on id."""
    scores: dict[str, float] = {}
    best: dict[str, int] = {}
    for ranking in rankings:
        for rank, item in enumerate(ranking, start=1):
            scores[item] = scores.get(item, 0.0) + 1.0 / (k + rank)
            best[item] = min(best.get(item, rank), rank)
    return sorted(scores.items(), key=lambda kv: (-kv[1], best[kv[0]], kv[0]))
