"""25 search requests (length=20, full select) at <=1 req/s, for response-time percentiles."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from hudoc import Hudoc  # noqa: E402

SELECT = "itemid,docname,appno,doctype,doctypebranch,languageisocode,kpdate,respondent,article,conclusion,importance,ecli,separateopinion"
B = 'contentsitename=ECHR AND (respondent:"GBR") AND (languageisocode:"ENG") AND '
FILTERS = [
    '(doctype:"HEJUD")',
    '(doctype:"HEDEC")',
    '(doctype:"HECOM")',
    '(doctype:"CLIN")',
    '(doctype:"HEREP")',
    '(doctype:"HEJUD") AND (article:"3")',
    '(doctype:"HEJUD") AND (article:"8")',
    '(doctype:"HEDEC") AND (conclusion:"Inadmissible")',
    '(doctype:"HEJUD") AND (deportation)',
    '(doctype:"HEDEC") AND (expulsion)',
    '(doctype:"HEJUD") AND (extradition)',
    '(doctype:"HEJUD") AND (importance:"1")',
    '(doctype:"HEJUD") AND (doctypebranch:"GRANDCHAMBER")',
    '(doctype:"HEJUD") AND (kpdate>="2020-01-01")',
    '(doctype:"HEDEC") AND (kpdate>="2015-01-01")',
    '(doctype:"HEJUD") AND ("margin of appreciation")',
    '(doctype:"HEJUD") AND (article:"6")',
    '(doctype:"HEJUD") AND (article:"5")',
    '(doctype:"HEJUD") AND ("proportionality")',
    '(doctype:"HEDEC") AND (article:"3")',
    '(doctype:"HEDEC") AND (article:"8")',
    '(doctype:"HECOM") AND (article:"3")',
    '(doctype:"CLIN") AND (article:"8")',
    '(doctype:"HEJUD") AND (separateopinion:"TRUE")',
    '(doctype:"HEJUD") AND (kpdate<"1990-01-01")',
]
h = Hudoc()
for i, f in enumerate(FILTERS):
    d = h.search(B + f, SELECT, start=0, length=20, sort="kpdate Descending", tag="timing")
    print(i, d["resultcount"], flush=True)
