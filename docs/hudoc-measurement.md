# HUDOC measurement (G0b)

What HUDOC (https://hudoc.echr.coe.int) contains for the United Kingdom, how to query it, how fast and how
clean it is, and what we may do with it. Everything here was measured on **2026-11-03** with the throwaway
scripts in `scripts/g0b/`; raw logs are not committed (`data/raw/` is gitignored) but every number can be
reproduced with the query strings below.

## Headline findings (read these first)

1. **HUDOC is behind a Cloudflare managed challenge.** Plain HTTP clients get `403` (`cf-mitigated: challenge`,
   page title "Just a moment...") on both URLs we tried (`/eng` and `/app/query/results`). A real browser passes it. We did
   all HUDOC traffic as same-origin `fetch()` calls from inside Orca's embedded browser tab, with our own rate
   limiter in front. **Gate 1's S1 cannot use plain `httpx` against HUDOC**; "full" mode needs a browser-driven
   downloader (or a bulk-access agreement with the Court). Snapshot mode is unaffected (offline).
2. **Because the browser sends the request, we could not set our own `User-Agent`** (page JavaScript may not).
   The brief's "descriptive User-Agent with a contact URL" was therefore **not possible for HUDOC traffic**.
   Non-HUDOC fetches (legislation.gov.uk, echr.coe.int) used `echr-lookup-research/0.1 (+https://github.com/hutchida/echr-lookup)`.
3. **English UK corpus: 4,484 documents** (586 judgments, 2,532 decisions, 230 communicated cases, 444 legal
   summaries, 307 Commission reports, 385 Committee of Ministers resolutions). French-only documents: 17.
4. **HTML is the best download format**: the only one that is both small and keeps every paragraph number as
   plain text. DOCX silently loses the numbers of auto-numbered paragraphs (36% of Ndidi).
5. **HUDOC metadata is clean for judgments and thin for decisions.** Only 18 of 671 inadmissible Court
   decisions say *why* in the `conclusion` field, so "why was it inadmissible?" must be extracted from the text.
   Fourteen of the 40 snapshot decisions (35%) and all legal summaries have **no paragraph numbers**.
6. **Politeness held:** at most one request per 1.05 s from our code, no rate-limit response ever seen
   (all 298 browser requests returned `200`), 301 limiter-counted requests in total.

## 1. How the HUDOC site queries its results

Found by opening `https://hudoc.echr.coe.int/eng?i=001-57619` in Orca's browser and listing
`performance.getEntriesByType('resource')`.

### Search endpoint

`GET /app/query/results` (same origin, JSON). Parameters:

| Parameter | Meaning | Example |
|---|---|---|
| `query` | boolean query, see syntax below | `contentsitename=ECHR AND (respondent:"GBR") AND (languageisocode:"ENG") AND (doctype:"HEJUD")` |
| `select` | comma-separated columns to return. Unknown names come back `null`, they do not error | `itemid,docname,appno,doctype,doctypebranch,languageisocode,kpdate,respondent,article,conclusion,importance,ecli,separateopinion` |
| `sort` | `<field> Descending` / `Ascending`; empty = relevance (`rank`) | `kpdate Descending` |
| `start`, `length` | paging. We used `length=500` (works); the web app itself asks for `length=1000` in one query | `start=0&length=500` |
| `rankingModelId` | constant the web app sends | `11111111-0000-0000-0001-000000000001` |

Response: `{"resultcount": 586, "results": [{"columns": {...}}, ...], "message": null}`. Every column is a string;
multi-valued fields are joined with `;` (`article = "3;6;6-3-c;13"`). **`length=1` is a cheap exact counter**:
`resultcount` is the total, regardless of `length`.

**Query syntax** (as observed): `field="value"` or `field:"value"`; `AND`, `OR`, `NOT`, parentheses; ranges on
dates (`kpdate>="2020-01-01"`); a bare quoted or unquoted word is a **full-text** search of the document body
(`... AND ("deportation")` matched 177 decisions; `fulltext:"deportation"` is not a field and matches 0).
Useful fields: `respondent` (`GBR`), `languageisocode` (`ENG`, `FRE`), `doctype`, `doctypebranch`,
`documentcollectionid2`, `article`, `appno`, `itemid`, `kpdate`, `importance`, `conclusion`, `ecli`.

**Quirk that changes counts:** field matching on `doctypebranch` / `documentcollectionid2` is a *substring/prefix
style* match. `doctypebranch:"CHAMBER"` also matches `GRANDCHAMBER` and `DECGRANDCHAMBER` (583 instead of 507),
and `doctypebranch:"ADMISSIBILITY"` also matches `ADMISSIBILITYCOM` (1,319 instead of 1,198). The exact queries
in section 2 use `AND NOT (...)` to remove the overlap. Always cross-check counts against a metadata dump.

**Document-type codes** (`doctype`): `HEJUD`/`HFJUD` judgments (English/French), `HEDEC`/`HFDEC` decisions,
`HECOM` communicated cases, `CLIN`/`CLINF` legal summaries (Case-Law Information Note), `HEREP`/`HFREP`
Commission reports, `HERES54`/`HFRES54` and `HERES32`/`HFRES32` Committee of Ministers resolutions.
`doctypebranch` values: `GRANDCHAMBER`, `CHAMBER`, `COMMITTEE` (judgments); `ADMISSIBILITY` (Chamber/Section
decisions), `ADMISSIBILITYCOM` (Committee decisions), `DECGRANDCHAMBER`, `DECCOMMISSION` (old European
Commission of Human Rights decisions); `COMMUNICATEDCASES`; `CLIN`; `REPORTS`; `EXECUTION`, `MERITS`.
Each language version is a **separate item with its own `itemid`** (English `001-244218`, French `001-244459`
for the same 2025 judgment).

### Document-conversion endpoints (bodies)

| Format | URL | Notes |
|---|---|---|
| HTML | `/app/conversion/docx/html/body?library=ECHR&id=<itemid>` | what the web app itself loads. A `<style>` block then `<p>` elements; no `<html>`/`<body>` |
| DOCX | `/app/conversion/docx/?library=ECHR&id=<itemid>&filename=<name>.docx&logEvent=False` | `filename` only names the download; `logEvent=False` keeps us out of HUDOC's download statistics |
| PDF | `/app/conversion/pdf/?library=ECHR&id=<itemid>&filename=<name>.pdf&logEvent=False` | |

Other endpoints the page calls (UI configuration, not needed): `/app/odata/resources?endpoint=Configuration|Labels|Taxonomy`.

## 2. Exact counts: respondent = United Kingdom (`GBR`)

All queries start `contentsitename=ECHR AND (respondent:"GBR") AND (languageisocode:"<L>")` and add the filter
shown. Each count was returned by HUDOC (`length=1`) **and** cross-checked against a tally of a full 4,484-row
metadata dump; the two agree on every line. Run `scripts/g0b/verify_counts.py` to reproduce.

**Third check, from HUDOC itself.** Opening
`https://hudoc.echr.coe.int/eng#{"respondent":["GBR"],"languageisocode":["ENG"]}` (then reload) shows the site's
own facet counts in the left column, and they match ours exactly: Case-Law 4,484; Judgments 586 (Grand Chamber 69,
Chamber 507, Committee 10); Decisions 2,532 (Grand Chamber 7, Chamber 1,198, Committee 121, Commission 1,206);
Communicated Cases 230; Legal Summaries 444; Reports 307; Resolutions 385 (Execution 291, Merits 94).

### English (`languageisocode:"ENG"`), the main target

| Document type | Count | Extra filter appended to the base query |
|---|---:|---|
| **All English documents** | **4,484** | *(none)* |
| **Judgments** | **586** | `(doctype:"HEJUD")` |
| ... Grand Chamber | 69 | `(doctype:"HEJUD") AND (doctypebranch:"GRANDCHAMBER")` |
| ... Chamber | 507 | `(doctype:"HEJUD") AND (doctypebranch:"CHAMBER") AND NOT (doctypebranch:"GRANDCHAMBER")` |
| ... Committee | 10 | `(doctype:"HEJUD") AND (doctypebranch:"COMMITTEE")` |
| **Decisions (Court + Commission)** | **2,532** | `(doctype:"HEDEC")` |
| ... Court, Chamber/Section | 1,198 | `(doctype:"HEDEC") AND (doctypebranch:"ADMISSIBILITY") AND NOT (doctypebranch:"ADMISSIBILITYCOM")` |
| ... Court, Committee | 121 | `(doctype:"HEDEC") AND (doctypebranch:"ADMISSIBILITYCOM")` |
| ... Court, Grand Chamber | 7 | `(doctype:"HEDEC") AND (doctypebranch:"DECGRANDCHAMBER")` |
| ... European Commission of Human Rights decisions | 1,206 | `(doctype:"HEDEC") AND (doctypebranch:"DECCOMMISSION")` |
| **Communicated cases** | **230** | `(doctype:"HECOM")` |
| **Legal summaries / Case-Law Information Notes** | **444** | `(doctype:"CLIN")` |
| **Commission reports** | **307** | `(doctype:"HEREP")` |
| Committee of Ministers resolutions, Art 46 (execution) | 291 | `(doctype:"HERES54")` |
| Committee of Ministers resolutions, Art 32 (merits) | 94 | `(doctype:"HERES32")` |

Court decisions in total: 1,198 + 121 + 7 = **1,326**. Of the 1,326, 671 are "Inadmissible" (the rest: struck out,
admissible, partly admissible). Date ranges: judgments 1975-2026, Court and Commission decisions 1956-2026,
communicated cases 2008-2026, legal summaries 1991-2026, Commission reports 1958-1999.

### French (`languageisocode:"FRE"`), counted separately

| Document type | Count | Extra filter |
|---|---:|---|
| All French documents | 1,803 | *(none)* |
| Judgments | 586 | `(doctype:"HFJUD")` (every English UK judgment is also in French) |
| Decisions | 367 | `(doctype:"HFDEC")` |
| Legal summaries | 444 | `(doctype:"CLINF")` |
| Commission reports | 22 | `(doctype:"HFREP")` |
| Committee of Ministers resolutions | 384 | `(doctype:"HFRES54" OR doctype:"HFRES32")` |

**French-only** documents (a French item with no English item of the same application number, date and
document family): **17** (14 decisions, 2 resolutions, 1 legal summary). Not worth ingesting.
Communicated cases exist only in English.

## 3. Response times, rate limiting, politeness

**Request budget.** The limiter in `scripts/g0b/hudoc.py` takes a cross-process lock, enforces at least 1.05 s
between request *starts*, and refuses past a 1,500 hard cap. It counted **301 requests**: 298 successful
(`200`, all through the browser), 2 blocked (`403`, the plain-HTTP probes) and 1 failed probe. In addition Orca's browser loaded the
HUDOC web app **seven times** (two clean loads at the start, a document page, and two facet pages loaded and
reloaded for the cross-check in section 2), each issuing its own burst of sub-requests: measured 67 and 63
resource entries on the first two loads; the rest are **unavailable** (the browser's 250-entry resource buffer
overflowed). Upper bound: 301 + 7 x 67 = **at most about 770**, far below the 1,500 cap. **Max observed rate from our
code: 0.95 requests/second** (minimum gap between starts 1.05 s; never more than one request in any 1 s window).

**Response times** (in-page `fetch` duration, ms; from the log of the 298 successful requests):

| Request kind | n | p50 | p95 | max | mean size |
|---|---:|---:|---:|---:|---:|
| Search, `length=20`, full `select` (dedicated timing run) | 25 | 254 | 2,688 | 3,224 | 10.6 KB |
| Count only (`length=1`) | 74 | 249 | 549 | 3,349 | 0.1 KB |
| Search, `length=500` (metadata dump pages) | 13 | 665 | 822 | 869 | 553 KB |
| HTML body | 136 | 175 | 257 | 2,252 | 97 KB |
| DOCX | 18 | 283 | 390 | 486 | 117 KB |
| PDF | 18 | 307 | 2,854 | 3,199 | 225 KB |
| All 298 successful requests | 298 | 222 | 861 | 3,349 | 90 KB |

Typical requests take ~0.2-0.3 s; about 4% (11 of 301) took 1.6-3.3 s, seemingly at random (not tied to one
query or to size). Plan on ~0.25 s typical, 3 s worst case, plus our own 1.05 s spacing.

**Rate limiting or blocking:** none observed at <= 1 request/s. No `429`, no `Retry-After`, no block page after
the browser session was established. The only block was the Cloudflare challenge for non-browser clients.
There is no `robots.txt` (the path returns the single-page-app shell).

## 4. Metadata completeness

Measured over **all 4,484 English UK documents** (far above the 100-record minimum). "Empty" = `null` or `""`.

| Field | Judgments (586) | Decisions (2,532) | Communicated (230) | Legal summaries (444) | Commission reports (307) |
|---|---:|---:|---:|---:|---:|
| `conclusion` | 0.3% | 0.4% | **37.4%** | 0.0% | 5.5% |
| `article` | **4.8%** | 0.7% | 1.7% | 0.0% | 4.9% |
| `importance` | 0.0% | 0.0% | 0.0% | 0.0% | 0.0% |
| `ecli` | 0.0% | 0.0% | **100%** | **100%** | 0.7% |
| `appno` | 0.0% | 0.1% | 0.0% | 0.0% | 0.0% |
| `kpdate` | 0.0% | 0.0% | 0.0% | 0.0% | 0.0% |
| `doctypebranch` | 0.0% | 0.0% | 0.0% | 0.0% | 0.0% |
| `separateopinion` | 0.0% | **100%** | 67.8% | **100%** | **100%** |

Where "present" does not mean "useful":

- **`importance`** is never empty, but for decisions it is `4` in 2,277 of 2,532 (90%): a default, not a judgement.
  For judgments it is spread (1: 121, 2: 131, 3: 152, 4: 182).
- **`conclusion` for decisions** is almost always the bare word `Inadmissible` (653 of the 1,326 Court decisions)
  or `Struck out of the list`. Only **18 of 671** inadmissible Court decisions name the ground
  (`Inadmissible (Art. 35) Admissibility criteria;(Art. 35-3-a) Manifestly ill-founded`). The stats question
  "why?" cannot be answered from metadata.
- **`conclusion` for communicated cases** is `Communicated` (144) or empty (86). The empties cluster in 2012-2014.
- **`article` is empty for 28 judgments (4.8%)**, mostly 2007-2009 (9% of the 2000s). `conclusion` is empty for 2
  judgments (`001-93082`, `001-85663`). Fall back to parsing the text.
- **`ecli`** is present on every judgment and decision (older ones too, e.g. `ECLI:CE:ECHR:1975:0221JUD000445170`),
  absent on legal summaries and communicated cases.
- **`separateopinion`** exists only on judgments (`TRUE` 209, `FALSE` 377); it is empty on everything else.
- **Multi-valued fields**: 95 of 586 judgments have several application numbers (`;`-joined); `article` is
  multi-valued for 4,051 documents. `conclusion` is free text with `;`-separated findings and varies in style by
  era ("Violation of Art. 3" vs "Violation of Article 3 - Prohibition of torture (Article 3 - Extradition)").
  The normalised `outcome` in the snapshot manifest is derived from it.
- `violation` / `nonviolation` columns (article lists) are empty for 44% / 58% of judgments: do not rely on them.
- `judgementdate` / `decisiondate` / `introductiondate` are mutually exclusive by type and mostly empty
  (93% of judgments have no `decisiondate`). Use `kpdate`, which is always set.

## 5. Download formats

Fetched all three formats for **18 documents** (old and recent judgments, Grand Chamber, decisions, legal
summaries): `200` for **18/18 HTML, 18/18 DOCX, 18/18 PDF** (100% success). Plus 118 HTML-only fetches for the
snapshot candidates: 118/118 `200`.

Numbered paragraphs recovered per format (HTML via our prototype parser, DOCX via `python-docx` styles + number
prefix, PDF via `pypdf` text + sequential-number rule):

| Document | HTML | DOCX | PDF | HTML / DOCX / PDF KB |
|---|---:|---:|---:|---|
| `001-176931` Ndidi (2017) | 86 | **55** | 86 | 94 / 98 / 238 |
| `001-108599` Harkins and Edwards (2012) | 148 | **134** | 148 | 210 / 297 / 389 |
| `001-4648` Ajayi (1999 decision) | 5 | **0** | 5 | 55 / 40 / 121 |
| `001-57943` McCann (1995) | 222 | 220 | **41** | 221 / 106 / 306 |
| `001-57619` Soering, `001-58004` Chahal, `001-70442` Hirst, `001-84709` Saadi, `001-243879` Hayes, `001-229321`, `001-231646`, `001-114244`, `001-98645` | all equal | all equal (Soering 127 of 128) | all equal | |
| `001-5425`, `001-95232` decisions, `002-14577`, `002-14484`, `002-428` legal summaries | 0 (unnumbered) | 0-1 | 0 | |
| **Mean size** | **105 KB** | **114 KB** | **219 KB** | |

Findings:

- **HTML is the format to store.** It keeps every number as text, is the smallest (half the PDF), parses in
  ~4 ms per document (`lxml`), and is what the HUDOC web app itself renders.
- **DOCX loses numbers.** Modern documents number paragraphs with Word's automatic list numbering, which
  `python-docx` does not expose (the number is not in the text): Ndidi lost 31 of 86 paragraphs. DOCX does carry
  semantic styles (`Ju_Para`, `Ju_H_1.`, `ECHR_Heading_3`, ...) that help with headings, but the style names
  differ between eras (`Ju_Para` vs `ECHR_Para` vs `jupara`).
- **PDF** keeps the numbers (and is the only format that matches the authentic printed layout) but is twice the
  size, needs line re-joining and header/footer stripping. McCann's 41 is a limit of our strict "N." rule (see
  below), not of PDF.
- Quirks found while parsing HTML (all in `data/snapshot/README.md`): a numbered paragraph continues in
  following unnumbered `<p>` blocks (the key sentence of Soering §111 lives in one); old documents glue
  paragraph N+1 into N's `<p>` (McCann §41/§42) or drop the full stop after a number (McCann §131); operative
  provisions and separate opinions restart numbering at 1; hashed CSS class names are per document.
- 14 of the 40 snapshot decisions and all 15 legal summaries have **no paragraph numbers** at all. Some of those
  decisions have *numbered sub-headings* ("1. The applicant's submissions", "2. The Court's assessment") that look
  like paragraph 1, 2: a parser must not treat a handful of short numbered lines covering a minority of the text
  as paragraph numbering.

## 6. Reuse terms

### HUDOC / the Court's website

Source: **https://www.echr.coe.int/copyright-and-disclaimer** ("Copyright and Disclaimer", linked as
"Disclaimer" in HUDOC's own footer, which we confirmed in the page). Quotes:

> "The information and texts available on the Court's website may be reproduced provided the source is
> acknowledged (© ECHR-CEDH) and the reproduction is made for private use or for the purposes of information and
> education in connection with the Court's activities. This authorisation is subject to the condition that the
> source is indicated and that any such reproduction is free of charge."

> "Persons wishing to use information and texts on the Court's website for any use other than those listed above,
> and in particular for commercial use, must request prior written permission using the form available on the
> website. Users should nevertheless be aware that certain information and texts may be protected under
> intellectual property law, in particular by copyright."

> "The electronic version of the Court's judgments and decisions is provided in order to ensure compliance with
> Article 44 § 3 of the European Convention on Human Rights, which provides that final judgments shall be
> published. However, it is not possible to guarantee that an electronic document faithfully reproduces a formally
> adopted text and the electronic version remains subject to editorial revision. The original signed text held in
> the Court's archives is the authentic version."

> "The Court hereby disclaims any liability or responsibility arising from the use of information or data
> contained on its website."

**What this allows for a public, non-commercial portfolio repo:** reproducing the texts is permitted
**free of charge, with the source acknowledged ("© ECHR-CEDH")**, for **information and education**. A
learning/portfolio project that is free, non-commercial and explains the Court's case-law fits that wording, so
committing ~41 judgments, 40 decisions and 15 legal summaries as a demo snapshot with attribution is within the
stated terms. It does **not** allow commercial use without written permission, and HUDOC publishes no terms
that cover bulk or automated downloading (neither a licence nor a prohibition, other than the Cloudflare
challenge, which signals the operator does not want anonymous scripts). We should therefore: keep the
attribution in `data/snapshot/README.md` and in the app footer, keep `data/full/` out of git, throttle to 1
request/s, and not redistribute a full corpus. The disclaimer means we must never present the electronic text as
the authentic judgment. This is not legal advice; if the repo ever becomes commercial, ask the Registry via the
form linked from that page.

### legislation.gov.uk (Human Rights Act 1998)

Source: the site footer, "All content is available under the Open Government Licence v3.0 except where otherwise
stated" (https://www.legislation.gov.uk/ukpga/1998/42/contents), and the licence itself
https://www.nationalarchives.gov.uk/doc/open-government-licence/version/3/:

> "You are free to: copy, publish, distribute and transmit the Information; adapt the Information; exploit the
> Information commercially and non-commercially for example, by combining it with other Information, or by
> including it in your own product or application."

> "You must (where you do any of the above): acknowledge the source of the Information ... 'Contains public
> sector information licensed under the Open Government Licence v3.0.'"

**Allows:** everything we need (copy, adapt, commit to a public repo, commercial or not) provided the attribution
line is shown. The XML is stored unmodified in `data/snapshot/legislation/ukpga-1998-42.xml`.

### The Convention text

Source of the snapshot text: the Court's own PDF "European Convention on Human Rights"
(https://www.echr.coe.int/documents/d/echr/convention_eng), published on echr.coe.int and therefore covered by
the same "Copyright and Disclaimer" page quoted above: free reproduction with the source acknowledged
(© ECHR-CEDH) for information and education, not for commercial use. The Convention is a treaty text; the
Council of Europe's version here is the authoritative English edition ("Convention ... as amended by Protocols
Nos. 11, 14 and 15 supplemented by Protocols Nos. 1, 4, 6, 7, 12, 13 and 16"). The Human Rights Act's Schedule 1
(OGL) is an alternative, openly licensed copy of the articles the UK has incorporated.

## 7. What this means for Gate 1

- **S1 (ingest)**: HUDOC needs a browser-class client in `full` mode; the snapshot path needs no network.
  Use the counts in section 2 to size the work (4,099 text documents is about 72 minutes at 1 req/s, see
  `docs/learn/ingestion-estimates.md`). List with `length=500` pages (9 requests for all 4,484 rows).
- **S2 (parse)**: store/parse **HTML**. Handle continuation `<p>`s, glued and dot-less numbers, restarting
  operative/opinion numbering and unnumbered documents (`§u<n>`), see `data/snapshot/README.md`.
- **S3/S4 (stats route)**: inadmissibility *grounds* must come from text (or an LLM pass), not metadata. The contract has `inadmissibility_grounds` / `inadmissibility_grounds_source` for this and `data/snapshot/README.md` has a regex-prototype oracle. Trust
  `outcome` (normalised from `conclusion`), `article`, `kpdate`, `appno`; do not trust `importance` for
  decisions, `article` before 2010 for judgments, or `conclusion` for communicated cases.
- **Counting questions** must say which collection they count (court decisions vs including Commission
  decisions; the UK has 1,326 vs 2,532).

## 8. Reproduce

```sh
# needs Orca's browser tab on https://hudoc.echr.coe.int/eng (Cloudflare challenge already passed)
cd py && uv run python ../scripts/g0b/verify_counts.py     # section 2
uv run python ../scripts/g0b/measure_counts.py             # full metadata dump -> data/raw/g0b/uk_{eng,fre}.json
uv run python ../scripts/g0b/measure_timing.py             # 25 timing requests
uv run python ../scripts/g0b/analyse_hudoc.py              # sections 3 and 4 from the request log + dump
uv run python ../scripts/g0b/measure_formats.py <ids>      # section 5
```
