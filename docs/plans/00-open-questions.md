# ShopPilot+ — open questions for the team (deduped, 2026-10-30)

Every unresolved user decision from specs/plans 01–07 and the integrator. Each has a **default** already baked into `00-master-waves.md` and `../specs/00-contract-resolutions.md`, so no task waits on an answer. Change a default by editing this file and telling the integrator; rows marked **blocking-by** need an answer before that task runs.

| # | Question | Default assumed | Blocking-by | Raised by |
|---|---|---|---|---|
| Q1 | Demo date, and when to move Render Free → Starter ($7/mo, 0.5 CPU, no sleep)? | Starter at T-3 days. If no date by 2026-11-24, switch on 2026-12-01 and keep until grading closes; downgrade after. | P7-D4 | P7, P1 Q1 |
| Q2 | Public GitHub repo? | Yes (free Actions minutes, free secret scanning). | P7-D0 | P1 Q2, P7 |
| Q3 | OK that grader stores vanish on deploy/restart/sleep and reseed with a "store reset" banner? | Yes. | — | P1 Q3, P7 §6 |
| Q4 | Session idle TTL 24 h and cap of 100 stores? | Yes (~2 MB per store with the 2,700-order seed → ≤ 200 MB in `/tmp`). | — | P1 Q4 |
| Q5 | Who funds Anthropic, and the Console caps? | Team lead's card; smallest credit pack; org $40/mo, `shoppilot-prod` $20/mo, `shoppilot-dev` $20/mo (R7). Expected spend $50 over 2 months. | P7-D0 | P2 §6.2, P4 §7, P7 §3 |
| Q6 | Who creates and owns the Stripe account and restricted key? | Repo owner, on day 1; `rk_test_` restricted key, not agent-tagged (R15). | P7-D0, P5-I9 | P5 I9, P7 D0 |
| Q7 | Planner effort `low` or `medium`? | `medium` until the P2-T13 sweep; switch to `low` only if it keeps ≥ 22/24 eval and the injection set green. | — | P2 §3 |
| Q8 | 10–30 s spinner or token streaming for `/api/plan`? | Spinner with stage counter + "Use recorded plan" at 12 s; no SSE (R16). | — | P2 C10, P6 §11 |
| Q9 | Recorded replay or a second (free) LLM provider as fallback? | Replay only; no second SDK (R8). Gemini/Groq listed in P2 §11 as a manual escape hatch. | — | P2 §11, P6 C6 |
| Q10 | Keep the server-side refusal fallback beta (`server-side-fallback-2026-07-01`) on the planner? | On if P2-T4 live smoke passes with strict tools + `output_config`; otherwise drop it. `stop_reason: refusal` is handled either way. | — | P2 §3 |
| Q11 | Let graders submit their own attack email (`POST /api/inbox`)? | Not built (new endpoint, new abuse surface). Graders attack through the request box; the README says so. Stretch only after W3. | — | orchestrator |
| Q12 | Separate store/orders tab in the UI? | No tab. Header shows store name; orders appear in plan rows and exports. Add in W3 only if UI-6 has spare time. | — | orchestrator |
| Q13 | Should `send_email` need explicit approval (at least for `custom` template)? | No: `destructive=False`, pre-ticked; outbox is fake and recall is the undo; custom body shown in the diff (R43). | — | P4 #7, orchestrator |
| Q14 | Build stretch S1 (read-only Stripe MCP lookup)? | Skip unless P5-I10 is green with ≥ 2 spare days. Stripe stops accepting non-agent keys on MCP after 2026-11-30, so it needs a separate read-only agent key. | P5-S1 | P5 §2 |
| Q15 | Add a `hold_order` action for flagged anomalies? | No. `flag_anomalies` reports only (P3 scope); `on_hold` status stays in the schema for later. | — | P3 §1, orchestrator |
| Q16 | Keep-warm ping on Render Free (fair-use concern)? | Yes, UptimeRobot every 5 min on `/healthz` (one free service fits 750 h). Stop pinging if Render support objects. | P7-D1 | P1 Q5 vs P7 §4 |
| Q17 | Raise `LLM_DAILY_BUDGET_USD` from $5 to $10 during grading week? Who flips it? | Yes; the presenter sets the Render env var at T-3 days with the Starter switch. | P7-D4 | P2 §6.2 |
| Q18 | Sentry for errors? | No; Render logs. Add `SENTRY_DSN` only if W3 errors can't be read from logs. | — | P7 §5 |
| Q19 | Custom domain? | No; `*.onrender.com`. | — | P7 §2 |
| Q20 | Apply for Anthropic student/startup credits? | Apply if a program exists; plan assumes none. | — | P2 §11 |
| Q21 | Who records and narrates the demo video and runs the live demo? Phone shot real or emulated? | Presenter = team lead; phone shot via DevTools at 390 px, labelled "Phone (emulated)". | P6-UI7 | P6 §13 |
| Q22 | Team names and roles for the end card and README? | Placeholder `<team>` until filled; INT-2 blocks on it. | INT-2 | P6 §13 |
| Q23 | Fallback host if Render fails in W0? | Railway Hobby (~$5–7/mo), same Dockerfile, `smoke.sh` unchanged (P7 plan). Cloud Run rejected (~$45/mo always-on). | — | P1 Q1, P7 §1 |
| Q24 | Should owner-typed requests be guard-screened too? | No: the owner is the principal; `policy` caps apply to owner requests (P4 §4.5). | — | P4 |

**Count: 24 open questions, all with defaults; 9 are blocking-by a specific task (Q1, Q2, Q5, Q6, Q14, Q16, Q17, Q21, Q22).**

Next action: answer Q1, Q5 and Q6 before running P7-D0.

## User answers (2026-10-30)

| Q | Answer | Effect |
|---|---|---|
| Q1 | **Demo 2026-11-05.** Deployment, tests, integration, report, video, website and links all done before it. | Starter switch 2026-11-02 (T-3). Deploy freeze 2026-11-05 T-2 h. Schedule: 10-30 W0–W1, 10-31 W2, 11-01 INT-1 + W3, 11-02 W4 deploy + Starter, 11-03 video + report, 11-04 buffer. |
| Q5 | Anthropic key with a **$100 hard cap** for this project. Groq/other providers asked about. | Anthropic only in the core build: expected $50, worst $80, both under $100. Record/replay is the outage fallback (R8). A second provider (Groq) stays a W3 stretch, only if the team asks. |
| Q6 | **User creates the Stripe account** (restricted `rk_test_` key). | P7-D0 Stripe step owner = user. |
| Exec | **Subagent-driven, Opus-led teams in dynamic workflows.** | One team per planner area: Sonnet implements, Opus reviews each task before dependants start. |
