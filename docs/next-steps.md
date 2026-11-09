# Lessons learned and things to try next

For when you come back to the project. Plain English, one section per item. Each has what we found, why it matters, and the concrete next step. Numbers come from [`eval-judging.md`](eval-judging.md), [`hosting-options.md`](hosting-options.md), [`orchestration/retrospective.md`](orchestration/retrospective.md) and [`decisions.md`](decisions.md). Nothing here has been done yet.

State when this was written (2026-11-06): everything is merged on `main`, nothing is deployed, the Anthropic key is at its usage limit until 2026-12-01 (so no paid app or eval runs until then).

## 1. The reranker did not earn its keep

**What we found.** Under the wider answer key (qrels v2, see [`eval-judging.md`](eval-judging.md)), plain hybrid search beats hybrid plus reranking on ordering, for all three chunking strategies:

| Chunking | MRR hybrid → rerank | nDCG@10 hybrid → rerank | Recall@10 hybrid / rerank |
|---|---|---|---|
| fixed | 0.66 → 0.49 (−0.17) | 0.41 → 0.33 (−0.08) | 0.40 / 0.40 |
| recursive | 0.63 → 0.54 (−0.09) | 0.46 → 0.41 (−0.05) | 0.31 / 0.32 |
| by_section | 0.69 → 0.55 (−0.14) | 0.44 → 0.34 (−0.10) | 0.41 / 0.40 |

Recall@10 is a tie. The reranker (`BAAI/bge-reranker-base`, a general-purpose model) tends to lift statute text, such as section 3(5)(a) of the Immigration Act 1971 quoted inside a judgment, above the Court's own reasoning. It also costs about 4.5 s per search on 4 vCPU (15.2 s on 1 vCPU, 2.9 s on 14).

`by_section` + `hybrid` is the best config on both keys for recall@5 and recall@10 (recall@10 is tied on the original key). It is tied-best on v2 MRR (0.69). `recursive` + `hybrid` is slightly ahead on v2 nDCG@10 (0.46 against 0.44). So "best" is true for finding the right paragraphs, not for every metric.

**Why it matters.** The default setup (`/ask` and the MCP `search_case_law` tool) pays the reranker's time and CPU cost and gets worse ordering for it. It also forces a bigger host (see item 5). The earlier "reranker lowers MRR" conclusion came from the narrow key; the wider key says the same thing more strongly.

**Next step.**
- (a) Record **D-005** in [`decisions.md`](decisions.md): reranking becomes a config flag that defaults to off, and the default config becomes `by_section` + `hybrid`, in `/ask` and in the MCP `search_case_law` tool. Today `RERANK_ENABLED` already exists in `py/rag/config.py` (default `1`), and `/ask` hard-codes `recursive` + `hybrid_rerank` in `py/rag/answer/context.py`. Switching `/ask` changes what the answer step sees (its statute demotion was tuned with the reranker), so it needs a judged answer eval before and after. That is paid and has to wait for the key limit to reset.
- (b) As a learning experiment, swap in a stronger general reranker (Cohere, Voyage) and a legal-specific one, and rescore against both keys with the existing `python -m rag.eval.judging rescore`. I have not checked which legal-specific rerankers exist or what they cost, so look that up first. **Paid models need your approval before any call.**
- Caveat for (b): the v2 key only grades paragraphs that were in the J1 pool (top-10 hits of the 12 configs plus the original gold). A new reranker will surface paragraphs nobody graded, and those count as 0. That under-credits new methods. Either grade the new paragraphs (small paid judge run) or say clearly that the comparison is pool-limited.

## 2. Decide the output style before you build

**What we found.** `/ask` was built to be *checkable*, not *readable*: short answer, then claim-by-claim evidence, each with a citation chip and a verifier badge. That is what the brief asked for in effect (every claim cited, every citation checked). It works as designed. But on the owner-review questions, Claude using the MCP tools gave 21.7 claims per answer against `/ask`'s 4.6, and 65% of the tool answer's claims had no citation, so neither extreme is what you actually want to read.

**Why it matters.** The brief never said whether the output should be an academic, evidence-heavy record or a readable answer. Two builds (A1 and the A–G refactor) went on fixing the shape after every gate had passed.

**Next step.**
- Keep `/ask` as it is. Its verifier and strict citations are valuable and are the project's best feature.
- Every future brief states up front which one it wants: **evidence-heavy** (claim by claim, verified) or **readable answer**.
- Your usefulness standard for the MCP route: a readable answer, roughly right, with citations **per paragraph rather than per sentence**, which confirm the overall picture when you check them. Today's MCP instructions (`py/echr_mcp/server.py`, F1) ask for a copied cite at the end of every factual sentence, which is the opposite. Change the instructions to match your standard, then check the 10 owner-review questions by hand against it.

## 3. Grill before briefing

**What we found.** The stats bugs (stats accuracy 6/12 before S4-fix) and the stat-003 dispute (expected 5, system says 4) were **glossary problems**, found late. Examples of terms that decide a count:
- *deportation* (in this project: raises Article 3, 8 or 5(1)(f) **and** at least two paragraphs mention deport/expel/extradit/removal; gives 27);
- *declared inadmissible* (the whole application; excludes `partly_inadmissible`);
- *found a violation* (includes `mixed`);
- *Grand Chamber* (HUDOC's chamber field).

**Why it matters.** The eval set was written in parallel with the answer code, so the definitions were implicit. Fixing them later cost an S4-fix round and a disputed expected count.

**Next step.** Before the next project brief, run Matt Pocock's `grill-with-docs` skill (grilling plus domain modelling). It asks one question at a time, branch by branch, and writes a `GLOSSARY.md` and numbered ADRs in `docs/adr/`. I have not checked its current install command, so look at his skills repo first. Use it to pin down the counted terms and the **answer shape** (item 2) *before* writing the eval set. Existing decisions (D-001 to D-004) can stay in [`decisions.md`](decisions.md) or move to `docs/adr/` later; pick one place.

## 4. Leaner orchestration

**What we found.** In Build 1 the three Opus orchestrators cost $60.17, which is **60% of the $100.03 build spend** (the retrospective's final figure). In the MCP slice the Opus orchestrator was 56% ($15.51 of $27.62 agent spend). In the follow-up slice a Sonnet orchestrator ran at about 15% (total slice $6.67). That last one is a small slice, so it is a hint, not proof. Long Opus contexts re-read every turn, and waits longer than the roughly 5-minute prompt-cache life re-wrote the whole context.

**Why it matters.** Workers were cheap ($0.2 to $5 each). Coordination was the expensive part.

**Next step.** Next time:
- **Opus** for the plan, the contract and the briefs only.
- A **fresh Sonnet orchestrator per gate**.
- Continuity lives in a short status file and a handoff doc written at each gate, not in a long-lived context.
- Workers report a brief summary and a PR link.
- No waits longer than about 5 minutes.
- The orchestrator never writes feature code (the A–G refactor done inside the orchestrator is what the retrospective flags).

## 5. Hosting (undecided; this is a portfolio demo)

**What we found.** The front end can live on Netlify or Vercel. Neither can run the backend: it needs a long-running Python process with models loaded, plus ParadeDB with `pg_search` for BM25. The M3 spike confirmed this for Netlify; **Vercel was not researched there**, so check it before relying on it. CPU, not RAM, is the limit, and almost all of the CPU cost is the reranker (about 15 CPU-seconds per search). Without it a search takes 0.01 to 0.08 s. One process needs about 1 GiB of RAM, and API + MCP + database about 4 GiB. The baked image is 2.8 GB, and about 1.1 GB of that is the reranker model.

**Why it matters.** If item 1 goes ahead (reranker off), the host can be small and cheap. The €36/month Hetzner CPX32 recommended in [`hosting-options.md`](hosting-options.md) was sized for the reranker.

**Next step.** Pick one after item 1, in this order of effort:
- **A cheap VPS** (Hetzner or DigitalOcean). Re-check prices first: Hetzner has raised prices in 2026, and the cheap CX33 (€8.99) was shown as unavailable on 2026-11-04. Same `docker compose` as `infra/deploy/`, Caddy for TLS.
- **An AWS or Google Cloud VM** if the CV value matters. Set a **billing alert on day one**.
- **Free self-hosting at home**, exposed through Tailscale Funnel or a Cloudflare Tunnel. Claude's connectors call from Anthropic's cloud, so the URL must be public HTTPS; a private tailnet will not work.

Whichever you choose:
- Do not expose `/ask` publicly as it is. It has no auth or rate limit and spends your Anthropic key. The MCP server makes no model calls, so it is the safer thing to put online, still behind a path secret and rate limiting.
- Load the committed 98-document snapshot only. `data/full/` must stay private (HUDOC terms, see item 6).
- `py/api/main.py` hard-codes CORS to localhost, and the web app reads `API_URL`; both need to be configurable.
- The amd64 image has been built but never run.

## 6. Make the repo fit to be public

**What we found.** A review of the repo and its full git history before a public release: no secrets in history (a gitleaks scan of every commit on every ref found nothing), `data/full/` and `.env` were never committed, and the README lacked the data attribution and a human-readable story. Some docs named a work proxy and an internal tool; those were reworded, and some old numbers were stale.

**Why it matters.** The repo is a portfolio piece. The first screen is the README.

**Next step (done).** README rewritten, © ECHR-CEDH and Open Government Licence notes added, stale numbers fixed, work-specific names removed. The public repo was published as a fresh, single-commit history, so the old commit messages and PR text did not carry over.

## Where things stand at a glance

| Item | Needs | Blocked by |
|---|---|---|
| 1 Reranker | D-005, then a judged answer eval; optional paid reranker experiment | Anthropic key limit until 2026-12-01; your approval for paid models |
| 2 Output style | Change MCP instructions; state style in the next brief | — |
| 3 Grill | Install `grill-with-docs`, run it before the next brief | — |
| 4 Orchestration | Apply to the next build | — |
| 5 Hosting | Choose a host after item 1 | Decision |
| 6 Public repo | Done | — |
