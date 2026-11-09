"""HUDOC HTML, Convention text and HRA XML -> citable paragraphs; three chunkers. Owner: S2."""

from __future__ import annotations

from . import hudoc, legislation
from .chunking import STRATEGIES, chunk_paragraphs
from .grounds import extract_grounds, merge_grounds
from .tokens import approx_count_tokens

__all__ = ["STRATEGIES", "approx_count_tokens", "chunk_paragraphs", "parse_document"]

_DOCUMENT_FIELDS = (
    "item_id",
    "case_name",
    "application_numbers",
    "ecli",
    "doc_type",
    "chamber",
    "date",
    "articles",
    "outcome_raw",
    "outcome",
    "inadmissibility_grounds",
    "inadmissibility_grounds_source",
    "importance",
    "language",
    "source_url",
    "sha256",
    "data_source",
)
_INADMISSIBLE = ("inadmissible", "partly_inadmissible")


def _paragraph(doc_id: str, p) -> dict:
    ref, number, section, text = (
        (p.ref, p.number, p.section, p.text)
        if hasattr(p, "ref")
        else (p["ref"], p["number"], p["section"], p["text"])
    )
    return {
        "id": f"{doc_id}§{ref}",
        "doc_id": doc_id,
        "number": number,
        "section": section,
        "text": text,
    }


def parse_document(entry: dict, raw: bytes) -> dict:
    """ManifestEntry-shaped metadata + stored file bytes -> {"document", "paragraphs"}."""
    doc_id = entry["item_id"]
    document = {k: entry.get(k) for k in _DOCUMENT_FIELDS}
    fmt = entry.get("format")
    if fmt == "html":
        blocks = hudoc.blocks(raw.decode("utf-8", errors="replace"))
        raw_paras = hudoc.parse_blocks(blocks, entry["doc_type"])
        if entry["doc_type"] == "decision" and entry["outcome"] in _INADMISSIBLE:
            stated = list(entry.get("inadmissibility_grounds") or [])
            found = [g for g, _ in extract_grounds([b.text for b in blocks])]
            merged = merge_grounds(stated, found)
            if merged and set(merged) != set(stated):
                document["inadmissibility_grounds"] = merged
                document["inadmissibility_grounds_source"] = "text"
    elif fmt == "txt":
        raw_paras = legislation.parse_convention(raw.decode("utf-8", errors="replace"), doc_id)
    elif fmt == "xml":
        raw_paras = legislation.parse_hra(raw)
    else:
        raise ValueError(f"cannot parse format {fmt!r} of {doc_id}")
    return {"document": document, "paragraphs": [_paragraph(doc_id, p) for p in raw_paras]}
