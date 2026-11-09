"""Inadmissibility grounds from the text of a decision.

HUDOC's own metadata names the ground for only a small minority of inadmissible decisions, so the
grounds are read from the Court's concluding sentences. Method: split the text into sentences; skip
sentences that recite the Convention or the Rules, report a party's argument, negate a ground
("cannot be considered manifestly ill-founded") or mention a preliminary objection; a ground counts
when its phrase occurs in a remaining sentence in which the Court is rejecting something.
"""

from __future__ import annotations

import re

# Same vocabulary as packages/contract/src/shared.ts InadmissibilityGround, in enum order.
PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("manifestly_ill_founded", re.compile(r"manifestly\s+ill[\s\-\u2010\u2011]*founded", re.I)),
    (
        "non_exhaustion",
        re.compile(
            r"(failed|failure|failing|not|never)\b.{0,40}\bexhaust|not (yet )?(been )?exhausted"
            r"|non-exhaustion|premature",
            re.I,
        ),
    ),
    (
        "out_of_time",
        re.compile(r"(six|four)[\s\-]months?|out of time|outside the (six|time)", re.I),
    ),
    ("incompatible_ratione_materiae", re.compile(r"ratione\s+materiae", re.I)),
    ("incompatible_ratione_personae", re.compile(r"ratione\s+personae", re.I)),
    ("incompatible_ratione_temporis", re.compile(r"ratione\s+temporis", re.I)),
    ("incompatible_ratione_loci", re.compile(r"ratione\s+loci", re.I)),
    (
        "abuse_of_right",
        re.compile(r"abuse of (the )?(right of )?(individual )?(petition|application)", re.I),
    ),
    ("no_significant_disadvantage", re.compile(r"no significant disadvantage", re.I)),
    (
        "substantially_same",
        re.compile(
            r"substantially the same|already (been )?examined by the Court|Article 35 § 2 \(b\)",
            re.I,
        ),
    ),
    (
        "not_a_victim",
        re.compile(
            r"cannot (claim to )?be (considered|regarded) (as )?(a|the) victim"
            r"|no longer (a|the) victim"
            r"|lost (his|her|their) victim status|victim status|cannot claim to be a victim",
            re.I,
        ),
    ),
]

# The Court is rejecting something.
REJECTING = re.compile(
    r"\b(be|is|are|to be|falls to be|fall to be) (rejected|dismissed|declared inadmissible)"
    r"|\binadmissible\b|\bthe Court (rejects|dismisses)\b"
    r"|\brejected (as|pursuant|in accordance|for)\b"
    r"|Article 35 §",
    re.I,
)
# Recitals of the law, party arguments, negations and narrative are not the Court's finding.
SKIP = re.compile(
    r"shall declare|any individual application|\(see [A-Z]|reiterates|recalls|(has|have) held"
    r"|(submit(s|ted)?|argu(e|es|ed)|contend(s|ed)?|maintain(s|ed)?|alleg(e|es|ed)"
    r"|complain(s|ed)?) that"
    r"|cannot,? (therefore,? )?be (considered|regarded)|no other ground|not manifestly|plea of"
    r"|raised the objection|preliminary objection|even assuming|reads as follows|purpose of Article"
    r"|\bwhether\b|need not|does not need to|may only deal|does not consider it necessary"
    r"|fundamentally subsidiary|rule of exhaustion|:\s*$",
    re.I,
)
SENT = re.compile(r"(?<=[.;?!])\s+(?=[A-Z“\"(])")
ART_35_1 = re.compile(r"Article 35 §§? ?1\b")


def sentences(texts: list[str]) -> list[str]:
    out: list[str] = []
    for text in texts:
        out += SENT.split(text)
    return out


def extract_grounds(texts: list[str]) -> list[tuple[str, str]]:
    """[(ground, evidence sentence)] in enum order, first evidence per ground."""
    found: dict[str, str] = {}
    sents = sentences(texts)
    for i, s in enumerate(sents):
        if SKIP.search(s):
            continue
        if "Government" in s and "the Court" not in s:
            continue
        if not REJECTING.search(s):
            continue
        for name, pat in PATTERNS:
            if name not in found and pat.search(s):
                found[name] = s.strip()
        if ART_35_1.search(s) and "out_of_time" not in found and "non_exhaustion" not in found:
            # "rejected in accordance with Article 35 § 1": the two Art 35 § 1 grounds are told
            # apart by the three sentences before.
            context = " ".join(sents[max(0, i - 3) : i + 1])
            if re.search(r"(six|four)[\s\-]months?|out of time", context, re.I):
                found["out_of_time"] = s.strip()
            elif re.search(r"remed|exhaust", context, re.I):
                found["non_exhaustion"] = s.strip()
    return [(g, found[g]) for g, _ in PATTERNS if g in found]


def merge_grounds(stated: list[str], found: list[str]) -> list[str]:
    """Union of the grounds HUDOC's metadata names and those the text states, in enum order."""
    order = [g for g, _ in PATTERNS]
    union = set(stated) | set(found)
    return sorted(union, key=lambda g: order.index(g) if g in order else len(order))
