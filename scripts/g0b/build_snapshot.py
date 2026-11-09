"""Assemble data/snapshot/ from the already-downloaded pool (data/raw/g0b/pool) + legislation.

No network access here: the HUDOC download happened in download_pool.py (rate limited). This script
only copies, hashes and writes manifest.json. Throwaway.
"""

import hashlib
import json
import re
import shutil
from datetime import UTC, datetime
from pathlib import Path

from snapshot_ids import DECISIONS, JUDGMENTS, LEGAL_SUMMARIES

ROOT = Path(__file__).resolve().parents[2]
RAW = ROOT / "data" / "raw" / "g0b"
SNAP = ROOT / "data" / "snapshot"


def sha256(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def iso(p: Path) -> str:
    return datetime.fromtimestamp(p.stat().st_mtime, UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def normalise_outcome(conclusion: str | None) -> str:
    c = conclusion or ""
    viol = bool(re.search(r"(?<![Nn]o )(?<![Nn]on-)\b[Vv]iolation of", c))
    noviol = bool(re.search(r"\b[Nn]o violation", c))
    if viol and noviol:
        return "mixed"
    if viol:
        return "violation"
    if noviol:
        return "no_violation"
    if re.match(r"(?i)partly (admissible|inadmissible|struck)", c):
        return "partly_inadmissible"
    if re.match(r"(?i)inadmissible", c):
        return "inadmissible"
    if re.match(r"(?i)struck out", c):
        return "struck_out"
    if re.match(r"(?i)admissible", c):
        return "admissible"
    return "other"


# HUDOC conclusion fragments that name an inadmissibility ground -> contract enum value
METADATA_GROUNDS = [
    (r"manifestly ill-founded", "manifestly_ill_founded"),
    (r"exhaustion of domestic remedies", "non_exhaustion"),
    (r"six-month|six month", "out_of_time"),
    (r"ratione materiae", "incompatible_ratione_materiae"),
    (r"ratione personae", "incompatible_ratione_personae"),
    (r"ratione temporis", "incompatible_ratione_temporis"),
    (r"ratione loci", "incompatible_ratione_loci"),
    (r"abuse of", "abuse_of_right"),
    (r"no significant disadvantage", "no_significant_disadvantage"),
    (r"matter already examined|substantially the same", "substantially_same"),
    (r"\(art\. 34\) victim|article 34 - victim", "not_a_victim"),
]


def metadata_grounds(conclusion: str | None) -> list[str] | None:
    """Grounds that HUDOC's own `conclusion` states, or None when it does not name any.

    The conclusion is a `;`-separated list. A part such as "(Art. 35-3-a) Manifestly ill-founded" belongs to the
    "Inadmissible" / "Remainder inadmissible" part before it, but "(Art. 34) Victim" after a "Preliminary objection
    dismissed" part is about the objection, so only parts directly following an inadmissibility part count.
    """
    if not conclusion or "nadmissible" not in conclusion:
        return None
    found: list[str] = []
    in_inadmissible = False
    for part in (p.strip() for p in conclusion.split(";")):
        starts_inadmissible = bool(
            re.match(
                r"(?i)(partly )?(remainder )?inadmissible|partly (admissible;)?inadmissible", part
            )
        )
        if starts_inadmissible:
            in_inadmissible = True
        elif not part.startswith("("):
            in_inadmissible = False
        if starts_inadmissible or (in_inadmissible and part.startswith("(")):
            for pat, ground in METADATA_GROUNDS:
                if re.search(pat, part, re.I) and ground not in found:
                    found.append(ground)
    return found or None


def doc_type(m: dict) -> str:
    return {
        "HEJUD": "judgment",
        "HEDEC": "decision",
        "HECOM": "communicated",
        "CLIN": "legal_summary",
    }[m["doctype"]]


def chamber(m: dict) -> str | None:
    b = m["doctypebranch"]
    if b in ("GRANDCHAMBER", "DECGRANDCHAMBER"):
        return "Grand Chamber"
    if b in ("CHAMBER", "ADMISSIBILITY"):
        return "Chamber"
    if b in ("COMMITTEE", "ADMISSIBILITYCOM"):
        return "Committee"
    return None


def entry_from_hudoc(m: dict, f: Path) -> dict:
    name = re.sub(r"^CASE OF ", "", m["docname"])
    return {
        "item_id": m["itemid"],
        "case_name": name,
        "application_numbers": [a for a in (m["appno"] or "").split(";") if a],
        "ecli": m["ecli"] or None,
        "doc_type": doc_type(m),
        "chamber": chamber(m),
        "date": m["kpdate"][:10],
        "articles": [a for a in (m["article"] or "").split(";") if a],
        "outcome_raw": m["conclusion"] or None,
        "outcome": normalise_outcome(m["conclusion"]),
        "inadmissibility_grounds": (g := metadata_grounds(m["conclusion"])),
        "inadmissibility_grounds_source": "metadata" if g else None,
        "importance": int(m["importance"]) if m["importance"] else None,
        "language": "en",
        "source_url": f"https://hudoc.echr.coe.int/eng?i={m['itemid']}",
        "sha256": sha256(f),
        "data_source": "snapshot",
        "retrieved_at": iso(f),
        "format": "html",
        "path": f"hudoc/{m['itemid']}.html",
    }


def legislation_entries() -> list[dict]:
    leg = SNAP / "legislation"
    leg.mkdir(parents=True, exist_ok=True)
    hra = leg / "ukpga-1998-42.xml"
    shutil.copyfile(RAW / "leg" / "hra.xml", hra)
    conv = leg / "echr-convention.txt"
    shutil.copyfile(RAW / "leg" / "conv_clean.txt", conv)
    base = {
        "application_numbers": [],
        "ecli": None,
        "doc_type": "legislation",
        "chamber": None,
        "articles": [],
        "outcome_raw": None,
        "outcome": "not_applicable",
        "inadmissibility_grounds": None,
        "inadmissibility_grounds_source": None,
        "importance": None,
        "language": "en",
        "data_source": "snapshot",
    }
    return [
        {
            **base,
            "item_id": "echr-convention",
            "case_name": "European Convention on Human Rights (as amended by Protocols 11, 14 and 15, with Protocols 1, 4, 6, 7, 12, 13, 16)",
            "date": "1950-11-04",
            "source_url": "https://www.echr.coe.int/documents/d/echr/convention_eng",
            "sha256": sha256(conv),
            "retrieved_at": iso(RAW / "leg" / "conv.pdf"),
            "format": "txt",
            "path": "legislation/echr-convention.txt",
        },
        {
            **base,
            "item_id": "ukpga-1998-42",
            "case_name": "Human Rights Act 1998",
            "date": "1998-11-09",
            "source_url": "https://www.legislation.gov.uk/ukpga/1998/42",
            "sha256": sha256(hra),
            "retrieved_at": iso(RAW / "leg" / "hra.xml"),
            "format": "xml",
            "path": "legislation/ukpga-1998-42.xml",
        },
    ]


def main() -> None:
    meta = {r["itemid"]: r for r in json.loads((RAW / "uk_eng.json").read_text())}
    # CLIN rows can be absent from the dump if respondent is multi-valued; all current ones are present.
    hudoc = SNAP / "hudoc"
    if hudoc.exists():
        shutil.rmtree(hudoc)
    hudoc.mkdir(parents=True)
    entries = []
    for i in [*JUDGMENTS, *DECISIONS, *LEGAL_SUMMARIES]:
        src = RAW / "pool" / f"{i}.html"
        dst = hudoc / f"{i}.html"
        shutil.copyfile(src, dst)
        shutil.copystat(src, dst)
        entries.append(entry_from_hudoc(meta[i], dst))
    entries.sort(key=lambda e: (e["doc_type"], e["date"], e["item_id"]))
    entries += legislation_entries()
    (SNAP / "manifest.json").write_text(json.dumps(entries, indent=1, ensure_ascii=False) + "\n")
    from collections import Counter

    print(Counter(e["doc_type"] for e in entries), Counter(e["outcome"] for e in entries))


if __name__ == "__main__":
    main()
