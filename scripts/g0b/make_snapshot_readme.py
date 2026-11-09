"""Generate data/snapshot/README.md from manifest.json + snapshot_ids.py (so tables can't drift)."""

import hashlib
import json
from collections import Counter
from pathlib import Path

from grounds_regex import extract
from snapshot_ids import (
    DECISIONS_IMMIGRATION_INADMISSIBLE,
    DECISIONS_OTHER,
    JUDGMENTS,
    LEGAL_SUMMARIES,
)

ROOT = Path(__file__).resolve().parents[2]
SNAP = ROOT / "data" / "snapshot"
manifest = json.loads((SNAP / "manifest.json").read_text())
by_id = {e["item_id"]: e for e in manifest}
total = sum(p.stat().st_size for p in SNAP.rglob("*") if p.is_file())
by_type = Counter(e["doc_type"] for e in manifest)
PDF_SHA = hashlib.sha256((ROOT / "data/raw/g0b/leg/conv.pdf").read_bytes()).hexdigest()
stats = json.loads((ROOT / "data/raw/g0b/bench/parse_chunk.json").read_text())["parse"]["stats"]
N_UNNUMBERED_DEC = sum(
    1 for e in manifest if e["doc_type"] == "decision" and stats[e["item_id"]]["n_numbered"] == 0
)
by_outcome = {t: Counter(e["outcome"] for e in manifest if e["doc_type"] == t) for t in by_type}


def row(i: str, why: str, extra: str = "") -> str:
    e = by_id[i]
    arts = ", ".join(e["articles"][:6]) + (" …" if len(e["articles"]) > 6 else "")
    name = e["case_name"].replace("|", "/")
    cells = [
        name,
        f"`{i}`",
        "; ".join(e["application_numbers"][:2])
        + (" …" if len(e["application_numbers"]) > 2 else ""),
        e["date"],
        arts,
        f"{e['outcome']}",
    ]
    if extra:
        cells.append(extra)
    cells.append(why.replace("|", "/"))
    return "| " + " | ".join(cells) + " |"


def table(head: list[str], rows: list[str]) -> str:
    return "\n".join(["| " + " | ".join(head) + " |", "|" + "---|" * len(head), *rows])


J_HEAD = ["Case", "Item ID", "Application no.", "Date", "Articles", "Outcome", "Why it is here"]
j_rows = [row(i, why) for i, why in sorted(JUDGMENTS.items(), key=lambda kv: by_id[kv[0]]["date"])]


def found(i: str) -> str:
    return ", ".join(f"`{g}`" for g, _ in extract(SNAP / by_id[i]["path"])) or "(none found)"


d_imm = [
    row(i, "Stats demo: inadmissible deportation/expulsion/extradition decision.", found(i))
    for i in sorted(DECISIONS_IMMIGRATION_INADMISSIBLE, key=lambda i: by_id[i]["date"])
]
oracle_ids = [
    e["item_id"]
    for e in manifest
    if e["doc_type"] == "decision" and e["outcome"] in ("inadmissible", "partly_inadmissible")
]
oracle_rows = [
    "| `{}` | {} | {} | {} | {} |".format(
        i,
        by_id[i]["case_name"].replace("|", "/"),
        by_id[i]["outcome"],
        ", ".join(f"`{g}`" for g in by_id[i]["inadmissibility_grounds"] or []) or "-",
        found(i),
    )
    for i in sorted(oracle_ids, key=lambda i: (by_id[i]["date"], i))
]
meta_rows = [
    f"| `{e['item_id']}` | {e['doc_type']} | {e['outcome']} | "
    + ", ".join("`" + g + "`" for g in e["inadmissibility_grounds"])
    + " |"
    for e in manifest
    if e["inadmissibility_grounds"]
]
d_other = [
    row(i, why) for i, why in sorted(DECISIONS_OTHER.items(), key=lambda kv: by_id[kv[0]]["date"])
]
s_rows = [
    row(i, why) for i, why in sorted(LEGAL_SUMMARIES.items(), key=lambda kv: by_id[kv[0]]["date"])
]

outcome_lines = "\n".join(
    f"  - {t}: " + ", ".join(f"{o} {n}" for o, n in c.most_common()) for t, c in by_outcome.items()
)

readme = f"""# Demo snapshot

A small, committed, **offline** copy of the corpus: {by_type["judgment"]} UK judgments,
{by_type["decision"]} UK decisions, {by_type["legal_summary"]} legal summaries, the Convention and the
Human Rights Act 1998. Nothing in Gate 1 may need the network in snapshot mode: everything reads from here.

- Total size: **{total / 2**20:.1f} MB** (limit 30 MB). `du -sh data/snapshot`.
- Counts per type: judgment {by_type["judgment"]}, decision {by_type["decision"]}, legal_summary {by_type["legal_summary"]}, legislation {by_type["legislation"]} (total {len(manifest)} documents).
- Outcomes (normalised, see below):
{outcome_lines}
- Built by `scripts/g0b/` (throwaway). Retrieval dates are in `manifest.json` (`retrieved_at`). HUDOC was
  fetched at no more than 1 request per second.

## Layout (this is an interface: Gate 1 depends on it)

```
data/snapshot/
  manifest.json                 JSON array of ManifestEntry, sorted by (doc_type, date, item_id)
  hudoc/<itemid>.html           one stored body per HUDOC document
  legislation/ukpga-1998-42.xml Human Rights Act 1998 (legislation.gov.uk CLML XML)
  legislation/echr-convention.txt  the Convention + Protocols (text extracted from the ECHR PDF)
```

### `manifest.json`

A JSON array. Every element validates against `packages/contract/schema/ManifestEntry.json`
(zod source: `packages/contract/src/source-document.ts`). Every element is a `SourceDocument`
plus three storage fields:

| Field | Meaning |
|---|---|
| `item_id` | HUDOC item id (`001-57619` judgments/decisions, `002-14484` legal summaries) or `echr-convention` / `ukpga-1998-42` |
| `case_name` | HUDOC `docname` without the leading `CASE OF ` (judgments from before ~2000 are upper case) |
| `application_numbers` | HUDOC `appno` split on `;` |
| `ecli` | ECLI where HUDOC has one. Present on every judgment, absent (`null`) on legal summaries |
| `doc_type` | `judgment` / `decision` / `legal_summary` / `legislation` (`communicated` is in the schema but not in the snapshot) |
| `chamber` | `Grand Chamber` / `Chamber` / `Committee`; `null` for legal summaries and legislation. For decisions it comes from HUDOC `doctypebranch` (`ADMISSIBILITY` = Chamber/Section, `ADMISSIBILITYCOM` = Committee) |
| `date` | HUDOC `kpdate` (judgment or decision date). Legislation: Convention = signature date 1950-11-04, HRA = Royal Assent 1998-11-09. The stored *text* is the current version, see `retrieved_at` |
| `articles` | HUDOC `article` split on `;`, e.g. `["3","8-1","P1-3","35-3-a"]` |
| `outcome_raw` | HUDOC `conclusion` verbatim (may be `null`) |
| `inadmissibility_grounds` | list of `InadmissibilityGround` (`manifestly_ill_founded`, `non_exhaustion`, `out_of_time`, `incompatible_ratione_*`, `abuse_of_right`, `no_significant_disadvantage`, `substantially_same`, `not_a_victim`, `other`) or `null`. In the manifest it is filled **only where HUDOC's `conclusion` names the ground** ({len(meta_rows)} entries, see below); otherwise `null` = not extracted yet |
| `inadmissibility_grounds_source` | `metadata` (stated in `conclusion`) or `text` (extracted from the decision text by Gate 1's S2); `null` exactly when the grounds are `null`. The manifest only ever contains `metadata` or `null` |
| `outcome` | normalised, derived by us: `violation` (violation findings only), `no_violation` (no-violation findings only), `mixed` (both), `inadmissible`, `partly_inadmissible`, `struck_out`, `admissible`, `other`, `not_applicable` |
| `importance` | HUDOC importance 1 (key case) to 4 (low); `null` for legislation |
| `language` | `en` |
| `source_url` | link a human can open (`https://hudoc.echr.coe.int/eng?i=<itemid>`) |
| `sha256` | sha256 of the stored file (`py/tests/test_snapshot_manifest.py` checks every one, offline) |
| `data_source` | always `snapshot` here |
| `retrieved_at` | UTC time the file was fetched |
| `format` | `html` / `txt` / `xml` |
| `path` | relative to `data/snapshot/` |

### Stored formats and how to parse them

Format choice (measured in `docs/hudoc-measurement.md`): **HTML** keeps every paragraph number as plain text and is
the smallest and simplest to parse. DOCX loses the numbers of automatically numbered paragraphs in modern documents (it dropped 31
of 86 in `001-176931`, Ndidi); PDF keeps them but is 2x larger and needs line re-joining.

`hudoc/<itemid>.html` is the raw response of `/app/conversion/docx/html/body?library=ECHR&id=<itemid>`,
unmodified: a `<style>` block followed by `<p>` elements, no `<html>`/`<body>`. Things the parser must know
(all seen in this snapshot):

- Paragraph numbers are plain text at the start of a `<p>`: `88.` + non-breaking spaces. CSS class names are
  generated per document: never rely on them.
- A numbered paragraph can continue in the following **unnumbered** `<p>` blocks (quotes, lists, a concluding
  sentence). Soering's key sentence is in such a continuation of §111. Attach them to the numbered paragraph.
- Old documents sometimes glue paragraph N+1 onto the end of N inside one `<p>` (McCann §41/§42), or omit the
  full stop after the number (McCann §131). Expect the numbers to be a strict 1, 2, 3… sequence and use that.
- Operative provisions ("For these reasons, the Court…") restart numbering at 1: give them ids like `§op1`.
- Separate opinions restart numbering too: treat as section `Other`.
- {N_UNNUMBERED_DEC} of the {by_type["decision"]} decisions and all legal summaries have **no paragraph numbers at all**
  (older or struck-out decisions, summaries): cite them by running index (`§u1`, `§u2`, …).
- Section headings are upper-case lines (`PROCEDURE`, `THE FACTS`, `THE LAW`, `FOR THESE REASONS…`); sub-headings
  are short lines without a final full stop.

Paragraph id convention (see `packages/contract/src/shared.ts`): `<item_id>§<ref>` where ref is `88` (numbered),
`op3` (operative item), `u12` (unnumbered), or for legislation `art8` / `s3`.

`legislation/ukpga-1998-42.xml` is the CLML XML from `https://www.legislation.gov.uk/ukpga/1998/42/data.xml`
(current revised version, modified 2026-10-07). Section = `<P1>` elements; Schedule 1 reprints the Convention
rights. `legislation/echr-convention.txt` is plain text extracted with pypdf from
`https://www.echr.coe.int/documents/d/echr/convention_eng` (Convention as amended by Protocols 11, 14, 15, plus
Protocols 1, 4, 6, 7, 12, 13, 16). Page numbers were stripped; layout is `ARTICLE <n>` / title / numbered
sub-paragraphs. The PDF is the source of record: its sha256 is
`{PDF_SHA}`.

## What is in the snapshot, and why

Selection method: HUDOC metadata (`respondent=GBR`, English) plus full-text search for deportation / expulsion /
extradition, then read-through. Every case's item id, application number, date, articles and outcome below comes
from HUDOC metadata, not from memory. "Outcome" is our normalised value; the raw HUDOC text is in `manifest.json`.

### Judgments ({by_type["judgment"]})

Demo steps this serves: "Article 3 and extradition/expulsion" (violation and no-violation), "Article 8
deportation" (including criminals whose deportation was allowed: Ndidi, A.H. Khan, Balogun, Onur, Joseph
Grant, Otite), and neutrality questions on contested non-immigration cases (Hirst (No. 2), Al-Skeini, Saadi…).

{table(J_HEAD, j_rows)}

### Decisions ({by_type["decision"]})

**Inadmissible UK deportation / expulsion / extradition decisions ({len(d_imm)})**: the count/stats demo
("how many UK deportation complaints were declared inadmissible, and why?"). All mention deportation,
expulsion, removal or extradition at least 10 times and raise Article 3 or 8 (checked by
`py/tests/test_snapshot_manifest.py`). The "Grounds found in the text" column is the output of the regex prototype
`scripts/g0b/grounds_regex.py` (see "Inadmissibility grounds" below). HUDOC's own `conclusion` states the ground
for only 18 of 671 inadmissible Court decisions, so the real stats pipeline has to extract grounds from the text.

{table([*J_HEAD[:6], "Grounds found in the text (prototype)", "Why it is here"], d_imm)}

**Other decisions ({len(d_other)})**: other outcomes for the breakdown (struck out, admissible, partly admissible)
and non-immigration decisions for neutrality questions.

{table(J_HEAD, d_other)}

### Inadmissibility grounds (test oracle for S2)

Demo step 3 asks "why were they inadmissible?". HUDOC metadata rarely says, so each decision's ground(s) must be
read from its text at parse time (`inadmissibility_grounds_source = "text"`). The table below is what the regex
prototype `scripts/g0b/grounds_regex.py` finds for **every inadmissible or partly inadmissible decision in the
snapshot** ({len(oracle_ids)}). **It is prototype-derived**: for each decision the evidence sentence the regex
matched was read by the author (not by a lawyer); decisions can rest on several grounds and the prototype only
reports the ones the Court states in a concluding sentence. Gate 1's S2 can use it as a test oracle (a correct
extractor should reproduce each row, or improve on it with a reason). `-` in the metadata column means HUDOC's
`conclusion` does not name a ground (that is the normal case).

How the prototype works: split the HTML text into sentences; ignore sentences that recite the Convention or
the Rules, report a party's argument, negate the ground ("cannot be considered manifestly ill-founded"), or
mention a preliminary objection; a ground counts when its phrase ("manifestly ill-founded", "failed to exhaust",
"ratione materiae", ...) occurs in a sentence in which the Court is rejecting something ("must be rejected",
"inadmissible", "Article 35 §"). Sentences ending "rejected in accordance with Article 35 § 1" are told apart
(six months vs exhaustion) by looking at the three sentences before.

| Item ID | Case | Outcome | Grounds in HUDOC metadata | Grounds found in the text (prototype) |
|---|---|---|---|---|
{chr(10).join(oracle_rows)}

Entries whose **manifest** already carries grounds (`inadmissibility_grounds_source = "metadata"`), because HUDOC's
`conclusion` names them. Judgments and legal summaries appear here when the *remainder* of the application was
declared inadmissible:

| Item ID | Type | Outcome | Grounds |
|---|---|---|---|
{chr(10).join(meta_rows)}

### Legal summaries ({by_type["legal_summary"]})

HUDOC Case-Law Information Note summaries (doc type `CLIN`). Short, unnumbered, each a different
"view" of a judgment in the snapshot: useful for checking that retrieval prefers the judgment's numbered
paragraphs when asked for citations.

{table(J_HEAD, s_rows)}

### Legislation (2)

| Document | Item ID | Source | Licence / terms |
|---|---|---|---|
| European Convention on Human Rights | `echr-convention` | https://www.echr.coe.int/documents/d/echr/convention_eng | © Council of Europe; reproduction allowed with source acknowledged (© ECHR-CEDH) for information and education, free of charge (https://www.echr.coe.int/copyright-and-disclaimer) |
| Human Rights Act 1998 | `ukpga-1998-42` | https://www.legislation.gov.uk/ukpga/1998/42/data.xml | Open Government Licence v3.0: "Contains public sector information licensed under the Open Government Licence v3.0." |

## Attribution and terms

HUDOC texts: © ECHR-CEDH, reproduced for information and education under the Court's reproduction terms, see
`docs/hudoc-measurement.md` section "Reuse terms" for the quoted text and what it allows. The electronic version
of a judgment "remains subject to editorial revision"; the signed original is the authentic version.

## Rebuild

`scripts/g0b/` holds the throwaway scripts that built this (`download_pool.py` talks to HUDOC through Orca's
browser at 1 request per second; `build_snapshot.py` assembles the files and manifest;
`make_snapshot_readme.py` writes this file). Gate 1 does not need them.
"""
(SNAP / "README.md").write_text(readme, encoding="utf-8")
print(len(readme))
