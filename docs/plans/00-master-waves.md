# ShopPilot+ Master Build Plan (W0 → W4)

> **For agentic workers:** REQUIRED SUB-SKILL: use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans. Each row below points to the task body in its source plan (`plans/0N-*.md`). Contract: `../specs/00-shared-brief.md` **as amended by** `../specs/00-contract-resolutions.md` (resolutions win). Unresolved user decisions and their defaults: `00-open-questions.md`.

**Goal:** One public URL where an anonymous grader types a shop-ops request, sees a validated, previewed plan of typed tool calls (ML forecast, guarded inbox, Stripe test refunds, fake outbox), approves it step by step, and can undo from a tamper-evident audit log; plus repo, demo script and 1–2 min video.

**Architecture:** FastAPI + vanilla JS on one uvicorn worker in one Docker image on Render. Per-session SQLite file (cookie id → hashed file name), seeded deterministically. `make_plan` = Haiku router → Sonnet strict-tool loop (reads run, writes are staged and validated in-loop) → deterministic validator + `policy` → Haiku judge. Plans are stored server-side; `/api/execute` runs approved steps one call per step with lock-then-check and a `step_runs` table. Inbound email passes a regex + Haiku guard (fail closed). Stripe test mode via SDK; emails go to an in-app outbox. LLM calls go through one client with retries, $ budgets, prompt caching and record/replay.

**Tech Stack:** Python 3.12, FastAPI 0.162.0, Pydantic 2.14.2, uvicorn 0.54.0, stdlib sqlite3, jsonschema, anthropic 2.3.0 (`claude-sonnet-5-5`, `claude-haiku-5-5`), stripe 16.1.0, reportlab 5.1.0; pytest 9.2.0, ruff 0.17.3, Python Playwright with system Chrome; Docker `python:3.12-slim`; GitHub Actions; Render (Free → Starter); UptimeRobot.

**Specs (read in this order):** `00-shared-brief.md` → `00-contract-resolutions.md` → `01-architecture.md` · `02-agent-core.md` · `03-ml-actions.md` · `04-safety.md` · `05-integrations.md` · `06-ui-demo.md` · `07-hosting-deploy.md`.

## Global Constraints

1. Names in the brief + resolutions §2 are frozen. A task that needs a change files it with the integrator; it never renames locally.
2. **No two tasks in one wave own the same file.** A task edits only files in its `Owns-files` cell (plus new test files it creates under its own name). Shared files (`app/main.py`, `pyproject.toml`, `tests/conftest.py`, `.env.example`) change only in P1 tasks and the INT batches.
3. Tests never touch the network (P1 autouse block). Live tests are `@pytest.mark.live`, run only with `RUN_LIVE=1`; CI runs `pytest -m "not live"`.
4. Secrets only in env (Render env, GitHub secrets, password manager). Stripe keys `sk_test_`/`rk_test_` only. Raw session id never leaves the server (R21).
5. Money = integer cents. Timestamps ISO-8601 UTC `Z`. Store "today" = `ctx.today` (= seed anchor).
6. Tools never call `log_action` and never commit (R23). Policy numbers live only in `app/safety/policy.py` (R18).
7. Untrusted text (email bodies, names, LLM reasons) renders with `textContent` only; every POST carries `X-ShopPilot: 1`.
8. Files < 400 lines (`app.js` ≤ 800), functions < 50 lines. Commits: conventional (`feat:`, `fix:`, `test:`, `docs:`, `ci:`).
9. Executor column: `sonnet` = implementation subagent, `haiku` = trivial, `HUMAN` = account/card/OAuth/recording step (agent stops and asks). `+HUMAN` = an agent can do the code, a human supplies a key or clicks.

## Review Focus (top 5 cross-cutting risks)

1. **Money path under per-step execute (R1, R20).** Two tabs or a double click must never refund twice; a crash after Stripe succeeds must replay the same `re_` id on retry. Guarded by lock-then-check in `claim_plan`, `step_runs` PK, business-state idempotency keys. Tests: P2-T10, P4-T4 `test_double_execute_one_refund`, P5-I6 case 4.
2. **Seed calibration is a single point of coupling (R4).** One generator feeds the ML gates (MAE, coverage, 8/8 anomalies), eval ids, policy caps (damaged ≤ $200, ≤ 30 d) and demo copy ("runs out in about 4 days"). It sits on the W1 critical path; changing it after P2-T11 forces a re-record (~$1, ~1 h). Freeze `RNG_SEED` and the constants at the end of W1.
3. **Replay fallback goes stale (R8, R25).** Prompt edits change `PROMPT_VERSION`; replayed tool args carry recorded dates while the prod store is anchor-relative; guard recordings are needed or the damaged email fails closed in replay. Gates: `test_recordings_fresh`, P6-UI5 live tests in `LLM_MODE=replay` on the three chip prompts, re-record in P2-T13 ≥ 2 days before the demo.
4. **Latency and cold start.** Plans take 10–30 s (90 s deadline) on 0.1 CPU Render Free with a ~1 min wake. UI: 95 s timeout, stage counter, "Use recorded plan" at 12 s. Ops: UptimeRobot 5-min ping, Starter (0.5 CPU, no sleep) from T-3 days, deploy freeze T-2 h.
5. **Anonymous public URL abuse.** Budget burn, classroom NAT, CSRF, XSS through the hostile inbox. Layers: $ budgets + 300 plans/day + per-session/IP limits (R7, R36), Console caps, guard fail-closed, policy caps, `textContent` + CSP + static hygiene test (P4-T5).

Later (not top 5): prompt-engineering visibility in the UI (R35), 512 MB RSS with reportlab (P7-D3), Stripe MCP agent-key deadline 2026-11-30 (only matters for stretch S1).

---

## W0 — Repo bootstrap and day-1 deploy

| id | Title | Depends-on | Owns-files | Est h | Executor |
|---|---|---|---|---|---|
| P1-T1 | Repo bootstrap, hello app, CI `name: CI`, Dockerfile `${PORT:-8000}`, conftest, all package `__init__`s, pinned deps (R11–R13, R29, R30) | — | `pyproject.toml`, `.gitignore`, `.env.example`, `README.md`, `.dockerignore`, `Dockerfile`, `.github/workflows/ci.yml`, `app/__init__.py`, `app/{seed,llm,llm/prompts,agent,tools,ml,safety,integrations}/__init__.py`, `tests/__init__.py`, `tests/{agent,tools,llm,seed,ml,safety,integrations,static,eval,e2e}/__init__.py`, `app/main.py`, `app/static/index.html`, `tests/conftest.py`, `tests/test_main.py` | 3.5 | sonnet |
| P7-D0 | Accounts, repo ruleset, Anthropic org/workspace caps, Stripe sandbox key | P1-T1 (ruleset needs CI checks) | — | 1 | HUMAN |
| P7-D1 | `render.yaml` Blueprint + hello deploy + UptimeRobot (replaces P1-T1D, R14) | P7-D0, P1-T1 | `render.yaml` | 0.75 | sonnet +HUMAN |
| P7-D2 | `scripts/smoke.sh` + gated `deploy.yml` | P7-D1 | `scripts/smoke.sh`, `.github/workflows/deploy.yml` | 1.5 | sonnet |
| ~~P1-T1D~~ | Manual Render deploy | — | — | 0 | dropped (R14) |

W0: **6.75 h**, critical path P1-T1 → P7-D0 → P7-D1 → P7-D2 = 6.75 h, max parallelism **2** (D0 account signups can run beside P1-T1).

## W1 — Foundations

| id | Title | Depends-on | Owns-files | Est h | Executor |
|---|---|---|---|---|---|
| P1-T2 | Settings (full list R31) + DB core, merged DDL (R5), `session_hash`, `rk_test_` (R15) | P1-T1 | `app/config.py`, `app/db.py`, `tests/test_config.py`, `tests/test_db.py` | 3.5 | sonnet |
| P1-T3 | Deterministic seed per resolutions §4 (R4) | P1-T2 | `app/seed/generate.py`, `tests/seed/test_generate.py` | 4 | sonnet |
| P1-T4 | Tool registry + `Ctx(session_id, db, now, today)` (R3) | P1-T1 | `app/tools/registry.py`, `tests/tools/test_registry.py` | 1.5 | sonnet |
| P1-T5 | Audit log, hash chain, single-shot undo, `changed_since` (R22, R38) | P1-T2, P1-T4 | `app/agent/audit.py`, `tests/agent/test_audit.py` | 2 | sonnet |
| P1-T6 | HTTP skeleton: sessions, all routes with final shapes (§7), rate limits (R36), route orchestration (R32), CSP | P1-T2, P1-T3, P1-T5, P2-T1 | `app/main.py`, `tests/test_main.py`, `tests/test_sessions.py` | 4 | sonnet |
| P2-T1 | Agent models incl. `StepResult`, `Plan.source` (R2) | P1-T4 | `app/agent/models.py`, `tests/agent/test_models.py` | 0.5 | haiku |
| P2-T2 | LLM budget ledger, prices, slot | P1-T2 | `app/llm/budget.py`, `tests/llm/test_budget.py` | 2 | sonnet |
| P2-T3 | LLM client: retries, spend guard, caching, record/replay, `complete_json` (R25) | P2-T2 | `app/llm/client.py`, `tests/llm/test_client.py` | 4.5 | sonnet |
| P2-T4 | Live smoke: strict tools + format + fallback beta + cache hit | P2-T3, P1-T4, P7-D0 (dev key) | `tests/llm/test_live_smoke.py` | 1 | sonnet +HUMAN |

W1: **23 h**, critical path P1-T2 → P1-T3 → P1-T6 = 11.5 h (runner-up P1-T2 → P2-T2 → P2-T3 → P2-T4 = 11 h), max parallelism **4** (P1-T3, P1-T5, P2-T1, P2-T2 after P1-T2/T4). End-of-W1 gate: seed constants and `RNG_SEED` frozen.

## W2 — Features in parallel

| id | Title | Depends-on | Owns-files | Est h | Executor |
|---|---|---|---|---|---|
| P2-T5 | Prompts package (policy numbers R18, tool descriptions §3) | P2-T1 | `app/llm/prompts/{planner_system,policy,examples,router,judge}.md`, `app/llm/prompts/__init__.py` content*, `tests/llm/test_prompts.py` | 3 | sonnet |
| P2-T6 | Read tools `list_orders` (no notes), `list_inbox` via `screen_inbox` (R24) | P1-T3, P1-T4, P4-T1 | `app/tools/list_orders.py`, `app/tools/list_inbox.py`, `tests/tools/test_read_tools.py` | 2 | sonnet |
| P2-T7 | Validator; calls `policy.check_plan` (hard import, R18) | P2-T1, P1-T3, P1-T4, P4-T2 | `app/agent/validator.py`, `tests/agent/test_validator.py` | 3 | sonnet |
| P2-T8 | Planner (router, staged loop, judge), `save_plan`, `force_replay` (R8, R32) | P2-T3, P2-T5, P2-T6, P2-T7, P1-T5 | `app/agent/planner.py`, `tests/agent/test_planner.py` | 5 | sonnet |
| P2-T9 | Dry-run | P2-T1, P1-T4 | `app/agent/dryrun.py`, `tests/agent/test_dryrun.py` | 1.5 | sonnet |
| P2-T10 | Executor: per-step, lock-then-check, `step_runs` (R1) | P2-T7, P1-T2, P1-T5 | `app/agent/executor.py`, `tests/agent/test_executor.py` | 3.5 | sonnet |
| P3-ML1 | Forecast core + DB wrapper | P1-T3 | `app/ml/forecast.py`, `tests/ml/conftest.py`, `tests/ml/test_forecast.py` | 3.5 | sonnet |
| P3-ML2 | Anomaly core + DB wrapper | P1-T3 | `app/ml/anomaly.py`, `tests/ml/test_anomaly.py` | 2.5 | sonnet |
| P3-ML3 | `forecast_demand` tool | P3-ML1, P1-T4, P2-T1 | `app/tools/forecast_demand.py`, `tests/tools/test_forecast_demand.py` | 1 | sonnet |
| P3-ML4 | `create_restock_po` tool (no `log_action`, R23) | P3-ML1, P1-T4, P2-T1, P4-T2 | `app/tools/create_restock_po.py`, `tests/tools/test_create_restock_po.py` | 2 | sonnet |
| P3-ML5 | `flag_anomalies` tool | P3-ML2, P1-T4 | `app/tools/flag_anomalies.py`, `tests/tools/test_flag_anomalies.py` | 1 | haiku |
| P4-T1 | Inbound guard + `screen_inbox` + 20-case set | P1-T4, P2-T3 | `app/safety/inbound_guard.py`, `tests/safety/test_inbound_guard.py`, `tests/safety/guard_cases.json` | 5.5 | sonnet |
| P4-T2 | Policy hard rules (single source, R18–R20) | P1-T3, P1-T4, P1-T5, P2-T1 | `app/safety/policy.py`, `tests/safety/test_policy.py` | 4 | sonnet |
| P4-T3 | Web hardening `install(app)`, `PLAN_DAILY_CAP=300` | P1-T6 | `app/safety/web.py`, `tests/safety/test_web_security.py` | 3 | sonnet |
| P5-I1 | Stripe client (modes, live guard, error map, session hash) | P1-T2 | `app/integrations/stripe_client.py`, `tests/integrations/test_stripe_client.py` | 3 | sonnet |
| P5-I2 | Fake outbox | P1-T2 | `app/integrations/outbox.py`, `tests/integrations/test_outbox.py` | 1 | sonnet |
| P5-I3 | Export CSV + PDF | P1-T3 | `app/integrations/export.py`, `tests/integrations/test_export.py` | 2 | sonnet |
| P5-I4 | `mark_shipped` tool | P1-T4, P2-T1 | `app/tools/mark_shipped.py`, `tests/tools/test_mark_shipped.py` | 1.5 | sonnet |
| P5-I5 | `send_email` tool | P5-I2, P1-T4 | `app/tools/send_email.py`, `tests/tools/test_send_email.py` | 1.5 | sonnet |
| P5-I6 | `refund_order` tool | P5-I1, P4-T2 | `app/tools/refund_order.py`, `tests/tools/test_refund_order.py` | 3 | sonnet |
| P5-I7 | `create_payment_link` tool (destructive=True, R6) | P5-I1, P1-T4 | `app/tools/create_payment_link.py`, `tests/tools/test_create_payment_link.py` | 2 | sonnet |
| P5-I8 | `export_report` tool | P5-I3 | `app/tools/export_report.py`, `tests/tools/test_export_report.py` | 0.5 | haiku |
| P6-UI1 | Fixture JSON (real id formats, R27/R28) | resolutions only | `app/static/fixtures/*.json`, `tests/static/test_fixtures.py` | 1.5 | sonnet |
| P6-UI4 | Browser smoke tests (red first) | P6-UI1 | `tests/static/test_ui.py` | 3 | sonnet |
| P6-UI2 | Markup + styles (+ `#under-hood`, `#judge`, R35) | P6-UI4 | `app/static/index.html`, `app/static/styles.css` | 4 | sonnet |
| P6-UI3 | Behaviour `app.js` (per-step run, under-hood, judge, CSRF header) | P6-UI1, P6-UI4 | `app/static/app.js` | 8.5 | sonnet |

\* `app/llm/prompts/__init__.py` is created empty by P1-T1 (W0); P2-T5 writes its content in W2 (different wave).

W2: **72 h** (P2 18, P3 10, P4 12.5, P5 14.5, P6 17), critical path P6-UI1 → P6-UI4 → P6-UI3 = 13 h (runner-up P4-T1 → P2-T6 → P2-T8 = 12.5 h; P4-T2 → P2-T7 → P2-T8 = 12 h), max parallelism **12** at wave start (P2-T5, P2-T9, P3-ML1, P3-ML2, P4-T1, P4-T2, P4-T3, P5-I1, P5-I2, P5-I3, P5-I4, P6-UI1). Option: P6-UI1/UI4 may start during W1 (they depend only on docs and own no W1 file), which takes the UI chain off the critical path.

## Integrator batch (between W2 and W3)

| id | Title | Depends-on | Owns-files | Est h | Executor |
|---|---|---|---|---|---|
| INT-1 | Shared-file batch: (1) `install(app)` in `main.py` (R10); (2) flip lazy 501 routes to live and tighten `test_unbuilt_route_501` to 200; (3) `--cov=app --cov-fail-under=80` in pytest addopts; (4) promote fixtures used by ≥ 2 W2 test files (LLM `Script` fake, Stripe fake) into conftest; (5) add any env name a W2 task requested to `.env.example`; (6) `pytest -m "not live" && ruff check . && docker build .` green | every W2 task | `app/main.py`, `pyproject.toml`, `tests/conftest.py`, `.env.example` | 2 | sonnet (opus reviews diff) |

Requested by: P1 (C4 / self-review coverage gate), P4 (spec §11 #2), P2 (self-review: main.py wiring). Config fields were moved up into P1-T2 (R31), so `app/config.py` is not in this batch.

## W3 — Integration, eval, hardening

| id | Title | Depends-on | Owns-files | Est h | Executor |
|---|---|---|---|---|---|
| P2-T11 | Eval set (24 cases incl. 3 chip prompts, R33) + recordings incl. guard (R25); prompt fixes | P2-T8, P2-T9, P2-T10, P2-T6, P3-ML3–5, P5-I4–I8, INT-1 | `tests/eval/cases.json`, `tests/eval/test_eval.py`, `tests/eval/record.py`, `app/llm/recordings/*.json`, `app/llm/prompts/*` | 4 | sonnet +HUMAN (dev key) |
| P2-T12 | LLM failure modes end-to-end | P2-T11 | `tests/agent/test_failure_modes.py` | 2 | sonnet |
| P3-ML6 | ML evaluation gates on the real seed | P3-ML1, P3-ML2 | `app/ml/evaluate.py`, `tests/ml/test_evaluate.py` | 1.5 | sonnet |
| P4-T4 | End-to-end safety tests (per-step execute semantics) | INT-1, P4-T1–T3, P2-T10, P5-I6 | `tests/safety/test_e2e_safety.py` | 4 | sonnet |
| P4-T5 | Static DOM hygiene + secret scan | P6-UI3 | `tests/safety/test_static_hygiene.py` | 1 | haiku |
| P4-T6 | Live guard eval + fixture recording | P4-T1, P7-D0 (dev key) | `tests/safety/guard_cases.json`, `tests/safety/test_inbound_guard.py`, `app/safety/inbound_guard.py` (prompt/rule lines only) | 1 | sonnet +HUMAN |
| P5-I9 | Live Stripe sandbox smoke + setup doc | P5-I1, P5-I6, P5-I7, P7-D0 (Stripe key) | `tests/integrations/test_stripe_live.py`, `docs/specs/05-stripe-setup.md` | 1.5 | sonnet +HUMAN |
| P5-I10 | Layer-4 end-to-end flow | P5-I4–I8, P2-T10, INT-1 | `tests/e2e/test_layer4_flow.py` | 1.5 | sonnet |
| P6-UI5 | Live API wiring, `LLM_MODE=replay` live tests | P6-UI3, INT-1, P2-T11 | `app/static/app.js`, `tests/static/test_ui_live.py` | 3 | sonnet |
| P6-UI6 | Accessibility, phone, worst-case pass | P6-UI2, P6-UI3 | `app/static/index.html`, `app/static/styles.css`, `tests/static/test_ui.py` | 2.5 | sonnet |
| P7-D3 | Production-shape checks (memory, restart, full smoke) | P7-D2, INT-1 | `scripts/smoke.sh` | 1 | sonnet |
| P5-S1 | *Stretch, optional:* read-only Stripe MCP lookup | P5-I10 green, ≥ 2 spare days | `app/integrations/stripe_mcp.py`, `app/agent/planner.py` (one option hook) | 2 | sonnet |

W3: **23 h** (+2 h optional S1), critical path P2-T11 → P6-UI5 = 7 h (runner-up P2-T11 → P2-T12 = 6 h), max parallelism **9** at wave start (P2-T11, P3-ML6, P4-T4, P4-T5, P4-T6, P5-I9, P5-I10, P6-UI6, P7-D3).

## W4 — Deploy, demo, video, submission

| id | Title | Depends-on | Owns-files | Est h | Executor |
|---|---|---|---|---|---|
| P7-D4 | Starter plan at T-3 days, `docs/ops.md`, rollback drill | P7-D3, demo date (Q1) | `render.yaml`, `docs/ops.md` | 1 | sonnet +HUMAN (card) |
| P2-T13 | Effort sweep, measured cost, re-record with chosen effort (moved from W3, R34) | P2-T11, P7-D3 | `app/config.py` (`planner_effort` default only), `app/llm/recordings/*.json`, `docs/specs/02-agent-core.md` (§3 effort line, §9) | 1.5 | sonnet +HUMAN (dev key) |
| P4-T7 | Deployed abuse smoke (headers, cookie, CSRF, XFF, stage rehearsal) | P7-D4, P4-T1–T6 | — | 1 | HUMAN |
| P5-I11 | Deploy check: TEST badge, `re_` id visible in Stripe Dashboard | P5-I9, P5-I10, P7-D4 | — | 0.5 | HUMAN |
| P6-UI7 | Demo rehearsal (cold start timing from dropped P1-T1D goes here) | P6-UI5, P6-UI6, P7-D4, P2-T13 | `docs/demo/rehearsal-log.md` | 1.5 | HUMAN |
| P6-UI8 | Demo video (OBS → Clipchamp → YouTube unlisted) | P6-UI7 | `docs/demo/video.md` | 3 | HUMAN |
| INT-2 | README (URL, video, eval/guard/ML tables, costs, known limits, stale-claim corrections §8) + submit repo URL, deployed URL, video URL (R40) | P6-UI8, P3-ML6, P2-T11, P4-T6 | `README.md` | 1.5 | sonnet +HUMAN (submit) |

W4: **10 h**, critical path P2-T13 (1.5, parallel with P7-D4 1 h) → P6-UI7 → P6-UI8 → INT-2 = 7.5 h, max parallelism **3** (P7-D4, P2-T13, then P4-T7 / P5-I11). Deploy freeze from T-2 h.

## Totals and critical path

| Wave | Tasks | Hours | Critical path (h) | Max parallel |
|---|---|---|---|---|
| W0 | 4 (+1 dropped) | 6.75 | 6.75 | 2 |
| W1 | 9 | 23 | 11.5 | 4 |
| W2 | 26 | 72 | 13 | 12 |
| INT-1 | 1 | 2 | 2 | 1 |
| W3 | 11 (+1 stretch) | 23 (+2) | 7 | 9 |
| W4 | 7 | 10 | 7.5 | 3 |
| **Total** | **58 (56 source + INT-1 + INT-2) + 1 stretch + 1 dropped** | **136.75 (+2)** | **47.75** | — |

Critical path end to end: P1-T1 → P7-D0 → P7-D1 → P7-D2 → P1-T2 → P1-T3 → P1-T6 → P6-UI1 → P6-UI4 → P6-UI3 → INT-1 → P2-T11 → P6-UI5 → P2-T13 → P6-UI7 → P6-UI8 → INT-2 = **47.75 h**. (Starting P6-UI1/UI4 in W1 shortens W2's path to 12.5 h via P4-T1 → P2-T6 → P2-T8.)

Coverage self-check (integrator, 2026-10-30): P1 7 tasks (T1, T1D dropped, T2–T6) · P2 13 (T1–T13) · P3 6 (ML1–ML6) · P4 7 (T1–T7) · P5 12 (I1–I11, S1) · P6 8 (UI1–UI8) · P7 5 (D0–D4) = 58 source tasks + INT-1 + INT-2; each appears exactly once. No file is owned twice inside one wave (checked by script over this file). Dependency graph is acyclic (every edge points to an earlier wave or to a same-wave task with no back-edge: W2 chains are P4-T1→P2-T6→P2-T8, P4-T2→{P2-T7, P3-ML4, P5-I6}, P2-T7→{P2-T8, P2-T10}, P3-ML1→{ML3, ML4}, P3-ML2→ML5, P5-I1→{I6, I7}, P5-I2→I5, P5-I3→I8, P6-UI1→UI4→{UI2, UI3}).

---

## Day-1 checklist (HUMAN; from P7-D0/D1, P5-I9 Step 1, P2/P4 Console notes)

1. **GitHub (D0):** create public repo `shoppilot`, push P1-T1 skeleton. Settings → Code security: secret scanning + push protection on. Rules → ruleset on `main`: require checks `test` and `docker`, block force-push and deletion.
2. **Anthropic (D0, card):** Console → Billing: buy smallest credit pack; Spend limits: **org $50/mo** (R47). Create workspace `shoppilot-prod` (limit **$30/mo**) and `shoppilot-dev` (limit **$20/mo**); one key in each (Default workspace cannot hold a limit). Store keys in a password manager; dev key in local `.env` only.
3. **Stripe (D0 + P5-I9 Step 1):** create account, stay in a sandbox named `shoppilot`; create a **restricted key `rk_test_…`, not agent-tagged**, write on PaymentIntents, Refunds, Payment Links, Prices, Products. Password manager only.
4. **Render (D1, OAuth):** sign up with GitHub → New → Blueprint → repo `shoppilot` → paste `ANTHROPIC_API_KEY` (prod key) and `STRIPE_SECRET_KEY` (`rk_test_`) → apply. `curl -fsS https://<service>.onrender.com/healthz` returns the 7-char SHA. Check the 100-minute request limit on Render's docs while there (R16).
5. **Wire CD (D1):** Render → Settings → Deploy Hook → GitHub Actions secret `RENDER_DEPLOY_HOOK_URL`; Actions variable `APP_URL`.
6. **UptimeRobot (D1):** HTTP(s) monitor on `$APP_URL/healthz`, 5 min, email alert.
7. **Verify (D0 Step 5):** `git log -p | grep -E "sk_(test|live)_|rk_(test|live)_|sk-ant-|api.render.com/deploy" | wc -l` → `0`.
8. **Answer or accept defaults** in `00-open-questions.md`, at least Q1 (demo date), Q5 (who funds Anthropic), Q6 (who owns Stripe).

## Consolidated cost (Nov–Dec 2026, prices read 2026-10-30)

Per-turn prices from P2 §9 (Sonnet 5.5 $2/$10, cache read $0.10, write $2.50 per MTok; Haiku 5.5 $0.10/$0.50): complex plan ≈ $0.046–0.058, simple ≈ $0.016, clarify ≈ $0.01–0.015, router reject ≈ $0.0003, grader turn average ≈ $0.023. Volumes from P7 §2, eval resized to 24 cases.

| Line | Best | Expected | Worst (capped) | Free alternative |
|---|---|---|---|---|
| Anthropic: dev plans | $7.50 (300 × $0.025, effort low) | $21 (600 × $0.035) | — | Replay mode, $0 |
| Anthropic: eval/record runs (24 cases ≈ $0.96/run) | $2.90 (3 runs) | $7.70 (8 runs) | — | CI replays, $0 |
| Anthropic: graders | $2.80 (20 × 6 turns) | $13.80 (40 × 15 turns) | — | Replay chips, $0 |
| Anthropic: rehearsal + video | $1.50 (50 turns) | $6.90 (150 complex) | — | Fixture mode, $0 |
| Anthropic: guard (Haiku, cached) | < $0.10 | < $0.10 | — | Heuristic only |
| **Anthropic subtotal** | **$15** | **$50** | **$100** (org cap $50/mo × 2 = account $100 total, R47) | — |
| Render | $0 (Free + ping) | $7 (Starter 1 month) | $14 (Starter 2 months) | Render Free; Heroku/Azure student credit |
| Stripe test mode, GitHub Actions (public), UptimeRobot, OBS/Clipchamp/YouTube, SQLite, outbox | $0 | $0 | $0 | — |
| **Total** | **$15** | **$57** | **$114** | — |

Reconciliation: P2's "$25–40" is **per month** during the build and grading month (≈ $21 build + $14 for 100 grader sessions); P7's "$47" is the two-month total at a flat $0.025/turn and its own table lists Anthropic at $40. Using P2's measured-shape prices with P7's volumes gives **$50 Anthropic + $7 Render = $57 expected**. The ceiling is set by Console caps, not the estimate: org $50/mo, prod workspace $30/mo, dev workspace $20/mo (R47). P2-T13 (W4) replaces these numbers with measured ones.
