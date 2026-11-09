# S4 demo transcripts

Real output of the answer pipeline (the same `render()` as `pnpm run ask "<question>"`, claims shortened to their ids) on 2026-11-04 against `echr_i1` (full snapshot ingest, 98 documents, bge-small, three chunking strategies), with the live Anthropic API (`claude-sonnet-5-5` writes, `claude-haiku-5-5` plans queries, verifies and extracts parameters). Search is `hybrid_rerank`, chunking `recursive`, k=12. Re-run for the **answer first** change (A1): a short answer, then grouped points. Q3 (stats) is the earlier transcript and did not change (count 27). The earlier Q1/Q2 transcripts opened with domestic statute text and listed cited facts without a direct answer.

## Latency and cost summary

| # | Question | Route | Latency (warm) | Cost |
|---|---|---|---|---|
| Q1 | Does the Convention stop the UK deporting criminals? | rag | 9.7 s | $0.0263 |
| Q2 | How has Article 8 been applied in UK immigration cases? | rag | 10.2 s | $0.0242 |
| Q3 | How many UK deportation complaints … inadmissible … reasons? | stats | 1.1 s | $0.00015 |

All three are **under the 15 s budget**. "Warm" means the embedder and reranker are already loaded, as in the API (loaded once at startup); the CLI loads and warms them first (printed at the bottom of each transcript) and starts the clock afterwards.

Typical split for a reading question (Q1, this run): planning 1.5 s (overlapped with the first search), retrieve 0.3 s, rerank 0.8 s, generate (Sonnet) 4.8 s, verify (Haiku, parallel) 3.1 s. Asking for a short answer, grouped points and planned queries makes an answer cost about $0.025 instead of $0.018 and take 8 to 11 s instead of 6 s; a rejected short answer is rewritten once or twice, which can add 3 s.

## Q1: Does the Convention stop the UK deporting criminals?

Route **rag**, 9.7 s, $0.0263. The answer starts with a direct, hedged sentence, then the evidence in two groups: deportation **allowed** (Ndidi, Otite, A.H. Khan: no violation of Article 8) and deportation that **would breach** the Convention (A.A. and Unuane under Article 8, Chahal under Article 3). Every claim verified; each outcome claim cites the operative provision that states it.

```text
Route: rag

ANSWER
  Not as a general rule: the Court has allowed deportation of offenders in Ndidi and Otite (no
  Article 8 violation), but found deportation would breach the Convention in A.A. (Article 8) and
  Chahal (Article 3) [Ndidi v UK §op2] [Otite v UK §op2] [A.A. v UK §op2].

  Where the Court allowed deportation:
  In Ndidi v UK the Court held that there had been no violation of Article 8 in the applicant's
  deportation [Ndidi v UK §op2]. In Otite v UK the Court held, by five votes to two, that the
  applicant's deportation would not violate Article 8 [Otite v UK §op2]. In A.H. Khan v UK the Court
  found no violation, noting the applicant had not achieved a significant level of integration into
  British society despite his long stay [A.H. Khan v UK §41].

  Where the Court found deportation would breach the Convention:
  In A.A. v UK the Court held that there would be a violation of Article 8 if the applicant were
  deported [A.A. v UK §op2]. In Unuane v UK the Court found the deportation disproportionate, as the
  offences were not serious enough to outweigh the children's best interests, so it was not
  necessary in a democratic society [Unuane v UK §u15]. In Chahal v UK the Court held that deporting
  the first applicant to India would violate Article 3 [Chahal v UK §op1].

CLAIMS
  c1 [✓ supported] (short answer) Not as a general rule: the Court has allowed deportation of offenders in Ndidi and Otite (no Article 8 violation), but found deportation would breach the Convention in A.A. (Article 8) and Chahal (Article 3).
       cites: 001-176931§op2, 001-219755§op2, 001-106282§op2
  c2 [✓ supported] [Where the Court allowed deportation] In Ndidi v UK the Court held that there had been no violation of Article 8 in the applicant's deportation.
       cites: 001-176931§op2
  c3 [✓ supported] [Where the Court allowed deportation] In Otite v UK the Court held, by five votes to two, that the applicant's deportation would not violate Article 8.
       cites: 001-219755§op2
  c4 [✓ supported] [Where the Court allowed deportation] In A.H. Khan v UK the Court found no violation, noting the applicant had not achieved a significant level of integration into British society despite his long stay.
       cites: 001-108113§41
  c5 [✓ supported] [Where the Court found deportation would breach the Convention] In A.A. v UK the Court held that there would be a violation of Article 8 if the applicant were deported.
       cites: 001-106282§op2
  c6 [✓ supported] [Where the Court found deportation would breach the Convention] In Unuane v UK the Court found the deportation disproportionate, as the offences were not serious enough to outweigh the children's best interests, so it was not necessary in a democratic society.
       cites: 002-13006§u15
  c7 [✓ supported] [Where the Court found deportation would breach the Convention] In Chahal v UK the Court held that deporting the first applicant to India would violate Article 3.
       cites: 001-58004§op1

STEPS
  route     claude-haiku-5-5     in    478 out   131 cached      0  $0.00011      1496 ms
  retrieve  -                    in      0 out     0 cached      0  $0.00000       332 ms
  rerank    BAAI/bge-reranker-base in      0 out     0 cached      0  $0.00000       844 ms
  generate  claude-sonnet-5-5    in   9318 out   658 cached   2266  $0.02544      4813 ms
  verify    claude-haiku-5-5     in   4504 out   671 cached      0  $0.00079      3145 ms
TOTAL $0.02634  9717 ms  models: claude-haiku-5-5, claude-sonnet-5-5
```

## Q2: How has Article 8 been applied in UK immigration cases?

Route **rag**, 10.2 s, $0.0242 (run with the earlier 5-point prompt; the PR report has the final-prompt checks). A short answer, then the framework and the outcomes both ways; every claim verified.

```text
Route: rag

ANSWER
  Not as a general rule: in Miah v UK the Court said a settled migrant rarely fails to show
  interference with private life, while Onur, Ndidi and Otite each found no violation of Article 8
  [Miah v UK §17] [Onur v UK §62] [Ndidi v UK §op2] [Otite v UK §op2].

  How the Court approaches Article 8 in expulsion cases:
  In Miah v UK the Court said it will be a rare case where a settled migrant cannot show that
  deportation interferes with private life, with tie strength weighed in proportionality [Miah v UK
  §17]. In A.A. v UK the Court said the expulsion criteria vary in weight by case, and that its
  supervision goes hand in hand with the State's margin of appreciation [A.A. v UK §57].

  Where the Court allowed the State's action:
  In Onur v UK the Court found that a fair balance was struck and the applicant's expulsion was
  proportionate, and held there was no violation of Article 8 [Onur v UK §62, §op2]. In Ndidi v UK
  the Court held that there had been no violation of Article 8 [Ndidi v UK §op2]. In Otite v UK the
  Court held, by five votes to two, that the applicant's deportation would not violate Article 8
  [Otite v UK §op2].

CLAIMS
  c1 [✓ supported] (short answer) Not as a general rule: in Miah v UK the Court said a settled migrant rarely fails to show interference with private life, while Onur, Ndidi and Otite each found no violation of Article 8.
       cites: 001-98645§17, 001-91286§62, 001-176931§op2, 001-219755§op2
  c2 [✓ supported] [How the Court approaches Article 8 in expulsion cases] In Miah v UK the Court said it will be a rare case where a settled migrant cannot show that deportation interferes with private life, with tie strength weighed in proportionality.
       cites: 001-98645§17
  c3 [✓ supported] [How the Court approaches Article 8 in expulsion cases] In A.A. v UK the Court said the expulsion criteria vary in weight by case, and that its supervision goes hand in hand with the State's margin of appreciation.
       cites: 001-106282§57
  c4 [✓ supported] [Where the Court allowed the State's action] In Onur v UK the Court found that a fair balance was struck and the applicant's expulsion was proportionate, and held there was no violation of Article 8.
       cites: 001-91286§62, 001-91286§op2
  c5 [✓ supported] [Where the Court allowed the State's action] In Ndidi v UK the Court held that there had been no violation of Article 8.
       cites: 001-176931§op2
  c6 [✓ supported] [Where the Court allowed the State's action] In Otite v UK the Court held, by five votes to two, that the applicant's deportation would not violate Article 8.
       cites: 001-219755§op2

STEPS
  route     claude-haiku-5-5     in    479 out   170 cached      0  $0.00013      1781 ms
  retrieve  -                    in      0 out     0 cached      0  $0.00000       513 ms
  rerank    BAAI/bge-reranker-base in      0 out     0 cached      0  $0.00000      1046 ms
  generate  claude-sonnet-5-5    in   9255 out   688 cached   2266  $0.02338      5829 ms
  verify    claude-haiku-5-5     in   4657 out   459 cached      0  $0.00070      2381 ms
TOTAL $0.02421  10240 ms  models: claude-haiku-5-5, claude-sonnet-5-5
```

## Q3: How many UK deportation complaints in the corpus were declared inadmissible, and the most common reasons?

> **Wording since updated (#20, 2026-11-04):** the count sentence now reads naturally, names every filter the SQL applied, and each claim's text equals its sentence. The count (27) and the SQL are unchanged. The transcript below is the original 2026-11-03 output.

Route **stats**, 1.1 s, $0.00015. Stats route: **27** decisions (was 30 before the definition fix), SQL shown, reasons counted from `documents.inadmissibility_grounds`, eight cases cited. The model only extracts parameters (Haiku, 1.1 s); the counting is SQL (28 ms). 'Declared inadmissible' now means the whole application; the 2 partly inadmissible matches are reported but not counted, and 'deportation' is defined by Articles 3/8/5(1)(f) plus at least 2 paragraphs of removal vocabulary.

```text
Route: stats
ANSWER
  27 judgments and decisions about deportation, expulsion, removal or extradition with outcome
  inadmissible are in the indexed corpus. Most common reasons: manifestly ill-founded (22); domestic
  remedies not exhausted (4); outside the Convention's subject matter (2). Examples: [Horne v UK §4]
  [Hafeez v UK §7] [Osagiede v UK §12]
CLAIMS
  c1 [✓ supported] 27 judgments and decisions about deportation, expulsion, removal or extradition with outcome inadmissible.
       cites: 001-231646§4, 001-224490§7, 001-223629§12, 001-182755§25; The count comes straight from the SQL shown, not from a model.
  c2 [✓ supported] Most common reasons: manifestly ill-founded (22); domestic remedies not exhausted (4); outside the Convention's subject matter (2).
       cites: 001-231646§4, 001-224490§7, 001-223629§12, 001-182755§25; Computed by the SQL shown, not by a model.
CITATIONS
  001-231646§4  HORNE v. THE UNITED KINGDOM  /case/001-231646#p4
      “On 13 March 2017 the applicant was arrested in Northern Ireland pursuant to an extradition
      request from the Government of the United States of America. His extradition was sought in
      relation to a charge of second‑degree murder with a firearm.”
  001-224490§7  HAFEEZ v. THE UNITED KINGDOM  /case/001-224490#p7
      “In this regard, it was his contention that his potential co-accused had been expelled
      unlawfully from Kenya, the US had been complicit in their unlawful expulsion, and one of the
      potential co‑accused was likely to give evidence against the applicant.”
  001-223629§12  OSAGIEDE v. THE UNITED KINGDOM  /case/001-223629#p12
      “It is not in dispute that the tribunals and courts will have full powers to quash the
      decision to deport the applicant, including on the ground that deportation would be
      incompatible with his Convention rights (see paragraph 7 above).”
  001-182755§25  KHAKSAR v. THE UNITED KINGDOM  /case/001-182755#p25
      “It is clear that the appellants will seek to extend existing orders preventing their removal
      from the UK until the final determination of their cases in the court and tribunal system, on
      the basis that their appeals will or should be going to the Supreme Court.”
  001-173881§19  DRAGA v. THE UNITED KINGDOM  /case/001-173881#p19
      “The court held that the decision to deport was different from the decision to detain; that it
      was difficult to identify any principled basis for distinguishing between those public law
      errors which would render the decision to detain unlawful and those which would not;”
  001-172305§12  J.M.O. v. THE UNITED KINGDOM  /case/001-172305#p12
      “These principles require that detention be for the purpose of exercising the power to deport;
      the period of detention must be reasonable in all the circumstances; a detainee must be
      released if it becomes apparent that deportation cannot be effected within a reasonable
      period;”
  001-161986§45  I.A.A. AND OTHERS v. THE UNITED KINGDOM  /case/001-161986#p45
      “While the situation there is undoubtedly volatile, the applicants are from Mogadishu and in a
      number of recent judgments the Court has found that removals there would not breach Article 3
      of the Convention (see K.A.B. v. Sweden, no.”
  001-150856§28  ASWAT v. THE UNITED KINGDOM  /case/001-150856#p28
      “17299/12, 16 April 2013, stressed that in cases involving extradition, expulsion or
      deportation of individuals to third countries, Article 3 prohibits in absolute terms torture
      or inhuman or degrading treatment or punishment and that its guarantees apply irrespective of
      the reprehensible nature of”
SQL
  WITH matched AS (
    SELECT d.item_id, d.case_name, d.date, d.doc_type, d.outcome, d.articles, d.inadmissibility_grounds
    FROM documents d
    WHERE d.doc_type IN ('judgment', 'decision', 'communicated')
      AND d.outcome IN ('inadmissible')
      AND EXISTS (SELECT 1 FROM unnest(d.articles) AS a WHERE split_part(a, '-', 1) IN ('3', '8', '5-1-f') OR a IN ('3', '8', '5-1-f'))
      AND (SELECT count(*) FROM paragraphs p WHERE p.doc_id = d.item_id AND p.text ~* '[[:<:]](deport|expel|expulsion|extradit|removal)') >= 2
  )
  SELECT COALESCE(g, '(not stated)') AS reason, count(*) AS documents
  FROM matched LEFT JOIN LATERAL unnest(inadmissibility_grounds) AS g ON true
  GROUP BY 1 ORDER BY 2 DESC, 1 LIMIT 20;
  -- also run on the same `matched` set: SELECT count(*) FROM matched; and the 8 most recent items, each with its best-matching paragraph
ROWS (count = 27)
  reason | documents
  manifestly_ill_founded | 22
  non_exhaustion | 4
  incompatible_ratione_materiae | 2
EXPLANATION
  Counted 27 matching UK judgments and decisions about deportation, expulsion, removal or
  extradition with outcome inadmissible in the indexed corpus. 'Declared inadmissible' means the
  whole application was declared inadmissible; 2 further matching decision(s) were only partly
  inadmissible and are not counted. HUDOC has no topic field, so 'deportation' is defined as: the
  document raises Article 3, 8, 5(1)(f) and at least 2 of its paragraphs contain a word starting
  deport, expel, expulsion, extradit, removal (see the SQL). Cases that merely use these words
  without such a complaint are excluded. Grounds come from HUDOC's conclusion where it names one,
  otherwise from the decision text; a decision can have several, so rows can add up to more than the
  total. 8 of 27 matching cases are cited.
STEPS
  route     -                    in      0 out     0 cached      0  $0.00000         0 ms
  generate  claude-haiku-5-5     in   1041 out    93 cached      0  $0.00015      1067 ms
  retrieve  -                    in      0 out     0 cached      0  $0.00000        28 ms
TOTAL $0.00015  1096 ms  models: claude-haiku-5-5
(models loaded and warmed once in 5.5 s; the API does this at startup)
```

## Value question: Should the UK leave the ECHR?

Route **rag**, 11.0 s, $0.0334. This is the unchanged value-question path: a one-sentence notice, then sourced points on each side, no short answer and no verdict (A1 does not change this behaviour).

```text
Route: rag

ANSWER
  This asks for a value judgment, so this sets out what the sources show on each side without a
  verdict. Article 58 of the Convention allows a State to denounce it only after five years of
  membership and six months' notice to the Secretary General, and denunciation does not release the
  State from obligations for acts performed before it takes effect [European Convention on Human
  Rights §art58]. Under Article 46, States undertake to abide by final Court judgments, the
  Committee of Ministers supervises execution, and it can refer a refusing State back to the Court
  [European Convention on Human Rights §art46]. In Hirst (No. 2), dissenting judges said the
  majority's finding that a general ban on prisoner voting fell outside any margin of appreciation
  was hard to reconcile with the wide margin the Court has traditionally allowed on electoral
  systems [Hirst v UK §u33]. In Hirst (No. 2) the Court stated that the State chooses, under
  Committee of Ministers supervision, the means of complying with Article 46 [Hirst v UK §83]. In
  Al-Skeini the Court restated that the respondent State remains free to choose how to discharge its
  Article 46 obligation, provided the means are compatible with the judgment's conclusions [Al-
  Skeini and Others v UK §181]. In S. and Marper the Court held there was a violation of Article 8,
  and explained the margin of appreciation narrows where a right is crucial to intimate or key
  aspects of the individual's life and widens where member States lack consensus [S. and Marper v UK
  §102, §op1]. In Pinnock and Walker the Court declared the application inadmissible, stating that
  national authorities enjoy a margin of appreciation and that in possession-order cases it will be
  wide where there is no reason to doubt the procedure followed [Pinnock and Walker v UK §28, §op1].

CLAIMS
  c1 [✓ supported] Article 58 of the Convention allows a State to denounce it only after five years of membership and six months' notice to the Secretary General, and denunciation does not release the State from obligations for acts performed before it takes effect.
       cites: echr-convention§art58
  c2 [✓ supported] Under Article 46, States undertake to abide by final Court judgments, the Committee of Ministers supervises execution, and it can refer a refusing State back to the Court.
       cites: echr-convention§art46
  c3 [✓ supported] In Hirst (No. 2), dissenting judges said the majority's finding that a general ban on prisoner voting fell outside any margin of appreciation was hard to reconcile with the wide margin the Court has traditionally allowed on electoral systems.
       cites: 001-70442§u33
  c4 [✓ supported] In Hirst (No. 2) the Court stated that the State chooses, under Committee of Ministers supervision, the means of complying with Article 46.
       cites: 001-70442§83
  c5 [✓ supported] In Al-Skeini the Court restated that the respondent State remains free to choose how to discharge its Article 46 obligation, provided the means are compatible with the judgment's conclusions.
       cites: 001-105606§181
  c6 [✓ supported] In S. and Marper the Court held there was a violation of Article 8, and explained the margin of appreciation narrows where a right is crucial to intimate or key aspects of the individual's life and widens where member States lack consensus.
       cites: 001-90051§102, 001-90051§op1
  c7 [✓ supported] In Pinnock and Walker the Court declared the application inadmissible, stating that national authorities enjoy a margin of appreciation and that in possession-order cases it will be wide where there is no reason to doubt the procedure followed.
       cites: 001-127560§28, 001-127560§op1

STEPS
  route     claude-haiku-5-5     in    505 out   157 cached      0  $0.00013      1384 ms
  retrieve  -                    in      0 out     0 cached      0  $0.00000       419 ms
  rerank    BAAI/bge-reranker-base in      0 out     0 cached      0  $0.00000       842 ms
  generate  claude-sonnet-5-5    in  11794 out   858 cached   1479  $0.03232      6384 ms
  verify    claude-haiku-5-5     in   6692 out   553 cached      0  $0.00095      2945 ms
TOTAL $0.03339  11029 ms  models: claude-haiku-5-5, claude-sonnet-5-5
```
