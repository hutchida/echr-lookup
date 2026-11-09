# Claude + MCP tools vs `/ask`

Gate 1 comparison eval (task M2). Claude answers the same questions two ways: **with the echr-lookup MCP tools** (Claude does the searching, reading and writing) and through the existing **`/ask` pipeline** (our code retrieves, one model writes, a second model checks each claim). Facts only here; the decision memo comes after the owner review.

## Setup

- **Host model with tools:** `claude-sonnet-5-5` through the Anthropic Messages API, system prompt = the server's `instructions`, the six tools exactly as the server lists them, prompt caching on the system prompt, the tools and the growing conversation, at most 8 tool calls per question (then it must answer without tools), thinking turned off the way `/ask` does.
- **Tool server:** `python -m echr_mcp --transport stdio`, one process for the whole run, database `echr_m2` (98 UK documents, snapshot). Embedder and reranker run locally.
- **`/ask`:** `rag.answer.answer(conn, {"question": q})` in-process, unchanged: router `claude-haiku-5-5`, answer `claude-sonnet-5-5`, claim check `claude-haiku-5-5`.
- **Judge:** `claude-sonnet-5-5` with the existing `judge_support` rubric (unchanged), the same judge for both systems. It also judges the owner-review prose checks, one call per answer.
- **Questions:** the 10 owner-review questions (status: draft) × 3 samples with tools and × 3 with `/ask` (or-10 is asked as a second turn after or-01 in the same conversation with tools; `/ask` is stateless, so it gets or-10 alone), and a fixed random retrieval subset of 30 questions from `data/eval/questions.jsonl` × 1 (seed `20261104`; ids in `data/eval/agentic/subset.json`).
- **When:** 2026-11-04 to 2026-11-04 (UTC). Raw per-answer results: `data/eval/agentic/results.jsonl`.

How each number is computed:

- *Claims*: the answer is split into sentences and bullets; a claim's citations are the paragraph ids it contains or the tool `cite` strings it contains (mapped through what the tools returned). `/ask` claims are its own claim list minus those its verifier marked unsupported (they are not in its answer text). A list introduced by a cited sentence inherits that citation.
- *Citation accuracy, per claim*: `judge_support` scores each claim 1 / ½ / 0 against all its cited paragraphs together; mean over the claims that cite something, then mean over answers. *Per citation*: the share of (claim, citation) pairs that support the claim on their own. Claims with no citation are not sent to the judge; they are counted as *uncited claims*.
- *Agentic recall* (subset only): share of the question's gold paragraphs (`expected_paragraph_ids`) among every paragraph id the model was shown. With tools: any paragraph id in any tool result (search hits, `get_paragraphs` including neighbours, operative provisions). For `/ask`: the paragraphs it put in its generation context.
- *Verbatim-quote rate*: every double-quoted passage of four or more words in the answer, attributed to the paragraphs cited by its claim and checked with `check_quote`; a quote with no citation counts as not verbatim. Pooled over quotes.
- *Shape checks*: the `checks` of `owner-review.jsonl`: deterministic ones in code, `judge` ones in one judge call; an answer passes if every applicable check passes. `tool_used count_cases` is met by `/ask` when it took its SQL stats route; `new_tool_calls` does not apply to `/ask`. `no_bare_yes_no` fails an answer whose first sentence starts with Yes or No and has no qualifier ("No, not as a general rule" passes; "No." fails).
- *Cost*: model calls that produce the answer (tools: every Messages call, cache writes at the cache-write price; `/ask`: its `total_cost_usd`); judging is extra and not in these rows.

## Side by side

> **After F1: not run.** The re-run needs the Anthropic key, which is at its usage limit until 2026-12-01 (or until the limit is raised); no paid call was made. The third column below is the planned re-run of Claude + tools against F1's server; every other number is the M2 run (2026-11-04), unchanged.

### Owner-review set

| | Claude + tools | `/ask` | Claude + tools, after F1 |
|---|---|---|---|
| answers scored | 30 | 30 | not run |
| shape checks: answers passing all | 22/30 (73%) | 16/30 (53%) | not run |
| citation accuracy, per claim (all its citations together; mean verdict 1 / ½ / 0) | 91% | 95% | not run |
| … share of claims fully supported | 86% | 90% | not run |
| citation accuracy, per citation | 92% | 95% | not run |
| claims per answer | 21.7 | 4.6 | not run |
| claims with no citation (share of all claims; not judged) | 65% | 7% | not run |
| verbatim-quote rate (quotes checked) | 69% (156) | n/a (0) | not run |
| … quote text found in any paragraph the model was shown (case ignored) | 97% | n/a | not run |
| tool calls per question | 4.0 | n/a | not run |
| tokens per question: input (uncached) | 8 | 11,984 | not run |
| … output | 1,552 | 999 | not run |
| … cache read / cache write | 24,540 / 9,207 | 1,783 / 0 | not run |
| cost per question (answering only) | $0.041 | $0.022 | not run |
| latency per question, mean (median), seconds | 17.2 (14.8) | 7.1 (8.0) | not run |

### Retrieval subset

| | Claude + tools | `/ask` | Claude + tools, after F1 |
|---|---|---|---|
| answers scored | 30 | 27 | not run |
| citation accuracy, per claim (all its citations together; mean verdict 1 / ½ / 0) | 94% | 96% | not run |
| … share of claims fully supported | 89% | 93% | not run |
| citation accuracy, per citation | 96% | 94% | not run |
| claims per answer | 23.4 | 6.0 | not run |
| claims with no citation (share of all claims; not judged) | 58% | 0% | not run |
| agentic recall (gold paragraphs the model was shown) | 60% | 23% | not run |
| … the same, against the wider answer key qrels-v2 | 51% | 27% | not run |
| verbatim-quote rate (quotes checked) | 65% (194) | n/a (0) | not run |
| … quote text found in any paragraph the model was shown (case ignored) | 95% | n/a | not run |
| tool calls per question | 4.0 | n/a | not run |
| tokens per question: input (uncached) | 8 | 13,854 | not run |
| … output | 1,674 | 1,425 | not run |
| … cache read / cache write | 19,585 / 10,218 | 2,356 / 0 | not run |
| cost per question (answering only) | $0.044 | $0.025 | not run |
| latency per question, mean (median), seconds | 17.7 (17.8) | 9.3 (8.8) | not run |

## Owner review, question by question

| id | question | Claude + tools: shape pass | `/ask`: shape pass | checks that failed (Claude + tools / `/ask`) | tool calls (mean) | cost: tools / ask |
|---|---|---|---|---|---|---|
| or-01 | Does the Convention stop the UK deporting criminals? | 3/3 | 0/3 | none / judge (States or implies the corpus scope (UK c…)×3 | 4.3 | $0.042 / $0.027 |
| or-02 | How has Article 8 been applied in UK immigration cases? | 1/3 | 2/3 | judge (Starts with a short direct answer, then …)×2 / judge (Starts with a short direct answer, then …)×1 | 7.3 | $0.076 / $0.025 |
| or-03 | Does the Convention apply to British troops in Iraq? | 2/3 | 0/3 | no_bare_yes_no×1 / judge (The opening sentence states under what c…)×3 | 3.7 | $0.042 / $0.029 |
| or-04 | How many UK deportation complaints in the corpus were declared inadmissible, and what were the most common reasons? | 3/3 | 3/3 | none / none | 2.7 | $0.023 / $0.000 |
| or-05 | How many Grand Chamber judgments are in the corpus, and how many of them found a violation? | 3/3 | 3/3 | none / none | 3.3 | $0.019 / $0.000 |
| or-06 | Does a ban on full-face veils breach Article 9? | 1/3 | 3/3 | judge (Does not present any case outside the co…)×2 / none | 3.0 | $0.026 / $0.020 |
| or-07 | Should the UK leave the ECHR? | 3/3 | 2/3 | none / judge (Presents cited points on more than one s…)×1 | 3.0 | $0.026 / $0.032 |
| or-08 | Can an applicant bring the same extradition complaint to the Court a second time because the Court's case law has changed since? | 3/3 | 0/3 | none / mentions ['Legal summary', 'legal summary']×3, judge (Makes clear the source is the Court's le…)×3 | 3.7 | $0.038 / $0.026 |
| or-09 | Can a person's own conduct, such as involvement in terrorism, justify deporting them to a country where they face torture? | 0/3 | 0/3 | quotes_verbatim×3, cites_paragraph 001-58004§79×1 / cites_paragraph 001-58004§79×3, quotes_contain irrespective of the victim's conduct×3 | 3.3 | $0.036 / $0.034 |
| or-10 | What about Article 8 specifically: when has the Court stopped a UK deportation on family-life grounds? | 3/3 | 3/3 | none / none | 6.0 | $0.082 / $0.025 |

## After F1: not run

<!-- after-f1:start -->
### After F1: what changed and what the re-run will answer

- **What F1 changed (merged, PR #30):** every hit and paragraph now has a readable `para_label` in its `cite` (for example "Law, para 2"), a `hudoc_url` that opens the document at the quoted words, and tighter server `instructions` (cite every factual sentence, quote only copied text, no cases from general knowledge, answer first). Paragraph ids are unchanged.
- **What the re-run will answer:** whether those changes alone cut uncited claims, non-verbatim quotes and outside cases (or-06) and raise the shape pass, and at what cost. The harness is ready (new cites and links map back to ids); the commands are in `docs/learn/F3.md`.
<!-- after-f1:end -->

## Transcripts (sample 1 of each, with tools)

### or-01: Does the Convention stop the UK deporting criminals?

Sample 1 of 3; 4 tool calls, $0.039, 17.6 s.

| # | tool | arguments | result |
|---|---|---|---|
| 1 | `corpus_info` | `{}` | 2,680 bytes |
| 2 | `search_case_law` | `{"query": "deportation of foreign criminal, Article 8 family life, proportionality, criteria", "limit": 8}` | 7,315 bytes |
| 3 | `search_case_law` | `{"query": "expulsion to country where risk of ill-treatment, absolute prohibition even for dangerous criminals", "article": "3", "limit": 6}` | 5,259 bytes |
| 4 | `search_case_law` | `{"query": "Üner criteria nature and seriousness of offence, length of stay, time elapsed since offence, solidity of ties", "article": "8", "doc_type": "judgment", "limit": 5}` | 4,801 bytes |

> **No, not as a general rule.** The Convention does not bar the UK from deporting people with criminal convictions. It limits deportation in two ways: an absolute bar where there is a real risk of torture or inhuman or degrading treatment, and a case-by-case proportionality test where family or private life is affected. The sample searched here is a small set of UK cases only, so this is a summary and not a complete account.
>
> **1. Absolute limit (Article 3).** A criminal record does not remove this protection.
> - Article 3 "is equally absolute in expulsion cases". Where there are "substantial grounds" for believing the person faces a real risk of treatment contrary to Article 3 if removed, the State's responsibility is engaged [Chahal v. the United Kingdom, Judgment, §80].
> - In such a case, "Article 3 is absolute and it is not possible to weigh the risk of ill-treatment against the reasons put forward for the expulsion" [Othman (Abu Qatada) v. the United Kingdom, Judgment, §185].
> - This is narrower than it may sound. Article 3 mainly applies where the risk comes from deliberate acts of the receiving State's authorities, or from non-State bodies that the authorities cannot control [F.N. v. the United Kingdom, Decision, §28]. In some cases the Court has found no violation, for example [N. v. the United Kingdom, Judgment, §30] and [Babar Ahmad and Others v. the United Kingdom, Judgment, §171].
>
> **2. Qualified limit (Article 8).** Here the Court balances the interests involved.
> - Deportation of a settled migrant will almost always interfere with private life, but that is only the first step. "It will be a rare case where a settled migrant will be unable to demonstrate that his or her deportation would interfere with his or her private life", and the strength of the person's ties is usually weighed when assessing proportionality [A.H. Khan v. the United Kingdom, Judgment, §32].
> - The Court looks at the nature and seriousness of the offence, the length of stay, the time since the offence and the person's conduct since, and the strength of ties to the UK and to the destination country [Balogun v. the United Kingdom, Judgment, §48]. These are the criteria from *Üner*, which the Court applies in UK cases.
> - Outcomes go both ways. The Court found no violation in [A.H. Khan v. the United Kingdom, Judgment, §32], [Balogun v. the United Kingdom, Judgment, §43] and [Otite v. the United Kingdom, Judgment, §u4]. It found a violation in [A.A. v. the United Kingdom, Judgment, §49] (a young adult deportee) and in [Unuane v. the United Kingdom, Judgment, §72].
> - In *Omojudi*, the Court's summary says only the offence committed after the applicant was granted indefinite leave to remain was relevant to proportionality, because the Home Office already knew his earlier offending history. It found a violation [Omojudi v. the United Kingdom, Legal summary, §u5]. This is the Court's digest of the case, not the judgment.
>
> **In short:** the Convention does not give criminals immunity from deportation. It rules out removal to a real risk of Article 3 ill-treatment and requires a proportionality assessment where Article 8 rights are engaged. Many UK deportations have been upheld, and some have been found disproportionate.
>
> The sample is small, so other relevant cases may not appear here. The UK's own domestic rules on deportation are outside this corpus.

Shape checks: no_bare_yes_no ✓, cites_min ✓, mentions ✓, mentions ✓, judge ✓, judge ✓.

### or-02: How has Article 8 been applied in UK immigration cases?

Sample 1 of 3; 8 tool calls, $0.078, 28.8 s.

| # | tool | arguments | result |
|---|---|---|---|
| 1 | `corpus_info` | `{}` | 2,680 bytes |
| 2 | `search_case_law` | `{"query": "Article 8 family life deportation of settled migrant, proportionality, fair balance", "article": "8", "limit": 10}` | 8,809 bytes |
| 3 | `search_case_law` | `{"query": "refusal of entry or residence to spouse; positive obligation to admit family members immigration control", "article": "8", "limit": 10}` | 8,920 bytes |
| 4 | `search_case_law` | `{"query": "Court finds deportation disproportionate: young age at entry, offence, ties to UK, no ties to country of origin", "article": "8", "outcome": "violation", "limit": 6}` | 5,335 bytes |
| 5 | `search_case_law` | `{"query": "Otite foreign criminal deportation Immigration Rules section 117C margin of appreciation domestic courts balancing", "article": "8", "year_from": 2015, "limit": 6}` | 5,054 bytes |
| 6 | `search_case_law` | `{"query": "Boultif Üner criteria nature and seriousness of offence, length of stay, solidity of social cultural family ties", "article": "8", "limit": 6}` | 4,558 bytes |
| 7 | `get_paragraphs` | `{"paragraph_ids": ["001-205796§81", "001-205796§82"], "neighbours": 1}` | 4,892 bytes |
| 8 | `search_case_law` | `{"query": "Hode and Abdi refugee spouse family reunion discrimination Article 14 with Article 8", "limit": 3}` | 2,461 bytes |

> In UK immigration cases, the Court has treated Article 8 mainly as a proportionality test, which has produced both violations and no-violation findings depending on the facts. This answer rests on a small sample of UK cases (98 documents), so it illustrates the case law and is not a complete survey.
>
> **1. Expulsion of settled migrants is usually an interference, so the dispute is over proportionality**
>
> - The Court accepts that "the totality of social ties between settled migrants and the community in which they are living constitutes part of the concept of 'private life'", whether or not there is a "family life" [Miah v. the United Kingdom, Decision, §16].
> - It follows that "it will be a rare case where a settled migrant will be unable to demonstrate that his or her deportation would interfere with his or her private life". The comparative strength of the ties is "in the majority of cases, more appropriately considered in assessing the proportionality" under Article 8 § 2 [Balogun v. the United Kingdom, Judgment, §43]. A.H. Khan v. the United Kingdom repeats the same passage at §32.
>
> **2. The Boultif/Üner criteria structure the balancing**
>
> - Üner added two criteria to those in Boultif. These are "the best interests and well-being of the children" and "the solidity of social, cultural and family ties with the host country and with the country of destination" [Otite v. the United Kingdom, Judgment, §37]. The same criteria appear in Omojudi [Omojudi v. the United Kingdom, Judgment, §41] and Onur [Onur v. the United Kingdom, Judgment, §54].
>
> **3. Outcomes in criminal deportation cases turn on the facts**
>
> - **Violations:**
>   - In A.W. Khan the Court relied on the length of residence, "very young age at the time of his entry", the lack of continuing ties to Pakistan, strong UK ties, and the absence of reoffending after release [Khan A.W. v. the United Kingdom, Judgment, §50].
>   - In Omojudi it relied on "the strength of the applicant's family ties to the United Kingdom, his length of residence, and the difficulty that his youngest children would face if they were to relocate to Nigeria" [Omojudi v. the United Kingdom, Judgment, §48].
>   - In A.A. the deportation was held disproportionate to the aim of preventing disorder and crime [A.A. v. the United Kingdom, Judgment, §69].
> - **No violation:** Balogun, A.H. Khan, Onur and Otite. Several further applications were declared inadmissible, for example Miah and Anam.
>
> **4. Domestic rules on "foreign criminals"**
>
> - In Unuane (2020) the applicant argued that the Immigration Rules and section 117C of the 2002 Act, with their "exceptional" or "very compelling circumstances" tests, prevented a proper proportionality assessment [Unuane v. the United Kingdom, Judgment, §80].
> - The Court noted that the domestic courts, and the Government before it, said that the rules leave scope for all relevant factors to be considered [Unuane v. the United Kingdom, Judgment, §81].
> - It also noted the Supreme Court's statement that appellate tribunals must make their own assessment of proportionality, using a "balance sheet" approach [Unuane v. the United Kingdom, Judgment, §82].
> - It concluded that "the Immigration Rules [do not] necessarily preclude the domestic courts and tribunals from employing the Boultif criteria" [Unuane v. the United Kingdom, Judgment, §83]. The corpus lists Unuane as a violation case overall. I did not read the part of the judgment explaining why, so I cannot say what the violation rested on.
> - In Otite the Court again described the rules in paragraphs 398-399D as a framework for deciding when private and family life outweighs the public interest in deportation [Otite v. the United Kingdom, Judgment, §11]. It found no violation.
>
> **5. Entry and family reunion**
>
> - **General rule:** Article 8 "cannot be considered to impose on a State a general obligation to respect the choice by married couples of the country of their matrimonial residence and to authorise family reunification in its territory" [I.A.A. and Others v. the United Kingdom, Decision, §39]. That application was inadmissible.
> - **Limits of the rule:** Even so, "it is not to be excluded that measures taken in the field of immigration may affect the right to respect for family life under Article 8" [Abdulaziz, Cabales and Balkandali v. the United Kingdom, Judgment, §60]. That case, from 1985, ended with a violation finding, including under Article 14 with Article 8.
> - **Relevant factors:** Whether exclusion is compatible with Article 8 depends on how far family life is ruptured, the ties in the state, whether there are "insurmountable obstacles" to living in the country of origin, and immigration-control or public-order factors [Ajayi and Others v. the United Kingdom, Decision, §u62].
> - **Adult children:** There is generally no family life between parents and adult children "unless they can demonstrate additional elements of dependence" [Yesufa v. the United Kingdom, Decision, §u24].
> - **Refugee spouses:** Hode and Abdi (2012) concerned the family-reunion rules for a refugee's spouse who had married after he left his country. The Court found a violation under Article 14 with Article 8 [Hode and Abdi v. the United Kingdom, Judgment, §7]. I did not review its reasoning.
>
> **Limits of this answer:** I did not search post-2012 entry-clearance or private-life-in-the-UK cases, so this covers deportation and a few family-reunion cases only. I also did not check domestic case law beyond what Strasbourg judgments summarise.

Shape checks: cites_min ✓, distinct_cases_min ✓, judge ✗.

### or-03: Does the Convention apply to British troops in Iraq?

Sample 1 of 3; 3 tool calls, $0.034, 14.5 s.

| # | tool | arguments | result |
|---|---|---|---|
| 1 | `search_case_law` | `{"query": "jurisdiction of UK over acts of British troops in Iraq, Article 1 extraterritorial", "limit": 10}` | 9,542 bytes |
| 2 | `corpus_info` | `{}` | 2,680 bytes |
| 3 | `search_case_law` | `{"query": "State agent authority and control over individuals; Iraqi detained in British-run detention facility within jurisdiction", "limit": 6, "year_from": 2009}` | 5,786 bytes |

> **Yes, in some circumstances.** The Court has held that the Convention applied to British forces in Iraq in two situations: where the UK exercised authority and control over detainees, and where its soldiers were carrying out security operations in south-east Iraq during the period of UK responsibility for security there. It has not held that the Convention applies to every act of British troops everywhere in Iraq.
>
> **1. Security operations in south-east Iraq (Al-Skeini, Grand Chamber, 2011).** The Court found that the UK had "assumed authority and responsibility for the maintenance of security in south-east Iraq". In those "exceptional circumstances", UK soldiers on security operations in Basra "exercised authority and control over individuals killed in the course of such security operations, so as to establish a jurisdictional link between the deceased and the United Kingdom for the purposes of Article 1 of the Convention" [Al-Skeini and Others v. the United Kingdom, Judgment, §149]. The Court described this as an "exceptional" basis for jurisdiction. The Chagos Islanders decision later restated the holding in the same limited terms [Chagos Islanders v. the United Kingdom, Decision, §70].
>
> **2. Detention in British-run facilities.** The Court has held that Iraqis held in British-controlled military prisons were within UK jurisdiction, because the UK had "total and exclusive control over the prisons and the individuals detained in them" [Al-Skeini and Others v. the United Kingdom, Judgment, §136], summarising the Al-Saadoon and Mufdhi decision. In Al-Saadoon the Court reasoned that the facilities were established on Iraqi territory through military force. It also found that the UK's de facto control over them was later reflected in law [Al-Saadoon and Mufdhi v. the United Kingdom, Decision, §87]. In the 2010 judgment it added that UK forces "took active steps to bring the applicants within the United Kingdom's jurisdiction, by arresting them and holding them in British-run detention facilities" [Al-Saadoon and Mufdhi v. the United Kingdom, Judgment, §140].
>
> **Concessions and the domestic courts.** The UK Government conceded jurisdiction in Baha Mousa's case, where he was in the custody of British troops [Al-Saadoon and Mufdhi v. the United Kingdom, Decision, §62]. In Al-Jedda it had conceded jurisdiction over a man held in a British-run military prison, then argued that the detention was attributable to the UN [Al-Jedda v. the United Kingdom, Judgment, §69]. The House of Lords had earlier held that the UK did not have jurisdiction over most of the Al-Skeini deaths. The Strasbourg Court took a different view for the deaths during security operations [Al-Skeini and Others v. the United Kingdom, Judgment, §84].
>
> **Limits of this answer.** The corpus is a small sample of UK cases, not the full HUDOC database. I have not covered later Iraq-related case law, such as the Court's treatment of the other issues raised by the Iraq cases, or any decisions outside the sample.

Shape checks: no_bare_yes_no ✓, mentions ✓, judge ✓.

### or-04: How many UK deportation complaints in the corpus were declared inadmissible, and what were the most common reasons?

Sample 1 of 3; 3 tool calls, $0.029, 7.3 s.

| # | tool | arguments | result |
|---|---|---|---|
| 1 | `count_cases` | `{"topic": "deportation", "outcomes": ["inadmissible"], "count_of": "total_and_subset", "group_by": "none"}` | 7,241 bytes |
| 2 | `count_cases` | `{"topic": "deportation", "outcomes": ["inadmissible"], "count_of": "total", "group_by": "reason"}` | 7,037 bytes |
| 3 | `corpus_info` | `{}` | 2,680 bytes |

> **27 of the 67 deportation-type cases in the corpus were declared inadmissible in their entirety.** The 67 are judgments and decisions about deportation, expulsion, removal or extradition.
>
> **Reasons given:**
>
> | Ground | Documents |
> |---|---|
> | Manifestly ill-founded | 22 |
> | Domestic remedies not exhausted | 4 |
> | Outside the Convention's subject matter (incompatible *ratione materiae*) | 2 |
>
> The rows add up to more than 27 because a decision can rest on more than one ground. Manifestly ill-founded is by far the most common reason.
>
> **Definitions and limits:**
> - "Declared inadmissible" means the whole application was rejected. Two further matching decisions were only partly inadmissible and are not counted.
> - HUDOC has no topic field, so a "deportation" case is one that raises Article 3, 8 or 5(1)(f) and has at least two paragraphs containing deport-, expel-, expulsion, extradit- or removal.
> - The corpus is a small sample of 98 UK documents (a snapshot, not the full HUDOC download), so these figures describe the sample only. They do not show how the Court has ruled on all UK deportation complaints.
> - The 27 cases run from 2009 to 2024. They include Horne (2024), Hafeez (2023), Osagiede (2023), Aswat (2015) and Khan Manwar (2009).

Shape checks: tool_used ✓, judge ✓.

### or-05: How many Grand Chamber judgments are in the corpus, and how many of them found a violation?

Sample 1 of 3; 2 tool calls, $0.016, 6.6 s.

| # | tool | arguments | result |
|---|---|---|---|
| 1 | `count_cases` | `{"count_of": "total_and_subset", "chambers": ["Grand Chamber"], "doc_types": ["judgment"], "outcomes": ["violation", "mixed"]}` | 4,001 bytes |
| 2 | `corpus_info` | `{}` | 2,680 bytes |

> The corpus holds **10 Grand Chamber judgments**, and **9 of them found at least one violation**.
>
> **How the count works**
> - "Found a violation" includes judgments with only violation findings and "mixed" judgments (at least one violation and at least one no-violation finding).
> - Only judgments are counted. Decisions, communicated cases and legal summaries are excluded.
> - Grand Chamber status comes from HUDOC's chamber field.
>
> **The 9 judgments with a violation**
> - McCann and Others v. the United Kingdom (1995): violation
> - Chahal v. the United Kingdom (1996): mixed
> - Hirst v. the United Kingdom (No. 2) (2005): violation
> - Saadi v. the United Kingdom (2008): mixed
> - S. and Marper v. the United Kingdom (2008): violation
> - A. and Others v. the United Kingdom (2009): mixed
> - Al-Skeini and Others v. the United Kingdom (2011): violation
> - Al-Jedda v. the United Kingdom (2011): violation
> - Vinter and Others v. the United Kingdom (2013): violation
>
> The tool listed only these nine, so I cannot say from this result which case is the tenth or how it ended.
>
> **Coverage:** The corpus contains only cases against the UK, and this is a small sample of 98 documents, not the full HUDOC download of about 3,500 UK documents. These figures describe the sample, so the Court may have decided other UK Grand Chamber cases that are not included here.

Shape checks: tool_used ✓, contains_numbers ✓, judge ✓.

### or-06: Does a ban on full-face veils breach Article 9?

Sample 1 of 3; 3 tool calls, $0.026, 11.4 s.

| # | tool | arguments | result |
|---|---|---|---|
| 1 | `corpus_info` | `{}` | 2,680 bytes |
| 2 | `search_case_law` | `{"query": "ban on full-face veil burqa niqab Article 9 manifestation of religion", "limit": 10}` | 7,732 bytes |
| 3 | `search_case_law` | `{"query": "religious dress headscarf veil restriction in public, living together, concealing face", "limit": 6}` | 4,426 bytes |

> **Not necessarily. The sourced material available to me doesn't contain a full-face veil case, so I can't give you the Court's ruling on one from this corpus.** The corpus is a small sample of UK-only cases. The Court's veil cases (for example, those against France and Belgium) are not in it, so "not found here" does not mean the Court never decided the question.
>
> **What the corpus does support**
>
> - Article 9(1) protects the right to manifest religion or belief "in worship, teaching, practice and observance", alone or in community, in public or in private. [Human Rights Act 1998, Legislation, §sch1-art9]
> - Not every act motivated by religion counts as a protected manifestation. The Court has said that Article 9 "does not protect every act motivated or inspired by a religion or belief." [Z. and T. v. the United Kingdom, Decision, §u26]
> - The term "practice" in Article 9(1) "does not cover each act which is motivated or influenced by a religion or belief." [Pretty v. the United Kingdom, Judgment, §82]
> - Article 9 also protects manifesting religion "not only in community with others, in public and within the circle of those whose faith one shares, but also alone and in private". [Z. and T. v. the United Kingdom, Decision, §u26]
>
> **What this means for a veil ban**
>
> From the Convention text alone, a restriction on religious dress would be assessed in two steps. First, is wearing the veil a manifestation of religion or belief that engages Article 9(1)? Second, if so, is the restriction justified under Article 9(2), which is not quoted in the passages above?
>
> The answer therefore turns on the Court's veil case-law and the margin of appreciation it gives states. Those are outside this sample, so for a definitive answer you would need to consult HUDOC directly.

Shape checks: judge ✓, judge ✗.

### or-07: Should the UK leave the ECHR?

Sample 1 of 3; 3 tool calls, $0.027, 13.5 s.

| # | tool | arguments | result |
|---|---|---|---|
| 1 | `corpus_info` | `{}` | 2,680 bytes |
| 2 | `search_case_law` | `{"query": "margin of appreciation national authorities better placed than international court; subsidiarity", "limit": 5}` | 4,878 bytes |
| 3 | `search_case_law` | `{"query": "prisoners voting ban blanket restriction violation Parliament debate", "limit": 5}` | 3,785 bytes |

> Whether the UK should leave the ECHR is a political and value question, and I take no side. The case law can show what each side points to. The corpus here is a small sample of UK cases (98 documents), so it illustrates the arguments and doesn't settle them.
>
> **Points made by those who favour staying or reforming**
>
> - **The Court gives states latitude.** It says national authorities "enjoy a margin of appreciation in recognition of the fact that they are better placed than international courts to evaluate local needs and conditions" [Pinnock and Walker v. the United Kingdom, Decision, §28].
>   - The Court "will generally respect the legislature's policy choice unless it is 'manifestly without reasonable foundation'" on economic and social strategy [Hode and Abdi v. the United Kingdom, Judgment, §52].
>   - On emergencies, it leaves a wide margin to national authorities, including domestic courts [A. and Others v. the United Kingdom, Judgment, §173; §174].
>   - The Court describes its own role as "supervisory", "subject to the principle of subsidiarity" [A. and Others v. the United Kingdom, Judgment, §174].
> - **Many UK applications fail.** In this sample, 35 of the 98 documents are whole-application inadmissibility decisions. That is only a sample figure, not a national rate.
> - **Supporters also point to the substance of the rulings.** In the sample, the Court found violations in cases such as the blanket prisoner voting ban [Hirst v. the United Kingdom (No. 2), Judgment, §79] and in the internment-related rulings in A. and Others and Ireland v. the United Kingdom.
>
> **Points made by those who favour leaving or curbing the Court's role**
>
> - **The Court can override Parliament.** In Hirst (No. 2), it found a violation partly because there had been no "substantive debate by members of the legislature" on the ban [Hirst v. the United Kingdom (No. 2), Judgment, §79].
>   - Critics note that the dissenting judges objected that the majority wrongly treated the law as passive adherence to tradition [Hirst v. the United Kingdom (No. 2), Judgment, §u39]. The UK government argued the policy had Parliament's explicit approval, most recently in the Representation of the People Act 2000, which carried a Human Rights Act compatibility statement [Hirst v. the United Kingdom (No. 2), Judgment, §47].
>   - On this view, an international court was second-guessing a democratic decision.
> - **The margin of appreciation varies.** The Court itself says the margin "will vary depending on the Convention right in issue and its importance for the individual" [Pinnock and Walker v. the United Kingdom, Decision, §28]. Critics say this makes outcomes harder to predict.
>
> **What the corpus can't tell you**
>
> Leaving would involve questions this sample doesn't address:
> - the effect on the Human Rights Act 1998, which I haven't analysed here
> - the Northern Ireland peace settlement
> - other treaties and trade relationships
> - whether domestic reform or a Bill of Rights could achieve similar aims
>
> I can look further into specific areas, such as deportation, Article 3, or how the UK has responded to adverse judgments.

Shape checks: judge ✓, judge ✓, cites_min ✓.

### or-08: Can an applicant bring the same extradition complaint to the Court a second time because the Court's case law has changed since?

Sample 1 of 3; 3 tool calls, $0.032, 14.5 s.

| # | tool | arguments | result |
|---|---|---|---|
| 1 | `search_case_law` | `{"query": "extradition complaint substantially the same as previous application already examined by the Court; change in case law not a new fact"}` | 6,158 bytes |
| 2 | `search_case_law` | `{"query": "Article 35 § 2 (b) substantially the same matter, new relevant information, repeat application"}` | 6,909 bytes |
| 3 | `count_cases` | `{"grounds": ["substantially_same"], "topic": "deportation", "count_of": "total"}` | 2,053 bytes |

> **No, not as a general rule.** In *Harkins v. the United Kingdom* (Grand Chamber decision, 2017), an extradition case, the Court held that a later development in its own case law is not "relevant new information", so a repeat complaint is inadmissible.
>
> **The rule.** Article 35 § 2(b) of the Convention says the Court shall not deal with an application that "is substantially the same as a matter that has already been examined by the Court … and contains no relevant new information" ([Convention, Art. 35](https://www.echr.coe.int/documents/d/echr/convention_eng)).
>
> **What *Harkins* decided.** The sources below are the Court's own legal summary of the decision, not the decision text.
> - **Same complaint.** An application generally falls foul of the first limb of Article 35 § 2(b) where the applicant "had previously brought an application which related essentially to the same person, the same facts and raised the same complaints." Mr Harkins's Article 3 complaint was substantially the same as his earlier one, and the underlying facts had not changed ([Harkins, Legal summary, §u8](https://hudoc.echr.coe.int/eng?i=002-11569)).
> - **Case-law developments.** The Court held that "the development in the Court's jurisprudence did not constitute 'relevant new information' for the purposes of Article 35 § 2 (b)." Its reasoning was that the case law is "constantly evolving". If such developments let unsuccessful applicants reintroduce their complaints, "final judgments would continually be called into question by the lodging of fresh applications" ([Harkins, Legal summary, §u12](https://hudoc.echr.coe.int/eng?i=002-11569)).
> - **Purpose.** The rule serves "the interests of finality and legal certainty by preventing an applicant from seeking, through lodging a fresh application, to appeal against previous judgments or decisions" ([Harkins, Legal summary, §u10](https://hudoc.echr.coe.int/eng?i=002-11569)).
> - **Equal treatment of the parties.** Legal certainty would not apply equally to both parties if "only an applicant, on the basis of subsequent jurisprudential developments, would effectively be permitted to 'reopen' previously examined cases" ([Harkins, Legal summary, §u12](https://hudoc.echr.coe.int/eng?i=002-11569)).
> - **New domestic proceedings.** Whether recent domestic proceedings amount to relevant new information was "inextricably linked" to whether the case-law development does. New proceedings built on the same case-law change therefore do not help ([Harkins, Legal summary, §u9](https://hudoc.echr.coe.int/eng?i=002-11569)).
>
> **Limits of this answer.**
> - The exception is in the text of Article 35 § 2(b). A repeat application can still be admissible if it contains relevant new information, meaning a genuine change in the facts. The case-law change itself does not count.
> - *Aswat v. the United Kingdom* shows a case where the Court looked at "new factual information" in an extradition matter. I did not read it closely enough to describe its outcome ([Aswat, Decision, §23](https://hudoc.echr.coe.int/eng?i=001-150856)).
> - The corpus is a small UK-only sample. It holds no other deportation or extradition decision declared inadmissible as "substantially the same", so I rely on *Harkins* alone. I could only retrieve the legal summary, so check the full decision text before quoting the Court's own wording.

Shape checks: cites_doc ✓, mentions ✓, judge ✓.

### or-09: Can a person's own conduct, such as involvement in terrorism, justify deporting them to a country where they face torture?

Sample 1 of 3; 3 tool calls, $0.031, 14.6 s.

| # | tool | arguments | result |
|---|---|---|---|
| 1 | `search_case_law` | `{"query": "deportation of terrorist suspect to country where risk of torture; Article 3 absolute, conduct of the applicant irrelevant", "article": "3", "limit": 8}` | 7,191 bytes |
| 2 | `corpus_info` | `{}` | 2,680 bytes |
| 3 | `search_case_law` | `{"query": "activities of the individual cannot be a material consideration; threat to national security cannot be weighed against risk of ill-treatment", "limit": 5}` | 4,582 bytes |

> **No.** Under Article 3, a person's own conduct, including involvement in terrorism, cannot justify deporting them to a country where they face a real risk of torture or inhuman or degrading treatment. This rests on the Court's UK case law in this corpus, which is a small sample of UK cases only, so other cases may add detail.
>
> **The rule**
> - In *Chahal v. the United Kingdom*, the Court acknowledged "the immense difficulties faced by States in modern times in protecting their communities from terrorist violence". It nonetheless held that "the Convention prohibits in absolute terms torture or inhuman or degrading treatment or punishment, irrespective of the victim's conduct" [Chahal v. the United Kingdom, Judgment, §79].
> - It applied this directly to expulsion: where there is a real risk of Article 3 treatment, "the activities of the individual in question, however undesirable or dangerous, cannot be a material consideration" [Chahal v. the United Kingdom, Judgment, §80].
> - The Court has repeated this in later cases: "the nature of the offence allegedly committed by the applicants is irrelevant for the purposes of Article 3" [Sufi and Elmi v. the United Kingdom, Judgment, §212]. See also [Al-Saadoon and Mufdhi v. the United Kingdom, Judgment, §122] and [Abdi Ibrahim v. the United Kingdom, Decision, §28].
> - Article 3 allows no derogation, even in a public emergency, and applies "even in the most difficult of circumstances, such as the fight against terrorism, and irrespective of the conduct of the person concerned" [A. and Others v. the United Kingdom, Judgment, §126].
>
> **What the State can still do**
> - States may deport people they regard as national security threats. The Court said in *Othman (Abu Qatada)* that it is "no part of this Court's function to review whether an individual is in fact such a threat". Its only task is to assess whether deportation is compatible with the Convention [Othman (Abu Qatada) v. the United Kingdom, Judgment, §184].
> - The question is therefore whether the risk of ill-treatment is real. If it is not, the person's conduct does not make removal unlawful.
>
> **The UK argument the Court rejected**
> The UK argued that, where the risk of ill-treatment was open to doubt, the threat to national security could weigh heavily in the balance [Chahal v. the United Kingdom, Judgment, §76]. The Court did not accept that national security can be weighed against a proven real risk of Article 3 treatment, as §§79–80 above show. This section of the judgment also appears in the corpus in a different, summary-style form, which says that the greater the risk of ill-treatment, the less weight the security threat carries [Chahal v. the United Kingdom, Judgment, §u59].
>
> The snapshot also holds *Aswat* and *Abdi Ibrahim*, both decisions declared inadmissible, which restate the same principle [Aswat v. the United Kingdom, Decision, §28]. I have not covered the separate question of "diplomatic assurances" from the receiving State, which is how *Othman* was resolved on the risk assessment.

Shape checks: cites_paragraph ✓, quotes_contain ✓, quotes_verbatim ✗.

### or-10: What about Article 8 specifically: when has the Court stopped a UK deportation on family-life grounds?

*Second turn of a conversation: asked after or-01; the model also had that turn's tool results.*

Sample 1 of 3; 7 tool calls, $0.086, 28.7 s.

| # | tool | arguments | result |
|---|---|---|---|
| 1 | `search_case_law` | `{"query": "deportation would violate Article 8 family life; violation found, expulsion disproportionate", "article": "8", "outcome": "violation", "limit": 10}` | 8,178 bytes |
| 2 | `count_cases` | `{"topic": "deportation", "articles": ["8"], "count_of": "total", "group_by": "outcome"}` | 6,711 bytes |
| 3 | `search_case_law` | `{"query": "Court's conclusion: deportation disproportionate, balance of offence seriousness against length of residence, ties, children, time since offending", "article": "8", "outcome": "violation", "doc_type": "judgment", "limit": 10}` | 9,261 bytes |
| 4 | `get_paragraphs` | `{"paragraph_ids": ["001-96587§35", "001-106282§69", "001-106282§70"], "neighbours": 1}` | 6,550 bytes |
| 5 | `search_case_law` | `{"query": "deportation of settled migrant with criminal record found proportionate, no violation of Article 8", "article": "8", "outcome": "no_violation", "limit": 5}` | 3,378 bytes |
| 6 | `search_case_law` | `{"query": "Khan A.W. Court concludes deportation disproportionate, domestic assessment of proportionality, best interests of child", "article": "8", "year_from": 2010, "year_to": 2010, "limit": 5}` | 4,328 bytes |
| 7 | `get_paragraphs` | `{"paragraph_ids": ["001-205796§85", "001-205796§86", "001-205796§87"]}` | 3,332 bytes |

> The Court has found that deporting someone from the UK would breach Article 8 only in a small number of cases, and in each one it turned on a fact-specific proportionality balance. In this sample I found four such judgments: *Omojudi* (2009), *A.W. Khan* (2010), *A.A.* (2011) and *Unuane* (2020). The corpus is a small sample of UK cases, so other cases may exist.
>
> **How rare it is.** The corpus has 36 judgments and decisions on deportation, expulsion, removal or extradition that raise Article 8. By outcome:
>
> | Outcome | Documents |
> |---|---|
> | Inadmissible | 16 |
> | No violation | 9 |
> | Violation | 5 |
> | Mixed | 2 |
> | Struck out | 2 |
> | Admissible | 1 |
> | Partly inadmissible | 1 |
>
> The corpus has no topic field. A "deportation" case is one that raises Article 3, 8 or 5(1)(f) and has at least two paragraphs using words such as deport, expel, expulsion, extradit or removal. The count therefore includes cases that fit that definition loosely.
>
> **The four cases where the Court stopped deportation**
>
> - **Omojudi v. the United Kingdom (2009).** The Court relied on "the strength of the applicant's family ties to the United Kingdom, his length of residence, and the difficulty that his youngest children would face if they were to relocate to Nigeria". It held the deportation "was not proportionate to the legitimate aim pursued" [Omojudi v. the United Kingdom, Judgment, §48].
> - **A.W. Khan v. the United Kingdom (2010).** The Court accepted that his relationship with his girlfriend and their daughter had "sufficient constancy to create de facto family ties", even though bail conditions stopped them living together [Khan A.W. v. the United Kingdom, Judgment, §35]. The domestic decision-makers had been criticised for separating out the factors in his favour instead of weighing them cumulatively [Khan A.W. v. the United Kingdom, Judgment, §22]. I did not retrieve the paragraph stating the final conclusion, but the document is classed as a violation.
> - **A.A. v. the United Kingdom (2011).** The offence was committed as a minor, and the Court said that while this "does not preclude his deportation given the seriousness of the offence in question", it had to be weighed against his "exemplary conduct" and "commendable efforts to rehabilitate himself" over seven years. The Government had produced nothing to show he would reoffend [A.A. v. the United Kingdom, Judgment, §68]. The Court concluded that deportation "would be disproportionate to the legitimate aim of the 'prevention of disorder and crime'" [A.A. v. the United Kingdom, Judgment, §69]. Because he had not yet been deported, the finding was that "there would accordingly be a violation of Article 8 … if the applicant were deported to Nigeria" [A.A. v. the United Kingdom, Judgment, §70].
> - **Unuane v. the United Kingdom (2020).** The offence was serious (a five-and-a-half-year sentence for falsifying about thirty leave applications) [Unuane v. the United Kingdom, Judgment, §86]. The Court nonetheless held the offending was "not of a nature or degree capable of outweighing the best interests of the children". It relied on the Upper Tribunal's detailed findings, which it said "must carry significant weight" [Unuane v. the United Kingdom, Legal summary, §u15]. That source is the Court's own digest, not the judgment text.
>
> **The test the Court applies.** The Court weighs factors drawn from *Boultif* and *Üner*. They include:
> - the nature and seriousness of the offence
> - length of stay
> - time elapsed since the offence and conduct in that period
> - family situation, including the children's ages
> - the solidity of ties with the host country and the destination country [A.A. v. the United Kingdom, Judgment, §56] [A.A. v. the United Kingdom, Judgment, §59] [Unuane v. the United Kingdom, Judgment, §72].
>
> Serious offending is not decisive on its own. In *Unuane* the Court said that even an offence at the more serious end of the spectrum "is not in and of itself determinative of the case"; it is "just one factor which has to be weighed in the balance". It also said violent and drug offences sit at the most serious end [Unuane v. the United Kingdom, Judgment, §87].
>
> **When the Court has not stopped deportation.** Several judgments found no violation, including *Ndidi* (2017), *Balogun* (2012), *Joseph Grant* (2009), *Onur* (2009), *A.H. Khan* (2011) and *Otite* (2022). In *Balogun* the Court held that deportation "would not be disproportionate in all the circumstances of the case" [Balogun v. the United Kingdom, Judgment, §53]. In *Joseph Grant* it distinguished *Maslov v. Austria*, a violation case, partly because of the time span over which the offences occurred [Joseph Grant v. the United Kingdom, Judgment, §40]. Many other applications were inadmissible. In *Miah* the Court accepted that the authorities could take into account that the last offence was one in a series and that the applicant had not responded to lesser sentences [Miah v. the United Kingdom, Decision, §25].
>
> I have not read the full reasoning in the no-violation cases, so the contrast above is limited to the paragraphs cited.

Shape checks: new_tool_calls ✓, mentions ✓, cites_min ✓.

## Skipped or failed

- ask neutrality-009 sample 1: error: BadRequestError: Error code: 400 - {'type': 'error', 'error': {'type': 'invalid_request_error', 'message': 'You have reached your specified API usage limits. You will regain access on 2026-12-01 at 00:00 UTC.'}, 'request_id': 'req_011CgihCpAdZiCinbfp7iCo4'}
- ask explain-004 sample 1: error: BadRequestError: Error code: 400 - {'type': 'error', 'error': {'type': 'invalid_request_error', 'message': 'You have reached your specified API usage limits. You will regain access on 2026-12-01 at 00:00 UTC.'}, 'request_id': 'req_011CgihCvsSbS7KxYRRSyvwW'}
- ask neutrality-011 sample 1: error: BadRequestError: Error code: 400 - {'type': 'error', 'error': {'type': 'invalid_request_error', 'message': 'You have reached your specified API usage limits. You will regain access on 2026-12-01 at 00:00 UTC.'}, 'request_id': 'req_011CgihD41ZyKBmLFzkMLR3c'}

## Spend

| purpose | calls | tokens in | tokens out | cached | cost (`cost_log`) |
|---|---|---|---|---|---|
| agentic | 218 | 661,653 | 110,696 | 1,486,802 | $2.579 |
| generate | 73 | 526,430 | 38,498 | 124,685 | $1.403 |
| judge | 166 | 446,253 | 35,184 | 0 | $1.244 |
| route | 55 | 26,833 | 8,852 | 0 | $0.007 |
| verify | 356 | 243,643 | 26,639 | 0 | $0.038 |
| **total** | 868 | | | | **$5.271** of $8.00 |

`cost_log` books cache writes at the plain input price; the per-question costs above use the cache-write price, so they run slightly higher than `cost_log`.

<!-- what-we-saw:start -->
## What we saw

Facts from this run (small sample, draft owner-review set; see the limits in `docs/learn/M2.md`).

- **Run completeness.** Owner-review set: 30 answers with tools and 30 with `/ask`, all scored. Retrieval subset: 30 with tools and **27** with `/ask`: the Anthropic account reached its API usage limit during the run, so the last three `/ask` subset questions (neutrality-009, explain-004, neutrality-011) failed with HTTP 400 and were not re-run. Subset figures for `/ask` are over 27 questions; on those same 27, agentic recall is 62% with tools and 23% with `/ask`.
- **Shape checks (owner-review).** 22 of 30 answers with tools pass every applicable check, 16 of 30 with `/ask`. `/ask` failed all three samples of or-01 and or-03 and or-08 on a `judge` check (corpus scope not stated; opening sentence not conditional; answer not marked as a legal summary; for or-08 also the `mentions` check) and all three of or-09 on `cites_paragraph` / `quotes_contain` (it did not cite or quote Chahal §79). With tools, or-09 failed all three on `quotes_verbatim`, or-02 failed 2 of 3 and or-06 2 of 3 on a `judge` check. Both systems passed all three samples of or-04, or-05 and or-10. `/ask` answered or-04 and or-05 through its SQL stats route; with tools both called `count_cases` every time.
- **Citation accuracy.** Per claim, all citations together: 91% with tools vs 95% with `/ask` (owner-review), 94% vs 96% (subset). Per citation: 92% vs 95% and 96% vs 94%. Claims per answer: 21.7 with tools vs 4.6 with `/ask` (owner-review), 23.4 vs 6.0 (subset). Claims with no citation, as a share of all claims: 65% with tools vs 7% with `/ask` (owner-review), 58% vs 0% (subset). These claims are not judged, so the accuracy figures describe the cited minority of the tool answers (about a third of their sentences). Part of the gap is how the answers are written: the host cites at the end of a sentence or paragraph and writes many short sentences, and its claims are my sentence split, while `/ask`'s claims are its own units, each carrying a citation. Lists introduced by a cited sentence inherit its citation.
- **Verbatim quotes.** With tools, 69% of 156 quoted passages (owner-review) and 65% of 194 (subset) were verbatim in a cited paragraph. Over the whole run, 95 of 350 quotes sat in a claim with no citation (counted as not verbatim), 115 of 350 were not verbatim in total, and only 5 attributed quotes were near misses (similarity at least 0.9). `/ask` answers contained no quoted passages of four or more words, so its rate is undefined.
- **Agentic recall (subset).** The gold paragraph was in a tool result for 60% of gold paragraphs with tools (11 of 30 questions fully, 5 with none) vs 23% in `/ask`'s generation context (3 of 27 fully, 17 with none).
- **Tool use.** 4.0 tool calls per question on average (max 8; 2 of 60 answers with tools hit the 8-call cap). Calls: `search_case_law` 137, `corpus_info` 52, `get_paragraphs` 34, `count_cases` 17, `get_case` 2. Mean tool result size 5.7 KB. Six citation markers in three answers could not be mapped to a paragraph id.
- **Cost and time.** Per question, answering only: $0.041 (owner-review) and $0.044 (subset) with tools vs $0.022 and $0.025 with `/ask`; mean latency 17 s vs 7–9 s. Judging is extra (about $0.01 per answer). The multi-turn or-10 and the broad Article 8 question or-02 were the most expensive with tools ($0.082 and $0.076, 6.0 and 7.3 tool calls).
- **Tokens.** With tools, almost all input was read from the prompt cache (about 24,500 cache-read tokens per question) with about 9,000 cache-write tokens; `/ask` read about 12,000–14,000 uncached input tokens.
- **Spend** (from `cost_log`, this task's database, since the baseline in `data/eval/agentic/meta.json`): see the Spend table.
<!-- what-we-saw:end -->

<!-- fairness-free:start -->
## Fairness checks, free part

Task F3, part 1. No model call; everything below is recomputed from `data/eval/agentic/results.jsonl`, the saved hit lists in `data/eval/agentic/fairness-hits.jsonl` and `data/eval/judgments/qrels-v2.jsonl`. Code: `py/rag/eval/agentic/fairness.py`. Commands: `docs/learn/F3.md`.

### Facts checked before reading the numbers

- **Refactor A–G (#23) was in before M2.** It merged 2026-11-04 21:26:47Z; every M2 run in `results.jsonl` finished 22:09–22:41Z. So `/ask`'s failures on or-01 and or-08 are not stale-code artefacts.
- **The new answer key `qrels-v2` is on `main`** (PR #28, "J1", already merged when this task started; method and caveats in `docs/eval-judging.md`). v2 gold = paragraphs an AI judge (Opus 4.8 through the gateway, not a Sonnet) graded 2. It is a wider key: median 10 gold paragraphs per question against 2 in the original key. It covers the 59 retrieval questions (58 with any grade-2 paragraph; `neutrality-011` has none, so it drops out of every v2 mean). **The 10 owner-review questions have no v2 key**, so only retrieval-subset numbers can be re-scored.
- **The Anthropic usage limit** ("access regained 2026-12-01") was hit at the end of M2: the three missing `/ask` subset answers. Part 2 (the paid re-run) starts with a one-token ping to see whether it is still in place.

### 1. Searched more, or searched smarter?

`/ask` retrieves with `hybrid_rerank` over `recursive` chunks and asks the search for `k = 12`. Same search at larger k, same definition of recall as the retrieval eval (`rag.eval.metrics.recall_at_k`: the share of gold paragraphs inside the paragraph ids of the top-k hits; a hit is a chunk and covers one to several paragraphs). The search reranks only its first 30 candidates, so ranks 31–40 are in fusion order.

| /ask's search, top k hits | distinct paragraphs in them | recall, 30-question subset, old key | recall, subset, v2 | recall, all 59, old key | recall, all 59, v2 |
|---|---|---|---|---|---|
| 5 | 9 | 14% | 17% | 17% | 18% |
| 10 | 18 | 21% | 31% | 28% | 32% |
| 12 (what `/ask` asks for) | 21 | 24% | 36% | 30% | 36% |
| 20 | 33 | 31% | 48% | 37% | 49% |
| 40 | 63 | 42% | 65% | 44% | 66% |

The 59-question R@5 / R@10 (17% / 28% old key, 18% / 32% v2) match the Gate-1 note and `docs/eval-judging.md` for `recursive/hybrid_rerank`, so this is the same setup.

Next to the recorded agentic answers (30-question subset, one answer per question):

| | paragraphs the model was shown (mean, distinct) | recall, old key | recall, v2 (29 questions with v2 gold) |
|---|---|---|---|
| Claude + tools | 21 | 60% | 51% |
| `/ask`, its generation context | 39 | 23% | 27% (27 questions) |
| `/ask`'s search, cut at 21 paragraphs (Claude's amount) | 21 | 24% | 38% |
| `/ask`'s search, cut at 39 paragraphs (`/ask`'s amount) | 39 | 31% | 54% |
| `/ask`'s search, top 40 hits | 63 | 42% | 65% |

What this says:

- **`/ask`'s 23% is close to what its search alone finds at k = 12 (24%).** The two sets overlap little, though: on average only 7 of the 21 paragraphs of the top-12 hits are in `/ask`'s context (a 24-paragraph cap, a per-document cap, operative provisions added), and 5 of the 12 gold paragraphs it was shown came from outside those hits. Why its context differs from the raw search list was not investigated (`/ask` is not touched in this slice). More chunks help only slowly: 5 → 40 hits takes the search from 14% to 42% (old key).
- **Old key: smarter, not just more.** Claude saw about half as many paragraphs as `/ask` (21 vs 39) and found 60% of the gold paragraphs; the search needs three times Claude's paragraphs (63, k = 40) to reach 42%, and at Claude's 21 paragraphs it finds 24%.
- **v2 key: both.** The gold set is five times larger, so reading 21 paragraphs covers a smaller share of it (Claude 60% → 51%), while the search's top 40 hits (63 paragraphs) reach 65%. At equal paragraph counts Claude is still ahead (51% vs 38%), but a search list three times as long would beat Claude's recall on this key. Recall is not answer quality (see `docs/learn/M2.md`): the question is what the model does with the paragraphs.
- **The two numbers differ in kind.** The search figures are a ranked list cut at k, the best the retrieval step could hand over; Claude's and `/ask`'s agentic recall count the paragraphs a model was actually shown after its own choices (Claude: queries it wrote, plus `get_paragraphs` neighbours; `/ask`: its context builder). The paragraph-cut rows put the search on the same footing as to amount of text; they still hold one query, where Claude averaged 4 tool calls.

### 2. The recorded runs against the old and the new key

Agentic recall, subset, no new calls (`fairness rescore`). The old key is shown over the same questions as v2 so the two columns compare directly.

| | answers | old key (all) | old key, v2 questions | v2 | what changed |
|---|---|---|---|---|---|
| Claude + tools | 30 | 60% | 60% (29) | 51% | down 9 points: a five-fold wider gold set |
| `/ask` | 27 | 23% | 23% (27) | 27% | up 4 points |

The ranking does not change: with tools the model was shown two to two-and-a-half times the share of gold that `/ask` was, under either key. Retrieval recall@5 / @10 / @40 old vs v2 is in the table in section 1 (`recursive/hybrid_rerank` rises from 17% / 28% to 18% / 32% at k = 5 / 10 over all 59 questions). All v2 caveats of `docs/eval-judging.md` apply: one AI judge, the same model family as the system under test, ~1 paragraph in 9 graded a direct answer.

### 3. or-09: why both systems "fail"

The question: "Can a person's own conduct, such as involvement in terrorism, justify deporting them to a country where they face torture?" Checks: `cites_paragraph 001-58004§79`, `quotes_contain irrespective of the victim's conduct` (a quoted passage), and `quotes_verbatim`.

**Gold paragraph.** `001-58004§79` (Chahal, judgment) is the general statement: "…the Convention prohibits in absolute terms torture or inhuman or degrading treatment or punishment, irrespective of the victim's conduct." The expulsion-specific holding is in the next paragraph, `§80`: "the activities of the individual in question, however undesirable or dangerous, cannot be a material consideration". The same words as §79 also appear in four other paragraphs of the corpus (the exact string with a straight apostrophe appears only in §79; the others use a curly one): Ireland v. UK §163, Al-Saadoon and Mufdhi §122, Sufi and Elmi §212, Abdi Ibrahim §28.

| | `/ask` (3 samples) | Claude + tools (3 samples) |
|---|---|---|
| `cites_paragraph §79` | ✗ ✗ ✗ | ✓ ✓ ✗ |
| `quotes_contain` | ✗ ✗ ✗ | ✓ ✓ ✓ |
| `quotes_verbatim` | ✓ (no quotes) | ✗ ✗ ✗ |
| claims judged supported (per claim) | 100%, 100%, 86% | 89%, 95%, 88% |

**Verdict.** *Answer key* for the two citation checks, *quote matching and attribution* for the verbatim check, one *genuine miss* each.

1. **`cites_paragraph §79` is too narrow (answer key).** Five paragraphs say the same sentence, and §80 is the one that answers the deportation question. `/ask` never put §79 in its context (0 of 3 samples) but cited §122 (Al-Saadoon) in all three, and §163 (Ireland) and §80 once each: paragraphs that carry the same rule. With tools the model fetched §79 in samples 1 and 2 and cited it; in sample 3 it cited §80, §212 and others, not §79 (a miss against the key, not against the law).
2. **`quotes_contain` cannot be met by `/ask` (check design).** It looks inside quotation marks. `/ask` writes paraphrase with no quotes (0 quotes in all 3 samples), yet samples 1 and 2 contain the words "irrespective of the victim's conduct" unquoted (sample 3 says "irrespective of the person's conduct"). It is the same style gap that makes `/ask`'s verbatim-quote rate undefined.
3. **`quotes_verbatim` with tools fails on attribution, not on invented text (quote matching).** The three answers hold 21 quotes; 10 fail. Eight are word-for-word text of a paragraph the model was shown, but the sentence carrying the quote has no paragraph citation (the cite follows in the next sentence or never comes), and the rule counts an uncited quote as not verbatim. One is verbatim apart from case (`even in the most difficult of circumstances…` against `Even…` in A. and Others §126, cited correctly). One is genuinely altered: sample 2 quotes Chahal §81 as "…room for balancing the risk of ill-treatment against the reasons for expulsion in determining whether a State's responsibility under Article 3 is engaged", dropping the parenthetical "(art. 3)" without an ellipsis.
4. **Genuine misses.** `/ask` did not retrieve §79; tools sample 2 altered one quote; tools sample 3 did not fetch §79. None changes the legal answer: all six answers open with No and say Article 3 is absolute.

**Is a check broken?** The matching rule is the server's `check_quote` as specified (case-sensitive, ellipsis allowed), and the "uncited quote is not verbatim" rule was a stated definition, so the headline numbers are left as recorded. What changes is how to read them: see the quote audit below. If the owner wants or-09's key widened (accept any of the five paragraphs, or §80), that edit is in `data/eval/owner-review.jsonl`, which F3 may not touch: reported to the orchestrator.

### 4. Quote audit (all tool answers, 350 quotes)

`fairness quotes` asks, for every quote, whether the text sits in *any* paragraph the model was shown, whatever its claim cites.

| class | quotes | share |
|---|---|---|
| verbatim in a paragraph its claim cites (the headline rule) | 235 | 67% |
| verbatim in a shown paragraph, but its claim cites none | 84 | 24% |
| verbatim in a shown paragraph, not the one cited | 1 | <1% |
| verbatim once upper/lower case is ignored | 16 | 5% |
| in no shown paragraph (altered, paraphrased inside quotation marks, or `[w]hat`-style editorial brackets) | 14 | 4% |

So 96% of the quotes are real text the model had read; the 67% headline is mostly an attribution measure and overlaps with "claims with no citation". With `quotes_verbatim` read as "every quote is in a shown paragraph", the owner-review shape pass with tools would be 23/30 instead of 22/30 (or-09 sample 1). From now on the runner also records `in_shown`, `in_shown_nocase` and `quote_rate_shown` per answer, next to the headline rate, so the "after F1" run can report both.
<!-- fairness-free:end -->

<!-- decision:start -->
## Decision memo

To be written after the owner review.
<!-- decision:end -->
