"""G0b throwaway chunkers. Gate 1 task S2 writes the real ones.

Each returns a list of {"text", "paragraph_ids", "token_count"}; token counts use the embedder's own
tokenizer so chunk sizes are comparable across models.
"""

from __future__ import annotations

import re

MAX_TOKENS = 256  # fixed / recursive target
SECTION_MAX_TOKENS = 480  # by_section cap (bge max sequence length is 512)


def _ntok(tok, text: str) -> int:
    return len(tok.encode(text, add_special_tokens=False))


def chunk_fixed(paras: list[dict], tok, size: int = MAX_TOKENS, overlap: int = 32) -> list[dict]:
    """Sliding window over the whole document's token stream; ignores paragraph boundaries."""
    ids: list[int] = []
    owner: list[int] = []  # token -> paragraph index
    for pi, p in enumerate(paras):
        t = tok.encode(p["text"] + "\n", add_special_tokens=False)
        ids += t
        owner += [pi] * len(t)
    out, start = [], 0
    while start < len(ids):
        end = min(start + size, len(ids))
        pis = sorted(set(owner[start:end]))
        out.append(
            {
                "text": tok.decode(ids[start:end]),
                "paragraph_ids": [paras[i]["ref"] for i in pis],
                "token_count": end - start,
            }
        )
        if end == len(ids):
            break
        start = end - overlap
    return out


def _split_sentences(text: str) -> list[str]:
    return [s for s in re.split(r"(?<=[.;:])\s+(?=[A-Z“\"(])", text) if s]


def chunk_recursive(paras: list[dict], tok, size: int = MAX_TOKENS) -> list[dict]:
    """Paragraph-first: pack whole paragraphs up to `size` tokens; a paragraph longer than `size`
    is split on sentences, then on tokens as a last resort."""
    out: list[dict] = []
    cur: list[tuple[str, str, int]] = []  # (ref, text, ntok)
    cur_n = 0

    def flush() -> None:
        nonlocal cur, cur_n
        if cur:
            out.append(
                {
                    "text": "\n".join(t for _, t, _ in cur),
                    "paragraph_ids": list(dict.fromkeys(r for r, _, _ in cur)),
                    "token_count": cur_n,
                }
            )
        cur, cur_n = [], 0

    for p in paras:
        n = _ntok(tok, p["text"])
        if n > size:
            flush()
            for piece in _pieces(p["text"], tok, size):
                pn = _ntok(tok, piece)
                if cur_n + pn > size:
                    flush()
                cur.append((p["ref"], piece, pn))
                cur_n += pn
            flush()
            continue
        if cur_n + n > size:
            flush()
        cur.append((p["ref"], p["text"], n))
        cur_n += n
    flush()
    return out


def _pieces(text: str, tok, size: int) -> list[str]:
    pieces, buf, bn = [], [], 0
    for s in _split_sentences(text):
        n = _ntok(tok, s)
        if n > size:  # pathological sentence: hard split by tokens
            ids = tok.encode(s, add_special_tokens=False)
            for i in range(0, len(ids), size):
                pieces.append(tok.decode(ids[i : i + size]))
            continue
        if bn + n > size and buf:
            pieces.append(" ".join(buf))
            buf, bn = [], 0
        buf.append(s)
        bn += n
    if buf:
        pieces.append(" ".join(buf))
    return pieces


def chunk_by_section(paras: list[dict], tok, cap: int = SECTION_MAX_TOKENS) -> list[dict]:
    """One chunk per section (Procedure / The Facts / The Law / ...), split on paragraph boundaries
    only when a section exceeds `cap` tokens. Never crosses a section boundary."""
    out: list[dict] = []
    by_sec: list[tuple[str, list[dict]]] = []
    for p in paras:
        if by_sec and by_sec[-1][0] == p["section"]:
            by_sec[-1][1].append(p)
        else:
            by_sec.append((p["section"], [p]))
    for _, ps in by_sec:
        out += chunk_recursive(ps, tok, size=cap)
    return out


STRATEGIES = {"fixed": chunk_fixed, "recursive": chunk_recursive, "by_section": chunk_by_section}
