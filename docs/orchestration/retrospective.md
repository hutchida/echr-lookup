# Retrospective: building echr-lookup (2026-11-03 → 2026-11-04)

_Post-mortem written 2026-11-04 by orchestrator #3 (`ses_e59e0b9f7ffe3ms3p7CJIoJNj6`) for Dan, to feed back to the planning agent. Companion: [`one-shot-prompt.md`](one-shot-prompt.md), a rewritten brief that builds these lessons in from the start._

Sources: [`plan.md`](plan.md) (the original brief and its amendments), [`status.md`](status.md) (timestamped decision log), [`report.md`](report.md) (per-task numbers), [`handoff.md`](handoff.md) §5 (environment gotchas), [`tasks/`](tasks/) (all 23 task briefs), [`../decisions.md`](../decisions.md), [`../demo.md`](../demo.md) (rehearsal log), and the final round of fixes after Dan's own testing (uncommitted at the time of writing).

## 1. What was built

A local RAG app over the UK's case law at the European Court of Human Rights (HUDOC), plus the Convention and the Human Rights Act. Every claim cites a paragraph, a second model checks each claim against its paragraph, and counting questions go to a fixed SQL template rather than the model.
- **Stack:** pnpm monorepo. Next.js 16 web app; FastAPI; Python RAG pipeline (`py/rag`); zod contract exported to JSON Schema and validated on both sides; ParadeDB (BM25 + pgvector); local embedder (bge-small) and reranker (bge-reranker-base); Claude Sonnet 5.5 writes the answers, Haiku 5.5 routes and verifies.
- **Corpus:** a committed 98-document snapshot (the demo), plus a one-off full HUDOC ingest (3,527 UK documents) in a separate database.
- **Pages:** `/ask` (cited answer, or SQL stats with the query shown), `/case/<id>` (the cited paragraph highlighted), `/lab` (BM25 / vector / fused / reranked side by side), `/stats` (corpus, ingest timings, cost log, eval table).
- **Eval:** 71 questions (draft, awaiting Dan's review): recall@k, MRR, faithfulness, citation accuracy, neutrality, stat accuracy.
- **Docs:** a learning doc per task (`docs/learn/`), a demo script, and a capabilities list.

| Gate | PRs | Result |
|---|---|---|
| G0a scaffold, G0b HUDOC measurement + snapshot + contract + estimates | #1, #2 | 11-03 afternoon |
| Gate 1 prep (interfaces, config, fixtures, briefs) | #3 | 11-03 |
| Gate 1: S1 ingest, S2 parse/chunk, S3 index/search, S4 answer/citations, S5 API, S6 eval, C1 screenshots, `pnpm dev` fix | #4–#11 | 7 parallel workers, 19:42 → 21:25 |
| Post-gate fixes: listing loop, stats + neutrality, K2 grounds, transport retries | #12–#15 | 11-03 evening, 11-04 morning |
| Full ingest (once) | — | 21:36 → 09:07, overnight |
| Gate 2 prep, then I1 Ask + case, I2 Lab, I3 Stats | #16–#19 | 3 parallel workers, 10:43 → 11:04 |
| Rehearsal fixes (R1), demo docs | #20, #21 | two clean runs |
| A1 answer first (after Dan's testing) | #22 | 14:11 → 15:25 |
| Final honesty refactor A–G (after Dan's testing) | uncommitted | ~16:00 → 17:00, done by the orchestrator |

## 2. Timeline (UTC)

- **11-03 15:34:** Orca run created; G0a, then G0b. The budget was raised from $50 to $100.
- **19:42:** Gate 1 launched: 7 Sonnet workers in parallel, disjoint paths, one database each.
- **20:05–20:48:**
  - contract gaps surfaced (no Commission-report doc type; no stat-accuracy field);
  - parallel embeddings overloaded the Mac, so the orchestrator ingested once and template-copied the database.
- **21:25:** Gate 1 merged. The check passed, except the snapshot load: 224.6 s against a 224 s limit, later re-based.
- **21:36:** full ingest started. **21:55:** stopped after an infinite HUDOC listing loop (710 polite requests). Fixed (#12) and resumed.
- **21:50–22:10:** S6's eval showed stats accuracy 6/12 and neutrality 6/11, which S4-fix took to 11/12 and 11/11.
- **11-04 09:07:** full ingest done: 3,527 loaded, 257 failed (scanned decisions with no text, communicated cases with no numbered paragraphs).
- **10:41–11:04:** Gate 2 prep, then three UI workers, all merged within 21 minutes. Gate check passed.
- **11:10 and 11:28:** two rehearsal runs from a fresh `docker compose up`, all budgets met.
- **~13:30, Dan's first test:** the deportation question gave a list of cited facts, no direct answer. This led to **A1 (#22)**.
- **~15:45, Dan's second review:** six honesty and clarity defects. This led to **refactor A–G**:
  - Ask implied the corpus covered all the case law;
  - the count prose dropped a total and used jargon;
  - the example quotes contradicted the count;
  - chips didn't show the document type;
  - quotes were cut before the supporting sentence;
  - a short answer opened with "Yes" when the holding was narrower.

## 3. Final time and cost

| | Budget figure ($) | Notes |
|---|---|---|
| Orchestrators #1 / #2 / #3 (Opus 5.5) | 17.38 / 15.87 / 26.92 | **60.17 = 60% of build spend** |
| G0b + fix | 9.69 | |
| Gate 1 workers incl. follow-ups (S4 7.95 incl. S4-fix) | ≈ 22 | |
| Gate 2 workers I1 / I2 / I3, R1 | 1.13 / 0.94 / 0.78, 0.93 | Gate 2 total ≈ $6 vs a $15–24 forecast |
| A1 worker | 4.75 | |
| **Build total** (`usage-all.sh`) | **100.03** | cache writes priced at the input rate |
| App runtime (Anthropic, `cost_log`) | ≈ 14.5 | Gate 1 5.30; Gate 2 + rehearsal 0.36; A1 8.12 (two judged evals ~$5.30, ~75 tuning asks); refactor checks 0.73 |
| **All-in** | **≈ 114.5 of the $100 budget** | |

Elapsed time was about 25.5 h, including an overnight full ingest and two long waits for Dan. Active build time: Gate 1 1 h 43 m, Gate 2 21 m.

## 4. What went well (keep)

1. **Contract first.** zod is the single source, exported to JSON Schema, with fixtures, and Python validates against it in tests. Parallel workers never drifted, and every shape change (e.g. `doc_type`, `scope_total`) was caught by tests on both sides.
2. **An orchestrator-owned interfaces file** (`docs/interfaces.md`): Python signatures, database tables, ports, ownership. Seven workers built in parallel against fakes, then integrated.
3. **One database per worker, copied from a template.** It removed contention and repeated embedding.
4. **A prep step before each gate** (typed client, ownership table, stable test IDs, ports). Gate 2 took 21 minutes and about $6.
5. **The model never writes SQL.** It fills a validated parameter template; the SQL runs read-only with a timeout; the SQL is shown to the user.
6. **Cost logged per call** (`cost_log`), and a usage script for agent sessions. Every number in the reports is measured, not estimated.
7. **Polite, resumable, incremental ingest** (1 request/s, content hashes). The full corpus loaded without a block.
8. **Rehearsing the demo twice from a fresh start**, with browser screenshot specs as smoke tests.
9. **A learning doc per task** with try-its, so Dan can verify each part himself.

## 5. What went wrong, and why

| # | What happened | Root cause | Cost | Prevention (now in the one-shot prompt) |
|---|---|---|---|---|
| 1 | **Every gate passed, but the answers weren't useful or honest.** Dan found it by using the app, twice (A1, then A–G). | The answer's shape (direct answer first, reach of the holding, corpus honesty, document types, quote rules) was never specified as a product requirement, and the metrics (faithfulness, citation accuracy, neutrality) can't detect an unhelpful but faithful answer. | ≈ $34 (A1 ≈ $20.5; refactor ≈ $14) | Write the answer rules into the brief. **Owner usefulness review** at Gate 1 and Gate 2, using 10 fixed real questions with expected answer shapes. |
| 2 | Stats accuracy 6/12 and neutrality 6/11, found after Gate 1 | The eval set (with expected counts) was written in parallel with the answer code, not before it | S4-fix $3.65 + $2.84 app | Write the eval set first, with SQL oracles; make passing it part of the answer task's acceptance |
| 3 | The orchestrators cost 60% of the build | Long-lived Opus contexts (150–250K tokens) re-read every turn; waits longer than the ~5-minute prompt-cache lifetime re-wrote the whole context; feature work (refactor A–G) done inside the orchestrator | ≈ $60 | Cap the orchestrator at 35% of budget; hand off at about 120K tokens; waits under 5 minutes or a fresh session; **the orchestrator never codes** (delegate every change to a Sonnet worker) |
| 4 | Estimates missed | Ingestion was estimated from the snapshot on an idle machine: 18% more chunks than estimated, and full-corpus embedding 2× (44.6 vs 22 min). Eval runs cost $2.63 vs $2.10. A1 was estimated at $5–7 and cost ≈ $20.5. | Re-basing, overruns | Estimate from a random sample of the full corpus under load; give ranges; give a hard live-call cap per task |
| 5 | The full ingest needed two fixes | An infinite HUDOC listing loop (710 requests); transient browser-call failures with no retry | Two fix tasks, a restart | A "pager terminates" test with a recorded last page; retry and backoff from day one; a dry run with `--limit` before the full run |
| 6 | Environment friction | SSH push broke; port 3000 owned by another app; `pnpm search` is pnpm's own command; `pnpm dev --parallel` didn't run root scripts; shell exported a work-proxy `ANTHROPIC_BASE_URL` (the first key test went to the proxy) | Hours of small detours | A G0 environment check: git auth, free ports, env scrub, script names; long jobs only in Orca terminals |
| 7 | Gaps found mid-build in the contract and data | No Commission-report doc type (307 skipped); no stat-accuracy field; Citation had no `doc_type`; no total for "how many X, and how many of them Y" | Workarounds, later contract changes | A contract review against real HUDOC doc types, the eval metrics and the answer rules before Gate 1 |
| 8 | Design traps | Search ignored `data_source`, so the full corpus needed its own database; `reset()` emptied `cost_log` and `eval_runs`, so the Stats eval table was empty after a reset | Extra database, demo setup step | Filter by `data_source`; never wipe logs on reset |

## 6. Pitfalls by stage (the details)

**Environment and tooling**
- zsh: never name a variable `path`; variables aren't word-split (use functions, not `P="docker exec …"; $P`).
- opencode background shells die when the session idles or the Mac sleeps. Run anything long in an Orca terminal.
- `uvicorn --reload` also reloads when test files change, and reloading the models makes the next request slow (one took 66 s). Warm up before a demo; Next dev compiles pages on first visit.
- Next.js 16 / React 19 differ from training data: read `node_modules/next/dist/docs/`. `next dev` rewrites `apps/web/AGENTS.md` and `next-env.d.ts`, so don't commit that churn.
- Port 3000 belongs to Dan's other app: use `WEB_PORT=3100`, plus per-worker `API_PORT` / `WEB_PORT`.
- Use `pnpm run search`, not `pnpm search`. Never `docker compose down -v`. `create database X template Y` needs no open connections to Y.
- Git: if SSH fails, use `git -c credential.helper= -c credential.helper='!gh auth git-credential' push https://github.com/<repo>.git <branch>`.
  - `gh pr merge --delete-branch` fails while a worktree has the branch checked out: merge, then `git push origin --delete`.
  - `gh run watch` right after a merge can catch the previous run.
- Build the Anthropic client explicitly from config, never from SDK environment defaults (`ANTHROPIC_BASE_URL` pointed at a work proxy).

**Orchestration (Orca + opencode)**
- `poll.py` doesn't acknowledge messages: ack each delivery after deciding the worker's next owner. An ack can return the next delivery.
- Agents' self-reported clock times can be ~30 min off: use `date -u` and PR timestamps.
- `opencode` model selection needs an existing worktree: create worktrees first, then `worker-start`.
- Parallel local embedding on one laptop pushed load to ~9 and skewed every timing. Embed once, then copy the database per worker.
- Prompt-cache expiry: Opus waits over 5 minutes with a large context cost more than the wait saved.
- A worker that asks before overspending is good. The orchestrator then has to say no, or report to Dan, instead of approving step by step (A1 went from a $4 to an $8 allowance).

**Data and ingest**
- HUDOC: 307 Commission reports (no doc type); 212 scanned 1970s–2000s decisions with no text; 45 communicated cases without numbered paragraphs; 2 empty replies.
- The listing pager can loop forever. Browser calls fail transiently: retry 3× (5/15/45 s), never retry a block.
- Incremental ingest skips by file hash, so parser changes need `--reset`. `--reset` also wipes `cost_log` and `eval_runs` (then re-run the retrieval eval before a demo).
- A no-change ingest run becomes the "last run" on `/stats`, hiding the real load timings.

**Retrieval**
- Recall@5 is about 0.23 on the 71 questions: retrieval is the weakest layer. The headline demo works because the answer context is curated after search.
- Recited domestic statute text ("section 3(5)(a) of the Immigration Act 1971…") ranks highly for deportation questions, so the answer context demotes it (`demote_statute_quotes`). Extradition cases (Soering) can stand in for deportation unless the context is planned by legal ground.

**Answers and citations**
- Without explicit rules the model writes a list of facts, not an answer. With "answer first" it over-generalises ("Yes" when the holding covered particular applicants). The fix is a rule about matching the reach of the holding, in both the generator and the rewrite prompt.
- Verifier replies were capped at 200 tokens with no retry, so long claims came back "Unverified (JSONDecodeError)". Now 700 tokens and one retry.
- Quote windows:
  - splitting sentences on `;` and `:` opened quotes mid-sentence ("and circumstances where…");
  - extending only forward cut off the sentence naming the Article;
  - abbreviations ("v.", "art.", "A.H.") and list items need care.
- Legal summaries (`002-…`) look like the judgment unless the document type is shown.
- An answer that reads "the Court has never decided this" when the corpus is a 98-document UK sample is misleading. The Ask page must state the corpus scope.

**Stats path**
- The template must cover the question's whole shape: "found a violation" includes `mixed`; "declared inadmissible" excludes `partly_inadmissible`; "most common X and how many" is the top group; "how many X, and how many of them Y" needs both numbers.
- The prose must name every filter in plain words: no "in formation", no raw enum keys, no implied "UK" filter.
- An example quote taken from operative paragraph 1 often contradicts the count (preliminary objection, join to merits, admissibility, "no violation"). Pick the clause that states the counted outcome, or show no quote.
- The count's evidence is the SQL. Example paragraphs must not be attached as the count's citations.
- The definition of "deportation case" decides counts (stat-003: expected 5, the system says 4). Write definitions down with the eval set.

**UI**
- Chips must sit at sentence ends; enum keys need plain labels; an unknown case needs a real 404.
- Long sentences need an ellipsis when cut, so a cut never reads as the whole sentence.
- Follow-up questions should be plain `GET /ask?q=` links (stateless), not a conversation.

**Eval**
- The judge scores each citation on its own, which penalises a legitimate multi-source summary (citation accuracy fell from 0.98 to 0.93).
- Neutrality on value questions is noisy: old and new code both passed about half the time on two items. One run per config isn't enough; sample repeatedly.
- A baseline that silently skipped an unscored item (reported as 1.00) made the later 0.82 look like a regression.
- None of the metrics catch "faithful but unhelpful". That needs a human review with written expectations.

## 7. Defects found by the owner, and the requirement that would have prevented each

| Defect (what Dan saw) | Fix | Requirement for next time |
|---|---|---|
| No direct answer to "Does the Convention stop the UK deporting criminals?" | A1: verified short answer first, grouped evidence | Explain answers open with a one-sentence direct answer about what the law does, backed by 1–3 citations |
| Short answer "Yes…" when the holding covered particular applicants | F: reach-of-holding rule in both prompts | No bare Yes/No unless a cited paragraph states the general rule; otherwise lead with the holding, or "Not as a general rule" / "It depends on…" |
| Weak evidence (statute text, an extradition case for deportation) | A1: planned and diversified context, statute demotion | Plan the answer context by legal ground and by outcome both ways; prefer the Court's reasoning and holdings over recited legislation |
| Ask read as if it covered all the Court's case law; refusals implied "never decided" | A: corpus line from GET /stats; refusal wording | The Ask page always states the live corpus size, scope (UK only) and whether it's a sample; refusals say so |
| "How many GC judgments, and how many found a violation?" dropped the total; "in formation" jargon | B: run the template twice; plain wording | Counting answers state every number asked for, in plain words |
| Violation counts illustrated by "no violation" or procedural clauses | C: pick the clause stating the counted outcome, or no quote; examples not cited as evidence | Examples illustrate; they never contradict the count and are never its citations |
| Legal summary indistinguishable from the judgment | D: `doc_type` on Citation; labelled chips and sources | Every citation shows its document type; a legal summary is visibly not the judgment |
| Source card cut off before the supporting sentence, or opened mid-sentence | E: sentence-aware quote windows; ellipsis on cuts | Quotes are verbatim, contain the supporting sentence, and start and end at sentence boundaries when one exists |
| No way to keep exploring | G: stateless follow-up links | Two or three standalone follow-up questions per answer, as plain links |
| Verifier errors shown as "Unverified" | A1: 700 tokens + retry | Verification must not fail silently; parse failures retry once and are counted |

## 8. Open items

- Dan to review the 71 draft eval questions; stat-003's expected count should probably be 4, not 5.
- The refactor A–G is uncommitted: review, then PR, then the free retrieval eval (ranking wasn't touched). The learning docs that describe the chips and the stats answer (S4, I1) need a refresh.
- Optional: metadata-only rows for the 212 scanned decisions; parse communicated cases' unnumbered paragraphs.
- Retrieval quality (recall@5 ≈ 0.23) is the biggest remaining technical gap.
