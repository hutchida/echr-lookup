# J1 — Relevance judging: is our answer key too narrow?

Code: `py/rag/eval/judging/` · Results: `docs/eval-judging.md` · Data: `data/eval/judgments/` · Run it: `cd py && uv run --group ml python -m rag.eval.judging --help`

## 1. What this is, in plain English

To measure whether search works, we need a list of right answers. For each test question (for example "Can the UK extradite a person who faces the death row phenomenon?") the **answer key** lists the paragraphs that a correct answer should cite. Search is then scored: **recall@5** is the share of those paragraphs that appear in the top 5 results, **recall@10** the same for the top 10, and **MRR** (mean reciprocal rank) rewards putting the first right paragraph near the top (first place scores 1, second 1/2, third 1/3, ...).

Our key (`data/eval/questions.jsonl`) was written quickly by one AI agent: about 2.5 paragraphs per question. That is risky. For "Can the UK extradite someone who faces the death row phenomenon?" it lists two paragraphs of *Soering v UK*. But *Soering* has other paragraphs that say much the same thing, and later cases quote it. If search returns one of those, the old scoring calls it a **miss**, although a lawyer would call it a **hit**. So the scores (about 0.2 for recall@5) may be too pessimistic, and we might "fix" search problems that are really key problems.

The fix is **pooled relevance judging**:

1. **Pool.** For every question we run all 12 search set-ups (3 ways of chopping documents into pieces x 4 search methods) and collect every paragraph any of them returned in its top 10, plus the original key's paragraphs. That is the **pool**: 54 to 184 paragraphs per question (median 94, 5,904 in total).
2. **Judge.** A different AI model reads the question and every pooled paragraph (shown in random order, without knowing which ones the key listed or which search found them) and gives each a grade.
3. **New key.** The grades become a second key, "qrels v2" (qrels = "query relevance judgments", the standard name for an answer key). We then re-score all 12 set-ups against both keys, side by side. The original key is never edited.

**Why pooling is fair.** The paragraphs nobody's search returned are never judged, and that is acceptable: if no system finds a paragraph, it cannot change how the systems compare. Every paragraph that any system could have scored with *is* judged, so no system is penalised for finding something the key's author did not think of. It is the standard method of the TREC search competitions.

**Graded relevance.** Right/wrong is too crude, so each paragraph gets one of three grades:

| Grade | Meaning | Example (question: "Does the long wait on death row count towards a breach of Article 3?") |
|---|---|---|
| 2 | Directly answers: states the holding, rule or test | *Soering* §111: the very long period on death row, in those conditions, crosses the Article 3 threshold |
| 1 | Relevant context, not enough alone | *Soering* §106: describes how long the wait is and why |
| 0 | Not relevant | *Soering* §22: the English habeas corpus procedure |

For recall and MRR under v2, "right answer" means grade 2. Questions with no grade-2 paragraph at all (one: `neutrality-011`, "Is the Human Rights Act good for the UK?") have nothing to hit, so they are left out of the v2 recall and MRR averages and the report says so.

**nDCG** (normalised discounted cumulative gain) uses all three grades and also rewards ordering. Give each result a gain (grade 0 = 0, grade 1 = 1, grade 2 = 3: we use 2^grade − 1, so a direct answer is worth three "context" paragraphs). Discount by position (divide by log2(position + 1), so position 1 counts fully, position 3 counts half), add up, and divide by the best total any ordering could reach. 1.0 = perfect order, 0 = nothing useful found. Tiny example with one grade-2 paragraph A and one grade-1 paragraph B:

- Best order [A, B]: 3/log2(2) + 1/log2(3) = 3 + 0.63 = 3.63.
- Search returns [B, X, A] (X is irrelevant): 1/log2(2) + 0 + 3/log2(4) = 1 + 0 + 1.5 = 2.5.
- nDCG = 2.5 / 3.63 = **0.69**. If it returned [A, B] it would be 1.0.

For the original key every key paragraph has gain 1, so its nDCG is on the same scale as v2.

## 2. Why it matters for answer quality

The pipeline will be tuned (chunking, search method, reranker) using these scores. Tuning against a too-narrow key rewards the wrong things: a method that returns the *Soering* paragraph the key author did not pick looks worse than one that happens to return the picked one. On the first question the effect is dramatic: recall@10 for `fixed/bm25` is 0.00 on the original key (neither listed paragraph was in its top 10) but 0.44 on v2, because it returned other paragraphs that state the *Soering* rule. Across all questions, the best configuration's recall@10 moved from 0.32 to 0.41, and MRR averaged over the 12 set-ups from 0.20 to 0.59 (see `docs/eval-judging.md` for the full table). The point of the exercise is that the answer key should not decide the winner.

## 3. How it works here

```
questions.jsonl ──► pool ──► judge (run 1, all 59 questions) ──► qrels-v2.jsonl ──► rescore ──► docs/eval-judging.md
 (original key)      │             └► recheck (run 2, 15 random questions) ──► agreement, flipped grades
                     └► retrieval.jsonl (top-10 hits per question and config, so re-scoring needs no search)
```

- **Judge model.** `vertex-ai-claude-opus-4.8`, reached through a LiteLLM gateway (the project's own Anthropic key hit its monthly limit; Opus 5.5 is not on the proxy). It is not the Sonnet 5.5 that wrote the key.
- **The prompt** (`grader.py`) is a written rubric with two worked examples from this corpus (*Soering* and *Hirst*) whose quotes were checked against the database. Paragraphs appear under aliases (P01, P02, ...) in a seeded random order, which are mapped back to the real ids afterwards.
- **Strict checking.** The reply must be JSON with every alias exactly once, a grade of 0, 1 or 2, and a non-empty reason. If it is not, the judge is asked once more; a question that still fails is counted and reported, never filled in. (In this run: 0 failures; 4 judge calls needed the one retry.)
- **Resumable.** Each finished question is appended to `judgments-run1.jsonl` straight away; a re-run skips finished questions, so a crash cannot make you pay twice.
- **Cost.** Every call is logged to `cost_log` (`request_id` starting `relevance-`) with the cost the proxy reports. The run cost about $22.7 in total, shown in `spend.log` as it went.
- **Consistency check.** 15 random questions were judged a second time, with the paragraphs reshuffled: 86% of paragraphs got exactly the same grade, and 96% agreed on "grade 2 or not". Run 1 is the one used for v2.

## 4. Try it

All commands run from `py/` (`cd py`) and need no database or API key unless stated. Outputs below are from the real run.

1. **How big are the pools, and what would judging cost?**
   `uv run --group ml python -m rag.eval.judging preflight`
   → `Pool: 59 questions, 5904 paragraphs; per question min 54 / median 94 / max 184` and `Projected at vertex-ai-claude-opus-4.8: 59 judge calls $15.81 + 15 re-judge calls $4.02 = $19.82 (ESTIMATE ...)`.
   *Proves:* every question has dozens of candidate paragraphs, not the 2 or 3 in the original key, and the cost was estimated from the real pool before any paid call. (The measured bill, $22.72, came out about 15% higher: the proxy charges a little over list price and the output estimate was rough, which is why the report labels estimate and measurement separately.)
2. **Read one question end to end.**
   `uv run --group ml python -m rag.eval.judging show explain-001 --limit 3`
   → `Pool: 124 paragraphs; original gold: 2`, both original paragraphs graded 2 with reasons such as `Court's holding: extradition would breach Article 3 due to death row phenomenon.`, then `Graded 2 but not in the original key: 7`, led by `001-58004§u62  Restates Soering holding: death row phenomenon brings Article 3 into play...` and a table of recall@10 per config (for example `fixed/bm25 0.00 -> 0.44`).
   *Proves:* the key was narrow (seven more paragraphs directly answer this question) and you can read the judge's reason for each one yourself.
3. **See which searches found an added paragraph.**
   `python3 -c "import json;[print(p['id'],'gold:',p['gold'],'found by',p['n_configs'],'of 12; best rank',p['best_rank'],'\n',p['found_by']) for l in open('../data/eval/judgments/pool.jsonl') for q in [json.loads(l)] if q['question_id']=='explain-001' for p in q['paragraphs'] if p['id']=='001-58004§u62']"`
   → `001-58004§u62 gold: False found by 10 of 12; best rank 2` followed by the list of configs and their ranks (for example `'fixed/hybrid': 2`).
   *Proves:* this paragraph is not an obscure find. Ten of twelve set-ups returned it, one in second place, yet the original key counted every one of those as a miss.
4. **Compare original and v2 scores for all 12 set-ups.**
   `uv run --group ml python -m rag.eval.judging rescore | head -5`
   → `fixed/hybrid_rerank  recall@5 0.215 -> 0.246  recall@10 0.319 -> 0.396  MRR 0.189 -> 0.490  nDCG@10 0.091 -> 0.327` (the left numbers are the known baseline, 0.21 / 0.32 / 0.19).
   *Proves:* the original-key column reproduces the earlier eval, so the comparison is like for like, and nearly every score is higher under the wider key (two recall@5 values dip slightly, for example `recursive/bm25` 0.206 -> 0.174). It also rewrites `qrels-v2.jsonl` (same content each time).
5. **Check the judge's work yourself.**
   `python3 -c "import json;r=json.load(open('../data/eval/judgments/review-list.json'));print(len(r),'items');print(r[0]['question']);print(r[0]['paragraph_id'],'grade',r[0]['grade'],'-',r[0]['reason'])"`
   → `10 items`, then `Should UK courts have to follow decisions from the Strasbourg Court?` and `001-70442§82 grade 0 - Margin of appreciation prisoner voting; off point.`
   *Proves:* the judge disagrees with the key in places, and here it looks right: the key lists *Hirst* §82 (a paragraph about prisoners' votes) for a question about following Strasbourg decisions. Open `docs/eval-judging.md`, "Review list", to read all ten with their quotes; some are clearly right, some arguable, and that is the human spot-check.
6. **See what the judging cost, from the database.**
   `docker exec echr-lookup-db-1 psql -U echr echr -c "SELECT round(sum(cost_usd),2) AS usd, count(*), sum(tokens_in) AS tok_in, sum(tokens_out) AS tok_out FROM cost_log WHERE request_id LIKE 'relevance-%'"` (needs the dev database running)
   → `22.72 | 79 | 2442872 | 337508`.
   *Proves:* every judge call is logged under the `relevance-` prefix with the proxy-reported cost, so the spend is checkable and not just claimed.

## 5. Limits / what can go wrong

- **An AI judge is not the truth.** It can be wrong, and a second run of the same judge changed 224 of 1,641 grades (mostly between 0 and 1; only 2 jumped between 0 and 2, and in both the first run had filed a reason under the wrong paragraph). It was generous: about one pooled paragraph in nine got a 2 (652 of 5,904), so v2 has a median of 10 "right" paragraphs per question against 2 in the original key. Some added paragraphs are arguable (a UNHCR guideline quoted in a case, a paragraph describing the applicant's argument). The recall and MRR increases come partly from simply having more right answers to hit.
- **Self-preference and family bias.** AI judges tend to favour text that looks like their own writing, and models from one family share blind spots. The judge here is a different model from the key's author, but both are Claude models. A run with a GPT-5.x model through the same proxy would be the next independence check; it has not been run.
- **Position and order effects.** A model can grade differently depending on where a paragraph appears in a 100-paragraph list. We shuffle with a recorded seed and re-judged 15 questions in a different order to measure this; the 86% exact agreement is the measured size of the effect.
- **Pooling blind spot.** A paragraph that no one of the 12 set-ups returned is never judged, so a better search method that finds new paragraphs would be under-credited by this key. Re-pool when the retrieval changes a lot.
- **Human spot-check.** Ten items for Dan are in `docs/eval-judging.md` (original paragraphs the judge rejected, added paragraphs it accepted, grades that flipped between runs). Ten items cannot validate 5,904 grades; they show whether the judge is sensible, not how accurate it is.
- **Only 59 questions**, and the 12 counting questions are not covered at all. Differences of a few hundredths between set-ups are noise.
