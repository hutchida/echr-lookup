# Demo snapshot

A small, committed, **offline** copy of the corpus: 41 UK judgments,
40 UK decisions, 15 legal summaries, the Convention and the
Human Rights Act 1998. Nothing in Gate 1 may need the network in snapshot mode: everything reads from here.

- Total size: **10.1 MB** (limit 30 MB). `du -sh data/snapshot`.
- Counts per type: judgment 41, decision 40, legal_summary 15, legislation 2 (total 98 documents).
- Outcomes (normalised, see below):
  - decision: inadmissible 33, struck_out 4, partly_inadmissible 2, admissible 1
  - judgment: no_violation 17, violation 16, mixed 8
  - legal_summary: violation 7, no_violation 4, mixed 2, inadmissible 2
  - legislation: not_applicable 2
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
| `inadmissibility_grounds` | list of `InadmissibilityGround` (`manifestly_ill_founded`, `non_exhaustion`, `out_of_time`, `incompatible_ratione_*`, `abuse_of_right`, `no_significant_disadvantage`, `substantially_same`, `not_a_victim`, `other`) or `null`. In the manifest it is filled **only where HUDOC's `conclusion` names the ground** (6 entries, see below); otherwise `null` = not extracted yet |
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
- 14 of the 40 decisions and all legal summaries have **no paragraph numbers at all**
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
`f4608f7ed2d505debc85866f02290cf1e1c386eb1a605833bd6a3ee4ffb3febe`.

## What is in the snapshot, and why

Selection method: HUDOC metadata (`respondent=GBR`, English) plus full-text search for deportation / expulsion /
extradition, then read-through. Every case's item id, application number, date, articles and outcome below comes
from HUDOC metadata, not from memory. "Outcome" is our normalised value; the raw HUDOC text is in `manifest.json`.

### Judgments (41)

Demo steps this serves: "Article 3 and extradition/expulsion" (violation and no-violation), "Article 8
deportation" (including criminals whose deportation was allowed: Ndidi, A.H. Khan, Balogun, Onur, Joseph
Grant, Otite), and neutrality questions on contested non-immigration cases (Hirst (No. 2), Al-Skeini, Saadi…).

| Case | Item ID | Application no. | Date | Articles | Outcome | Why it is here |
|---|---|---|---|---|---|---|
| IRELAND v. THE UNITED KINGDOM | `001-57506` | 5310/71 | 1978-01-18 | 33, 3, 5, 5-1-c, 5-2, 5-3 … | mixed | Ireland v UK: inter-state case on interrogation techniques. Neutrality/old-case eval. |
| ABDULAZIZ, CABALES AND BALKANDALI v. THE UNITED KINGDOM | `001-57416` | 9214/80; 9473/81 … | 1985-05-28 | 8, 8-1, 14+8, 14, 3, 13 … | violation | Abdulaziz, Cabales and Balkandali: Art 14+8 immigration rules (sex discrimination). Violation. |
| SOERING v. THE UNITED KINGDOM | `001-57619` | 14038/88 | 1989-07-07 | 3, 6, 6-3-c, 6-3-d, 6-1, 13 … | mixed | Soering: the founding Art 3 extradition case (death-row phenomenon). Violation. Demo: citing 001-57619§88. |
| VILVARAJAH AND OTHERS v. THE UNITED KINGDOM | `001-57713` | 13163/87; 13164/87 … | 1991-10-30 | 3, 13 | no_violation | Vilvarajah: Art 3 asylum expulsion to Sri Lanka. No violation (contrast with Chahal). |
| McCANN AND OTHERS v. THE UNITED KINGDOM | `001-57943` | 18984/91 | 1995-09-27 | 2, 2-1, 2-2, 41 | violation | McCann: Gibraltar shootings. Violation of Art 2. GC. Neutrality eval. |
| CHAHAL v. THE UNITED KINGDOM | `001-58004` | 22414/93 | 1996-11-15 | 3, 5, 5-1, 5-1-f, 5-4, 8 … | mixed | Chahal: Art 3 bars deportation even for national-security threats. Violation. GC. |
| D. v. THE UNITED KINGDOM | `001-58035` | 30240/96 | 1997-05-02 | 2, 2-1, 3, 8, 13, 41 | mixed | D v UK: Art 3 and removal of a terminally ill man. Violation. |
| BENSAID v. THE UNITED KINGDOM | `001-59206` | 44599/98 | 2001-02-06 | 3, 8, 8-1, 8-2, 13 | no_violation | Bensaid: Art 3/8 and removal of a schizophrenic applicant. No violation. |
| PRETTY v. THE UNITED KINGDOM | `001-60448` | 2346/02 | 2002-04-29 | 2, 2-1, 3, 8, 8-1, 8-2 … | no_violation | Pretty: assisted dying, Art 2/8. No violation. Neutrality eval. |
| HIRST v. THE UNITED KINGDOM (No. 2) | `001-70442` | 74025/01 | 2005-10-06 | 10, 10-1, 14+P1-3, 14, P1-3, 41 | violation | Hirst (No. 2): prisoner voting ban, politically contested. Violation. GC. Neutrality eval. |
| SAADI v. THE UNITED KINGDOM | `001-84709` | 13229/03 | 2008-01-29 | 5, 5-1, 5-2, 5-1-f, 41 | mixed | Saadi v UK: detention of an asylum seeker (Art 5). GC. No violation of 5-1, violation of 5-2. |
| NNYANZI v. THE UNITED KINGDOM | `001-85726` | 21878/06 | 2008-04-08 | 3, 8, 8-2, 8-1, 29, 29-3 … | no_violation | Nnyanzi: Art 3 and Art 8 removal to Uganda. No violation on both. |
| N. v. THE UNITED KINGDOM | `001-86490` | 26565/05 | 2008-05-27 | 3, 29, 29-3 | no_violation | N v UK: Art 3 medical-case threshold, removal to Uganda. No violation. GC. |
| NA. v. THE UNITED KINGDOM | `001-87458` | 25904/07 | 2008-07-17 | 2, 3, 29, 29-3, 41 | violation | NA v UK: Art 3 and removal to Sri Lanka. Violation. |
| S. AND MARPER v. THE UNITED KINGDOM | `001-90051` | 30562/04; 30566/04 | 2008-12-04 | 8, 8-1, 8-2, 41, 46, 46-2 | violation | S. and Marper: DNA retention. Violation. GC. Neutrality eval. |
| JOSEPH GRANT v. THE UNITED KINGDOM | `001-90402` | 10606/07 | 2009-01-08 | 8, 8-1, 8-2 | no_violation | Joseph Grant: Art 8 deportation of an offender ALLOWED. No violation. |
| ONUR v. THE UNITED KINGDOM | `001-91286` | 27319/07 | 2009-02-17 | 8, 8-1, 8-2 | no_violation | Onur: Art 8 deportation of an offender ALLOWED. No violation. |
| A. AND OTHERS v. THE UNITED KINGDOM | `001-91403` | 3455/05 | 2009-02-19 | 3, 5, 5-1, 5-1-f, 5-4, 5-5 … | mixed | A and Others (Belmarsh): indefinite detention of terror suspects. GC. Neutrality eval. |
| OMOJUDI v. THE UNITED KINGDOM | `001-95777` | 1820/08 | 2009-11-24 | 8 | violation | Omojudi: Art 8 deportation of a settled offender. Violation. |
| KHAN A.W. v. THE UNITED KINGDOM | `001-96587` | 47486/06 | 2010-01-12 | 8, 8-2, 8-1 | violation | Khan A.W.: Art 8 deportation of a criminal. Violation. |
| AL-SAADOON AND MUFDHI v. THE UNITED KINGDOM | `001-97575` | 61498/08 | 2010-03-02 | 3, 6, 6-1, 13, 34, 41 … | mixed | Al-Saadoon and Mufdhi: Art 3 transfer to Iraqi custody. Violation. |
| S.H. v. THE UNITED KINGDOM | `001-99407` | 19956/06 | 2010-06-15 | 3 | violation | S.H. v UK: Art 3 expulsion. Violation. |
| SUFI AND ELMI v. THE UNITED KINGDOM | `001-105434` | 8319/07; 11449/07 | 2011-06-28 | 3 | violation | Sufi and Elmi: Art 3 and removal to Somalia. Violation. |
| AL-SKEINI AND OTHERS v. THE UNITED KINGDOM | `001-105606` | 55721/07 | 2011-07-07 | 1, 2, 2-1, 34, 41 | violation | Al-Skeini: UK jurisdiction extraterritorially (Iraq). GC. Neutrality eval. |
| AL-JEDDA v. THE UNITED KINGDOM | `001-105612` | 27021/08 | 2011-07-07 | 1, 5, 5-1, 41 | violation | Al-Jedda: internment in Iraq. Violation of Art 5-1. GC. Neutrality eval. |
| A.A. v. THE UNITED KINGDOM | `001-106282` | 8000/08 | 2011-09-20 | 8, 8-1, 8-2 | violation | A.A. v UK: Art 8 deportation of a young offender. Violation (contrast with Ndidi). |
| J.H. v. THE UNITED KINGDOM | `001-108157` | 48839/09 | 2011-12-20 | 3 | no_violation | J.H. v UK: Art 3 expulsion to Afghanistan. No violation. |
| A.H. KHAN v. THE UNITED KINGDOM | `001-108113` | 6222/10 | 2011-12-20 | 8, 8-1, 8-2, 3 | no_violation | A.H. Khan: Art 8 deportation of a drug offender ALLOWED. No violation. |
| OTHMAN (ABU QATADA) v. THE UNITED KINGDOM | `001-108629` | 8139/09 | 2012-01-17 | 3, 3+13, 5, 5-1, 6, 6-1 … | mixed | Othman (Abu Qatada): Art 3 not breached by deportation to Jordan, Art 6 flagrant denial. Eval: national-security expulsions. |
| HARKINS AND EDWARDS v. THE UNITED KINGDOM | `001-108599` | 9146/07; 32650/07 | 2012-01-17 | 2, 2-1, 3, 5, 5-1, 5-4 … | no_violation | Harkins and Edwards: Art 3 extradition to the US, life sentences. No violation. |
| BABAR AHMAD AND OTHERS v. THE UNITED KINGDOM | `001-110267` | 24027/07; 11949/08 … | 2012-04-10 | 3, 35 | no_violation | Babar Ahmad and Others: Art 3 extradition to the US (supermax). No violation. |
| BALOGUN v. THE UNITED KINGDOM | `001-110271` | 60286/09 | 2012-04-10 | 8 | no_violation | Balogun: Art 8 deportation of an offender ALLOWED. No violation. |
| HODE AND ABDI v. THE UNITED KINGDOM | `001-114244` | 22341/09 | 2012-11-06 | 8, 8-1, 14, 14+8, 41 | violation | Hode and Abdi: Art 14+8 refugee spouse residence. Violation. |
| S.H.H. v. THE UNITED KINGDOM | `001-116123` | 60367/10 | 2013-01-29 | 3 | no_violation | S.H.H.: Art 3 expulsion of a disabled Afghan. No violation. |
| ASWAT v. THE UNITED KINGDOM | `001-118583` | 17299/12 | 2013-04-16 | 3 | violation | Aswat: Art 3 extradition of a mentally ill applicant. Violation. |
| VINTER AND OTHERS v. THE UNITED KINGDOM | `001-122664` | 66069/09; 130/10 … | 2013-07-09 | 3, 41 | violation | Vinter and Others: whole-life sentences. Violation. GC. Neutrality eval. |
| NDIDI v. THE UNITED KINGDOM | `001-176931` | 41215/14 | 2017-09-14 | 8 | no_violation | Ndidi: Art 8 deportation of a criminal ALLOWED. No violation. Demo: 'deportation of a criminal allowed'. |
| UNUANE v. THE UNITED KINGDOM | `001-205796` | 80343/17 | 2020-11-24 | 35, 35-3-a, 8, 8-1, 8-2, 41 | violation | Unuane: Art 8 deportation of a man with family in the UK. Violation (2020). |
| OTITE v. THE UNITED KINGDOM | `001-219755` | 18339/19 | 2022-09-27 | 8, 8-1, 8-2 | no_violation | Otite: recent Art 8 deportation. No violation. |
| H.A. v. THE UNITED KINGDOM | `001-229321` | 30919/20 | 2023-12-05 | 3 | no_violation | H.A. v UK: recent Art 3 expulsion case. No violation. |
| HAYES AND OTHERS v. THE UNITED KINGDOM | `001-243879` | 56532/22; 56889/22 … | 2025-07-01 | 3 | no_violation | Hayes and Others: recent Art 3 extradition (whole-life risk). No violation. Recent-case eval. |

### Decisions (40)

**Inadmissible UK deportation / expulsion / extradition decisions (27)**: the count/stats demo
("how many UK deportation complaints were declared inadmissible, and why?"). All mention deportation,
expulsion, removal or extradition at least 10 times and raise Article 3 or 8 (checked by
`py/tests/test_snapshot_manifest.py`). The "Grounds found in the text" column is the output of the regex prototype
`scripts/g0b/grounds_regex.py` (see "Inadmissibility grounds" below). HUDOC's own `conclusion` states the ground
for only 18 of 671 inadmissible Court decisions, so the real stats pipeline has to extract grounds from the text.

| Case | Item ID | Application no. | Date | Articles | Outcome | Grounds found in the text (prototype) | Why it is here |
|---|---|---|---|---|---|---|---|
| ALIDJAH-ANYAME v. THE UNITED KINGDOM | `001-4596` | 39633/98 | 1999-05-04 | 3, 8, 8-1, 10, 11 | inadmissible | `manifestly_ill_founded` | Stats demo: inadmissible deportation/expulsion/extradition decision. |
| AJAYI AND OTHERS v. THE UNITED KINGDOM | `001-4648` | 27663/95 | 1999-06-22 | 3, 8, 8-1, 14 | inadmissible | `manifestly_ill_founded` | Stats demo: inadmissible deportation/expulsion/extradition decision. |
| T.I. v. THE UNITED KINGDOM | `001-5105` | 43844/98 | 2000-03-07 | 3, 13 | inadmissible | `manifestly_ill_founded` | Stats demo: inadmissible deportation/expulsion/extradition decision. |
| ZHU v. THE UNITED KINGDOM | `001-5425` | 36790/97 | 2000-09-12 | 3, 35, 35-1 | inadmissible | `manifestly_ill_founded` | Stats demo: inadmissible deportation/expulsion/extradition decision. |
| K.R.S. v. THE UNITED KINGDOM | `001-90500` | 32733/08 | 2008-12-02 | 3, 13, 5, 5-1-f | inadmissible | `manifestly_ill_founded` | Stats demo: inadmissible deportation/expulsion/extradition decision. |
| ANDREWS v. THE UNITED KINGDOM | `001-95232` | 46263/06 | 2009-09-29 | 3, 8 | inadmissible | `manifestly_ill_founded` | Stats demo: inadmissible deportation/expulsion/extradition decision. |
| KHAN MANWAR v. THE UNITED KINGDOM | `001-96380` | 19641/07 | 2009-12-08 | 8, 37, 37-1 | inadmissible | `manifestly_ill_founded` | Stats demo: inadmissible deportation/expulsion/extradition decision. |
| YESUFA v. THE UNITED KINGDOM | `001-97175` | 7347/08 | 2010-01-26 | 8 | inadmissible | `manifestly_ill_founded` | Stats demo: inadmissible deportation/expulsion/extradition decision. |
| MIAH v. THE UNITED KINGDOM | `001-98645` | 53080/07 | 2010-04-27 | 3, 7, 8 | inadmissible | `manifestly_ill_founded`, `incompatible_ratione_materiae` | Stats demo: inadmissible deportation/expulsion/extradition decision. |
| ANAM v. THE UNITED KINGDOM | `001-105173` | 21783/08 | 2011-06-07 | 2, 3, 8 | inadmissible | `manifestly_ill_founded` | Stats demo: inadmissible deportation/expulsion/extradition decision. |
| H.A.L. v. THE UNITED KINGDOM | `001-111361` | 61533/10 | 2012-05-22 | 2, 3, 35 | inadmissible | `manifestly_ill_founded` | Stats demo: inadmissible deportation/expulsion/extradition decision. |
| ABDI IBRAHIM v. THE UNITED KINGDOM | `001-113684` | 14535/10 | 2012-09-18 | 3, 8, 35 | inadmissible | `manifestly_ill_founded` | Stats demo: inadmissible deportation/expulsion/extradition decision. |
| M.S. v. THE UNITED KINGDOM | `001-114508` | 56090/08 | 2012-10-16 | 3, 8, 35 | inadmissible | `manifestly_ill_founded` | Stats demo: inadmissible deportation/expulsion/extradition decision. |
| F.A. v. THE UNITED KINGDOM | `001-127061` | 20658/11 | 2013-09-10 | 3, 4, 35 | inadmissible | `non_exhaustion` | Stats demo: inadmissible deportation/expulsion/extradition decision. |
| ISMAIL v. THE UNITED KINGDOM | `001-127160` | 48078/09 | 2013-09-17 | 5, 5-1-f, 5-4, 35, 35-3 | inadmissible | `incompatible_ratione_materiae` | Stats demo: inadmissible deportation/expulsion/extradition decision. |
| F.N. v. THE UNITED KINGDOM | `001-127188` | 3202/09 | 2013-09-17 | 3, 8, 35 | inadmissible | `manifestly_ill_founded` | Stats demo: inadmissible deportation/expulsion/extradition decision. |
| I.R. AND G.T. v. THE UNITED KINGDOM | `001-141330` | 14876/12; 63339/12 | 2014-01-28 | 8, 13, 13+8, 35 | inadmissible | `manifestly_ill_founded` | Stats demo: inadmissible deportation/expulsion/extradition decision. |
| IGNAOUA AND OTHERS v. THE UNITED KINGDOM | `001-142459` | 46706/08 | 2014-03-18 | 3, 13, 35 | inadmissible | `manifestly_ill_founded` | Stats demo: inadmissible deportation/expulsion/extradition decision. |
| ASWAT v. THE UNITED KINGDOM | `001-150856` | 62176/14 | 2015-01-06 | 3, 35 | inadmissible | `manifestly_ill_founded` | Stats demo: inadmissible deportation/expulsion/extradition decision. |
| I.A.A. AND OTHERS v. THE UNITED KINGDOM | `001-161986` | 25960/13 | 2016-03-08 | 1, 3, 8, 35 | inadmissible | `manifestly_ill_founded` | Stats demo: inadmissible deportation/expulsion/extradition decision. |
| K2 v. THE UNITED KINGDOM | `001-172143` | 42387/13 | 2017-02-07 | 8, 8-1, 14, 35, 35-3-a | inadmissible | `manifestly_ill_founded`, `non_exhaustion` | Stats demo: inadmissible deportation/expulsion/extradition decision. |
| J.M.O. v. THE UNITED KINGDOM | `001-172305` | 54318/14 | 2017-02-21 | 5, 5-1-f, 35 | inadmissible | `non_exhaustion` | Stats demo: inadmissible deportation/expulsion/extradition decision. |
| DRAGA v. THE UNITED KINGDOM | `001-173881` | 33341/13 | 2017-04-25 | 5, 5-1-f, 8, 35 | inadmissible | `manifestly_ill_founded` | Stats demo: inadmissible deportation/expulsion/extradition decision. |
| KHAKSAR v. THE UNITED KINGDOM | `001-182755` | 2654/18 | 2018-04-03 | 3, 8, 35, 35-1 | inadmissible | `non_exhaustion` | Stats demo: inadmissible deportation/expulsion/extradition decision. |
| OSAGIEDE v. THE UNITED KINGDOM | `001-223629` | 228/20 | 2023-02-07 | 8, 35 | inadmissible | `non_exhaustion` | Stats demo: inadmissible deportation/expulsion/extradition decision. |
| HAFEEZ v. THE UNITED KINGDOM | `001-224490` | 14198/20 | 2023-03-28 | 3, 6, 35 | inadmissible | `manifestly_ill_founded` | Stats demo: inadmissible deportation/expulsion/extradition decision. |
| HORNE v. THE UNITED KINGDOM | `001-231646` | 34392/21 | 2024-02-13 | 3, 35 | inadmissible | `manifestly_ill_founded` | Stats demo: inadmissible deportation/expulsion/extradition decision. |

**Other decisions (13)**: other outcomes for the breakdown (struck out, admissible, partly admissible)
and non-immigration decisions for neutrality questions.

| Case | Item ID | Application no. | Date | Articles | Outcome | Why it is here |
|---|---|---|---|---|---|---|
| BENSAID v. THE UNITED KINGDOM | `001-5038` | 44599/98 | 2000-01-25 | 3, 8, 8-1, 13 | admissible | Bensaid (dec.): admissible Art 3 removal case, precursor to the 2001 judgment. |
| Z. and T. v. THE UNITED KINGDOM | `001-72783` | 27034/05 | 2006-02-28 | 9, 9-1, 8, 8-1 | inadmissible | Z. and T.: Art 9 religion, inadmissible. Neutrality eval. |
| AL-SAADOON AND MUFDHI v. THE UNITED KINGDOM | `001-93398` | 61498/08 | 2009-06-30 | 1, 2, 2-1, 3, 6, 6-1 … | partly_inadmissible | Al-Saadoon and Mufdhi (dec.): partly admissible, precursor to the 2010 judgment. |
| BABAR AHMAD AND OTHERS v. THE UNITED KINGDOM | `001-99876` | 24027/07; 11949/08 … | 2010-07-06 | 2, 3, 5, 6, 6-1, 8 … | partly_inadmissible | Babar Ahmad and Others (dec.): partly admissible extradition decision, precursor to the 2012 judgment. |
| ALI v. THE UNITED KINGDOM | `001-115660` | 18815/11 | 2012-12-04 | 3, 8, 39 | struck_out | Ali: Art 3/8 complaints about deportation to Pakistan, struck out because the deportation order was revoked (Art 39). Stats: struck out. |
| CHAGOS ISLANDERS v. THE UNITED KINGDOM | `001-115714` | 35622/04 | 2012-12-11 | 1, 6, 34, 35, 35-3, 56 | inadmissible | Chagos Islanders: complaint about removal from and exclusion from the Chagos Islands, inadmissible. Politically contested: neutrality eval. |
| K.A.S. v. THE UNITED KINGDOM | `001-122048` | 38844/12 | 2013-06-04 | 37 | struck_out | K.A.S.: Art 8 complaint about extradition to the US, struck out (Art 37). Another non-inadmissible outcome for stats. |
| PINNOCK AND WALKER v. THE UNITED KINGDOM | `001-127560` | 31673/11 | 2013-09-24 | 8, 35 | inadmissible | Pinnock and Walker: Art 8 housing, inadmissible. |
| LE LIEVRE AND OTHERS v. THE UNITED KINGDOM | `001-161891` | 36522/15 | 2016-03-01 | 6, 14, 14+P1-3, 35, P1-3 | inadmissible | Le Lievre and Others: Sark's electoral system (Art P1-3 and Art 14), inadmissible. |
| TIMES NEWSPAPERS LIMITED AND KENNEDY v. THE UNITED KINGDOM | `001-188457` | 64367/14 | 2018-11-13 | 10, 10-1, 10-2, 35 | inadmissible | Times Newspapers and Kennedy: Art 10, inadmissible. |
| M.T. v. THE UNITED KINGDOM | `001-220259` | 63230/19 | 2022-09-22 | 3, 8, 39 | struck_out | M.T.: Art 3/8 complaints about deportation to the DRC, struck out after a friendly settlement (Art 39). Stats: struck out. |
| FIELD AND OTHERS v. THE UNITED KINGDOM | `001-225312` | 34442/18; 34472/18 … | 2023-05-16 | 14, 14+P1-3, P1-3, 35 | inadmissible | Field and Others: daughters of hereditary peers complain they cannot inherit peerages (Art 14 with P1-3), inadmissible. Constitutional and contested: neutrality eval. |
| N.S.K. v. THE UNITED KINGDOM | `001-237927` | 28774/22 | 2024-10-03 | 3, 37, 37-1 | struck_out | N.S.K.: Art 3 complaint about removal to Rwanda (asylum partnership) struck out because the applicant no longer pursued it. A non-inadmissible outcome for stats; recent. |

### Inadmissibility grounds (test oracle for S2)

Demo step 3 asks "why were they inadmissible?". HUDOC metadata rarely says, so each decision's ground(s) must be
read from its text at parse time (`inadmissibility_grounds_source = "text"`). The table below is what the regex
prototype `scripts/g0b/grounds_regex.py` finds for **every inadmissible or partly inadmissible decision in the
snapshot** (35). **It is prototype-derived**: for each decision the evidence sentence the regex
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
| `001-4596` | ALIDJAH-ANYAME v. THE UNITED KINGDOM | inadmissible | - | `manifestly_ill_founded` |
| `001-4648` | AJAYI AND OTHERS v. THE UNITED KINGDOM | inadmissible | - | `manifestly_ill_founded` |
| `001-5105` | T.I. v. THE UNITED KINGDOM | inadmissible | - | `manifestly_ill_founded` |
| `001-5425` | ZHU v. THE UNITED KINGDOM | inadmissible | - | `manifestly_ill_founded` |
| `001-72783` | Z. and T. v. THE UNITED KINGDOM | inadmissible | - | `manifestly_ill_founded` |
| `001-90500` | K.R.S. v. THE UNITED KINGDOM | inadmissible | - | `manifestly_ill_founded` |
| `001-93398` | AL-SAADOON AND MUFDHI v. THE UNITED KINGDOM | partly_inadmissible | - | `non_exhaustion` |
| `001-95232` | ANDREWS v. THE UNITED KINGDOM | inadmissible | - | `manifestly_ill_founded` |
| `001-96380` | KHAN MANWAR v. THE UNITED KINGDOM | inadmissible | - | `manifestly_ill_founded` |
| `001-97175` | YESUFA v. THE UNITED KINGDOM | inadmissible | - | `manifestly_ill_founded` |
| `001-98645` | MIAH v. THE UNITED KINGDOM | inadmissible | - | `manifestly_ill_founded`, `incompatible_ratione_materiae` |
| `001-99876` | BABAR AHMAD AND OTHERS v. THE UNITED KINGDOM | partly_inadmissible | - | `manifestly_ill_founded` |
| `001-105173` | ANAM v. THE UNITED KINGDOM | inadmissible | - | `manifestly_ill_founded` |
| `001-111361` | H.A.L. v. THE UNITED KINGDOM | inadmissible | - | `manifestly_ill_founded` |
| `001-113684` | ABDI IBRAHIM v. THE UNITED KINGDOM | inadmissible | - | `manifestly_ill_founded` |
| `001-114508` | M.S. v. THE UNITED KINGDOM | inadmissible | - | `manifestly_ill_founded` |
| `001-115714` | CHAGOS ISLANDERS v. THE UNITED KINGDOM | inadmissible | - | `manifestly_ill_founded`, `non_exhaustion` |
| `001-127061` | F.A. v. THE UNITED KINGDOM | inadmissible | - | `non_exhaustion` |
| `001-127160` | ISMAIL v. THE UNITED KINGDOM | inadmissible | - | `incompatible_ratione_materiae` |
| `001-127188` | F.N. v. THE UNITED KINGDOM | inadmissible | - | `manifestly_ill_founded` |
| `001-127560` | PINNOCK AND WALKER v. THE UNITED KINGDOM | inadmissible | - | `manifestly_ill_founded` |
| `001-141330` | I.R. AND G.T. v. THE UNITED KINGDOM | inadmissible | - | `manifestly_ill_founded` |
| `001-142459` | IGNAOUA AND OTHERS v. THE UNITED KINGDOM | inadmissible | - | `manifestly_ill_founded` |
| `001-150856` | ASWAT v. THE UNITED KINGDOM | inadmissible | - | `manifestly_ill_founded` |
| `001-161891` | LE LIEVRE AND OTHERS v. THE UNITED KINGDOM | inadmissible | - | `manifestly_ill_founded`, `incompatible_ratione_personae` |
| `001-161986` | I.A.A. AND OTHERS v. THE UNITED KINGDOM | inadmissible | - | `manifestly_ill_founded` |
| `001-172143` | K2 v. THE UNITED KINGDOM | inadmissible | `manifestly_ill_founded` | `manifestly_ill_founded`, `non_exhaustion` |
| `001-172305` | J.M.O. v. THE UNITED KINGDOM | inadmissible | - | `non_exhaustion` |
| `001-173881` | DRAGA v. THE UNITED KINGDOM | inadmissible | - | `manifestly_ill_founded` |
| `001-182755` | KHAKSAR v. THE UNITED KINGDOM | inadmissible | `non_exhaustion` | `non_exhaustion` |
| `001-188457` | TIMES NEWSPAPERS LIMITED AND KENNEDY v. THE UNITED KINGDOM | inadmissible | - | `non_exhaustion` |
| `001-223629` | OSAGIEDE v. THE UNITED KINGDOM | inadmissible | - | `non_exhaustion` |
| `001-224490` | HAFEEZ v. THE UNITED KINGDOM | inadmissible | - | `manifestly_ill_founded` |
| `001-225312` | FIELD AND OTHERS v. THE UNITED KINGDOM | inadmissible | - | `incompatible_ratione_materiae` |
| `001-231646` | HORNE v. THE UNITED KINGDOM | inadmissible | - | `manifestly_ill_founded` |

Entries whose **manifest** already carries grounds (`inadmissibility_grounds_source = "metadata"`), because HUDOC's
`conclusion` names them. Judgments and legal summaries appear here when the *remainder* of the application was
declared inadmissible:

| Item ID | Type | Outcome | Grounds |
|---|---|---|---|
| `001-172143` | decision | inadmissible | `manifestly_ill_founded` |
| `001-182755` | decision | inadmissible | `non_exhaustion` |
| `001-205796` | judgment | violation | `manifestly_ill_founded` |
| `002-11569` | legal_summary | inadmissible | `substantially_same`, `manifestly_ill_founded` |
| `002-11935` | legal_summary | inadmissible | `non_exhaustion` |
| `002-13006` | legal_summary | violation | `manifestly_ill_founded` |

### Legal summaries (15)

HUDOC Case-Law Information Note summaries (doc type `CLIN`). Short, unnumbered, each a different
"view" of a judgment in the snapshot: useful for checking that retrieval prefers the judgment's numbered
paragraphs when asked for citations.

| Case | Item ID | Application no. | Date | Articles | Outcome | Why it is here |
|---|---|---|---|---|---|---|
| Hirst v. the United Kingdom (no. 2) [GC] | `002-3706` | 74025/01 | 2005-10-06 | 10, 10-1, 14+P1-3, 14, P1-3, 41 | violation | Hirst (No. 2) [GC]: summary of 001-70442. Neutrality eval. |
| Saadi v. the United Kingdom [GC] | `002-2289` | 13229/03 | 2008-01-29 | 5, 5-1, 5-2, 5-1-f, 41 | mixed | Saadi [GC]: summary of 001-84709. |
| N. v. the United Kingdom [GC] | `002-2189` | 26565/05 | 2008-05-27 | 3, 29, 29-3 | no_violation | N. v UK [GC]: summary of 001-86490. |
| Omojudi v. the United Kingdom | `002-1238` | 1820/08 | 2009-11-24 | 8 | violation | Omojudi: summary of 001-95777. |
| Sufi and Elmi v. the United Kingdom | `002-460` | 8319/07; 11449/07 | 2011-06-28 | 3 | violation | Sufi and Elmi: summary of 001-105434. |
| Al-Skeini and Others v. the United Kingdom [GC] | `002-428` | 55721/07 | 2011-07-07 | 1, 2, 2-1, 34, 41 | violation | Al-Skeini [GC]: summary of 001-105606. Neutrality eval. |
| A.A. v. the United Kingdom | `002-400` | 8000/08 | 2011-09-20 | 8, 8-1, 8-2 | violation | A.A. v UK: summary of 001-106282. |
| Othman (Abu Qatada) v. the United Kingdom | `002-44` | 8139/09 | 2012-01-17 | 3, 5, 5-1, 6, 6-1, 13 … | mixed | Othman (Abu Qatada): summary of 001-108629. |
| Harkins and Edwards v. the United Kingdom | `002-74` | 9146/07; 32650/07 | 2012-01-17 | 2, 2-1, 3, 5, 5-1, 5-4 | no_violation | Harkins and Edwards: summary of 001-108599. |
| Babar Ahmad and Others v. the United Kingdom | `002-2139` | 24027/07; 11949/08 … | 2012-04-10 | 3, 35 | no_violation | Babar Ahmad and Others: summary of 001-110267. |
| Aswat v. the United Kingdom | `002-7466` | 17299/12 | 2013-04-16 | 3 | violation | Aswat: summary of 001-118583. |
| Harkins v. the United Kingdom (dec.) [GC] | `002-11569` | 71537/14 | 2017-06-15 | 3, 6, 35, 35-2-b, 35-3-a | inadmissible | Harkins (dec.) [GC]: extradition decision summary. |
| Khaksar v. the United Kingdom (dec.) | `002-11935` | 2654/18 | 2018-04-03 | 3, 8, 35, 35-1 | inadmissible | Khaksar (dec.): summary of an inadmissible expulsion decision (001-182755). |
| Unuane v. the United Kingdom | `002-13006` | 80343/17 | 2020-11-24 | 35, 35-3-a, 8, 8-1, 8-2, 41 | violation | Unuane: Art 8 deportation summary. |
| Hayes v. the United Kingdom | `002-14484` | 56532/22; 56889/22 … | 2025-07-01 | 3 | no_violation | Hayes and Others: summary of the 2025 extradition judgment (001-243879). |

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
