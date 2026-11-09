"""Three chunking strategies. Every chunk records the paragraphs it contains (citations)."""

from __future__ import annotations

import re
from collections.abc import Callable

from .tokens import approx_count_tokens

STRATEGIES: tuple[str, ...] = ("fixed", "recursive", "by_section")

FIXED_OVERLAP = 32
BY_SECTION_MAX_TOKENS = 480  # bge-small reads at most 512 tokens

_SENTENCE = re.compile(r"(?<=[.;:?!])\s+(?=[A-Z“\"(‘'])")


class _Counter:
    """Memoised count_tokens. `base` is what the counter charges for empty text (special tokens),
    so per-word counts can be added up without paying it for every word."""

    def __init__(self, count_tokens: Callable[[str], int]) -> None:
        self._count = count_tokens
        self._cache: dict[str, int] = {}
        self.base = count_tokens("")

    def __call__(self, text: str) -> int:
        n = self._cache.get(text)
        if n is None:
            n = self._cache[text] = self._count(text)
        return n

    def word(self, word: str) -> int:
        return max(1, self(word) - self.base)


def _shrink_word(word: str, budget: int, count: _Counter) -> list[str]:
    """A single word longer than the budget (a URL, say): halve it until each part fits."""
    if count.word(word) <= budget or len(word) < 2:
        return [word]
    mid = len(word) // 2
    return _shrink_word(word[:mid], budget, count) + _shrink_word(word[mid:], budget, count)


def _make_chunk(doc_id: str, strategy: str, index: int, text: str, ids: list[str], n: int) -> dict:
    return {
        "id": f"{doc_id}:{strategy}:{index}",
        "doc_id": doc_id,
        "strategy": strategy,
        "text": text,
        "paragraph_ids": list(dict.fromkeys(ids)),
        "token_count": n,
    }


# ------------------------------------------------------------------------------ fixed ---------


def _chunk_fixed(paras: list[dict], max_tokens: int, count: _Counter) -> list[dict]:
    """Sliding window over the whole document's word stream, ignoring paragraph boundaries."""
    budget = max(1, max_tokens - count.base)
    words: list[str] = []
    owner: list[int] = []  # word -> paragraph index
    newline: list[bool] = []  # word starts a paragraph (joined to the previous word by "\n")
    for pi, p in enumerate(paras):
        for k, w in enumerate(p["text"].split()):
            for m, piece in enumerate(_shrink_word(w, budget, count)):
                words.append(piece)
                owner.append(pi)
                newline.append(k == 0 and m == 0 and pi > 0)
    sizes = [count.word(w) for w in words]

    def join(i: int, j: int) -> str:
        return "".join(
            (("\n" if newline[k] else " ") if k > i else "") + words[k] for k in range(i, j)
        )

    out: list[dict] = []
    n, i = len(words), 0
    doc_id = paras[0]["doc_id"]
    while i < n:
        j, total = i, 0
        while j < n and total + sizes[j] <= budget:
            total += sizes[j]
            j += 1
        j = max(j, i + 1)
        text = join(i, j)
        tokens = count(text)
        while tokens > max_tokens and j > i + 1:  # a counter that is not additive: trim the tail
            j -= 1
            text = join(i, j)
            tokens = count(text)
        ids = [paras[owner[k]]["id"] for k in range(i, j)]
        out.append(_make_chunk(doc_id, "fixed", len(out), text, ids, tokens))
        if j >= n:
            break
        k, overlap = j, 0
        while k > i + 1 and overlap + sizes[k - 1] <= FIXED_OVERLAP:
            k -= 1
            overlap += sizes[k]
        i = k
    return out


# -------------------------------------------------------------------------- recursive --------


def _pieces(text: str, limit: int, count: _Counter) -> list[tuple[str, int]]:
    """An over-long paragraph -> pieces that each fit: sentences first, then words."""
    out: list[tuple[str, int]] = []
    buf: list[str] = []
    buf_n = 0

    def flush() -> None:
        nonlocal buf, buf_n
        if buf:
            out.append((" ".join(buf), buf_n))
        buf, buf_n = [], 0

    budget = max(1, limit - count.base)
    for sentence in _SENTENCE.split(text):
        n = count(sentence)
        if n > limit:
            flush()
            w_buf: list[str] = []
            w_n = 0
            for w in (x for word in sentence.split() for x in _shrink_word(word, budget, count)):
                wn = count.word(w)
                if w_n + wn > budget and w_buf:
                    out.append((" ".join(w_buf), w_n + count.base))
                    w_buf, w_n = [], 0
                w_buf.append(w)
                w_n += wn
            if w_buf:
                buf, buf_n = [" ".join(w_buf)], w_n + count.base
            continue
        if buf_n + n > limit:
            flush()
        buf.append(sentence)
        buf_n += n
    flush()
    return out


def _chunk_recursive(
    paras: list[dict], limit: int, count: _Counter, strategy: str, start_index: int = 0
) -> list[dict]:
    """Pack whole paragraphs up to `limit`; split an over-long one on sentences, then words."""
    out: list[dict] = []
    parts: list[tuple[str, str]] = []  # (separator, text)
    ids: list[str] = []
    total = 0
    doc_id = paras[0]["doc_id"]

    def flush() -> None:
        nonlocal parts, ids, total
        if parts:
            text = "".join((sep if k else "") + t for k, (sep, t) in enumerate(parts))
            index = start_index + len(out)
            out.append(_make_chunk(doc_id, strategy, index, text, ids, count(text)))
        parts, ids, total = [], [], 0

    for p in paras:
        n = count(p["text"])
        if n <= limit:
            if total + n > limit:
                flush()
            parts.append(("\n", p["text"]))
            ids.append(p["id"])
            total += n
            continue
        flush()
        for piece, pn in _pieces(p["text"], limit, count):
            if total + pn > limit:
                flush()
            parts.append((" ", piece))
            ids.append(p["id"])
            total += pn
        flush()
    flush()
    return out


def _chunk_by_section(paras: list[dict], count: _Counter) -> list[dict]:
    """Like recursive, but each section is chunked on its own, so a chunk never crosses one."""
    out: list[dict] = []
    group: list[dict] = []
    for p in paras:
        if group and group[-1]["section"] != p["section"]:
            out += _chunk_recursive(group, BY_SECTION_MAX_TOKENS, count, "by_section", len(out))
            group = []
        group.append(p)
    if group:
        out += _chunk_recursive(group, BY_SECTION_MAX_TOKENS, count, "by_section", len(out))
    return out


def chunk_paragraphs(
    paragraphs: list[dict],
    strategy: str,
    *,
    count_tokens: Callable[[str], int] | None = None,
    max_tokens: int = 256,
) -> list[dict]:
    """Paragraph dicts (document order) -> Chunk dicts.

    ids are `<doc>:<strategy>:<index>`; `paragraph_ids` is non-empty and in document order.
    `max_tokens` is the limit for `fixed` and `recursive`; `by_section` has its own limit of 480.
    """
    if strategy not in STRATEGIES:
        raise ValueError(f"unknown chunking strategy {strategy!r}; use one of {STRATEGIES}")
    if not paragraphs:
        return []
    count = _Counter(count_tokens or approx_count_tokens)
    if strategy == "fixed":
        return _chunk_fixed(paragraphs, max_tokens, count)
    if strategy == "recursive":
        return _chunk_recursive(paragraphs, max_tokens, count, "recursive")
    return _chunk_by_section(paragraphs, count)
