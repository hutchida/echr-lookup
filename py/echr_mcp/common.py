"""Shared helpers: display names, citations, the corpus block, labels, size limits."""

from __future__ import annotations

import json
import re
import urllib.parse

from rag import config

RESULT_MAX_BYTES = 25_000  # MCP_LIMITS.resultMaxBytes
SCOPE = "UK cases only (plus the Convention and the Human Rights Act 1998)"
SAMPLE_NOTE = "Small committed sample, not the full HUDOC download."

DOC_TYPE_LABELS = {
    "judgment": "Judgment",
    "decision": "Decision",
    "communicated": "Communicated case",
    "legal_summary": "Legal summary",
    "legislation": "Legislation",
}

OUTCOME_LABELS = {
    "violation": "Violation: only violation findings",
    "no_violation": "No violation: only no-violation findings",
    "mixed": "Mixed: at least one violation and at least one no-violation finding",
    "inadmissible": "Inadmissible: the whole application was declared inadmissible",
    "partly_inadmissible": (
        "Partly inadmissible: part of the application was declared inadmissible or struck out"
    ),
    "struck_out": "Struck out of the list",
    "admissible": "Declared admissible (decision on admissibility only)",
    "other": "Other: none of the usual outcomes (for example a just-satisfaction ruling)",
    "not_applicable": "Not applicable (legislation, communicated cases)",
}


class ToolError(Exception):
    """A failure the model should read: one plain sentence, returned as an MCP tool error."""


class UserError(ToolError):
    pass


# --- case names ------------------------------------------------------------------------------

_LOWER_WORDS = {"AND": "and", "THE": "the", "OF": "of", "V.": "v.", "V": "v."}
_INITIALS = re.compile(r"^\(?(?:[A-Z]\.)+[A-Z]?\.?\)?[,;:]?$")
_MC = re.compile(r"^(\(?)(Mc|Mac)([A-Z]{2,})(\)?[,;:]?)$")


def _title_part(part: str) -> str:
    return part[:1].upper() + part[1:].lower() if part else part


def _display_word(word: str, first: bool) -> str:
    """One whitespace-separated token of a HUDOC case name."""
    core = word.strip("()[],;:")
    if not core:
        return word
    if m := _MC.match(word):  # McCANN -> McCann
        return f"{m.group(1)}{m.group(2)}{_title_part(m.group(3))}{m.group(4)}"
    if re.search(r"[a-z]", core):  # already mixed case ("Others", "(No.", "Qatada)"): unchanged
        return word
    if not re.search(r"[A-Z]", core):  # numbers, punctuation
        return word
    if _INITIALS.match(word) or re.search(r"\d", core):  # "A.H.", "N.", "K2"
        return word
    if re.fullmatch(r"\[[A-Z]{1,4}\]", word) or core == "UK":  # "[GC]"
        return word
    if core == "DEC.":
        return word.replace("DEC.", "dec.")
    if not first and core in _LOWER_WORDS:
        return word.replace(core, _LOWER_WORDS[core])
    lead = re.match(r"^[(\[]*", word).group(0)
    trail = re.search(r"[)\],;:]*$", word).group(0)
    body = word[len(lead) : len(word) - len(trail)]
    return lead + re.sub(r"[A-Za-z]+", lambda m: _title_part(m.group(0)), body) + trail


def display_case_name(case_name: str) -> str:
    """'CHAHAL v. THE UNITED KINGDOM' -> 'Chahal v. the United Kingdom'; mixed-case names stay."""
    name = re.sub(r"^CASE OF\s+", "", case_name.strip(), flags=re.IGNORECASE)
    words = name.split()
    out = [_display_word(w, i == 0) for i, w in enumerate(words)]
    return " ".join(out)[:200]


def cite(case_name: str, doc_type: str, label: str, doc_id: str | None = None) -> str:
    """'[Chahal v. the United Kingdom, Judgment, §79]'; brackets inside the name become ( ).

    `label` is the paragraph's `para_label`. `doc_id` is only given to tell apart two documents
    that share a name and type: '[Chahal v. the United Kingdom, Judgment (001-58004), §79]'."""
    name = display_case_name(case_name).replace("[", "(").replace("]", ")")
    kind = DOC_TYPE_LABELS.get(doc_type, doc_type)
    if doc_id:
        kind = f"{kind} ({doc_id})"
    return f"[{name}, {kind}, {label}]"[:200]


def unique_cites(items: list[dict]) -> None:
    """Make `cite` unique per paragraph within one result: items whose cite string is shared with
    a different paragraph get their doc id added (see `cite`). Items need the display fields
    case_name, doc_type, doc_id, para_label, paragraph_id and cite."""
    owners: dict[str, set[str]] = {}
    for item in items:
        owners.setdefault(item["cite"], set()).add(item["paragraph_id"])
    for item in items:
        if len(owners[item["cite"]]) > 1:
            item["cite"] = cite(
                item["case_name"], item["doc_type"], item["para_label"], item["doc_id"]
            )


# --- text fragments --------------------------------------------------------------------------

FRAGMENT_WORDS = 8
FRAGMENT_MAX_CHARS = 120  # encoded; keeps hudoc_url well below the contract's 400


def encode_fragment_text(text: str) -> str:
    """Percent-encode for a text directive: everything except letters, digits and `_.!~*'()`.
    That is encodeURIComponent plus `-`, `&` and `,`, which the directive syntax reserves."""
    return urllib.parse.quote(text, safe="_.!~*'()").replace("-", "%2D")


def text_fragment(quote: str) -> str | None:
    """'' + the first up to 8 whole words of `quote` as `:~:text=<encoded>`, or None if it has no
    words. Words are cut from the quote exactly as returned (no normalising); a leading '…' (a cut
    marker, not source text) is skipped, a trailing one dropped. Fewer words are used when 8 would
    encode to more than FRAGMENT_MAX_CHARS."""
    text = quote.strip()
    if text.startswith("…"):
        text = text[1:]
    words = text.split()
    if words and words[-1].endswith("…") and len(words) <= FRAGMENT_WORDS:
        words[-1] = words[-1][:-1]
    words = [w for w in words[:FRAGMENT_WORDS] if w]
    while words:
        encoded = encode_fragment_text(" ".join(words))
        if len(encoded) <= FRAGMENT_MAX_CHARS:
            return f":~:text={encoded}"
        words.pop()
    return None


def with_text_fragment(url: str, quote: str) -> str:
    """`url` with the text fragment of `quote` appended: after an existing '#…' part with no second
    '#', otherwise after a new '#'. Unchanged when the quote has no words."""
    fragment = text_fragment(quote)
    if fragment is None:
        return url
    return f"{url}{'' if '#' in url else '#'}{fragment}"


# --- the corpus block ------------------------------------------------------------------------


def corpus_block(conn) -> dict:
    source = config.data_source()
    documents = conn.execute(
        "SELECT count(*) FROM documents WHERE data_source = %s", (source,)
    ).fetchone()[0]
    return {
        "documents": int(documents),
        "data_source": source,
        "scope": SCOPE,
        "sample_note": SAMPLE_NOTE if source == "snapshot" else None,
    }


def corpus_sentence(corpus: dict) -> str:
    """For error messages: 'snapshot: 98 UK documents'."""
    return f"{corpus['data_source']}: {corpus['documents']} UK documents"


def nearest_sentence_cut(text: str, limit: int) -> str:
    """`text` cut to at most `limit` characters ('…' included), at a sentence end if possible."""
    if len(text) <= limit:
        return text
    head = text[: max(limit - 1, 0)]
    stops = [m.end() for m in re.finditer(r"[.!?][\"'”’)\]]*\s", head)]
    if stops and stops[-1] >= limit * 0.4:
        head = head[: stops[-1]]
    else:
        space = head.rfind(" ")
        if space >= limit * 0.4:
            head = head[:space]
    return head.rstrip() + "…"


def json_bytes(result: dict) -> int:
    return len(json.dumps(result, ensure_ascii=False, separators=(",", ":")).encode("utf-8"))
