"""HUDOC HTML (judgments, decisions, legal summaries) -> citable paragraphs."""

from __future__ import annotations

import re
from dataclasses import dataclass

from lxml import html as lhtml

# Paragraph numbers are plain text at the start of a block; some old documents omit the full stop.
NUM = re.compile(
    r"^\s*(\d{1,3})(?:(\.)[\s\u00a0]+(?=[A-Z0-9“\"(‘'\[])|[\s\u00a0]+(?=[A-Z“\"(‘']))(.*)$", re.S
)
# Enumerated items inside "For these reasons": "1. Holds ...", "(a) that ...".
OP_MARK = re.compile(r"^\s*(?:\d{1,2}\.|\([a-z0-9]{1,3}\))\s+")
ROMAN = re.compile(r"^(?:[IVX]+\.\s*|[A-Z]\.\s*|\d+\.\s*)+")
FOR_THESE_REASONS = re.compile(r"^(For these reasons|On these grounds)\b", re.I)
DONE = re.compile(r"^Done in (English|French)", re.I)
MAX_GAP = 10  # numbering may skip (HUDOC sometimes loses the numbers of a few paragraphs)
MIN_ORPHAN = 60  # an unnumbered block between numbered paragraphs is kept only if it is prose
NAMES_ONLY = re.compile(r"^(?:[A-ZÀ-Þ][\w.\-’']*\s?)+$")
SIGNATURE = re.compile(r"(Registrar|President)\s*$")
# Separate opinions, declarations and appendices: restart numbering, always cited as §u<n>.
EXTRA_HEADING = re.compile(
    r"^(JOINT |PARTLY |PARTIALLY )*(CONCURRING |DISSENTING |SEPARATE |CONCURRING AND DISSENTING )*"
    r"(OPINION|DECLARATION)\b|^(JOINT )?(PARTLY )?(CONCURRING|DISSENTING) OPINION|^APPENDIX|^ANNEX"
    r"|^SEPARATE OPINION"
)

SECTION_PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("Operative provisions", re.compile(r"^FOR THESE REASONS|^ON THESE GROUNDS")),
    (
        "Procedure",
        re.compile(r"^(THE )?PROCEDURE\b|^INTRODUCTION\b|^COMPLAINTS?\b|^THE COMPLAINTS?\b"),
    ),
    ("The Facts", re.compile(r"^(AS TO )?THE FACTS\b|^THE CIRCUMSTANCES OF THE CASE|^FACTS\b")),
    ("The Law", re.compile(r"^(AS TO )?THE LAW\b")),
]


def classify_heading(text: str) -> str | None:
    t = re.sub(r"\s+", " ", text).strip().upper()
    t = ROMAN.sub("", t)
    for label, pat in SECTION_PATTERNS:
        if pat.search(t):
            return label
    return None


def is_extra_heading(text: str) -> bool:
    t = re.sub(r"\s+", " ", text).strip()
    return len(t) < 160 and t == t.upper() and bool(EXTRA_HEADING.search(ROMAN.sub("", t)))


def _is_names_only(text: str) -> bool:
    return len(text) < 60 and text != text.upper() and NAMES_ONLY.match(text) is not None


def _is_subheading(text: str) -> bool:
    if len(text) >= 100 or text.endswith((".", ";", ":", ",")):
        return False
    return not re.match(r"^[–\-•*]\s", text)


def _clean(el) -> str:
    for br in el.iter("br"):
        br.tail = " " + (br.tail or "")
    return re.sub(r"\s+", " ", el.text_content().replace("\u00a0", " ")).strip()


@dataclass
class Block:
    text: str
    is_item: bool = False  # an <li> of a numbered/lettered list (no number in the text)


def blocks(raw: str) -> list[Block]:
    """All non-empty <p>/<li> texts in document order (also the input of ground extraction)."""
    tree = lhtml.fromstring(raw)
    out: list[Block] = []
    for el in tree.iter("p", "li"):
        if el.tag == "li" and el.find(".//p") is not None:
            continue
        text = _clean(el)
        if text:
            out.append(Block(text, el.tag == "li"))
    return out


@dataclass
class _Para:
    ref: str
    number: int | None
    section: str
    text: str


class _Builder:
    def __init__(self) -> None:
        self.paras: list[_Para] = []
        self.cur: _Para | None = None  # paragraph that unnumbered blocks continue
        self.n_ops = 0
        self.n_unnumbered = 0

    def numbered(self, number: int, section: str, text: str) -> None:
        self.cur = _Para(str(number), number, section, text)
        self.paras.append(self.cur)

    def op(self, section: str, text: str) -> None:
        self.n_ops += 1
        self.cur = _Para(f"op{self.n_ops}", None, section, text)
        self.paras.append(self.cur)

    def unnumbered(self, section: str, text: str) -> None:
        self.n_unnumbered += 1
        self.cur = _Para(f"u{self.n_unnumbered}", None, section, text)
        self.paras.append(self.cur)

    def extend(self, text: str) -> None:
        assert self.cur is not None
        self.cur.text += "\n" + text


def _split_glued(body: str, last: int) -> tuple[list[tuple[int, str]], int, str]:
    """Old documents glue paragraph N+1 onto the end of N: split on the strictly-next number."""
    done: list[tuple[int, str]] = []
    while True:
        g = re.search(rf"(?<=[.;:?!”\"’)]) {last + 1}\.?\s+(?=[A-Z“\"(])", body)
        if not g:
            return done, last, body
        done.append((last, body[: g.start()].strip()))
        body, last = body[g.end() :].strip(), last + 1


def _next_number(n: int, has_dot: bool, last: int, later: dict[int, int], i: int) -> bool:
    """Is block `i` (starting with number n) paragraph n? Normally n == last + 1 (the full stop may
    be missing in old documents). HUDOC sometimes loses the numbers of a few paragraphs, so a skip
    of up to MAX_GAP is accepted too, but only with a full stop ("75 Council of Europe states" is
    not paragraph 75) and only if no later block is numbered last + 1: a judgment quoted inside a
    paragraph keeps its own numbers ("74. It would be quite wrong ...")."""
    if n == last + 1:
        return True
    return has_dot and last < n <= last + MAX_GAP and later.get(last + 1, -1) <= i


def _walk(bs: list[Block], numbered: bool) -> list[_Para]:
    """One pass over the blocks. `numbered` selects how the main text is cited (§n or §u<n>)."""
    b = _Builder()
    section = "Procedure"
    started = False  # skip the cover page until the first heading
    state = "main"  # main | signatures | extra
    last = 0
    last_at: dict[int, int] = {}  # number -> index of the last block starting with it
    for k, blk in enumerate(bs):
        if (m := NUM.match(blk.text)) and m.group(2):
            last_at[int(m.group(1))] = k
    for i, blk in enumerate(bs):
        text = blk.text
        short_upper = len(text) < 90 and (
            text == text.upper() or bool(FOR_THESE_REASONS.match(text))
        )

        if state != "extra":
            if is_extra_heading(text):
                state, section = "extra", "Other"
                b.unnumbered(section, text)
                continue
            if DONE.match(text):
                state, section, b.cur = "signatures", "Other", None
                continue
            if state == "signatures":
                continue
            if short_upper and (label := classify_heading(text)):
                section, b.cur, started = label, None, True
                continue
            if section == "Operative provisions" and SIGNATURE.search(text) and len(text) < 150:
                state, section, b.cur = "signatures", "Other", None
                continue
        else:
            if SIGNATURE.search(text) and len(text) < 60:
                continue
            b.unnumbered("Other", text)
            continue

        if section == "Operative provisions":
            if (
                b.cur is not None and _is_names_only(text) and not blk.is_item
            ):  # "S. Dollé J.-P. Costa"
                state, section, b.cur = "signatures", "Other", None
            elif b.cur is None or b.cur.section != section or blk.is_item or OP_MARK.match(text):
                b.op(section, OP_MARK.sub("", text, count=1) if not blk.is_item else text)
            else:
                b.extend(text)
            continue

        if numbered:
            m = NUM.match(text)
            if (
                m
                and (started or (last == 0 and m.group(1) == "1"))
                and _next_number(int(m.group(1)), bool(m.group(2)), last, last_at, i)
            ):
                started = True
                last = int(m.group(1))
                glued, last, body = _split_glued(m.group(3).strip(), last)
                for n, t in glued:
                    b.numbered(n, section, t)
                b.numbered(last, section, body)
            elif b.cur is not None and b.cur.number is not None:
                if _is_subheading(text):
                    b.cur = None
                else:
                    b.extend(text)
            elif started and len(text) >= MIN_ORPHAN and not _is_subheading(text):
                b.unnumbered(section, text)
        elif started and not _is_subheading(text):
            b.unnumbered(section, text)
    return b.paras


def _is_real_numbering(bs: list[Block], paras: list[_Para]) -> bool:
    """Some unnumbered decisions have numbered sub-headings ("1. The applicant's submissions"); a
    handful of "paragraphs" that cover under 60% of the text is that, not real numbering."""
    nums = [p for p in paras if p.number is not None]
    if not nums:
        return False
    total = sum(len(b.text) for b in bs)
    return len(nums) >= 10 or sum(len(p.text) for p in nums) >= 0.6 * total


_SUMMARY_DROP = re.compile(r"^(Click here|©|Information Note on the Court)")


def _parse_summary(bs: list[Block]) -> list[_Para]:
    """Legal summaries (Case-Law Information Notes): short, unnumbered, cited as §u<n>."""
    b = _Builder()
    section = "Other"
    for blk in bs:
        t = blk.text
        if _SUMMARY_DROP.match(t) or (
            len(t) < 25 and not t.startswith(("Conclusion", "Law", "Facts"))
        ):
            continue
        if t.startswith("Facts:"):
            section = "The Facts"
        elif t.startswith("Law:"):
            section = "The Law"
        b.unnumbered(section, t)
    return b.paras


def parse_blocks(bs: list[Block], doc_type: str) -> list[_Para]:
    if doc_type == "legal_summary":
        return _parse_summary(bs)
    paras = _walk(bs, numbered=True)
    if _is_real_numbering(bs, paras):
        return paras
    return _walk(bs, numbered=False)
