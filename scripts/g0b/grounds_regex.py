"""G0b-fix: regex PROTOTYPE that finds the inadmissibility ground(s) in a decision's text.

Gate 1's S2 writes the real extractor and may use this as a starting point; the grounds it finds for the
snapshot (data/snapshot/README.md, "Inadmissibility grounds") are the oracle S2 is tested against.
Prototype-derived: checked by reading the evidence sentences for the snapshot's decisions, not by a lawyer.

Method: split the Court's own text (everything after the headings, excluding the operative part) into
sentences; skip sentences that recite the Convention, the Rules or a party's argument; a ground counts
when its pattern matches inside a remaining sentence. Order of results is the enum order.
"""

from __future__ import annotations

import re
from pathlib import Path

from lxml import html as lhtml

# Same vocabulary as packages/contract/src/shared.ts InadmissibilityGround.
PATTERNS: list[tuple[str, re.Pattern[str]]] = [
    ("manifestly_ill_founded", re.compile(r"manifestly\s+ill[\s\-\u2010\u2011]*founded", re.I)),
    (
        "non_exhaustion",
        re.compile(
            r"(failed|failure|failing|not|never)\b.{0,40}\bexhaust|not (yet )?(been )?exhausted|non-exhaustion|premature",
            re.I,
        ),
    ),
    ("out_of_time", re.compile(r"six[\s\-]months?|out of time|outside the (six|time)", re.I)),
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
            r"cannot (claim to )?be (considered|regarded) (as )?(a|the) victim|no longer (a|the) victim|"
            r"lost (his|her|their) victim status|victim status|cannot claim to be a victim",
            re.I,
        ),
    ),
]
# the Court is rejecting something: "must be rejected", "inadmissible", "falls to be rejected", "Article 35 §"
REJECTING = re.compile(
    r"\b(be|is|are|to be|falls to be|fall to be) (rejected|dismissed|declared inadmissible)|\binadmissible\b|"
    r"\bthe Court (rejects|dismisses)\b|\brejected (as|pursuant|in accordance|for)\b|Article 35 §",
    re.I,
)
# recitals of the law, party arguments, negations and narrative are not the Court's finding
SKIP = re.compile(
    r"shall declare|any individual application|\(see [A-Z]|reiterates|recalls|(has|have) held|"
    r"(submit(s|ted)?|argu(e|es|ed)|contend(s|ed)?|maintain(s|ed)?|alleg(e|es|ed)|complain(s|ed)?) that|"
    r"cannot,? (therefore,? )?be (considered|regarded)|no other ground|not manifestly|plea of|raised the objection|"
    r"preliminary objection|even assuming|reads as follows|purpose of Article|may only deal|does not consider it necessary|fundamentally subsidiary|rule of exhaustion|:\s*$",
    re.I,
)
SENT = re.compile(r"(?<=[.;?!])\s+(?=[A-Z“\"(])")


def sentences(path: Path) -> list[str]:
    tree = lhtml.fromstring(path.read_text(encoding="utf-8", errors="replace"))
    out: list[str] = []
    for p in tree.iter("p"):
        text = re.sub(r"\s+", " ", p.text_content().replace("\u00a0", " ")).strip()
        out += SENT.split(text)
    return out


ART_35_1 = re.compile(r"Article 35 §§? ?1\b")


def extract(path: Path) -> list[tuple[str, str]]:
    """Return [(ground, evidence sentence)] in enum order, first evidence per ground."""
    found: dict[str, str] = {}
    sents = sentences(path)
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
            # "rejected in accordance with Article 35 § 1": the two Art 35 § 1 grounds are told apart by context
            context = " ".join(sents[max(0, i - 3) : i + 1])
            if re.search(r"six[\s\-]months?|out of time", context, re.I):
                found["out_of_time"] = s.strip()
            elif re.search(r"remed|exhaust", context, re.I):
                found["non_exhaustion"] = s.strip()
    return [(g, found[g]) for g, _ in PATTERNS if g in found]


if __name__ == "__main__":
    import json
    import sys

    root = Path(__file__).resolve().parents[2]
    manifest = json.loads((root / "data" / "snapshot" / "manifest.json").read_text())
    for e in manifest:
        if e["doc_type"] == "decision" and e["outcome"] in ("inadmissible", "partly_inadmissible"):
            res = extract(root / "data" / "snapshot" / e["path"])
            print(
                f"\n{e['item_id']} {e['case_name'][:40]} [{e['outcome']}] -> {[g for g, _ in res]}"
            )
            if "-v" in sys.argv:
                for g, s in res:
                    print(f"    {g}: {s[:230]}")
