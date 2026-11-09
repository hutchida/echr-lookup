"""The Convention (plain text from the ECHR PDF) and the Human Rights Act 1998 (CLML XML).

One paragraph per Article / section, so a citation like `echr-convention§art8` or
`ukpga-1998-42§s3` points at the whole provision.

Ids:
  Convention        `art<n>`, `preamble`; Protocols `p<k>-art<n>` (Protocol "No. 1" is the untitled
                    first Protocol in the PDF)
  Human Rights Act  `s<n>` (`s7A`); Schedule 1 `sch1-art<n>`, `sch1-p1-art<n>`, `sch1-p13-art1`;
                    Schedules 2 and 4 `sch<k>-para<n>`; Schedule 3 `sch3-part1`, `sch3-part2`
"""

from __future__ import annotations

import re

from lxml import etree

LAW = "The Law"

# ---------------------------------------------------------------- Convention (text) ----------

_PROTOCOL = re.compile(r"^Protocol(?: No\. (\d+))?$")
_ARTICLE = re.compile(r"^ARTICLE (\d+)$")
_SECTION = re.compile(r"^SECTION [IV]+$")
_END = re.compile(r"^(Done a|In witness whereof)", re.I)
_NEW_LINE = re.compile(r"^(\d+\.|\([a-z]{1,3}\)|\([ivx]+\))\s")


def _join_wrapped(lines: list[str]) -> str:
    """PDF lines -> text: wrapped lines are joined; numbered / lettered items start a new line."""
    out: list[str] = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        if out and not _NEW_LINE.match(line):
            out[-1] += " " + line
        else:
            out.append(line)
    return "\n".join(out)


_TITLE_TAIL = re.compile(r"^and [^.;:]{0,35}$")  # second line of a wrapped title


def _is_title(line: str, following: str) -> bool:
    """An article title is a short line without final punctuation, followed by the first line of
    the text (not by the lowercase continuation of a wrapped sentence)."""
    return (
        0 < len(line) <= 80
        and not _NEW_LINE.match(line)
        and not line.endswith((".", ",", ";", ":"))
        and not re.search(r"\b(the|and|of|to|a|in|or|by|for)$", line)
        and (not following[:1].islower() or _TITLE_TAIL.match(following) is not None)
    )


def parse_convention(raw: str, doc_id: str) -> list[dict]:
    lines = raw.split("\n")
    start = next(i for i, ln in enumerate(lines) if ln.startswith("The GovernmenTs siGnaTory"))
    paras: list[dict] = []

    keys: list[tuple[int, int]] = []

    def add(ref: str, text: str, section: str, key: tuple[int, int] = (0, 0)) -> None:
        paras.append({"ref": ref, "number": None, "section": section, "text": text})
        keys.append(key)

    protocol = 0  # 0 = the Convention itself
    i, n = start, len(lines)
    pre: list[str] = []
    while i < n and lines[i].strip() != "Have agreed as follows:":
        pre.append(lines[i])
        i += 1
    add("preamble", _join_wrapped(pre), "Other")
    while i < n:
        line = lines[i].strip()
        if m := _PROTOCOL.match(line):
            protocol = int(m.group(1) or 1)
            while i < n and lines[i].strip() != "Have agreed as follows:":
                i += 1
            continue
        if m := _ARTICLE.match(line):
            number = int(m.group(1))
            i += 1
            title = ""
            if _is_title(lines[i].strip(), lines[i + 1].strip() if i + 1 < n else ""):
                title = lines[i].strip()
                i += 1
                if _TITLE_TAIL.match(lines[i].strip()):
                    title += " " + lines[i].strip()
                    i += 1
            body: list[str] = []
            while i < n:
                cur = lines[i].strip()
                if _ARTICLE.match(cur) or _PROTOCOL.match(cur) or _END.match(cur):
                    break
                if _SECTION.match(cur):
                    i += 2  # "SECTION II" + its title line
                    continue
                body.append(cur)
                i += 1
            prefix = f"Protocol No. {protocol}, " if protocol else ""
            head = f"{prefix}Article {number}" + (f" – {title}" if title else "")
            ref = f"p{protocol}-art{number}" if protocol else f"art{number}"
            add(ref, head + "\n" + _join_wrapped(body), LAW, (protocol, number))
            continue
        i += 1
    # the PDF text of Protocol 16 has its articles out of order
    order = sorted(range(len(paras)), key=lambda k: keys[k])
    return [paras[k] for k in order]


# ---------------------------------------------------------------- HRA (CLML XML) -------------

NS = {"l": "http://www.legislation.gov.uk/namespaces/legislation"}
_CONTAINERS = {"P1", "P2", "P3", "P4", "P5"}


def _name(el) -> str:
    return etree.QName(el).localname


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", text.replace("\u00a0", " ")).strip()


def _marker(el, depth_fmt: dict[str, str]) -> str:
    pn = el.find("l:Pnumber", NS)
    if pn is None:
        return ""
    label = _norm("".join(pn.itertext()))
    if not label:
        return ""
    return depth_fmt.get(_name(el), "({})").format(label)


def _walk(el, fmt: dict[str, str], top: bool = False) -> list[str]:
    """Rendered lines of `el`'s children. Numbered containers prefix their first line."""
    lines: list[str] = []
    for c in el:
        if not isinstance(c.tag, str):
            continue
        name = _name(c)
        if name in ("Pnumber", "Number", "CommentaryRef", "Commentary"):
            continue
        if name == "Title":
            if top:
                continue
            if t := _norm("".join(c.itertext())):
                lines.append(t)
        elif name == "Text":
            if t := _norm("".join(c.itertext())):
                lines.append(t)
        elif name in _CONTAINERS:
            sub = _walk(c, fmt)
            mark = _marker(c, fmt)
            if mark and sub:
                sub[0] = f"{mark} {sub[0]}"
            elif mark:
                sub = [mark]
            lines += sub
        else:
            lines += _walk(c, fmt)
    return lines


_P1_PLAIN = {"P1": "", "P2": "({})", "P3": "({})", "P4": "({})", "P5": "({})"}
_P1_NUMBERED = {"P1": "{}.", "P2": "({})", "P3": "({})", "P4": "({})", "P5": "({})"}


def _render(el, head: str, fmt: dict[str, str]) -> str:
    body = "\n".join(_walk(el, fmt, top=True))
    return head + ("\n" + body if body else "")


def _text(el) -> str:
    return _norm("".join(el.itertext()))


def parse_hra(raw: bytes) -> list[dict]:
    root = etree.fromstring(raw)
    paras: list[dict] = []

    def add(ref: str, text: str) -> None:
        paras.append({"ref": ref, "number": None, "section": LAW, "text": text})

    for p1 in root.iterfind("l:Primary/l:Body//l:P1", NS):
        sid = p1.get("id", "")
        number = sid.removeprefix("section-")
        group = p1.getparent()
        title_el = group.find("l:Title", NS) if _name(group) == "P1group" else None
        title = _text(title_el) if title_el is not None else ""
        title = title if title.endswith("etc.") else title.rstrip(".")
        head = f"Human Rights Act 1998, section {number}" + (f" – {title}" if title else "")
        add(f"s{number}", _render(p1, head, _P1_PLAIN))

    for sched in root.iterfind("l:Primary/l:Schedules/l:Schedule", NS):
        k = sched.get("id", "").removeprefix("schedule-")
        title_el = sched.find("l:TitleBlock/l:Title", NS)
        sched_title = _text(title_el) if title_el is not None else ""
        if k == "1":
            for part in sched.iterfind(".//l:Part", NS):
                pid = part.get("id", "")
                proto = (
                    "" if pid.endswith("part-I") else "p1-" if pid.endswith("part-II") else "p13-"
                )
                for ch in part.iterfind("l:Chapter", NS):
                    num = _text(ch.find("l:Number", NS))
                    m = re.search(r"(\d+)", num)
                    ch_title = _text(ch.find("l:Title", NS))
                    label = (
                        f"Article {m.group(1)} of the Thirteenth Protocol" if num.isupper() else num
                    )
                    head = f"Human Rights Act 1998, Schedule 1, {label}"
                    head += f" – {ch_title}" if ch_title else ""
                    add(f"sch1-{proto}art{m.group(1)}", _render(ch, head, _P1_NUMBERED))
        elif k == "3":
            for j, part in enumerate(sched.iterfind(".//l:Part", NS), start=1):
                ptitle = _text(part.find("l:Title", NS))
                head = f"Human Rights Act 1998, Schedule 3, Part {j} – {ptitle.title()}"
                add(f"sch3-part{j}", _render(part, head, _P1_PLAIN))
        else:
            for p1 in sched.iterfind(".//l:P1", NS):
                n = p1.get("id", "").rsplit("-", 1)[-1]
                block = p1.getparent()
                bt = block.find("l:Title", NS)
                title = _text(bt) if bt is not None and _name(block) == "Pblock" else ""
                head = f"Human Rights Act 1998, Schedule {k} ({sched_title}), paragraph {n}"
                head += f" – {title}" if title else ""
                add(f"sch{k}-para{n}", _render(p1, head, _P1_PLAIN))
    return paras
