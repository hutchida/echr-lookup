"""`check_quote` as specified in docs/interfaces-mcp.md section 2 (deterministic, no model).

The real implementation is the server's (`echr_mcp.tools.check_quote`); `server_checker` uses it
once M1 is merged. `local_checker` is the same rule, written from the spec, so the harness and its
tests work before that and offline. A test (skipped until M1 is merged) checks they agree.
"""

import difflib
import re
import unicodedata
from collections.abc import Callable

from rag.answer.citations import _sentence_spans

Checker = Callable[[str, str], dict]
"""(paragraph_id, quote) -> {paragraph_found, verbatim, similarity, closest_match}"""

_DASHES = dict.fromkeys(map(ord, "–—‑"), "-")
_QUOTES = {ord(c): "'" for c in "‘’‚′"} | {ord(c): '"' for c in "“”„″"}
_ELLIPSIS = re.compile(r"\[\s*(?:…|\.\.\.)\s*\]|…|\.\.\.")


def normalise(text: str) -> str:
    text = unicodedata.normalize("NFKC", text).translate(_QUOTES).translate(_DASHES)
    return re.sub(r"\s+", " ", text).strip()


def quote_in_text(paragraph_text: str | None, quote: str, *, ignore_case: bool = False) -> bool:
    """The spec's `verbatim` rule alone (no similarity); `ignore_case` forgives "Even"/"even"."""
    if paragraph_text is None:
        return False
    fold = str.lower if ignore_case else str
    para = fold(normalise(paragraph_text))
    segments = [fold(normalise(s)) for s in _ELLIPSIS.split(quote)]
    position, found_any = 0, False
    for segment in segments:
        if not segment:
            continue
        found = para.find(segment, position)
        if found < 0:
            return False
        position, found_any = found + len(segment), True
    return found_any


def nested_variant(quote: str) -> str:
    """Nested single quotation marks turned back into double ones ('in accordance with the law'
    for the Court's "in accordance with the law")."""
    return re.sub(r"(?<![\w])'([^']+?)'(?![\w])", r'"\1"', quote)


def quote_in_any(texts, quote: str, *, ignore_case: bool = False) -> bool:
    """Is the quote verbatim (also in its nested-quotes variant) in any of the paragraph texts?"""
    variants = {quote, nested_variant(quote)}
    return any(quote_in_text(t, v, ignore_case=ignore_case) for t in texts for v in variants)


def check_text(paragraph_text: str | None, quote: str) -> dict:
    if paragraph_text is None:
        return {
            "paragraph_found": False,
            "verbatim": False,
            "similarity": 0.0,
            "closest_match": None,
        }
    para = normalise(paragraph_text)
    segments = [normalise(s) for s in _ELLIPSIS.split(quote)]
    segments = [s for s in segments if s]
    position, verbatim = 0, bool(segments)
    for segment in segments:
        found = para.find(segment, position)
        if found < 0:
            verbatim = False
            break
        position = found + len(segment)
    spans = _sentence_spans(paragraph_text)
    wanted = normalise(quote)
    best_ratio, best_text = 0.0, None
    for i in range(len(spans)):
        for j in range(i, min(i + 3, len(spans))):
            window = paragraph_text[spans[i][0] : spans[j][1]]
            ratio = difflib.SequenceMatcher(None, wanted, normalise(window), autojunk=False).ratio()
            if ratio > best_ratio:
                best_ratio, best_text = ratio, window
    return {
        "paragraph_found": True,
        "verbatim": verbatim,
        "similarity": 1.0 if verbatim else round(best_ratio, 4),
        "closest_match": best_text[:600] if best_text else None,
    }


def local_checker(text_lookup: Callable[[str], str | None]) -> Checker:
    return lambda pid, quote: check_text(text_lookup(pid), quote)


def server_checker(conn) -> Checker:
    """The server's own check_quote, called in-process (same code the MCP tool runs)."""
    from echr_mcp.tools import check_quote  # type: ignore[import-not-found]

    def check(pid: str, quote: str) -> dict:
        return check_quote(conn, {"paragraph_id": pid, "quote": quote[:2000]})

    return check
