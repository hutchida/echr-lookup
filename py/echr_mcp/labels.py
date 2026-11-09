"""`para_label`: the readable name of a paragraph ('§79', 'Law, para 2'). Display only: the stable
key stays `paragraph_id`, and nothing here changes it.

Rules (see docs/learn/mcp.md):
- A numbered paragraph is '§<number>'.
- An unnumbered paragraph of a judgment, decision or communicated case is '<Section>, para <n>':
  the section is the stored one without 'The ' ('Facts', 'Law', 'Procedure', 'Operative
  provisions', 'Other'); n counts the unnumbered paragraphs of that section in document order.
- A legal summary has no numbers, and the stored section is mostly 'Other', so its sections come
  from the text: everything before a paragraph starting 'Facts' is 'Summary', then 'Facts', then
  'Law' from the paragraph starting 'Law'; footnotes '[1] …' form 'Notes'. n counts every paragraph
  of that part.
- Legislation reads from the id: 'art8' -> 'Article 8', 's3A' -> 'section 3A', 'p1-art1' ->
  'Protocol 1, Article 1', 'preamble' -> 'Preamble'.
"""

from __future__ import annotations

import re
from collections.abc import Iterable

SECTION_NAMES = {"The Facts": "Facts", "The Law": "Law"}
_SUMMARY_FACTS = re.compile(r"Facts\b")
_SUMMARY_LAW = re.compile(r"Law\b")
_SUMMARY_NOTE = re.compile(r"\[\d+\]")
_LEGISLATION_PART = re.compile(r"(sch|part|para|art|p|s)(\d+[A-Za-z]*)", re.IGNORECASE)
_LEGISLATION_NAMES = {
    "sch": "Schedule",
    "part": "Part",
    "para": "paragraph",
    "art": "Article",
    "p": "Protocol",
    "s": "section",
}

ParagraphRow = tuple[str, int | None, str, str]  # id, number, section, text (start is enough)


def legislation_label(paragraph_id: str) -> str:
    ref = paragraph_id.partition("§")[2]
    if ref.lower() == "preamble":
        return "Preamble"
    parts = ref.split("-")
    matches = [_LEGISLATION_PART.fullmatch(p) for p in parts]
    if not ref or not all(matches):
        return f"§{ref}" if ref else paragraph_id
    return ", ".join(f"{_LEGISLATION_NAMES[m.group(1).lower()]} {m.group(2)}" for m in matches if m)


def _summary_part(current: str, text: str) -> str:
    head = text.lstrip()
    if current == "Summary" and _SUMMARY_FACTS.match(head):
        return "Facts"
    if current in ("Summary", "Facts") and _SUMMARY_LAW.match(head):
        return "Law"
    if current != "Summary" and _SUMMARY_NOTE.match(head):
        return "Notes"
    return current


def unnumbered_labels(doc_type: str, paragraphs: Iterable[ParagraphRow]) -> dict[str, str]:
    """paragraph id -> label for the unnumbered paragraphs among `paragraphs` (a whole document's
    rows, or at least all its unnumbered rows, in document order)."""
    labels: dict[str, str] = {}
    counts: dict[str, int] = {}
    part = "Summary"
    for pid, number, section, text in paragraphs:
        if number is not None:
            continue
        if doc_type == "legislation":
            labels[pid] = legislation_label(pid)
            continue
        if doc_type == "legal_summary":
            part = _summary_part(part, text)
            name = part
        else:
            name = SECTION_NAMES.get(section, section)
        counts[name] = counts.get(name, 0) + 1
        labels[pid] = f"{name}, para {counts[name]}"
    return labels


def para_label(paragraph_id: str, number: int | None, labels: dict[str, str]) -> str:
    """'§79' for a numbered paragraph, else its entry in `labels` (from `unnumbered_labels`)."""
    if number is not None:
        return f"§{number}"
    return labels.get(paragraph_id) or f"§{paragraph_id.partition('§')[2]}"


def load_unnumbered_labels(conn, doc_ids: Iterable[str], data_source: str) -> dict[str, str]:
    """`unnumbered_labels` for each of `doc_ids`, read from the database."""
    ids = sorted(set(doc_ids))
    if not ids:
        return {}
    rows = conn.execute(
        """
        SELECT p.doc_id, d.doc_type, p.id, p.section, left(p.text, 40)
        FROM paragraphs p JOIN documents d ON d.item_id = p.doc_id
        WHERE p.doc_id = ANY(%s) AND d.data_source = %s AND p.number IS NULL
        ORDER BY p.doc_id, p.position
        """,
        (ids, data_source),
    ).fetchall()
    labels: dict[str, str] = {}
    for doc_id in ids:
        mine = [r for r in rows if r[0] == doc_id]
        if mine:
            labels.update(unnumbered_labels(mine[0][1], [(r[2], None, r[3], r[4]) for r in mine]))
    return labels
