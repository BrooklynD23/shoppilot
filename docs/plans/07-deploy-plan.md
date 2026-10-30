# ShopPilot+ Deploy & Ops Implementation Plan

> Amended by 00-contract-resolutions.md (2026-10-30): R7, R11, R12, R13, R14, R15, R16, R42

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A public HTTPS URL that exists on day 1, redeploys only green commits from `main`, proves each deploy with a smoke test, stays warm for graders and the live demo, and can be rolled back in about 1 minute.

**Architecture:** Render web service built from P1's `Dockerfile` and declared in `render.yaml` (Blueprint). Render auto-deploy is off. P7's `deploy.yml` runs after P1's CI succeeds on `main`, calls the Render deploy hook with `ref=<sha>`, then polls `/healthz` until `version` equals that SHA. UptimeRobot pings `/healthz` every 5 min. The plan goes from Free (W0–W3) to Starter (W4).

**Tech Stack:** Render (Docker runtime, Blueprint), GitHub Actions, bash + curl, UptimeRobot.

**Spec:** `shoppilot/docs/specs/07-hosting-deploy.md`. Contract: `shoppilot/docs/specs/00-shared-brief.md`. Neighbor: `shoppilot/docs/plans/01-foundations-plan.md` (P1 owns `Dockerfile`, `.dockerignore`, `.github/workflows/ci.yml`, `app/main.py`, `.env.example`, `.gitignore`).

## Global Constraints

- One Docker image, one Render web service, region `oregon` (Render region names are UNVERIFIED; pick the US-West option).
- Plan `free` until task D4; `starter` (512 MB, 0.5 CPU, $7/mo) from T-3 days before the demo until grading closes.
- `autoDeployTrigger: off`. Only `deploy.yml` deploys.
- No persistent disk. `DATA_DIR=/tmp/shoppilot`. A deploy wipes all session stores.
- Secrets live only in Render env (`sync: false`) and GitHub Actions secrets. Never `echo` a secret; never commit `.env`.
- Stripe keys are test keys only: `rk_test_` restricted (recommended) or `sk_test_` (R15). Anthropic prod key comes from workspace `shoppilot-prod` (limit $20/mo); dev/eval key from `shoppilot-dev` ($20/mo); org limit $40/mo (R7).
- Smoke tests never call `/api/plan`, because that spends LLM money.
- Deploy freeze from T-2 h before the demo until it ends.
- Lines marked **HUMAN:** need account signup, OAuth, a card or a Console click. An agent stops there and asks.

## Review Focus

1. **A deploy or restart during grading wipes stores.** A grader's old cookie must get a reseeded store (`store_reset: true`), not a 500. Pinned in D3 Step 2 (restart, then reuse the cookie).
2. **Keep-warm ping misses on Free** (15-min spin-down, about 1 min to wake). The first grader sees Render's loading page. Fixed by the D0 monitor plus the D4 Starter switch before grading.
3. **OOM at 512 MB with several graders at once.** The container restarts, which wipes everyone's store. Pinned in D3 Step 3 (10 parallel sessions under `--memory=512m`).
4. **A commit passes CI but fails to boot in prod** (e.g. `ANTHROPIC_API_KEY` is missing, so P1's prod validator raises). The smoke test must fail red within the timeout, not hang. Pinned in D2 Step 4 (wrong-SHA case exits 1).
5. **Deploy-hook URL leaks in Actions logs.** It is stored as a secret, used through an env var, never echoed. The hook output goes to `/dev/null`. If leaked, regenerate it (D4 runbook). Checked in D2 Step 6 by reading the run log.

---

### Task D0: Accounts, repo protection, spend guards (HUMAN)

Wave: W0 · Depends-on: P1 Task 1 (CI must exist so its checks can be required) · Owns-files: none · Est: 1 h

**Interfaces:**
- Produces: GitHub repo `shoppilot` (public); Actions secret `RENDER_DEPLOY_HOOK_URL` (filled in D1); Actions variable `APP_URL`; Anthropic key in workspace `shoppilot-prod`; Stripe `sk_test_` key; UptimeRobot monitor (created in D1 Step 5).

- [ ] **Step 1: HUMAN:** create a **public** GitHub repo `shoppilot` and push P1's skeleton. Settings → Code security: turn on secret scanning and push protection.
- [ ] **Step 2: HUMAN:** Settings → Rules → new branch ruleset on `main`: require status checks `test` and `docker`, block force pushes, restrict deletions. Leave PR reviews off, since this is a solo project.
- [ ] **Step 3: HUMAN (card):** in the Claude Console, create workspaces `shoppilot-prod` and `shoppilot-dev`, each with a $20/mo spend limit. Set the org spend limit to $40/mo (Billing → Spend limits). Buy the smallest credit pack. Create one API key inside each workspace and keep both in a password manager (prod key → Render only; dev key → local `.env` for P2-T4/T11/T13, P4-T6).
- [ ] **Step 4: HUMAN:** create a Stripe account. Stay in a sandbox named `shoppilot` (no activation) and create a **restricted `rk_test_…` key, not agent-tagged**, with write on PaymentIntents, Refunds, Payment Links, Prices, Products (P5 spec §13, R15).
- [ ] **Step 5: Verify** that none of these values exist in git.
  Run: `git log -p | grep -E "sk_(test|live)_|sk-ant-|api.render.com/deploy" | wc -l`
  Expected: `0`

### Task D1: `render.yaml` and the day-1 hello deploy

Wave: W0 · Depends-on: D0, P1 Task 1 (hello `app/main.py` + `Dockerfile` with `CMD` on `${PORT:-8000}`) · Owns-files: `render.yaml` · Est: 0.75 h

**Interfaces:**
- Consumes: `GET /healthz` → `{"ok": true, "version": os.environ.get("RENDER_GIT_COMMIT", "dev")[:7]}` (P1-T1, R11). P1-T1D is dropped; this task is the only host setup (R14).
- Produces: live URL `https://<service>.onrender.com`, saved as Actions variable `APP_URL`; deploy hook URL saved as Actions secret `RENDER_DEPLOY_HOOK_URL`.

- [ ] **Step 1: Write `render.yaml`** with exactly these fields: one `type: web` service, `name: shoppilot`, `runtime: docker`, `plan: free`, `region: oregon`, `dockerfilePath: ./Dockerfile`, `healthCheckPath: /healthz`, `autoDeployTrigger: off`, and `envVars`:
  - `APP_ENV` = `prod`
  - `DATA_DIR` = `/tmp/shoppilot`
  - `ANTHROPIC_API_KEY` with `sync: false`
  - `STRIPE_SECRET_KEY` with `sync: false`

  No `disk:` block.
- [ ] **Step 2: Commit and push**
  ```bash
  git add render.yaml && git commit -m "ci: render blueprint (free plan, docker, manual deploys)" && git push
  ```
- [ ] **Step 3: HUMAN (OAuth):** sign up at render.com with GitHub. New → Blueprint → pick repo `shoppilot`. When prompted, paste the two `sync: false` values from D0 and apply.
- [ ] **Step 3b: Check** Render's request-duration limit on the docs (Render articles state 100 minutes; `/api/plan` needs ≤ 95 s, R16). Note the page URL in `docs/ops.md` later.
- [ ] **Step 4: Verify the URL exists**
  Run: `curl -fsS https://<service>.onrender.com/healthz`
  Expected: `{"ok":true,"version":"<first 7 chars of HEAD>"}`
- [ ] **Step 5: HUMAN:** copy Render → service → Settings → Deploy Hook into the GitHub Actions secret `RENDER_DEPLOY_HOOK_URL`. Set the Actions variable `APP_URL` to `https://<service>.onrender.com`. In UptimeRobot (free signup), add an HTTP(s) monitor on `$APP_URL/healthz`, 5-min interval, email alert.

### Task D2: Smoke script and gated deploy workflow

Wave: W0 · Depends-on: D1 · Owns-files: `scripts/smoke.sh`, `.github/workflows/deploy.yml` · Est: 1.5 h

**Interfaces:**
- Consumes: P1 workflow `name: CI` with jobs `test` and `docker` (spec §8.4); `APP_URL`; `RENDER_DEPLOY_HOOK_URL`.
- Produces: `scripts/smoke.sh BASE_URL [EXPECTED_SHA] [TIMEOUT_S=600]`. It exits 0 when `/healthz` returns 200 with `"version":"${EXPECTED_SHA:0:7}"` (version is skipped if no SHA is given) and `/` returns 200 containing `ShopPilot`. It exits 1 with the last response body on timeout. It polls every 10 s; each curl uses `-fsS --max-time 15`. `SMOKE_FULL=1` adds the D3 checks.
- Produces: workflow `Deploy`. Triggers: `workflow_run` (workflows `["CI"]`, types `[completed]`, branches `[main]`) and `workflow_dispatch` with optional input `ref`. Concurrency group `deploy`, `cancel-in-progress: false`.

- [ ] **Step 1: Write `scripts/smoke.sh`** (bash, `set -euo pipefail`, `chmod +x`) to the signature above. Match JSON with `grep -q`; Starlette emits compact JSON (`{"ok":true,"version":"abc1234"}`).
- [ ] **Step 2: Verify the pass case locally**
  Run:
  ```bash
  docker build -t sp . && docker run --rm -d -p 8000:8000 -e RENDER_GIT_COMMIT=abc1234def -e APP_ENV=test --name sp sp
  scripts/smoke.sh http://localhost:8000 abc1234def 60; echo "exit=$?"
  ```
  Expected: `exit=0`
- [ ] **Step 3: Verify the wrong-SHA case fails fast**
  Run: `scripts/smoke.sh http://localhost:8000 0000000 15; echo "exit=$?"; docker rm -f sp`
  Expected: the last body is printed, then `exit=1`, within about 25 s.
- [ ] **Step 4: Write `.github/workflows/deploy.yml`**:
  - Job `deploy` runs only `if:` `workflow_dispatch`, or (`workflow_run.conclusion == 'success'` and `workflow_run.event == 'push'`).
  - `SHA = inputs.ref || github.event.workflow_run.head_sha || github.sha`.
  - Steps:
    1. `actions/checkout` at `SHA`.
    2. `curl -fsS -X POST "$HOOK&ref=$SHA" -o /dev/null`, with `HOOK` read from `secrets.RENDER_DEPLOY_HOOK_URL` via `env:`.
    3. `scripts/smoke.sh "${{ vars.APP_URL }}" "$SHA" 600`.
  - Nothing echoes `HOOK`.
- [ ] **Step 5: Commit and push to `main`**
  ```bash
  git add scripts/smoke.sh .github/workflows/deploy.yml && git commit -m "ci: deploy green main commits to render and smoke-test /healthz" && git push
  ```
- [ ] **Step 6: Verify end to end**
  Run: `gh run list --workflow Deploy --limit 1` and then `gh run view --log <id> | grep -c "api.render.com/deploy"`
  Expected: the run is `completed success`, and the grep count is `0` (the hook URL never appears; GitHub masks secrets as `***`).

### Task D3: Production-shape checks (memory, restart, full smoke)

Wave: W3 · Depends-on: D2, P1 Task 6 (sessions + `/api/store`), W2 features merged · Owns-files: `scripts/smoke.sh` (W3 extension; D2 owned it in W0) · Est: 1 h

**Interfaces:**
- Consumes: P1 cookie `sp_session`; `POST /api/session` → 200; `GET /api/store` → JSON with `products` and, after a wipe, `"store_reset": true`; a garbage cookie → 401 `no_session`.

- [ ] **Step 1: Extend `scripts/smoke.sh`**. With `SMOKE_FULL=1` and a curl cookie jar:
  1. `POST /api/session` → 200.
  2. `GET /api/store` → 200 and the body contains `"products"`.
  3. `GET /api/store` with header `Cookie: sp_session=garbage` → `401`.
- [ ] **Step 2: Verify restart reseed locally**
  Run:
  ```bash
  docker run -d -p 8000:8000 --memory=512m -e APP_ENV=test --name sp sp
  SMOKE_FULL=1 scripts/smoke.sh http://localhost:8000
  docker restart sp && sleep 5
  curl -fsS -b /tmp/sp.jar localhost:8000/api/store | grep -c '"store_reset":true'
  ```
  Expected: the smoke test exits 0, and the grep prints `1`. The cookie jar path `/tmp/sp.jar` must match the one `smoke.sh` writes; set it with `SMOKE_JAR`, default `/tmp/sp.jar`.
- [ ] **Step 3: Verify memory under 10 parallel graders**
  Run:
  ```bash
  for i in $(seq 10); do (curl -fsS -c /tmp/j$i -X POST localhost:8000/api/session >/dev/null && curl -fsS -b /tmp/j$i localhost:8000/api/store >/dev/null) & done; wait
  docker stats --no-stream --format '{{.MemUsage}}' sp; docker inspect -f '{{.State.OOMKilled}}' sp; docker rm -f sp
  ```
  Expected: memory ≤ 450 MiB and `false`. If it fails, profile the reportlab import and per-session file count (ML is stdlib, no scikit-learn, R42). Do not raise the plan.
- [ ] **Step 4: Verify against prod**
  Run: `SMOKE_FULL=1 scripts/smoke.sh "$APP_URL"`
  Expected: exit 0.
- [ ] **Step 5: Commit**
  ```bash
  git add scripts/smoke.sh && git commit -m "ci: full smoke (session, store, bad cookie)" && git push
  ```

### Task D4: Demo hardening: Starter plan, runbook, rollback drill

Wave: W4 · Depends-on: D3; demo date known · Owns-files: `render.yaml` (W4), `docs/ops.md` · Est: 1 h

**Interfaces:**
- Produces: `docs/ops.md`, with sections `Pre-demo checklist`, `Rollback`, `Leaked secret`, `Costs`. The demo script owner links to it.

- [ ] **Step 1: HUMAN (card):** at T-3 days, add a card in Render → Billing.
- [ ] **Step 2: Switch the plan.** Set `plan: starter` in `render.yaml`. If Blueprint sync rejects the legacy name, use `0.5c-512mb`. Commit `ci: render starter plan for demo window`, push, and confirm Render → service shows Starter.
- [ ] **Step 3: Write `docs/ops.md`.** Copy the keep-warm and rollback steps from spec §4–§5 verbatim. Add:
  - **Leaked secret:** regenerate the deploy hook (Render → Regenerate Hook, then update the GitHub secret), rotate the Anthropic key (Console), roll the Stripe test key (Dashboard), and update Render env.
  - **Pre-demo checklist:**
    1. T-1 day: `SMOKE_FULL=1 scripts/smoke.sh "$APP_URL"` passes.
    2. Console usage is under $20 in `shoppilot-prod`; set Render env `LLM_DAILY_BUDGET_USD=10` for grading week (R7, Q17).
    3. UptimeRobot shows 100% for 24 h.
    4. T-2 h: deploy freeze starts.
    5. T-30 min: run one full demo turn on the URL in a private window.
    6. Have the backup video open in a tab.
- [ ] **Step 4: Rollback drill.** Push a harmless commit, then run `gh workflow run Deploy -f ref=<previous_sha>`.
  Expected: the Deploy run is green, and `/healthz` `version` equals the previous SHA's 7 chars. Then run `gh workflow run Deploy` (no ref) to return to the latest commit.
- [ ] **Step 5: Commit**
  ```bash
  git add docs/ops.md && git commit -m "docs: ops runbook, pre-demo checklist, rollback" && git push
  ```
- [ ] **Step 6: HUMAN:** after grading closes, switch Render back to `free` (or suspend the service) and delete the Stripe sandbox data. Leave the Anthropic limits in place.

---

## Task summary

| Id | Wave | Depends-on | Owns-files | Est h | HUMAN |
|---|---|---|---|---|---|
| D0 | W0 | P1 T1 | — | 1 | repo, ruleset, Anthropic card + limits, Stripe |
| D1 | W0 | D0, P1 T1 | `render.yaml` | 0.75 | Render OAuth, env values, hook → secret, UptimeRobot |
| D2 | W0 | D1 | `scripts/smoke.sh`, `.github/workflows/deploy.yml` | 1.5 | — |
| D3 | W3 | D2, P1 T6, W2 | `scripts/smoke.sh` | 1 | — |
| D4 | W4 | D3 | `render.yaml`, `docs/ops.md` | 1 | Render card, post-grading downgrade |

Total: 5.25 h. Deferred: Sentry (add `SENTRY_DSN` if W3 errors can't be read from Render logs), custom domain (`*.onrender.com` is enough), cron-job.org backup ping (add only if UptimeRobot misses a spin-down).

**Fallback host** if Render fails in W0 (one step, no new files): Railway → New Project → Deploy from GitHub repo (it detects the Dockerfile) → set the same env vars → Generate Domain. Replace the deploy hook step with Railway's GitHub auto-deploy and keep `smoke.sh` unchanged.
