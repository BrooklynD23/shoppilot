# 07 — Hosting, deploy, ops and whole-product cost

Planner P7, written 2026-10-30. Contract: `00-shared-brief.md`. Plan: `../plans/07-deploy-plan.md`.

**Verdict:** Render web service from the repo's Dockerfile, defined in `render.yaml`. Use the **Free** plan for W0–W3 with a 5-minute UptimeRobot ping. Switch to **Starter ($7/mo, 0.5 CPU, 512 MB, always on)** 3 days before the live demo and keep it until grading closes. Runner-up: **Railway Hobby** (about $5–7/mo, no sleep). Expected 2-month cash: **about $47** (Render $7 + Anthropic about $40). Hard ceiling: **$94**, enforced by spend limits.

Research note: the Agent tool hit the 20-subagent concurrency limit, so P7 did all web research itself with WebSearch/WebFetch on 2026-10-30. "UNVERIFIED" means from memory or third-party only.

## 1. Host comparison

Need: 1 Docker container, 512 MB–1 GB RAM, HTTPS URL, deploy from GitHub, env secrets, no sleep during the demo, local SQLite OK (stores are seeded and resettable, so ephemeral disk is fine; see §6).

| Host | Free tier (RAM / CPU) | Sleep / cold start | Disk | Card for free? | Cheapest always-on that fits | Verdict |
|---|---|---|---|---|---|---|
| **Render** | 512 MB / 0.1 CPU, 750 instance-h/mo per workspace | Spins down after 15 min idle; about 1 min to wake | Ephemeral. Persistent disk on paid only, $0.25/GB-mo | No (without a card, free services suspend when the bandwidth quota runs out) | Starter 512 MB / 0.5 CPU, **$7/mo** | **Pick.** Dockerfile + `render.yaml`, deploy hook with `?ref=<sha>`, Rollback button, `RENDER_GIT_COMMIT` env, WebSockets |
| **Railway** | Trial: $5 one-time, 30 days, 1 GB, no card. Then Free: $1/mo credit, 0.5 GB | Not mentioned (billed per second) | Volumes $0.15/GB-mo (Free 500 MB, Hobby 5 GB) | Trial: no | Hobby $5/mo incl. $5 usage. RAM ≈ $10/GB-mo, vCPU ≈ $20/mo → 512 MB ≈ **$6–7/mo** (P7 estimate) | **Runner-up** |
| Fly.io | None. Trial 2 machine-hours or 7 days | Optional auto-stop | Volumes $0.15/GB-mo | Yes, after trial | shared-cpu-1x 512 MB **$3.69**, 1 GB $6.70 (iad) | Cheapest paid; card + `flyctl` needed |
| Koyeb | 1 instance, 512 MB / 0.1 vCPU / 2 GB SSD | Free tier scales to zero after 1 h idle, can't be changed | Volumes (price not found) | Yes ($29 pre-auth hold) | eco-micro 512 MB **$2.68**, eco-small 1 GB $5.36 | Cheap; card hold |
| Northflank | Sandbox: 2 services, "always on, no sleeping" | None | Volumes $0.117/GiB-mo | Pricing page: "No card needed"; reviews: card check (conflict) | nf-compute-20 512 MB ≈ $5.40 (3rd-party); nf-compute-50 1 GB $12 | Best $0 candidate, but per-service RAM is UNVERIFIED |
| Google Cloud Run | Instance-based: 240k vCPU-s + 450k GiB-s/mo free | Scales to zero; cold start of a few seconds (UNVERIFIED) | Filesystem in memory (UNVERIFIED) | Billing account required (UNVERIFIED) | min-instances=1, 1 vCPU/0.5 GiB ≈ **$45/mo** (2.63M s × $0.000018, less free tier) | Too expensive always on |
| Azure Container Apps | 180k vCPU-s + 360k GiB-s + 2M req/mo | Scales to zero | Azure Files | Azure for Students: $100 credit, no card, 12 mo | Idle rate not shown on page | $0 via student credit; more setup (ACR, az CLI) |
| AWS App Runner | — | — | — | — | — | **Closed to new customers since 2026-04-30** |
| HF Spaces (Docker) | CPU Basic 2 vCPU / 16 GB, free hardware | Sleeps when unused | Not persistent | — | Creating a Docker Space needs **PRO $9/mo** | Shortlist claim **confirmed** (official docs) |
| Vercel (Python) | Serverless functions, 500 MB bundle, streaming OK | Per-invocation | No persistent local FS | — | — | Rejected: per-session SQLite can't live there |
| PythonAnywhere | 1 app, 100 CPU-s/day, 512 MB disk | — | Persistent | — | Developer $10/mo | Rejected: outbound allowlist, no Docker, ASGI not stated |
| Oracle Always Free | A1 allowance disputed in 2026 (4 OCPU/24 GB vs a reported cut to 2/12) | Idle reclaim if CPU, net and mem are all < 20% p95 over 7 days | Block volume | Yes | $0 | Rejected: raw VM ops, capacity errors |
| Heroku | Student pack: $13/mo credit (24 mo per 2026 aggregators, 12 mo per older Heroku blog) | Eco sleeps after 30 min; Basic always on | Ephemeral; dynos restart daily (UNVERIFIED) | Card for verification (aggregator) | Basic 512 MB **$7** → $0 with the student credit | $0-cash fallback if the student pack is approved |
| DigitalOcean App Platform | Static sites only | — | — | — | 512 MiB **$5**, 1 GiB $10 | Pack credit reportedly leaving (Sept 2026, 3rd-party) |
| Deta Space | — | — | — | — | — | Reported shut down (UNVERIFIED); skip |

**Why Render over Railway:** the free tier works for all of W0–W3 (Railway's trial ends after 30 days, and its $1/mo free credit covers about 1/10 of an always-on 512 MB box). Every feature P7 relies on was verified in Render's docs: `render.yaml` with `runtime: docker`, `healthCheckPath`, `autoDeployTrigger: off`, a deploy hook that takes `ref=<sha>`, Dashboard rollback, and `RENDER_GIT_COMMIT`. P1 (`01-foundations-plan.md`) already targets Render. You pay $7 only for the window when graders and the demo need it always on.

**Render caveats (verified):** as of 2026-08-01, Hobby workspaces include 5 GB/mo of outbound bandwidth, then $0.15/GB. 750 free hours cover **one** always-on service (744 h in a 31-day month), so create no second free service in the same workspace. A Dashboard rollback turns auto-deploy off; with `autoDeployTrigger: off` that changes nothing.

## 2. Whole-product cost matrix

Prices as read on 2026-10-30.

| # | Product (layer) | Free tier / limit | Paid price | Free alternative | **Pick** | 2-mo $ |
|---|---|---|---|---|---|---|
| 1 | Anthropic API: `claude-sonnet-5-5` planner (LLM) | None | $2 in / $10 out per MTok; cache hit $0.10; 5-min cache write $2.50 | None at Claude quality. Gemini Flash free tier trains on prompts (research 04) | Sonnet 5.5 + prompt caching | 15–60 |
| 2 | Anthropic API: `claude-haiku-5-5` router/judge/guard | None | $0.10 in / $0.50 out per MTok (prompts ≤ 100k tokens) | — | Haiku 5.5 | < 2 |
| 3 | Hosting | Render Free (sleeps) | Starter $7/mo | Render Free + ping; Heroku via student credit; Azure student credit | Render Free → Starter for the demo month | 0–14 |
| 4 | Guard model API (if the safety planner wants a dedicated classifier) | NVIDIA hosted NIM, free (~40 RPM, aggregator) | Groq Llama Guard 4 ≈ $0.20/MTok (aggregator); Prompt Guard 2 price UNVERIFIED | Haiku 5.5 as a classifier (row 2) or NIM | Safety planner decides; every option costs < $1 | 0–1 |
| 5 | Stripe | Test mode / sandboxes free; no real money moves | Live fees (never used) | — | Test mode, `sk_test_` only | 0 |
| 6 | Database | SQLite inside the container | Render disk $0.25/GB-mo | — | SQLite on ephemeral disk, no volume | 0 |
| 7 | Email sandbox (Resend, Mailtrap) | — | — | In-app fake outbox (contract rule 6) | **None needed** | 0 |
| 8 | Uptime / keep-warm | UptimeRobot Free: 50 monitors, 5-min interval, commercial OK | Solo $12/mo (annual) | cron-job.org: free, 1-min minimum, 30 s timeout | UptimeRobot | 0 |
| 9 | Error tracking | Sentry Developer: 1 user, 5k errors, 30-day lookback; student pack: 50k errors for 1 yr | Team $29/mo | Render logs (stdout) | Render logs. Sentry optional (§5) | 0 |
| 10 | CI/CD | GitHub Actions: standard runners free on public repos | Private repo: $12/mo of included compute | — | Public repo | 0 |
| 11 | Custom domain | Student pack: Namecheap .me 1 yr, Name.com 1 domain (.dev/.app etc.), .TECH 1 yr | .com ≈ $10–11/yr (Porkbun, 3rd-party) | `*.onrender.com` | **Skip.** If wanted, Name.com via the pack | 0 |
| 12 | Demo video | OBS Studio (free, open source), YouTube unlisted (free) | — | Windows Game Bar | OBS + YouTube unlisted | 0 |
| 13 | Secrets manager | Render env vars + GitHub secrets | Doppler (free for students) | — | Render env + GitHub secrets | 0 |

**LLM cost per agent turn (P7 estimate):** planner = 6,000-token cached prefix × $0.10/M ($0.0006) + 1,500 uncached × $2/M ($0.003) + 1,200 output × $10/M ($0.012) ≈ **$0.016**. A cache miss adds ≈ $0.015. Haiku guard and judge add ≈ $0.001. Budget **$0.025/turn**.

**Turn volume:** dev 800 (20/day × 40 days; pytest never calls the API) + eval 320 (40 cases × 8 runs) + graders 600 (≈40 graders × 15) + rehearsal and video 150 = **≈ 1,870 turns ≈ $47**. Best case ≈ 800 turns ≈ $15.

## 3. Two-month budget (Nov + Dec 2026)

| Line | Best | Expected | Worst (capped) |
|---|---|---|---|
| Render | $0 (Free + ping the whole time) | $7 (Starter for 1 month) | $14 (Starter for 2 months) |
| Anthropic | $15 | $40 | $80 (org spend limit $40/mo × 2) |
| Guard API, domain, monitoring, video | $0 | $0 | $0 (everything else on free tiers) |
| **Total** | **$15** | **$47** | **$94** |

Guards that enforce the ceiling:

1. **Org spend limit $40/mo:** Console → Billing → Spend limits. Over the limit, requests return HTTP 400 `invalid_request_error` "You have reached your specified API usage limits".
2. **Workspace `shoppilot-prod` limit $20/mo:** the deployed key lives in this workspace. Workspace limits can't be set on the Default workspace. Over the limit, the message reads "...specified workspace API usage limits".
3. **App caps:** `llm_max_plans_per_session_hour=20` (P1), plus a global daily cap (request in §8).
4. **Stripe:** test keys only. `sk_live_` aborts startup (P1).

A Start-tier org also has a hard $500/mo cap (429 `enforced_spend_limit_reached`, no `retry-after`).

## 4. Keep-warm plan

1. W0: UptimeRobot HTTP(s) monitor on `https://<app>.onrender.com/healthz`, every 5 min, email alerts on. On Free, this keeps the service under the 15-min spin-down. On Starter, it is just an alert.
2. If UptimeRobot misses (the service is seen spinning down in Render events), add a cron-job.org job on the same URL every 10 min. Don't build anything else.
3. T-3 days before the demo: switch `plan: free` → `plan: starter` in `render.yaml` (plan task D4). From then on there is no sleep and CPU goes from 0.1 to 0.5.
4. T-30 min: open the URL, run one full demo turn, check the UptimeRobot page is all green.
5. **Deploy freeze from T-2 h until the demo ends.** Each deploy restarts the container, which wipes every session store.

## 5. Ops

- **Repo:** public on GitHub (graders get the URL; Actions free). Protect `main`: require status checks `test` and `docker` (P1 CI jobs), block force-push and deletion. Turn on secret scanning push protection (free on public repos, UNVERIFIED wording). No secret ever goes in the repo; `.env` is git-ignored and `.env.example` holds names only (P1).
- **CI/CD:** P1's `ci.yml` (lint, pytest, docker build) runs on every push and PR. P7's `deploy.yml` runs on `workflow_run` of CI, completed with success on `main`. It calls the Render deploy hook with `&ref=<head_sha>`, then runs `scripts/smoke.sh` against the live URL until `/healthz` reports that SHA. Render auto-deploy is **off**, so only green commits ship.
- **Logs:** app logs to stdout as one line per event; read them in the Render Dashboard (retention on Free UNVERIFIED). The audit log lives in each session DB (contract). **Sentry:** skip. If W3 shows errors that logs can't explain, add `SENTRY_DSN` + `sentry-sdk[fastapi]` (Developer free tier, or the student pack's 50k errors).
- **Rollback**, fastest first:
  1. Render Dashboard → Deploys → Rollback on the last good deploy. This reuses the old build artifact, takes about 1 min, and turns auto-deploy off (already off here).
  2. `curl -fsS "$RENDER_DEPLOY_HOOK_URL&ref=<good_sha>"`, which rebuilds that commit.
  3. `git revert <bad_sha> && git push`, which goes through CI and deploys normally. Use this to fix `main` after step 1 or 2.

## 6. Data on ephemeral disk

There is no persistent disk. `DATA_DIR=/tmp/shoppilot` (P1 default). Every deploy, restart or (on Free) spin-down wipes all session stores. P1 already covers this: a missing file reseeds silently and returns `store_reset: true` for a UI banner. This is acceptable because stores are seeded and resettable by design. It saves $0.25/GB-mo and keeps rollback simple.

**RAM budget:** 512 MB. P1 targets idle RSS < 250 MB; P7 adds a W3 load check (≤ 450 MB under 10 parallel sessions with `--memory=512m`, not OOM-killed).

## 7. Secrets and config (names only)

| Where | Name | Notes |
|---|---|---|
| Render env (secret, `sync: false`) | `ANTHROPIC_API_KEY` | Key from workspace `shoppilot-prod` |
| Render env (secret) | `STRIPE_SECRET_KEY` | `sk_test_…` only |
| Render env (secret, optional) | `NVIDIA_API_KEY` or `GROQ_API_KEY` | Only if the safety planner picks a hosted guard |
| Render env (secret, optional) | `SENTRY_DSN` | Only if Sentry is added |
| Render env (plain) | `APP_ENV=prod`, `DATA_DIR=/tmp/shoppilot` | P1 `Settings` |
| GitHub Actions secret | `RENDER_DEPLOY_HOOK_URL` | From Render → Settings → Deploy Hook. Treat as a secret; regenerate it if leaked |
| GitHub Actions variable | `APP_URL` | `https://<app>.onrender.com`, not secret |

Render sets `PORT` (default 10000) and `RENDER_GIT_COMMIT`. Session cookies use random ids (P1), so no signing secret is needed.

## 8. Contract conflicts / cross-plan requests

1. **W0 overlap with P1 Task 0** (manual Render setup). P7 replaces it with `render.yaml` (task D1). Integrator: drop P1 Task 0 and keep D1. P1 still owns `Dockerfile`, `ci.yml`, `app/main.py`.
2. **`/healthz` `version` value:** P7 needs `version = os.environ.get("RENDER_GIT_COMMIT", "dev")[:7]` so the smoke test can tell when the new deploy is live. This only adds to P1's `{"ok": true, "version": str}`.
3. **Dockerfile `CMD`** must bind `--port ${PORT:-8000}` (shell form, or `sh -c`), because Render injects `PORT`. Keep `--workers 1 --proxy-headers --forwarded-allow-ips='*'`.
4. **CI workflow name:** `deploy.yml` triggers on `workflow_run: workflows: ["CI"]`. P1's `ci.yml` must have `name: CI` and jobs `test` and `docker`.
5. **Global LLM cap:** a public anonymous URL can burn the budget. Ask P1/the LLM planner to add `llm_max_plans_per_day: int = 300` (≈ $7.50/day at $0.025/turn) and return the friendly error `{"error": {"code": "demo_budget_reached", ...}}`. Also treat the Console spend-limit 400 and the spend-cap 429 as non-retryable.
6. **numba:** flagged. It means JIT warm-up on 0.1–0.5 CPU and extra RAM in a 512 MB box. Use plain numpy/scikit-learn (ML planner).

## 9. Sources (all read 2026-10-30)

- Render free: https://render.com/docs/free · plans: https://render.com/docs/compute-plans · Blueprint: https://render.com/docs/blueprint-spec · env vars: https://render.com/docs/environment-variables · deploy hooks: https://render.com/docs/deploy-hooks · rollbacks: https://render.com/docs/rollbacks · disk $0.25: https://render.com/articles/how-much-does-cloud-application-hosting-cost-for-small-businesses · Starter $7 and the 2026-08-01 plan change (3rd-party, updated 2026-08-06): https://jwatte.com/blog/render-com-platform-review.md
- Railway: https://railway.com/pricing · https://docs.railway.com/reference/pricing/free-trial
- Fly.io: https://docs.fly.io/about/pricing
- Koyeb: https://www.koyeb.com/docs/reference/instances · https://www.koyeb.com/docs/faq/pricing
- Northflank: https://northflank.com/pricing · card-check claim (3rd-party): https://freetier.co/directory/products/northflank
- Cloud Run: https://cloud.google.com/run/pricing (free-tier figures from search snippets of this page)
- Azure Container Apps: https://azure.microsoft.com/en-us/pricing/details/container-apps/ · Azure for Students: https://azure.microsoft.com/en-us/free/students
- App Runner closure: https://docs.aws.amazon.com/apprunner/latest/dg/apprunner-availability-change.html
- HF Spaces: https://huggingface.co/docs/hub/en/spaces-overview · https://huggingface.co/pricing
- Vercel Python (updated 2026-08-12): https://vercel.com/docs/functions/runtimes/python
- PythonAnywhere: https://www.pythonanywhere.com/pricing/
- Oracle: https://docs.oracle.com/en-us/iaas/Content/FreeTier/resourceref.htm · 2026 cut reports: https://braindetox.kr/en/posts/oracle_always_free_tier_reduced_2026.html
- Heroku: https://www.heroku.com/pricing · https://help.heroku.com/Z3RHNRHD/how-does-the-github-student-developer-pack-work
- DigitalOcean: https://www.digitalocean.com/pricing/app-platform · pack exit claim: https://capitalandcompute.net/blog/github-student-developer-pack-2026/
- GitHub Student Pack: https://education.github.com/pack · Actions billing: https://docs.github.com/en/billing/concepts/product-billing/github-actions
- Anthropic prices: https://platform.claude.com/docs/en/about-claude/pricing · spend limits: https://platform.claude.com/docs/en/api/rate-limits
- Stripe test mode: https://docs.stripe.com/test-mode
- UptimeRobot: https://uptimerobot.com/pricing/ · cron-job.org: https://cron-job.org/en/faq/ · Sentry: https://sentry.io/pricing/
- Groq guard prices (aggregator): https://cloudprice.net/models/groq/meta-llama/llama-guard-4-12b · NIM free tier: `research/products/02-nvidia-and-vendor-frameworks.md`
- Domains: https://www.cloudflare.com/products/registrar/ · https://domainoffer.net/tld/com/porkbun
