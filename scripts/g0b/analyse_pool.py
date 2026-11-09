import json
import re
import sys
from pathlib import Path

from lxml import html

POOL = Path(__file__).resolve().parents[2] / "data" / "raw" / "g0b" / "pool"
meta = {r["itemid"]: r for r in json.load(open(POOL.parent / "uk_eng.json"))}
sys.path.insert(0, str(Path(__file__).parent))
from snapshot_ids import DECISIONS_POOL


def text(i):
    t = html.fromstring((POOL / f"{i}.html").read_text(encoding="utf-8"))
    return re.sub(r"\s+", " ", t.text_content().replace("\xa0", " "))


REASONS = {
    "manifestly ill-founded": r"manifestly ill-founded|Article 35 § 3 \(a\)",
    "non-exhaustion": r"exhaust|Article 35 § 1",
    "out of time (six months)": r"six[- ]month|out of time|time[- ]limit",
    "no significant disadvantage": r"no significant disadvantage",
    "abuse of petition": r"abuse of (the right of )?(individual )?(petition|application)",
    "ratione": r"ratione (materiae|personae|temporis|loci)",
    "substantially the same": r"substantially the same",
}
for i in DECISIONS_POOL:
    m = meta[i]
    s = text(i)
    dep = len(
        re.findall(
            r"deport|expuls|expel|extradit|removal to|remov(e|ed|al) from the United Kingdom|immigration",
            s,
            re.I,
        )
    )
    tail = s[-2500:]
    why = [k for k, p in REASONS.items() if re.search(p, tail, re.I)]
    print(
        i,
        m["kpdate"][:10],
        m["docname"][:28].ljust(28),
        (m["conclusion"] or "")[:14].ljust(14),
        "dep",
        str(dep).rjust(3),
        "|",
        m["article"][:14].ljust(14),
        "|",
        ", ".join(why),
    )
