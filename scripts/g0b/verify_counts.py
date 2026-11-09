"""Run the exact query strings documented in docs/hudoc-measurement.md and cross-check each against a
tally of the full metadata dump (uk_eng.json / uk_fre.json). Prints a markdown table."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from hudoc import Hudoc  # noqa: E402

RAW = Path(__file__).resolve().parents[2] / "data" / "raw" / "g0b"
eng, fre = json.load(open(RAW / "uk_eng.json")), json.load(open(RAW / "uk_fre.json"))
BASE = 'contentsitename=ECHR AND (respondent:"GBR") AND (languageisocode:"%s")'
E = [  # (label, extra filter, dump predicate)
    ("All documents", "", lambda r: True),
    ("Judgments", '(doctype:"HEJUD")', lambda r: r["doctype"] == "HEJUD"),
    (
        "  Grand Chamber judgments",
        '(doctype:"HEJUD") AND (doctypebranch:"GRANDCHAMBER")',
        lambda r: r["doctype"] == "HEJUD" and r["doctypebranch"] == "GRANDCHAMBER",
    ),
    (
        "  Chamber judgments",
        '(doctype:"HEJUD") AND (doctypebranch:"CHAMBER") AND NOT (doctypebranch:"GRANDCHAMBER")',
        lambda r: r["doctype"] == "HEJUD" and r["doctypebranch"] == "CHAMBER",
    ),
    (
        "  Committee judgments",
        '(doctype:"HEJUD") AND (doctypebranch:"COMMITTEE")',
        lambda r: r["doctype"] == "HEJUD" and r["doctypebranch"] == "COMMITTEE",
    ),
    ("Decisions (Court + Commission)", '(doctype:"HEDEC")', lambda r: r["doctype"] == "HEDEC"),
    (
        "  Court decisions, Chamber/Section",
        '(doctype:"HEDEC") AND (doctypebranch:"ADMISSIBILITY") AND NOT (doctypebranch:"ADMISSIBILITYCOM")',
        lambda r: r["doctypebranch"] == "ADMISSIBILITY",
    ),
    (
        "  Court decisions, Committee",
        '(doctype:"HEDEC") AND (doctypebranch:"ADMISSIBILITYCOM")',
        lambda r: r["doctypebranch"] == "ADMISSIBILITYCOM",
    ),
    (
        "  Court decisions, Grand Chamber",
        '(doctype:"HEDEC") AND (doctypebranch:"DECGRANDCHAMBER")',
        lambda r: r["doctypebranch"] == "DECGRANDCHAMBER",
    ),
    (
        "  Commission decisions",
        '(doctype:"HEDEC") AND (doctypebranch:"DECCOMMISSION")',
        lambda r: r["doctypebranch"] == "DECCOMMISSION",
    ),
    ("Communicated cases", '(doctype:"HECOM")', lambda r: r["doctype"] == "HECOM"),
    ("Legal summaries (CLIN)", '(doctype:"CLIN")', lambda r: r["doctype"] == "CLIN"),
    ("Commission reports", '(doctype:"HEREP")', lambda r: r["doctype"] == "HEREP"),
    (
        "Committee of Ministers resolutions (Art 46)",
        '(doctype:"HERES54")',
        lambda r: r["doctype"] == "HERES54",
    ),
    (
        "Committee of Ministers resolutions (Art 32)",
        '(doctype:"HERES32")',
        lambda r: r["doctype"] == "HERES32",
    ),
]
F = [
    ("All documents", "", lambda r: True),
    ("Judgments", '(doctype:"HFJUD")', lambda r: r["doctype"] == "HFJUD"),
    ("Decisions", '(doctype:"HFDEC")', lambda r: r["doctype"] == "HFDEC"),
    ("Legal summaries (CLINF)", '(doctype:"CLINF")', lambda r: r["doctype"] == "CLINF"),
    ("Commission reports", '(doctype:"HFREP")', lambda r: r["doctype"] == "HFREP"),
    (
        "Committee of Ministers resolutions",
        '(doctype:"HFRES54" OR doctype:"HFRES32")',
        lambda r: r["doctype"] in ("HFRES54", "HFRES32"),
    ),
]
h = Hudoc()
out = []
for lang, rows, table in (("ENG", eng, E), ("FRE", fre, F)):
    for label, flt, pred in table:
        q = BASE % lang + (f" AND {flt}" if flt else "")
        n = h.search(q, "itemid", length=1, tag="count")["resultcount"]
        tally = sum(1 for r in rows if pred(r))
        out.append({"lang": lang, "label": label, "query": q, "count": n, "dump_tally": tally})
        print(f"| {label} | {n} | {tally} | `{q}` |", flush=True)
(RAW / "counts_final.json").write_text(json.dumps(out, indent=1))
