"""G0b throwaway parse prototypes: DOCX (style-driven) and HTML (text heuristics) -> paragraphs.

Gate 1 task S2 writes the real parser; this exists to (1) pick the storage format and (2) time it.
"""

from __future__ import annotations

import re
from pathlib import Path

from docx import Document
from lxml import html as lhtml

NUM = re.compile(
    r"^\s*(\d{1,3})\.?[\s\u00a0]+(?=[A-Z“\"(])(.*)$", re.S
)  # some old documents omit the full stop
HEAD_STYLE = re.compile(r"^(Ju_H_|ECHR_Heading|ECHR_Title|Dec_H_|Opi_H_|Ju_Title|ECHR_Cover)")
PARA_STYLE = re.compile(
    r"^(Ju_Para$|ECHR_Para$|jupara$|Ju_Para Char|Ju_Para_Last$|ECHR_Para_Last$)", re.I
)
ROMAN = re.compile(r"^(?:[IVX]+\.\s*|[A-Z]\.\s*|\d+\.\s*)+")

SECTION_PATTERNS = [
    ("Procedure", re.compile(r"^(THE )?PROCEDURE\b")),
    ("The Facts", re.compile(r"^(AS TO )?THE FACTS\b|^THE CIRCUMSTANCES OF THE CASE|^FACTS\b")),
    ("The Law", re.compile(r"^(AS TO )?THE LAW\b|^COMPLAINTS\b|^THE COMPLAINTS\b")),
    (
        "Operative provisions",
        re.compile(r"^FOR THESE REASONS|^THE COURT UNANIMOUSLY|^ON THESE GROUNDS"),
    ),
    (
        "Other",
        re.compile(
            r"^(JOINT |PARTLY )?(CONCURRING |DISSENTING |SEPARATE )?OPINION OF|^SEPARATE OPINION|^DONE IN ENGLISH|^APPENDIX|^ANNEX"
        ),
    ),
]


def classify_heading(text: str) -> str | None:
    t = re.sub(r"\s+", " ", text.replace("\u00a0", " ")).strip().upper()
    t = ROMAN.sub("", t)
    for label, pat in SECTION_PATTERNS:
        if pat.search(t):
            return label
    return None


def parse_docx(path: Path) -> list[dict]:
    out: list[dict] = []
    section = "Procedure"
    op_n = 0
    for p in Document(str(path)).paragraphs:
        text = p.text.replace("\u00a0", " ").strip()
        if not text:
            continue
        style = p.style.name if p.style is not None else ""
        if HEAD_STYLE.match(style) and not style.startswith("Ju_H_1."):
            label = classify_heading(text)
            if label:
                section = label
            continue
        m = NUM.match(text)
        if section == "Operative provisions" and m and style not in ("Opi_Para",):
            op_n += 1
            out.append(
                {"number": None, "ref": f"op{op_n}", "section": section, "text": m.group(2).strip()}
            )
        elif m and PARA_STYLE.match(style) and section != "Other":
            out.append(
                {
                    "number": int(m.group(1)),
                    "ref": m.group(1),
                    "section": section,
                    "text": m.group(2).strip(),
                }
            )
        elif style.startswith(
            ("Ju_Para", "ECHR_Para", "Opi_Para", "ClinContent", "Ju_List", "Dec_List", "Ju_Quot")
        ) and not style.startswith("ECHR_Para_Quote"):
            pass
    return out


def _is_subheading(text: str) -> bool:
    return len(text) < 100 and not text.endswith((".", ";", ":", ","))


def parse_html(path: Path) -> list[dict]:
    tree = lhtml.fromstring(path.read_text(encoding="utf-8", errors="replace"))
    out: list[dict] = []
    section = "Procedure"
    last = 0
    cur: dict | None = None  # numbered paragraph that unnumbered continuation <p>s attach to
    for p in tree.iter("p"):
        text = re.sub(r"\s+", " ", p.text_content().replace("\u00a0", " ")).strip()
        if not text:
            continue
        label = classify_heading(text) if len(text) < 90 else None
        if label and text == text.upper():
            section = label
            cur = None
            continue
        if re.match(r"^Done in (English|French)", text):
            section, cur = "Other", None
            continue
        m = NUM.match(text)
        if m and section == "Operative provisions":
            ops = sum(1 for q in out if q["ref"].startswith("op")) + 1
            cur = {
                "number": None,
                "ref": f"op{ops}",
                "section": section,
                "text": m.group(2).strip(),
            }
            out.append(cur)
        elif m and int(m.group(1)) == last + 1 and section not in ("Other",):
            last = int(m.group(1))
            body = m.group(2).strip()
            # Old documents sometimes glue paragraph N+1 onto the end of paragraph N inside one <p>.
            while True:
                g = re.search(rf"(?<=[.;:?!”\"’)]) {last + 1}\.\s+(?=[A-Z“\"(])", body)
                if not g:
                    break
                out.append(
                    {
                        "number": last,
                        "ref": str(last),
                        "section": section,
                        "text": body[: g.start()].strip(),
                    }
                )
                body, last = body[g.end() :].strip(), last + 1
            cur = {"number": last, "ref": str(last), "section": section, "text": body}
            out.append(cur)
        elif cur is not None and section != "Other":
            # A numbered paragraph can continue in following unnumbered <p> blocks (quotes, lists,
            # a concluding sentence). Sub-headings (short, no final punctuation) end the paragraph.
            if _is_subheading(text):
                cur = None
            else:
                cur["text"] += "\n" + text
    # Some decisions have no paragraph numbers but numbered sub-headings ("1. The applicant's submissions"):
    # a handful of "paragraphs" that cover under 60% of the text is that, not real numbering.
    total = sum(len(re.sub(r"\s+", " ", p.text_content()).strip()) for p in tree.iter("p"))
    if len(out) < 10 and sum(len(p["text"]) for p in out) < 0.6 * total:
        out = []
    if not out:  # legal summaries and unnumbered decisions: every non-trivial paragraph is "u<k>"
        section = "Other"
        for p in tree.iter("p"):
            text = re.sub(r"\s+", " ", p.text_content().replace("\u00a0", " ")).strip()
            label = classify_heading(text) if len(text) < 90 and text == text.upper() else None
            if label:
                section = label
            elif len(text) > 40:
                out.append(
                    {"number": None, "ref": f"u{len(out) + 1}", "section": section, "text": text}
                )
    return out


def completeness(paras: list[dict]) -> dict:
    nums = [p["number"] for p in paras if p["number"] is not None]
    gaps = [n for n in range(1, (max(nums) if nums else 0) + 1) if n not in set(nums)]
    dups = len(nums) - len(set(nums))
    return {
        "n_numbered": len(nums),
        "max": max(nums, default=0),
        "gaps": len(gaps),
        "dups": dups,
        "ops": sum(1 for p in paras if p["ref"].startswith("op")),
    }


if __name__ == "__main__":
    import sys

    for f in sys.argv[1:]:
        p = Path(f)
        ps = parse_docx(p) if p.suffix == ".docx" else parse_html(p)
        print(p.name, completeness(ps))
