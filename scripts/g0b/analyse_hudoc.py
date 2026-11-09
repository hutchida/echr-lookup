"""Summaries for docs/hudoc-measurement.md: request log stats, empty-field rates, French-only counts."""

import json
import statistics as st
from collections import Counter, defaultdict
from pathlib import Path

RAW = Path(__file__).resolve().parents[2] / "data" / "raw" / "g0b"
log = [json.loads(line) for line in open(RAW / "hudoc-requests.jsonl")]
print("requests logged:", len(log), "statuses:", Counter(r["status"] for r in log))


def pct(xs, p):
    xs = sorted(xs)
    return xs[min(len(xs) - 1, round(p / 100 * (len(xs) - 1)))]


def block(label, rows):
    secs = [r["secs"] for r in rows]
    print(
        f"{label:28s} n={len(rows):4d} p50={st.median(secs) * 1000:6.0f}ms p95={pct(secs, 95) * 1000:6.0f}ms "
        f"max={max(secs) * 1000:6.0f}ms mean_bytes={st.mean(r['bytes'] for r in rows):9.0f}"
    )


ok = [r for r in log if r["status"] == 200]
block("all 200s", ok)
for tag in sorted({r["tag"] for r in log}):
    rows = [r for r in ok if r["tag"] == tag]
    if rows:
        block(tag, rows)
# rate: starts = t - wall (python-side wall time of the request incl. orca eval overhead)
starts = sorted(r["t"] - r.get("wall", r.get("secs", 0)) for r in log)
gaps = [b - a for a, b in zip(starts, starts[1:], strict=False)]
print(
    "min gap between request starts (s):",
    round(min(gaps), 3),
    " median:",
    round(st.median(gaps), 3),
)
mx = 0
for i, s in enumerate(starts):
    mx = max(mx, sum(1 for x in starts[i:] if x < s + 1.0))
print("max requests in any 1 s window:", mx)
print(
    "elapsed s:",
    round(starts[-1] - starts[0]),
    "avg req/s:",
    round(len(starts) / (starts[-1] - starts[0]), 3),
)
print(
    "non-200:",
    [
        (r["n"], r["status"], r.get("url", r.get("path", ""))[:60])
        for r in log
        if r["status"] != 200
    ],
)

# --- empty-field rates on the full English UK dump ---
rows = json.load(open(RAW / "uk_eng.json"))
FIELDS = [
    "conclusion",
    "article",
    "importance",
    "ecli",
    "appno",
    "kpdate",
    "doctypebranch",
    "separateopinion",
    "originatingbody",
    "judgementdate",
    "decisiondate",
    "introductiondate",
    "violation",
    "nonviolation",
    "docname",
    "languageisocode",
    "respondent",
]
groups = {
    "judgments (HEJUD)": "HEJUD",
    "decisions (HEDEC)": "HEDEC",
    "communicated (HECOM)": "HECOM",
    "legal summaries (CLIN)": "CLIN",
    "commission reports (HEREP)": "HEREP",
}
print("\nempty-field % (null or empty string) among English UK documents")
print("group".ljust(28), "n".rjust(5), *[f[:10].rjust(11) for f in FIELDS[:8]])
for label, dt in groups.items():
    g = [r for r in rows if r["doctype"] == dt]
    cells = [
        f"{100 * sum(1 for r in g if r.get(f) in (None, '')) / len(g):10.1f}%" for f in FIELDS[:8]
    ]
    print(label.ljust(28), str(len(g)).rjust(5), *cells)
print("\nextra fields:")
for label, dt in groups.items():
    g = [r for r in rows if r["doctype"] == dt]
    print(
        label.ljust(28),
        {
            f: f"{100 * sum(1 for r in g if r.get(f) in (None, '')) / len(g):.0f}%"
            for f in FIELDS[8:14]
        },
    )
# judgments by decade: ecli/importance/conclusion
print("\njudgments: empty % by decade")
byd = defaultdict(list)
for r in rows:
    if r["doctype"] == "HEJUD":
        byd[r["kpdate"][:3] + "0s"].append(r)
for d, g in sorted(byd.items()):
    print(
        d,
        len(g),
        {
            f: f"{100 * sum(1 for r in g if r.get(f) in (None, '')) / len(g):.0f}%"
            for f in ("conclusion", "article", "importance", "ecli", "separateopinion")
        },
    )
print("\nconclusion values for decisions (top 8):")
print(
    Counter(
        r["conclusion"][:60] if r["conclusion"] else None for r in rows if r["doctype"] == "HEDEC"
    ).most_common(8)
)
print("importance values:", Counter(r["importance"] for r in rows))
print(
    "separateopinion values (judgments):",
    Counter(r["separateopinion"] for r in rows if r["doctype"] == "HEJUD"),
)
print(
    "multi-appno (judgments):",
    sum(1 for r in rows if r["doctype"] == "HEJUD" and ";" in (r["appno"] or "")),
)
print("article multi-valued:", sum(1 for r in rows if ";" in (r["article"] or "")))

# --- French-only: FRE docs with no ENG counterpart on (appno, kpdate, family) ---
fre = json.load(open(RAW / "uk_fre.json"))
fam = {
    "HEJUD": "J",
    "HFJUD": "J",
    "HEDEC": "D",
    "HFDEC": "D",
    "HECOM": "C",
    "HFCOM": "C",
    "HEREP": "R",
    "HFREP": "R",
    "CLIN": "S",
    "CLINF": "S",
    "HERES54": "X",
    "HFRES54": "X",
    "HERES32": "M",
    "HFRES32": "M",
}
eng_keys = {(r["appno"], r["kpdate"][:10], fam.get(r["doctype"])) for r in rows}
only = Counter(
    r["doctype"]
    for r in fre
    if (r["appno"], r["kpdate"][:10], fam.get(r["doctype"])) not in eng_keys
)
print("\nFrench docs total", len(fre), "by doctype", Counter(r["doctype"] for r in fre))
print("French-only (no English doc with same appno+date+family):", sum(only.values()), dict(only))
print("English counts by doctype:", Counter(r["doctype"] for r in rows), "total", len(rows))
print("English counts by doctypebranch:", Counter((r["doctype"], r["doctypebranch"]) for r in rows))
