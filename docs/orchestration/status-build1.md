# Orchestration status

_Last updated: 2026-11-04 15:30 UTC · A1 merged; **$100 budget reached: no new launches**_ · Orchestrator #3: `github-copilot/claude-opus-5.5` (session `ses_e59e0b9f7ffe3ms3p7CJIoJNj6`; #1 `ses_e5e0e07a8ffeNS2flouzfA6Z4q` and #2 `ses_e5cfd3c23ffee1W6h4E7UXcj50` retired) · Orca run `run_5aad27308746`

## Gates

| Gate | State | Notes |
|---|---|---|
| G0a: scaffold | ✅ merged (#1) | Fresh clone check 17 s |
| G0b: HUDOC, snapshot, contract, estimates | ✅ merged (#2) | |
| Gate 1 prep (interfaces, config, fixtures, prompts) | ✅ merged (#3) | Anthropic key verified: Sonnet 5.5 + Haiku 5.5 OK via api.anthropic.com |
| Gate 1: S1–S6, C1 | ✅ merged 21:25 (#4–#11), main green; check done 21:35 (see below) | Full ingest running into `echr_full` since 21:36 |
| Gate 2 prep (typed API client, nav shell, ports, interfaces §8–10) | ✅ merged 10:41 (#16, `e5082bd`) | per-worker DBs `echr_i1..3` (template `echr`, 12 eval runs copied from `echr_s4`) |
| Gate 2: I1–I3 | ✅ merged 11:04 (#17–#19), main green; check done 11:12 (see below) | **forecast $15–24** (seen by Dan): 3 Sonnet workers ~$3–5 each incl. follow-ups, orchestrator #3 ~$6–9, I1 live asks ≤ $1 |
| Rehearsal | ✅ two clean runs from fresh `docker compose up` (11:10, 11:28); R1 copy fixes #20; docs #21 | log in `docs/demo.md`; report `docs/orchestration/report.md` |

## Gate 2 tasks

| Task | Started | State | PR | Dispatch | opencode session |
|---|---|---|---|---|---|
| I1 Ask + case viewer | 10:43 | ✅ merged 11:04 (`1f2f6b7`); streamed `/ask?q=` (Suspense), chips + badges + per-step cost, `/case` `:target` highlight; /ask 0.02 s, /case 0.14 s, Q1 6–9 s, Q2 6–7 s, Q3 1.3 s; live spend ~$0.09; $1.13; worker released. Nit: unknown case id renders inline error with HTTP 200 | #19 | `ctx_6e05f34ce657` | `ses_e59d83e96ffeXh1qvsGqSNtO4w` |
| I2 Lab | 10:43 | ✅ merged 11:00 (`5a02f30`); 4 parallel searches; /lab warm 1.06–1.19 s (by_section 1.84–1.98 s); 25 tests; $0.94; worker released. Note: reranker puts s.3(5)(a) statute-quoting passages top for demo Q1 | #18 | `ctx_eb6e21eed00c` | `ses_e59d8373dffeVAKzZu66T80EVW` |
| A1 answer first (Dan's feedback: no direct answer; weak evidence; verifier JSON bug) | 14:11 | ✅ merged 15:25 (`5213f2f`). Short answer first + grouped evidence; planned/diversified retrieval for explain questions (value path unchanged, tested); verifier 700 tokens + retry (0 of 329 claims with verifier errors). Eval (5-point prompt): hybrid 0.98/0.94/1.00, rerank 0.95/0.93/0.82 (faith./cit./neutr.); citation drop = judge scores each short-answer citation alone; neutrality 0.82 = judge noise (pre-A1 main 5/10 vs 4/9 on 004/011). Worker $4.75 + live $8.12 (two judged evals $5.30) vs estimate $5–7; worker released. New eval runs copied into `echr`; demo Q1 11.2 s on `echr` | #22 | `ctx_f9a433edbcbc` | `ses_e59197cfdffeFmlFIijLespmkE` |
| R1 rehearsal copy/label fixes | 11:14 | ✅ merged 11:27 (`2f8251b`); stats sentence names every filter, chips at sentence end, plain ground labels, 404 for unknown case; counts unchanged (27, stat-003 4); $0.93; worker released | #20 | `ctx_e6587090a2a5` | `ses_e59bb584cffeJmkoiUxp9U7wkk` |
| I3 Stats | 10:43 | ✅ merged 10:58 (`a21bf93`); PR 10:51, CI green; /stats warm 0.14 s; 43 tests; $0.78; worker released | #17 | `ctx_aaca9eb913b3` | `ses_e59d8300fffe7KwXIn6264yS44` |

**Gate 2 check (main @ `03e39f7`, DB `echr`, `WEB_PORT=3100 pnpm dev`, live LLM):**
| Check | Budget | Result |
|---|---|---|
| `pnpm check` | green | ✅ 63 s local: web 91 tests, capture 21, pytest 507 passed / 4 skipped (live) |
| Page loads (warm, curl total) | < 2 s | ✅ `/` 0.03 s · `/ask` 0.02 s · `/case/001-57619` 0.13 s · `/lab` 1.06 s · `/lab?q=<Q1>` 1.05 s · `/stats` 0.16 s |
| Demo 1: `/ask?q=Q1` | < 15 s | ✅ 7.1 s (first byte 0.15 s, streamed), 7 citation chips, all supported; chip → `/case/001-108113#p19`, anchor present |
| Demo 2: `/ask?q=Q2` | < 15 s | ✅ 6.6 s, 7 chips; chip → `/case/001-205796#pop2`, anchor present |
| Demo 3: `/ask?q=Q3` (stats) | < 15 s | ✅ 1.8 s, route "Stats: SQL over metadata", SQL block, 27 cases (8 listed) |
| Demo 4: `/lab` | reachable | ✅ 4 columns (bm25 / vector / fused / reranked) |
| Demo 5: `/stats` | reachable | ✅ corpus, ingestion, cost, eval sections (12 eval runs) |
| C1 `home.json` capture | passes | ✅ |
App spend for the check: $0.039 (42 `cost_log` rows). Gate 2 actual: orchestrator #3 ≈ $3.1 so far + I1 $1.13 + I2 $0.94 + I3 $0.78 + app ≈ $0.13 → **≈ $6** vs forecast $15–24.

## Gate 1 tasks

| Task | Started | State | PR | Dispatch | opencode session |
|---|---|---|---|---|---|
| S2 parse + chunk | 19:42 | ✅ merged 20:09 (`057e796`); main green; worker released | #9 | `ctx_6cbe4f21a5a1` | `ses_e5d11ac66ffe7gw7ikccXYNEcE` |
| S3 index + search | 19:42 | ✅ merged 20:13 (`225cc87`); main green; worker released | #10 | `ctx_93164fb4e14b` | `ses_e5d11a3abffewYln3h9GsjLWUm` |
| S1 ingest | 19:42 | ✅ merged 20:42 (`53d385a`); main green; worker released. Snapshot `--reset` 211 s (≤ 224), 2nd run 4.6 s, `--limit 5` 7 req @ 0.94 req/s, 307 HEREP skipped | #5 | `ctx_521f16bf6b68` → `ctx_544c224b93c4` | `ses_e5d119adaffeI1bNZrPkyG4Xm4` |
| S4 answer + citations | 19:42 | ✅ merged 20:53 (`dc23666`); main green. Demo Q1 7.0 s, Q2 7.2 s, Q3 1.5 s; live spend ~$0.23. Terminal retained by Orca (`user_takeover`) | #8 | `ctx_661a46c3217d` → `ctx_9f838e56dc09` | `ses_e5d118626ffecY714tAqZS17cz` |
| S5 API | 19:42 | ✅ merged 21:00 (`bc6db12`); main green; worker released. /stats 14–25 ms, /case 9–12 ms, /search hybrid 50–84 ms, rerank ~1.45 s | #6 | `ctx_7eadfbe93683` → `ctx_c77de58bbdcd` | `ses_e5d11644cffeeo53sKWmE6JdKw` |
| S6 eval | 19:42 | ✅ merged 21:21 (`6f7a199`); worker released. Judged run 8 m 19 s, $2.12; faithfulness 0.96, citation acc. 0.94–0.98, neutrality 0.55–0.75, stat acc. 6/12 | #7 | `ctx_adc7ee56ba2c` → `ctx_13d09d48120f` | `ses_e5d114a9effeA8A3C7yDLNR9rh` |
| S4-fix stats + neutrality | 21:50 | ✅ merged 22:10 (`a47cda4`), main green. Stat acc. 11/12 (was 6/12), neutrality 11/11 (was 6/11), faithfulness 0.952, citation acc. 0.982; demo 6.1/6.5/1.1 s; live ≤ $2.84. Remaining miss: S2 grounds extraction omits K2 v UK non_exhaustion | #13 | `ctx_ff86b93cc714` | `ses_e5d118626ffecY714tAqZS17cz` (reused) |
| S1-fix listing pager loop | 21:53 | ✅ merged 21:58 (`507b0fd`); resume finished decisions listing in 1 request; $0.25 | #12 | `ctx_5f58c4697665` | `ses_e5c9a4de1fferKp1BzSfF2KVDC` |
| S2-fix K2 grounds (metadata + text) | 08:39 (11-04) | ✅ merged 08:49 (`514bdad`); oracle 35/35 over all entries; only K2 changed; `echr` reloaded 08:50; $0.22 | #14 | `ctx_d5a497339809` | `ses_e5a490336ffecftBR5g4NZI8fs` |
| S1-retry transport retries | 08:39 (11-04) | ✅ merged 08:47 (`523fbd4`); 3 retries at 5/15/45 s, blocks never retried, 12 offline tests; $0.27 | #15 | `ctx_b3ae2c9bd5d1` | `ses_e5a48fb4affecMnryQLtTr4Egz` |
| C1 capture | 19:42 | ✅ merged 21:25 (`536fc14`); main green | #4 | `ctx_9129ee24f7ae` | `ses_e5d1140f8ffeMXb75kryKwGzze` |

Merge order: S2 → S3 → S1 → S4 → S5 → S6 → C1 (+ #11 `pnpm dev` fix), all merged by 21:25.

**Gate 1 check (main @ `536fc14`, DB `echr`):**
| Check | Budget | Result |
|---|---|---|
| `pnpm check` | green | ✅ 460 passed, 4 skipped, 63 s local |
| `ingest:snapshot --reset` from empty | ≤ 224 s → **re-based to ~264 s** (Dan, 11-04) | ✅ 224.6 s (embed 219 s); S1's clean run 211 s; 246 s under agent load. Cause: ~16.2k chunks vs G0b's ~13.7k estimate |
| 2nd snapshot ingest | < 15 s | ✅ 4.6 s (S1) |
| `/search` live (hybrid_rerank / hybrid) | < 3 s | ✅ 0.89 s / 0.05 s |
| `/ask` live Q1 / Q2 / Q3 | < 15 s | ✅ 7.2 s / 5.9 s / 1.1 s (stats route) |
| `eval:snapshot` writes the table | — | ✅ `--retrieval-only` on main, 249 s, identical numbers to S6; S6's judged run 8 m 19 s, $2.12 |
| `ingest:full` (once) | est. ~72 min download + 22 min embed | ✅ done 09:07 (11-04), DB `echr_full`: 3,782 seen, 3,527 loaded, **257 failed** (212 scanned 1950s–2000s Commission-era decisions: page images, no text; 45 communicated cases: no numbered paragraphs; 2 empty HTTP 204), 307 Commission reports skipped. Download ~73 min (est. 72). Processing 45.6 min wall: parse 36 s, chunk 122 s, **embed 44.6 min (est. 22)**, index 5.8 min |

Decisions during Gate 1:
- 08:45 (11-04): Dan accepted the snapshot-load result; target re-based to ~264 s (G0b's 149 s scaled to the real 16.2k chunks, +50%).
- 08:39 (11-04): Dan asked to tidy up before Gate 2: S2-fix (K2 grounds; the only oracle mismatch of 35) and S1-retry (retry transient `orca eval` failures). Then stop and wait for Dan's Gate 2 go-ahead.
- 21:55: stopped `ingest:full` (infinite listing loop, 710 HUDOC requests total, 1 req/s, no block). Fix → S1-fix; resuming counts as the same single full run.
- 21:50: Dan chose to fix stats accuracy (6/12) and neutrality (0.55) before Gate 2 → S4-fix on S4's terminal. Gate 2 go-ahead and the 224.6 s ingest question are still open.
- 21:13: the full ingest will go into a separate DB `echr_full` (created), because search doesn't filter by `data_source`; mixing it into `echr` would change the snapshot demo.
- 21:10: gate-check eval on main uses `--quick` (proves the table); S6's single full judged run supplies the real numbers (saves ~$3).
- 21:05: fixed `pnpm dev` (#11): `--parallel` made pnpm run recursively, so the root `dev:*` scripts never ran.
- 20:48: to avoid 4 parallel embeddings, the orchestrator runs the Gate 1 snapshot ingest into `echr` now (all ingest code merged) and template-copies it to the empty `echr_s5` / `echr_s6`.
- 20:31: S1's first timed ingest (242 s) overlapped S4's dev-loader embedding (load avg ~9; macOS Spotlight is also busy); asked for one clean re-run → 211 s.
- 20:19: S4's follow-up split in two: phase A (rebase, real search, dry run on S3's dev-loader data) now; phase B (real ingest, demo transcripts) after S1 merges. S4 blocks on `ask` between phases.
- 20:17: S1 follow-up: HEREP is skipped and counted in the CLI summary only (`IngestRun` is strict; contract gap).
- 20:05: S6 asked about stat accuracy (no contract field). Answer: report it in markdown/README only; expected count in tag `expected_count:<n>`.
- 20:15: S1 reported it never received the HEREP answer and stored reports as `decision`. Fix in its integration follow-up.
- 19:47: S1 asked about Commission reports (no `report` DocType). Answer: skip HEREP in full mode, and record the skipped count (contract gap noted).

## Budget ($100 total, raised from $50 by Dan on 2026-11-03)

Run `scripts/orchestration/usage-all.sh` for the live table (budget figure prices cache writes at the input rate).

| Item | Budget $ (21:38) |
|---|---|
| Orchestrator #1 (`ses_e5e0e07a8ffeNS2flouzfA6Z4q`, retired) | 17.38 |
| Orchestrator #2 (`ses_e5cfd3c23ffee1W6h4E7UXcj50`, retired 11-04 10:30) | 15.47 |
| G0b + fix | 9.69 |
| Gate 1 agents incl. follow-ups (S1 2.54, S2 2.73, S3 1.25, S4 4.30, S5 2.02, S6 3.81, C1 0.57) | 17.22 |
| Post-gate fixes: S4-fix 3.65, S1-fix 0.25, S2-fix 0.22, S1-retry 0.27 | 4.39 |
| Model test calls (Copilot) | 0.03 |
| App runtime (Anthropic): S4-fix $2.84, S6 eval $2.19, S4 ~$0.23, orchestrator /ask timing $0.04 | 5.30 |
| Orchestrator #3 (`ses_e59e0b9f7ffe3ms3p7CJIoJNj6`) | 3.10 (11:12) |
| Gate 2 agents: I1 1.13, I2 0.94, I3 0.78 | 2.85 |
| App runtime Gate 2: I1 live asks ~$0.09, gate check $0.04 | 0.13 |
| R1 | 0.93 |
| App runtime rehearsal + try-it checks (`echr` $0.22 total incl. gate check; R1 live on `echr_i1`) | ≈ 0.23 |
| A1: worker 4.75, live app 8.12 | 12.87 |
| Orchestrator #3 from 11:40 to 15:30 (long waits expired the prompt cache, so each turn re-wrote ~150K tokens) | +7.62 (now 13.35) |
| **Total (11-04 15:30)** | **≈ 100.3: $100 reached, new launches paused** (build $86.46 from `usage-all.sh`; app ≈ $13.81). opencode's own figure (cache writes at $0) is lower: orchestrator #3 $5.91 |
| _Superseded:_ Total (11-04 11:40) | **≈ 79.8** (build $74.09 from `usage-all.sh`, orchestrator #3 $5.73 at that point; app ≈ $5.66). **$80 threshold reached: Dan told.** |

Thresholds: message Dan at $50 and $80; pause new launches at $100.

## Open issues / notes for Dan

- ✅ Fixed in #13: stats accuracy 6/12 → 11/12, neutrality 6/11 → 11/11.
- ✅ #14: K2 now has both grounds. stat-003 still 4 vs expected 5: K2 (citizenship deprivation + exclusion) isn't a deportation case under S4's definition. Recommend expected = 4 when Dan reviews the drafts.
- Stats answer sentence omits its ground filter (SQL is right): copy fix at rehearsal.
- ✅ #15: `ingest:full` retries transient `orca eval` failures (3×), never blocks.
- Full corpus gaps: 212 scanned old decisions (no text without OCR; their metadata is in the listing, so they could be stored as metadata-only rows to keep full-mode counts complete) and 45 communicated cases (parser needs numbered paragraphs). The snapshot demo is unaffected.
- Incremental ingest skips by file hash, so parser changes need `--reset` to take effect.
- ✅ Snapshot load 211–225 s accepted; target re-based to ~264 s.
- **Search ignores `data_source`**, so the full corpus lives in its own DB `echr_full` (switch with `DATABASE_URL=…/echr_full DATA_SOURCE=full`).
- **`reset()` also empties `cost_log`**, so `/stats` app cost only covers the time since the last reset.
- `pnpm search` is shadowed by pnpm's built-in; use `pnpm run search`.
- Contract gaps: no `report` DocType (307 Commission reports skipped in full mode); no `stat_accuracy` / `expected_count` in EvalRun / EvalItem.
- S4's terminal is retained by Orca (`user_takeover`), not released.

- Dan's shell exports `ANTHROPIC_BASE_URL` (a work proxy) and `ANTHROPIC_AUTH_TOKEN`. The app now ignores them (`rag.config.anthropic_base_url()`). The first test sent the new key to that proxy, which rejected it.
- Port 3000 is in use by another local dev server (another app). The demo URL needs it free, or use `WEB_PORT=3100 pnpm dev`.
