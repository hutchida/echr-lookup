"""G0b: exact UK counts per document type + full UK metadata dump (for empty-field stats and
snapshot selection). Throwaway. Output: data/raw/g0b/uk_{eng,fre}.json (gitignored)."""

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from hudoc import Hudoc  # noqa: E402

OUT = Path(__file__).resolve().parents[2] / "data" / "raw" / "g0b"
SELECT = (
    "itemid,docname,appno,doctype,doctypebranch,documentcollectionid2,languageisocode,"
    "kpdate,respondent,article,conclusion,importance,ecli,separateopinion,originatingbody,"
    "violation,nonviolation,sclappnos,extractedappno,judgementdate,decisiondate,"
    "introductiondate,typedescription,rank,publishedby,kpthesaurus,application,"
    "countryofresidence,representedby,docnamefull,issue,respondentOrderEng,scl"
)
BASE_Q = 'contentsitename=ECHR AND (respondent:"GBR") AND (languageisocode:"%s")'
CATS = {
    "judgments_all": "JUDGMENTS",
    "judgments_grand_chamber": "GRANDCHAMBER",
    "judgments_chamber": "CHAMBER",
    "judgments_committee": "COMMITTEE",
    "decisions_all": "DECISIONS",
    "decisions_court_admissibility": "ADMISSIBILITY",
    "decisions_commission": "DECCOMMISSION",
    "decisions_admissibility_com": "ADMISSIBILITYCOM",
    "communicated_cases": "COMMUNICATEDCASES",
    "legal_summaries_clin": "CLIN",
    "commission_reports": "REPORTS",
    "execution_resolutions": "EXECUTION",
}


def main() -> None:
    h = Hudoc()
    counts: dict = {}
    for lang in ("ENG", "FRE"):
        counts[lang] = {}
        total = h.search(BASE_Q % lang, "itemid", length=1, tag="count")["resultcount"]
        counts[lang]["ALL"] = {"query": BASE_Q % lang, "count": total}
        for label, coll in CATS.items():
            q = BASE_Q % lang + f' AND (documentcollectionid2:"{coll}")'
            counts[lang][label] = {
                "query": q,
                "count": h.search(q, "itemid", length=1, tag="count")["resultcount"],
            }
            print(lang, label, counts[lang][label]["count"], flush=True)
    (OUT / "counts.json").write_text(json.dumps(counts, indent=1))
    for lang in ("ENG", "FRE"):
        rows, start = [], 0
        total = counts[lang]["ALL"]["count"]
        while start < total:
            d = h.search(
                BASE_Q % lang, SELECT, start=start, length=500, sort="kpdate Descending", tag="dump"
            )
            rows += [r["columns"] for r in d["results"]]
            start += 500
        (OUT / f"uk_{lang.lower()}.json").write_text(json.dumps(rows))
        print(lang, "dumped", len(rows), flush=True)


if __name__ == "__main__":
    main()
