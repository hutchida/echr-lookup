# Hosting options for the API + MCP server (M3 spike)

Status: research and a **local** build only (phase 1 and the MCP check after M1). Nothing here was deployed; no account, cloud resource or public URL was created. Prices and limits come from public pages fetched on **2026-11-04** (linked inline). Measurements are from `infra/deploy/` on Dan's Mac (Docker Desktop VM: 14 vCPU, 15.6 GiB, linux/arm64).

## 1. Answer in four lines

1. **Yes, one image runs the FastAPI app and the MCP server (verified after M1 merged) next to ParadeDB with pgvector + BM25.** Image: 2.8 GB on disk with both models baked in (1.5 GB compressed), 1.6 GB without them. One idle process uses ~0.8 GiB RAM; a search peaks near 1.1 GiB.
2. **The limiting resource is CPU, not RAM or disk.** The cross-encoder reranker scores 30 chunks per search: **15.2 s on 1 vCPU, 8.0 s on 2, 4.5 s on 4, 2.9 s on 14** (median, warm). Without the reranker a search takes 0.01–0.08 s.
3. **Netlify cannot host this part.** Functions are zip bundles with 1–4 GB memory and 60 s limits and the docs do not list pgvector or a BM25 extension for Netlify Database. Netlify is a good home for the **web app**; the API + MCP container + Postgres need a host that runs containers.
4. **Recommendation: web app on Netlify, API + MCP + ParadeDB as one `docker compose` on a Hetzner Cloud CPX32 (4 vCPU, 8 GB, EU), about €36/month**, with Caddy for TLS. See §7.

## 2. What was built (`infra/deploy/`)

| File | What it is |
|---|---|
| `Dockerfile` (+ `Dockerfile.dockerignore`) | Multi-stage: `deps` (uv, `--no-dev --group ml`, CPU-only torch from the lockfile) → `models` (downloads only the needed files of `BAAI/bge-small-en-v1.5` and `BAAI/bge-reranker-base`) → `runtime-slim` (no models) → `runtime-baked` (default, models in `/models`, `HF_HUB_OFFLINE=1`). Runs as a non-root user. |
| `compose.yml` | Project `echr-deploy`: `db` (same ParadeDB image as `infra/docker-compose.yml`) on host **5434**, `api` on **8003**, `mcp` on **8103** (`MCP_HOST=0.0.0.0` inside the container; see §9). |
| `compose.slim.yml` | Override for the "models in a volume" variant (`IMAGE_TARGET=runtime-slim`). |
| `load-snapshot.sh` | `ingest` (default: `rag.ingest --source snapshot --reset` inside the image) or `dump` (`pg_dump` of a dev DB piped into the compose DB). |
| `measure.py` | Restarts the `api` container and prints cold start, idle/peak RAM and warm latency. |

Things the image needed that are easy to miss: `rag.config.REPO_ROOT` is derived from the file's own path, so the image keeps the repo layout under `/app` (`py/`, `infra/migrations/`, `config/`, `data/snapshot/`, `packages/contract/{schema,fixtures}/`); the API imports contract fixtures at start-up for its OpenAPI examples and crashes without them; the MCP server will need the contract schemas.

## 3. Measurements

All numbers from this machine; "baked" = default image.

| Measurement | Result |
|---|---|
| Image size, arm64, baked (sum of layers on disk, `du -sx /`) | **2,776 MB** (compressed: 1.52 GB) |
| Image size, arm64, slim (no models) | **1,566 MB** (compressed: 0.43 GB) |
| Image size, amd64, slim (built with `--platform linux/amd64`) | 1,683 MB (compressed: 0.47 GB); torch alone is 809 MB there vs 688 MB on arm64. A baked amd64 image is therefore about 1,683 + 1,200 (models, measured) ≈ 2.9 GB. |
| What is big | torch 688 MB, transformers 120 MB, scipy 118 MB, sympy 74 MB, sklearn 57 MB, models 1.2 GB (reranker 1.1 GB fp32 safetensors) |
| `docker images` shows 4.44 GB for the same image | Docker Desktop's containerd store double counts; ignore it |
| RAM, API container, idle (5 s after `/health`) | **768 MiB** |
| RAM, API container, after 20 reranked searches | 880 MiB; **peak sampled during searches 1,090 MiB** |
| RAM, ParadeDB container (98 docs, 107 MB database) | 142 MiB |
| Memory cap test (`--memory 1g`, `1536m`, 4 vCPU) | No OOM kill, searches OK; RSS fits in 1 GiB for one process but with no headroom |
| Cold start, baked: `compose up` returns | 1.5 s |
| Cold start, baked: first `/health` 200 | **8.1 s** after `up` (almost all model loading) |
| Cold start, baked: first `/search` (hybrid_rerank, k=30) | 3.2 s (warm median 2.9 s: the first search is not a cold start) |
| Cold start, slim image, **empty** model volume (downloads 1.2 GB from Hugging Face) | `/health` after **79.8 s** |
| Cold start, slim image, warm model volume | `/health` after 7.0 s |
| Warm `/search` `hybrid_rerank`, k=30, 14 vCPU (n=20) | median **2.90 s**, min 2.57, p90 3.36, max 3.51 |
| Warm `/search` by mode, 14 vCPU (median of 12) | bm25 0.01 s · vector 0.07 s · hybrid 0.08 s · hybrid_rerank k=12 2.82 s · k=30 2.94 s |
| Warm `/search` hybrid_rerank k=30 with the container limited to N CPUs (`--cpus N`, `OMP_NUM_THREADS=N`, median of 8) | **1 vCPU 15.2 s** · **2 vCPU 8.0 s** · **4 vCPU 4.5 s** (RAM ≈ 0.9 GiB in all three) |
| Snapshot load, `ingest` mode (embeds 16,154 chunks in the container) | **531 s** (embed 524 s). Result: 98 documents, 9,430 paragraphs, 16,154 chunks |
| Snapshot load, `dump` mode (`pg_dump` of `echr_m3` → compose DB, indexes rebuilt) | **2 s** (3.6 s wall) with identical counts; `chunks_bm25_idx` (pg_search) and the HNSW index are present |
| MCP container (M1's `python -m echr_mcp --transport http`): first `initialize` OK after `up` | **5.7 s** |
| MCP: `tools/list` (six tools) | 0.00 s (after initialize) |
| MCP: first `search_case_law` (8 hits) | **2.8 s** (warm median 2.6 s, min 2.3, p90 3.3, max 3.8; n=20, 14 vCPU) |
| MCP RAM idle / peak during searches | **791 MiB / 1,129 MiB** (one process; running API and MCP together is ~2× this plus the DB) |

Reading the table:

- The reranker always scores the top 30 fused chunks, whatever `k` is (k=12 and k=30 cost the same). Its cost is almost linear in CPU time: ~15 CPU-seconds per search.
- `docs/eval-results.md` shows the reranker does not improve MRR on this eval set (hybrid 0.22 vs hybrid_rerank 0.18; recall@10 within noise), and `docs/interfaces-mcp.md` asks `search_case_law` for hybrid + rerank with a warm budget under 3 s. On a 4 vCPU host that budget is missed by 1.5 s. This is a product decision for the orchestrator (not a hosting one): either buy ≥ 8 vCPU, or accept ~4.5 s, or change rerank depth later.
- Two Python processes (API and MCP) each load both models, so RAM is roughly **2 × 0.9 GiB + ParadeDB**. The MCP server does not call the API, so a deployment that only serves MCP can skip the `api` container.

## 4. Requirements derived from the measurements

| Need | Value | Why |
|---|---|---|
| RAM | **≥ 2 GiB for one Python process + DB; 4 GiB for API + MCP + DB; 8 GiB for headroom and the full corpus** | 0.9–1.1 GiB per process (models are ~1.2 GB on disk, loaded once); DB 0.15 GiB for 98 docs |
| CPU | **4 vCPU for ~4.5 s searches; 8+ vCPU to stay near the 3 s budget; 1–2 vCPU only if the reranker is dropped** | rerank is CPU-bound (§3) |
| Disk | image 2.8 GB + DB. Snapshot DB is 107 MB. The full corpus is 3,527 loaded documents (`docs/orchestration/status-build1.md`) against 98 here: scaling the snapshot's 1.1 MB per document gives roughly 4 GB of tables and indexes. This is arithmetic, not a measurement; measure `echr_full`'s size before buying a disk | |
| Always-on vs scale-to-zero | Scale-to-zero works for the *tool* (start 8 s with baked models, then search 3 s) but a claude.ai connector call allows 240 s ([Claude docs](https://claude.com/docs/connectors/building), fetched 2026-11-04), so a cold start is tolerable; the **Postgres cannot scale to zero cheaply** (data on disk, index builds) and must stay up | |
| Postgres | ParadeDB 0.26.4 on Postgres 17 (`pg_search` + `pgvector`); the app's `/health` requires both extensions, and `rag.search` uses BM25 syntax from `pg_search` | |
| Network | Public HTTPS URL for the MCP endpoint (both vendors, §6), streamable HTTP at `/mcp`; outbound to Hugging Face only for the slim variant | |

**Models baked vs volume (recommendation: baked).** Baked costs 1.2 GB more image (pull 1.5 GB instead of 0.43 GB) but starts in 8 s with no internet access and no first-start download; the slim image needed 80 s on first start and a volume to survive redeploys. Baked also makes a deploy reproducible (no dependency on Hugging Face being up). Use the slim variant only where image pulls are metered and a persistent volume is free.

## 5. Netlify first

Sources: [Functions configuration](https://docs.netlify.com/build/functions/configuration.md), [Functions API](https://docs.netlify.com/build/functions/api.md), [Edge Functions limits](https://docs.netlify.com/build/edge-functions/limits.md), [Netlify Database](https://docs.netlify.com/build/data-and-storage/netlify-database/index.md) and its [billing and limits](https://docs.netlify.com/build/data-and-storage/netlify-database/billing-and-usage.md), [Pricing](https://www.netlify.com/pricing/); all fetched 2026-11-04.

| Question | What the docs say | Verdict for us |
|---|---|---|
| Can it run a container? | Netlify Functions are source files bundled and run in an "ephemeral runtime environment"; the documentation index lists Functions, Edge Functions, Async Workloads, Blobs and Database, with **no container hosting** | **No.** Our image cannot be deployed as is |
| Memory | Functions default 1,024 MB; Credit-based Pro/Enterprise can raise it to 4,096 MB (`vcpu` 0.5–2.0). Edge Functions: 512 MB for the whole set of deployed edge functions | One loaded process needs ~0.9–1.1 GiB (RSS) before the OS and DB driver. 1 GB is too small; 4 GB fits only on the Pro plan |
| CPU | max 2.0 vCPU per function | From §3: ~8 s per reranked search at 2 vCPU. Edge Functions: **50 ms CPU per request** |
| Timeouts | Synchronous 60 s, scheduled 30 s, background 15 min; buffered payload 6 MB; streamed response 20 MB with a 60 s execution limit | A tool call fits in 60 s, but a **long-lived streamable-HTTP/SSE session does not**: every stream dies at 60 s. Stateless MCP over single request/response could work in principle |
| Cold start | Every cold function must load torch and 1.2 GB of models (8 s measured here) on each new instance, and instances are ephemeral | Poor |
| Bundle size | The pages I read give no bundle limit. torch alone is 688–809 MB installed and the models are 1.2 GB; any zip-style limit (AWS Lambda's 250 MB unzipped is the usual one) is far exceeded | **No** (limit not documented in the pages I read; treat as unconfirmed but irrelevant at this size) |
| Netlify Database | "Fully managed Postgres built into the platform", on Credit-based plans only, with branches per deploy preview. Free: 1 compute unit max, 48 compute units per billing period, sleeps after 5 min idle; Personal: up to 4 units, sleep 5 min; Pro: up to 16 units, can stay always-on | **Extensions are not documented** in the Database pages I fetched, so pgvector is unconfirmed and a BM25 extension (`pg_search`) is not mentioned anywhere. Treat both as unavailable until Netlify says otherwise |
| Netlify costs | Free $0 (300 credits), Personal $9/month (1,000 credits), Pro $20/month (3,000 credits). Compute 10 credits per GB-hour ($0.07), bandwidth 20 credits per GB, web requests 2 credits per 10k | The web app fits easily on Free/Personal |

**Realistic hybrid:** Netlify hosts `apps/web` (Next.js). The API + MCP container and ParadeDB run elsewhere. Netlify can also own the DNS zone, so `mcp.<domain>` and `api.<domain>` point at the other host. Two follow-ups for the orchestrator, both outside this task's files: `py/api/main.py` hard-codes `CORS_ORIGINS` to localhost (a deployed web app needs a configurable origin), and the web app reads `API_URL`.

## 6. Auth for remote MCP (current vendor docs, fetched 2026-11-04)

| | claude.ai (custom connectors) | ChatGPT (plugins / custom MCP server) |
|---|---|---|
| Docs | [Get started with custom connectors](https://support.claude.com/en/articles/11175166-get-started-with-custom-connectors-using-remote-mcp) · [Building connectors](https://claude.com/docs/connectors/building) · [Add an unlisted connector](https://claude.com/docs/connectors/custom/add-unlisted) · [Anthropic IP addresses](https://platform.claude.com/docs/en/api/ip-addresses) | [Connect and test your plugin](https://developers.openai.com/plugins/deploy/connect-chatgpt.md) · [Build an MCP server](https://developers.openai.com/plugins/build/mcp-server.md) · [Authentication](https://developers.openai.com/plugins/build/auth.md) · [IP ranges](https://developers.openai.com/api/docs/guides/ip-addresses.md) |
| Transport | **Streamable HTTP** (recommended); legacy HTTP+SSE still supported but being deprecated; a URL ending `/sse` selects SSE | **Streamable HTTP**, typically at `/mcp` |
| URL | Public **HTTPS** URL, e.g. `https://mcp.example.com/mcp`. Anthropic's cloud connects (not your device), so a server on a private network/VPN won't work unless Anthropic's IPs are allowed | Public **HTTPS** endpoint (or an OpenAI "Secure MCP Tunnel" for private servers; a tunnel does not satisfy public submission) |
| Auth options | OAuth 2.0 (specs 2025-03-26, 2025-06-18 and 2025-11-25), **dynamic client registration (DCR)** or Anthropic's published client identity (Client ID Metadata Document) or your own OAuth client, **static request headers** (beta, limited organizations), or **no authentication** ("No sign-in" in the add dialog). Redirect URI `https://claude.ai/api/mcp/auth_callback` | **Anonymous (`noauth`) is allowed**: "many plugin MCP servers can operate in a read-only, anonymous mode"; tools declare `noauth`/`oauth2` per tool. For OAuth 2.1: protected-resource metadata + authorization-server metadata, PKCE, resource parameter, and CIMD, DCR or predefined clients. mTLS available |
| Allow-listing | Inbound to your server comes from Anthropic's published outbound range `160.79.104.0/21` and `153.61.208.0/20` (IPv4) | OpenAI publishes egress ranges in the IP-ranges page; "an IP allowlist does not replace authentication" |
| Limits | Tool result ~150,000 chars on claude.ai/Desktop; tool call timeout 240 s | Not stated in the pages read |
| Plans | Custom connectors on **Free (one connector), Pro, Max, Ultra, Team, Enterprise**. On Team/Enterprise only Owners (or custom roles) add them | **Not stated in the OpenAI developer docs**: "Account and workspace policies apply"; the OpenAI Help Center article on developer mode returned HTTP 403 to my fetch. Check which ChatGPT plan shows "Add custom MCP server" at https://chatgpt.com/plugins before promising anything |
| Submission | Optional directory listing; not needed for a personal custom connector | Optional public review; not needed for personal use |

What this means for us: the server is read-only public data, so **authless is acceptable to both vendors**, which avoids running an OAuth authorization server. The cost is that anyone who finds the URL can burn ~15 CPU-seconds per search. Mitigations that need no vendor support: a long unguessable path secret enforced by the reverse proxy (`/mcp/<random>`, entered once in the connector URL), per-IP rate limiting in Caddy, and logs (`tool_log` from M1). Claude's request-header (bearer) option is beta and limited to some organizations, so do not depend on it.

## 7. Comparison of three hosts (all with the web app on Netlify)

Workload: 4 vCPU / 8 GB class, always on, API + MCP + ParadeDB, ~10 GB disk, light traffic (bandwidth costs ~ $0). Prices excl. VAT as shown on 2026-11-04.

| | **A. Hetzner Cloud VPS** (recommended) | **B. Fly.io Machines** | **C. Render** |
|---|---|---|---|
| Source | [hetzner.com/cloud/regular-performance](https://www.hetzner.com/cloud/regular-performance/) | [fly.io/docs/about/pricing](https://fly.io/docs/about/pricing/) | [render.com/pricing](https://render.com/pricing) |
| Shape | One CPX32: 4 AMD vCPU, 8 GB RAM, 160 GB NVMe. One `docker compose` (API, MCP, ParadeDB) | App Machine `shared-cpu-4x` 4 GB + DB Machine `shared-cpu-1x` 1 GB + 10 GB volume | Web service 4 CPU / 8 GB + ParadeDB as a private service 1 CPU / 2 GB with a 10 GB disk |
| Monthly cost | **€35.99** (CPX32). Included traffic 20 TB in EU. (CX33 4 vCPU/8 GB at €8.99 was shown as *currently unavailable* on 2026-11-04; check again, it would cut the bill by 75%.) | App 4 × 8.465e-7 $/s × 2,592,000 s = $8.78 + extra RAM (4 GB − 4 × 0.25 GB) × $6.00 = $18.01 → **$26.79**; DB $6.70 (1 GB preset price); volume 10 × $0.15 = $1.50; dedicated IPv4 $2.00 → **$37.0** | $175 (4c-8g) + $25 (1c-2g) + 10 × $0.25 = $2.50 → **$202.5**; the 2 CPU / 4 GB web service is $85 (→ ~$112 total, 8 s searches) |
| Netlify web | $0 (Free) or $9 (Personal) | same | same |
| Scale to zero | No (always on, hourly billing, can be stopped and deleted) | Yes: stopped Machines cost only rootfs ($0.15/GB-month); auto-stop saves the compute while idle. The DB machine should stay up | No (free plan spins down but cannot hold this memory); services stay up |
| RAM / CPU | 8 GB / 4 AMD vCPU ("Regular Performance" line; whether the vCPUs are shared or dedicated is not stated on the page I read, and I did not benchmark it) | 4 GB / 4 *shared* vCPU; shared presets are burstable: not measured here; `performance-2x` 4 GB is $66.00 | 8 GB / 4 CPU |
| **ParadeDB (`pg_search`)** | **Yes**: we run the same container | **Yes** as a self-run container on a volume. Fly's *Managed Postgres* lists pgvector and PostGIS only | **Self-run only**: Render Postgres lists pgvector but no `pg_search` ([extensions](https://render.com/docs/postgresql-extensions)), so managed Postgres means the BM25 fallback below |
| Cold start | n/a (always on); a reboot is ~8 s app start | Machine start + our 8 s model load; image pull time not measured | n/a |
| TLS / domain | None built in: run Caddy (automatic Let's Encrypt) with a DNS record from Netlify DNS or any registrar | Built in (free `*.fly.dev`; own domain with the first 10 certificates free) | Built in |
| Data residency | Choose Falkenstein/Nuremberg (DE) or Helsinki (FI): EU | Choose region (e.g. `lhr`, `ams`, `fra`) | Region choice (Frankfurt, Oregon, …) |
| Ops burden | Highest: OS patches, firewall, backups, restarts | Medium: `fly.toml`, volumes, Machine sizing | Lowest |

The arithmetic for Fly uses the page's own constants (shared CPU $8.465e-7 per vCPU-second, RAM $2.316e-9 per GB-second, 0.25 GB RAM included per shared vCPU, 2,592,000 s per 30-day month). It reproduces the page's published `shared-cpu-1x` 1 GB = $6.70. Render's compute and the Hobby workspace ($0 + compute; Pro workspace is $25/month) are as printed on the pricing page; no workspace fee is included above.

### BM25 fallback (if `pg_search` is not available: Netlify Database, Render Postgres, Fly Managed Postgres, Neon)

Neon documents pgvector but lists `pg_search` as unavailable and deprecated ([Neon extensions](https://neon.com/docs/extensions/pg-extensions), 2026-11-04). Options when no BM25 extension exists:

1. **Postgres full-text search** (`tsvector` + `ts_rank_cd`, GIN index). Needs a migration (`infra/migrations/` is read-only for this task) and a second code path in `py/rag/search` (also read-only). It is ranking by term frequency/proximity, not BM25 (no IDF and no length normalisation), so rare legal terms (`Chahal`, `Article 5(4)`) are weighted less sharply.
2. **In-process BM25 index** (e.g. the `rank_bm25` library built at start-up from `chunks.text`): real BM25, but a new dependency and 16,154 chunks (19 MB of text in the snapshot; roughly 36× that for the full corpus by document count) held in each process's RAM.
3. **Vector-only plus rerank** (drop BM25).

Cost in retrieval quality, from `docs/eval-results.md` (71 explain/neutrality questions, snapshot): across chunking strategies, bm25 averages MRR 0.19 against vector 0.22 and hybrid 0.22, and recall@10 is within a few points. So losing BM25 would cost a few hundredths of MRR, i.e. small on this snapshot eval, but I did not measure `ts_rank` or any fallback, and the full corpus (3,527 documents) is a different test. Treat "no BM25 extension" as a retrieval-quality risk to measure before choosing, not as a free swap.

## 8. Recommendation

**Web app on Netlify (Free or Personal, $0–9/month) + the API/MCP/ParadeDB compose on a Hetzner Cloud CPX32 in Falkenstein or Helsinki (€35.99/month excl. VAT). Total about €36–45 per month.**

Why: it is the only option where ParadeDB (real BM25) runs unchanged, it is the cheapest of the three that meets 4 vCPU / 8 GB, it keeps Dan's Netlify workflow for the web app and DNS, and the same compose file I tested is the deployment. If Hetzner CX33 (€8.99) is available when you buy, use it and re-measure search latency first (the cost-optimized line is a different, cheaper CPU class; I did not benchmark either).

Steps (not executed):
1. Buy a domain or use one Dan owns; in Netlify DNS add `A mcp.<domain> → <server IP>` after step 3.
2. Create a Hetzner Cloud project and a CPX32 (Ubuntu LTS, SSH key only, EU location). Firewall: allow 22 (your IP) , 80, 443 only.
3. Install Docker, clone the repo (or `docker save`/`load` a built image: `docker buildx build --platform linux/amd64 -f infra/deploy/Dockerfile --target runtime-baked`; the image must be amd64, mine were arm64).
4. Copy `infra/deploy/compose.yml`, remove the host `ports` for `db`, `api`, `mcp` (bind to the Docker network), and set `MCP_ALLOWED_HOSTS=mcp.<domain>` on the `mcp` service (§9), and add a `caddy` service proxying `https://mcp.<domain>/mcp/<secret>` → `mcp:8100/mcp`, with per-IP rate limiting. Set strong DB credentials via an env file (the compose file's `echr`/`echr` is for local use only).
5. `docker compose up -d --build`, then load data with the **dump** path (`load-snapshot.sh dump`; 2 s instead of 531 s), or `pg_dump` of the final full DB.
6. In claude.ai: Customize → Connectors → Add custom connector → URL, **No sign-in**. In ChatGPT: https://chatgpt.com/plugins → Add custom MCP server (if your plan offers it), authentication none. Run the six-tool check with MCP Inspector first.
7. Nightly `pg_dump` to a Hetzner Storage Box or object storage, plus Hetzner server backups (+20%, price not fetched).

Risks:
- **Latency**: 4 vCPU gives ~4.5 s per reranked search (measured on a laptop with the container capped to 4 CPUs; a real CPX32 was not measured). The 3 s budget in `docs/interfaces-mcp.md` is missed unless the reranker depth changes or you pay for 8+ vCPU (CPX42: 8 vCPU / 16 GB at €69.99).
- **Abuse of an authless endpoint** burns CPU. Path secret + rate limit reduce it; real OAuth is the proper fix and is a larger job.
- **Single box, self-managed**: patching, backups and restarts are yours. No HA.
- The image I measured is arm64; **amd64 is untested at run time** (only built to measure size).
- Unverified: ChatGPT plan eligibility (§6); Hetzner CPX CPU performance; Fly shared-CPU throttling; Netlify Database extensions.
- `py/api/main.py` CORS list and the web app's `API_URL` need changing before the Netlify web app can call the API (not in this task's ownership).

**If Dan wants scale-to-zero or less ops, choose Fly.io (§7 column B, ~$37/month always on, less when the app machine auto-stops).** Fly is the runner-up.

## 9. MCP in the container

Verified after M1 merged (`8898617`), on the same image (`runtime-baked`) and compose DB loaded with `load-snapshot.sh dump`:

- `python -m echr_mcp --transport http --port 8100` runs in the container and is reachable at `http://localhost:8103/mcp`. The official `mcp` client lists the six tools (`search_case_law`, `get_paragraphs`, `get_case`, `count_cases`, `corpus_info`, `check_quote`) and `search_case_law` for "Are prisoners entitled to vote?" returns `Hirst v. the United Kingdom (No. 2)` paragraphs with `cite` strings and `corpus` = 98 snapshot documents.
- Timings are in the §3 table. The MCP process is no heavier than the API (791 MiB idle, 1,129 MiB peak).
- **Bind address and host-header protection.** M1's server listened on `127.0.0.1` only, which Docker's port mapping cannot reach. The orchestrator granted one narrow edit to `py/echr_mcp/__main__.py`: `--host` / `MCP_HOST` (default unchanged) and `MCP_ALLOWED_HOSTS` (comma list). The SDK (`mcp` 2.3) switches DNS-rebinding protection on by itself **only for a localhost bind**; with `0.0.0.0` and no settings it would run with no Host/Origin check at all. So any non-local bind now passes explicit `TransportSecuritySettings` (protection on; `localhost`/`127.0.0.1`/`[::1]` on any port plus the names in `MCP_ALLOWED_HOSTS`). Checked against the running container: `Host: localhost:8103` → 200, `Host: evil.example.com` → 421.
- For a public deployment set `MCP_ALLOWED_HOSTS=mcp.<your-domain>` (the name the vendor connects to); otherwise the proxy's Host header is rejected with 421.
