# ruff: noqa: E501, SIM905
"""Turning a host answer into claims, citations and quotes. Pure functions, no I/O.

The host writes free text. To judge it the same way as `/ask` we need: each claim (a sentence or
bullet), the paragraph ids it cites, and each quoted passage. Citations come in two forms: the
tool's own `cite` string `[Chahal v. the United Kingdom, Judgment, §79]` (resolved through what the
tools actually returned, `Evidence`) or a bare paragraph id `001-58004§79`.
"""

import re
from dataclasses import dataclass, field
from typing import Any

BRACKET = re.compile(r"\[([^\[\]]*§[^\[\]]*)\]")
PID = re.compile(r"(?<![\w§])([A-Za-z0-9][A-Za-z0-9._-]*§[A-Za-z0-9][A-Za-z0-9._-]*)")
REF = re.compile(r"§§?\s*([A-Za-z0-9][A-Za-z0-9._\u2013-]*?)(?=[\s,;.)\]§]|$)")
QUOTE = re.compile(r"“([^”]+)”|\"([^\"]+)\"|«([^»]+)»")
BULLET = re.compile(r"^\s*(?:[-*•]|\d+[.)])\s+")
CITE_SHAPE = re.compile(
    r",\s*(?:Judgment|Decision|Legal summary|Communicated case|Legislation)\b.*,", re.IGNORECASE
)  # "[Case, Judgment, para 4]": the shape of a returned cite
MASK = "⟦{}⟧"
MASK_RE = re.compile(r"\s*⟦(\d+)⟧")
MIN_CLAIM_WORDS = 3
MIN_QUOTE_WORDS = 4
ABBREVIATIONS = frozenset(
    "v vs no nos art arts para paras mr mrs ms dr cf eg ie st vol p pp ibid op cit seq ch sec "
    "cl sch inc ltd co jr sr rev".split()
)
SENTENCE_END = re.compile(r"[.!?][\"”’)]*(?:\s*⟦\d+⟧)*\s+(?=[\"“(*]?[A-Z0-9])")


def clean_pid(pid: str) -> str:
    return pid.rstrip(".-_")


@dataclass
class Evidence:
    """Everything the tools returned: how cite strings and case names map to paragraph ids, and the
    full text of any paragraph the model was shown whole."""

    cites: dict[str, str] = field(default_factory=dict)
    docs: dict[tuple[str, str], set[str]] = field(default_factory=dict)
    names: dict[str, set[str]] = field(default_factory=dict)
    texts: dict[str, str] = field(default_factory=dict)
    pids: set[str] = field(default_factory=set)
    urls: dict[str, str] = field(
        default_factory=dict
    )  # hudoc_url (with its #:~:text= fragment) -> id
    _known: tuple | None = field(default=None, repr=False)  # compiled lookups, see `known_cites`

    def absorb(self, node: Any) -> None:
        if isinstance(node, dict):
            pid, cite = node.get("paragraph_id"), node.get("cite")
            if isinstance(pid, str):
                self.pids.add(pid)
            if isinstance(pid, str) and isinstance(cite, str):
                self.cites[cite] = pid
            if isinstance(pid, str) and isinstance(node.get("hudoc_url"), str):
                self.urls[node["hudoc_url"]] = pid
            if isinstance(pid, str) and isinstance(node.get("text"), str):
                self.texts[pid] = node["text"]
            doc, name = node.get("doc_id"), node.get("case_name")
            if isinstance(doc, str) and isinstance(name, str):
                label = str(node.get("doc_type_label") or "").lower()
                self.docs.setdefault((name.lower(), label), set()).add(doc)
                self.names.setdefault(name.lower(), set()).add(doc)
            for child in node.values():
                self.absorb(child)
        elif isinstance(node, list):
            for child in node:
                self.absorb(child)


def _norm_cite(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip().strip("[]")).casefold()


def known_cites(evidence: Evidence) -> tuple[re.Pattern | None, dict[str, str]]:
    """Citations of any shape the tools handed out: a `[...]` that is a returned `cite` (so
    `[Harkins v. the United Kingdom, Legal summary, Law, para 2]`, which has no §), optionally
    followed by `(hudoc_url)`, or a link whose URL is a returned `hudoc_url`, whatever its label.
    -> (pattern with groups label and url, normalised cite -> paragraph id)."""
    key = (len(evidence.cites), len(evidence.urls))
    if evidence._known is None or evidence._known[0] != key:
        by_cite = {_norm_cite(c): pid for c, pid in evidence.cites.items()}
        tail = ""
        if evidence.urls:
            urls = "|".join(re.escape(u) for u in sorted(evidence.urls, key=len, reverse=True))
            tail = rf"(?:\((?P<url>{urls})\))?"
        pattern = re.compile(r"\[(?P<label>[^\[\]]+)\]" + tail) if by_cite or tail else None
        evidence._known = (key, pattern, by_cite)
    return evidence._known[1], evidence._known[2]


def _refs(text: str) -> list[str]:
    """Section references after § or §§; a range like §§73-74 stands for each number in it."""
    refs: list[str] = []
    for ref in REF.findall(text):
        span = re.fullmatch(r"(\d+)[\u2013-](\d+)", ref)
        if span and 0 < int(span[2]) - int(span[1]) < 10:
            refs += [str(n) for n in range(int(span[1]), int(span[2]) + 1)]
        else:
            refs.append(ref)
    return refs


def _resolve_part(inner: str, whole: str, evidence: Evidence) -> tuple[list[str], str | None]:
    direct = [clean_pid(m) for m in PID.findall(inner)]
    if direct:
        return direct, None
    refs = _refs(inner)
    head = inner.split("§")[0].strip().rstrip(",").strip()
    name, _, label = head.rpartition(",")
    candidates: set[str] = set()
    if name:
        candidates = evidence.docs.get((name.strip().lower(), label.strip().lower()), set())
    if not candidates:
        candidates = evidence.names.get(head.lower(), set())
    if refs and len(candidates) == 1:
        doc = next(iter(candidates))
        return [f"{doc}§{ref.rstrip('.')}" for ref in refs], None
    if refs:  # the model shortened or reworded the case name: the section alone may still be unique
        found = [{p for p in evidence.pids if p.endswith(f"§{ref.rstrip('.')}")} for ref in refs]
        if all(len(f) == 1 for f in found):
            return [next(iter(f)) for f in found], None
    return [], whole


def resolve_bracket(inner: str, evidence: Evidence) -> tuple[list[str], str | None]:
    """The text inside `[...§...]` -> (paragraph ids, unresolved text or None). One bracket may
    hold several citations separated by ";"."""
    whole = f"[{inner}]"
    if whole in evidence.cites:
        return [evidence.cites[whole]], None
    ids: list[str] = []
    bad: list[str] = []
    for part in (p for p in inner.split(";") if "§" in p):
        found, unresolved = _resolve_part(part.strip(), f"[{part.strip()}]", evidence)
        ids += found
        if unresolved:
            bad.append(unresolved)
    return list(dict.fromkeys(ids)), "; ".join(bad) or None


def unmask(sentence: str, raws: list[str]) -> str:
    return re.sub(r"⟦(\d+)⟧", lambda m: raws[int(m.group(1))], sentence)


def _split_sentences(text: str) -> list[str]:
    parts: list[str] = []
    start = 0
    for m in SENTENCE_END.finditer(text):
        before = text[start : m.start() + 1]
        last = re.search(r"([\w.]+)$", before)
        word = last.group(1).strip(".").lower() if last else ""
        if word in ABBREVIATIONS or (last and re.fullmatch(r"(?:[A-Za-z]\.)+", last.group(1))):
            continue
        parts.append(text[start : m.end()].strip())
        start = m.end()
    parts.append(text[start:].strip())
    return [p for p in parts if p]


def _is_heading(line: str, has_cite: bool) -> bool:
    stripped = line.strip()
    if stripped.startswith("#") or re.fullmatch(r"[-*_=\s|:]{3,}", stripped):
        return True
    if re.fullmatch(r"\*\*[^*]+\*\*:?", stripped):
        return True
    return stripped.endswith(":") and not has_cite and len(stripped) <= 120


def _plain(text: str) -> str:
    text = re.sub(r"[*_`]{1,3}", "", text)
    return re.sub(r"\s+", " ", text).strip()


@dataclass
class ParsedAnswer:
    claims: list[dict]  # {id, text, citation_ids, blockquote}
    unresolved: list[str]  # citation markers that could not be mapped to a paragraph id

    @property
    def cited_ids(self) -> list[str]:
        out: list[str] = []
        for claim in self.claims:
            for pid in claim["citation_ids"]:
                if pid not in out:
                    out.append(pid)
        return out


def parse_answer(answer_text: str, evidence: Evidence) -> ParsedAnswer:
    claims: list[dict] = []
    unresolved: list[str] = []
    pattern, by_cite = known_cites(evidence)
    lead_ids: list[str] = []  # citations of the sentence that introduced the current list ("...:")
    for line in answer_text.splitlines():
        if not line.strip():
            continue
        blockquote = line.lstrip().startswith(">")
        line = line.lstrip().lstrip(">").strip() if blockquote else line
        is_item = bool(BULLET.match(line))
        if not is_item:
            lead_ids = []
        line = BULLET.sub("", line)
        marks: list[list[str]] = []
        raws: list[str] = []

        def mask(m: re.Match, marks: list[list[str]] = marks, raws: list[str] = raws) -> str:
            ids, bad = resolve_bracket(m.group(1), evidence)
            if bad:
                unresolved.append(bad)
            marks.append(ids)
            raws.append(m.group(0))
            return MASK.format(len(marks) - 1)

        def known(m: re.Match, marks: list[list[str]] = marks, raws: list[str] = raws) -> str:
            pid = by_cite.get(_norm_cite(m.group("label")))
            if pid is None and "url" in m.groupdict() and m.group("url"):
                pid = evidence.urls.get(m.group("url"))
            if pid is None:
                if CITE_SHAPE.search(m.group("label")) and "§" not in m.group("label"):
                    unresolved.append(f"[{m.group('label')}]")  # a cite no tool returned
                    marks.append([])
                    raws.append(f"[{m.group('label')}]")
                    return MASK.format(len(marks) - 1)
                return m.group(0)
            marks.append([pid])
            raws.append(f"[{m.group('label')}]")  # the link target is not part of the claim
            return MASK.format(len(marks) - 1)

        masked = BRACKET.sub(mask, pattern.sub(known, line) if pattern else line)
        if _is_heading(MASK_RE.sub("", masked), bool(marks)):
            continue
        for sentence in _split_sentences(masked):
            ids = [pid for i in map(int, re.findall(r"⟦(\d+)⟧", sentence)) for pid in marks[i]]
            body = MASK_RE.sub("", sentence)
            ids += [clean_pid(m) for m in PID.findall(body)]
            ids = list(dict.fromkeys(ids))
            # the claim keeps its citation markers as written: they tell the judge which case is meant
            text = _plain(unmask(sentence, raws))
            if len(_plain(body).split()) < MIN_CLAIM_WORDS:
                if ids and claims:  # a lone citation: it belongs to the claim before it
                    claims[-1]["citation_ids"] = list(
                        dict.fromkeys(claims[-1]["citation_ids"] + ids)
                    )
                continue
            inherited = bool(is_item and lead_ids and not ids)
            claims.append(
                {
                    "id": f"c{len(claims) + 1}",
                    "text": text,
                    "citation_ids": lead_ids if inherited else ids,
                    "inherited": inherited,
                    "blockquote": blockquote,
                }
            )
            if not is_item and ids and sentence.rstrip().endswith(":"):
                lead_ids = ids
    return ParsedAnswer(claims, unresolved)


def extract_quotes(claim: dict) -> list[str]:
    """Quoted passages of a claim (double quotes, guillemets, or a whole blockquote line)."""
    if claim.get("blockquote"):
        found = [claim["text"].strip('"“”')]
    else:
        found = [next(g for g in m.groups() if g) for m in QUOTE.finditer(claim["text"])]
    return [q.strip() for q in found if len(q.split()) >= MIN_QUOTE_WORDS]
