# Build report: echr-lookup

_Written 2026-11-04 ~11:40 UTC by orchestrator #3 (`ses_e59e0b9f7ffe3ms3p7CJIoJNj6`). Source of truth for numbers: `scripts/orchestration/usage-all.sh` (opencode session exports; no estimates) and `cost_log` in the app databases._

## Outcome

All gates passed and the demo was rehearsed twice from a fresh `docker compose up` (`docs/demo.md`, rehearsal log at the end).

| Gate | Tasks | PRs | Result |
|---|---|---|---|
| G0a / G0b | scaffold; HUDOC measurement, snapshot, contract, estimates, embedder | #1, #2 | merged 2026-11-03 |
| Gate 1 prep | interfaces, config, fixtures, prompts | #3 | merged |
| Gate 1 | S1 ingest, S2 parse + chunk, S3 index + search, S4 answer + citations, S5 API, S6 eval, C1 capture (+ `pnpm dev` fix) | #4–#11 | merged 21:25; check passed (snapshot load re-based to ~264 s by Dan) |
| Post-gate fixes | S1-fix listing loop, S4-fix stats + neutrality, S2-fix K2 grounds, S1-retry transport retries | #12–#15 | merged; stats accuracy 6/12 → 11/12, neutrality 6/11 → 11/11 |
| Full ingest (once) | `echr_full`: 3,527 of 3,782 loaded | — | done 11-04 09:07 |
| Gate 2 prep | typed API client, nav shell, per-worker ports/DBs | #16 | merged 10:41 |
| Gate 2 | I1 Ask + case viewer, I2 Lab, I3 Stats | #17–#19 | merged 11:04; check passed (every page < 2 s, demo steps 1–5 reachable) |
| Rehearsal | R1 copy/label fixes; docs (`demo.md`, learning-docs README, capabilities) | #20, #21 | two clean runs |

## Time, tokens and cost per task

All coding agents: `github-copilot/claude-sonnet-5.5`; orchestrators: `github-copilot/claude-opus-5.5`. `cost_budget` prices cache writes at the input rate (the conservative figure used against the $100 budget); `wall_min` is the session's first-to-last message span, including idle waits for follow-ups.

| task | model | input | output | reasoning | cache_read | cache_write | cost_opencode | cost_budget | wall_min |
|---|---|---|---|---|---|---|---|---|---|
| orchestrator | github-copilot/claude-opus-5.5 | 368 | 124780 | 89129 | 39437458 | 1302312 | 12.17 | 17.38 | 298.2 |
| orchestrator2 | github-copilot/claude-opus-5.5 | 557 | 90937 | 57007 | 35788427 | 1437070 | 10.12 | 15.87 | 866.1 |
| orchestrator3 | github-copilot/claude-opus-5.5 | 242 | 51659 | 24574 | 12552438 | 423062 | 4.04 | 5.73 | 58.2 |
| G0b | github-copilot/claude-sonnet-5.5 | 2475 | 186593 | 115531 | 55888800 | 538979 | 8.64 | 9.69 | 71.1 |
| S1 | github-copilot/claude-sonnet-5.5 | 2224 | 63792 | 21876 | 8337015 | 423624 | 1.71 | 2.54 | 60.5 |
| S2 | github-copilot/claude-sonnet-5.5 | 2241 | 66886 | 37710 | 12242707 | 228738 | 2.3 | 2.73 | 26.6 |
| S3 | github-copilot/claude-sonnet-5.5 | 2170 | 46617 | 12931 | 4089437 | 122591 | 1.02 | 1.25 | 29.8 |
| S4 | github-copilot/claude-sonnet-5.5 | 310 | 130365 | 64546 | 32176543 | 1390049 | 5.17 | 7.95 | 147.4 |
| S5 | github-copilot/claude-sonnet-5.5 | 150 | 57404 | 19709 | 7471955 | 251866 | 1.52 | 2.02 | 78.5 |
| S6 | github-copilot/claude-sonnet-5.5 | 236 | 79338 | 38067 | 17797756 | 429324 | 2.95 | 3.81 | 99.2 |
| C1 | github-copilot/claude-sonnet-5.5 | 2130 | 20320 | 3743 | 1959412 | 67072 | 0.46 | 0.57 | 8.7 |
| S1fix | github-copilot/claude-sonnet-5.5 | 2713 | 9533 | 2994 | 484653 | 37506 | 0.2 | 0.25 | 4.7 |
| S2fix | github-copilot/claude-sonnet-5.5 | 2607 | 8012 | 605 | 631330 | 34300 | 0.17 | 0.22 | 6.2 |
| S1retry | github-copilot/claude-sonnet-5.5 | 32 | 11375 | 1638 | 523942 | 42055 | 0.18 | 0.27 | 5.9 |
| I1 | github-copilot/claude-sonnet-5.5 | 2144 | 38702 | 12764 | 3896552 | 111465 | 0.92 | 1.13 | 18.3 |
| I2 | github-copilot/claude-sonnet-5.5 | 2103 | 36782 | 9677 | 2790536 | 95974 | 0.76 | 0.94 | 15.2 |
| I3 | github-copilot/claude-sonnet-5.5 | 2082 | 33830 | 4218 | 2148238 | 89500 | 0.61 | 0.78 | 10.3 |
| R1 | github-copilot/claude-sonnet-5.5 | 2123 | 23621 | 9885 | 3681301 | 112963 | 0.74 | 0.93 | 12.0 |
| tests | github-copilot/claude-sonnet-5.5 | 4 | 4 | 0 | 5331 | 5504 | 0.0 | 0.01 | 0.0 |
| tests2 | github-copilot/claude-opus-5.5 | 4 | 4 | 0 | 5331 | 5500 | 0.0 | 0.02 | 0.0 |

Total (budget figure): $74.09

**Wall time, start → merge:** S2 27 min, S3 31, S1 60, S4 71, S5 78, S6 99, C1 103 (all started 19:42, run in parallel; Gate 1 merged in 1 h 43 min). Gate 2: I3 15 min, I2 17, I1 21 (started 10:43, all merged by 11:04); R1 13 min.

**App runtime (Anthropic, from `cost_log`):** ≈ $5.66: Gate 1 + fixes $5.30 (S4-fix $2.84, S6 judged eval $2.19, S4 ~$0.23, orchestrator timing $0.04), Gate 2 + rehearsal ≈ $0.36 (I1 + R1 live asks $0.14 on `echr_i1`, gate check, rehearsals and try-it verification $0.22 on `echr`). Embeddings and reranking are local and cost $0.

**Total at writing ≈ $79.8 of $100** (build $74.09 + app ≈ $5.66). **Final after A1: ≈ $100.3** (build $86.46 + app ≈ $13.81). This is the figure at the end of A1; the refactor A–G that followed brought Build 1 to **≈ $114.5 all-in** (build $100.03 + app ≈ $14.5), the number used in `retrospective.md`. Gate 2 + rehearsal cost ≈ $10 (orchestrator #3 ≈ $5.7 at writing, I1–I3 $2.85, R1 $0.93, app $0.36) against a $15–24 forecast.

## Ingestion: actual vs estimated

| Run | Stage | Estimate (G0b) | Actual | Why |
|---|---|---|---|---|
| Snapshot from empty (98 docs) | total | 149 s (gate ≤ 224 s) | 211–225 s (246 s under agent load) | 16,154 chunks vs 13,724 estimated (+18%); embedding is ~97% of the time. Target re-based to ~264 s |
| | embed | 147 s | 219 s | as above |
| | 2nd run (no changes) | < 15 s | 4.6 s | skip by content hash |
| Full HUDOC (3,782 seen) | download | ~72 min | ~73 min | 1 req/s via the Orca browser transport; on target |
| | parse | — | 36 s | |
| | chunk | — | 122 s | |
| | embed | ~22 min | **44.6 min** | 2× over: the estimate scaled snapshot chunks/doc; full-corpus documents are longer, and the machine was shared |
| | index | — | 5.8 min | BM25 + HNSW over the larger table |
| | outcome | — | 3,527 loaded, 257 failed (212 scanned Commission-era decisions with no text, 45 communicated cases without numbered paragraphs, 2 empty), 307 Commission reports skipped | |

## Top bottlenecks

1. **Orchestrator cost.** Three Opus orchestrator sessions cost ≈ $39 of the $74 build (≈ 53%). Long contexts re-read on every turn (cache reads ≈ 35–40M tokens per session) dominate; worker sessions were cheap ($0.2–4 each). Gate 2, with a tight prep step and long poll waits, needed far less orchestration.
2. **Quality found late.** Stats accuracy (6/12) and neutrality (6/11) only surfaced in S6's eval after Gate 1, costing an S4-fix round ($3.65 + $2.84 app). The eval questions with expected counts existed only as S6's drafts.
3. **Estimates from the snapshot.** Chunk counts (+18%) and full-corpus embedding (2×) were under-estimated because G0b measured on the snapshot, on an idle machine.
4. **Full-ingest robustness.** An infinite HUDOC listing loop (710 polite requests before it was stopped, #12) and transient `orca eval` failures (#15) each needed a fix and a resume.
5. **Machine contention.** Parallel embeddings across worktrees (load avg ~9) skewed timings; solved by one orchestrator ingest plus `create database … template echr` copies per worker.
6. **Environment friction:** SSH pushes failing (HTTPS-via-gh workaround), port 3000 owned by another app, `pnpm search` shadowed by pnpm's built-in, `pnpm dev --parallel` not running root scripts (#11), opencode background shells dying when a session idles (long jobs moved to Orca terminals).
7. **Contract gaps** found mid-build: no `report` DocType (307 Commission reports skipped), no stat-accuracy fields in `EvalRun`.

## Changes for the next plan prompt

1. **Budget the orchestrator explicitly** (e.g. ≤ 35% of build), hand off at a fixed context size, and do gate prep up front so the coordinator mostly waits (long `check --wait`, delta-only poll output).
2. **Write the eval set first.** Put the question set, with expected paragraphs, expected counts and SQL oracles, before the answer task, and make "eval green" part of the answer task's acceptance.
3. **Estimate ingestion on a random sample of the full corpus** under realistic load, with real tokenizer chunk counts; report a range, not a point.
4. **Keep the per-gate prep step** that made Gate 2 fast: typed client from the contract, path-ownership table, per-worker DB copies and ports, stable `data-testid`s.
5. **Fix the environment in G0a:** working git auth, free ports (`WEB_PORT`/`API_PORT` from day one), long jobs in Orca terminals.
6. **Design for both corpora in one DB:** search filters by `data_source`, and `reset()` keeps `cost_log` and `eval_runs`.
7. **Contract completeness review** before Gate 1 against the real HUDOC doc types and the eval metrics the README will show.
8. **Make a demo smoke check part of the gate** (curl timings for every demo URL + the capture specs), as done in this rehearsal.

## After the rehearsal: A1 answer first (#22, 2026-11-04 14:11–15:25)

Dan's own testing found the headline answer unhelpful: a list of cited facts with no direct answer. Causes: the generator prompt allowed only single-paragraph claims and over-applied neutrality; retrieval let statute text crowd out the Court's holdings; and the verifier truncated its replies (200 tokens) with no retry. A1 added a verified short answer first (optional `Claim.role` / `Claim.group` in the contract), grouped evidence, planned and diversified retrieval for explain questions, and a verifier retry. Demo Q1 now opens "Not as a general rule: the Court has blocked some UK deportations, such as Chahal v UK (Article 3) and A.A. v UK (Article 8), while in Balogun v UK it held deporting to Nigeria would not violate Article 8."

Cost: estimate $5–7, actual ≈ $20.5 (worker $4.75; live app $8.12, including two judged evals at $2.6 each where ~$2.1 was expected, plus ~75 prompt-tuning asks; orchestrator +$7.6). The overall build reached the $100 budget here.

**Lessons:** (1) a usefulness check by the owner (not only metric gates) belongs in Gate 1: the eval passed while the answer shape was wrong; (2) prompt-tuning needs a fixed live-ask budget and an offline replay set; (3) the judge scores each citation alone, which penalises legitimate multi-source summaries, and value-question neutrality is noisy (pre-A1 code passed 5/10 on two items), so neutrality needs repeated sampling; (4) **orchestrator waits longer than the prompt-cache lifetime (~5 min) re-write the whole context on the next turn**: in the budget figure that cost more than the waiting saved. Prefer waits under 5 min while the context is large, or hand off to a fresh, small orchestrator.

## Open items for Dan

- **stat-003 expected count:** 4, not 5 (K2 is citizenship deprivation, not deportation, under S4's definition). Confirm when reviewing the draft question set (`data/eval/questions.jsonl`, all `status: draft`).
- Optional: store the 212 scanned decisions as metadata-only rows in `echr_full` so full-mode counts are complete; parse communicated cases' unnumbered paragraphs.
- The reranker tends to lift passages that quote s.3(5)(a) of the Immigration Act 1971 for the headline question (visible in `/lab`); a retrieval-quality item for a future eval round, not a demo blocker.

## Follow-up slice: F1 and F3 (2026-11-05 20:30 → ~21:35 UTC)

All agents `github-copilot/claude-sonnet-5.5`, orchestrator included. Source: `scripts/orchestration/usage-f.sh` (opencode exports). Budget $10 all-in, live cap $5.

| task | PR | input | output | reasoning | cache_read | cache_write | cost_opencode | cost_budget | wall_min | result |
|---|---|---|---|---|---|---|---|---|---|---|
| F1 citations + instructions | #30 | 2011 | 43181 | 19647 | 6461469 | 153166 | 1.31 | 1.58 | 20.1 | merged; text-fragment URLs, `para_label`, new instructions; paragraph ids unchanged (114 real-DB id lists identical) |
| F3 fair measurement | #29, #31 | 2169 | 73481 | 40156 | 19962830 | 489106 | 3.15 | 4.12 | 55.5 | free part merged (recall@k, qrels-v2 re-score, or-09 diagnosis); paid re-run **not run** (API key at usage limit until 2026-12-01; two 1-token pings failed); offline harness prep merged |
| orchestrator (this session) | | 104 | 19937 | 11490 | 3166846 | 169924 | 0.63 | 0.97 (at 21:35) | 58.5 | |

Totals at the time of writing: agents ≈ $6.7 (budget figure), live app spend **$0**, so ≈ $6.7 of $10. F3 ran about twice its $2 soft target (long investigation of or-09 and of the key failure; the second ping and the key-fingerprint comparison alone cost ≈ $0.7 of agent tokens). Orchestrator share ≈ 15%.

Lessons: (1) check the API key with a one-token ping in Step 0, not at the start of the paid part (the previous slice's log already said the limit was hit); (2) tell workers who are blocked on a human to stop and idle, not investigate.
