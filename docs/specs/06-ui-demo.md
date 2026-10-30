# 06 UI, demo and video (spec)

Planner P6, 2026-10-30. Scope: `app/static/index.html`, `app/static/app.js`, `app/static/styles.css`, `app/static/fixtures/*.json`, the live demo script and the 1–2 min video. Reads `00-shared-brief.md` (frozen). Plan: `../plans/06-ui-demo-plan.md`.

## 0. Decisions in one table

| # | Decision | Why |
|---|---|---|
| 1 | One page, Operate mode. Problem strip on top, task column left, rail (Inbox / Outbox / Audit) right. Phone: one column, sticky run bar. | Grader does the whole task without navigating. ui-unified: Operate surface, the tool disappears into the task. |
| 2 | No SSE. "Execution stream" = one `POST /api/execute` per approved step, in order, each row updates as its call returns. | Real per-step status with zero new endpoints, no proxy buffering, no 60 s idle cut (Fly), works on every host (§11). |
| 3 | Fixture mode: `?fixtures=<scenario>` swaps `fetch('/api/...')` for `fixtures/*.json`. Same files drive W2 dev, the smoke tests and the offline demo fallback. | UI ships in W2 without the backend; one mechanism, three uses. |
| 4 | `<template>` + `textContent` for every rendered record. No `innerHTML` with data, ever. | Inbox bodies are hostile on purpose (the injection email). XSS floor. |
| 5 | Inherit The Tank's paper/ink palette and stamps (root `DESIGN.md`), drop its Courier-everywhere and condensed display face. System font stack, mono only for IDs and JSON args. | Contrast already verified (§7), no font download, BLOCKED stamp makes the injection obvious. ui-unified conflict 8 (mono only for IDs). |

## 1. Surface and world

- Mode: **Operate** (app). The problem strip is a short header for the same view, not a Persuade hero: no motion theatre, no marketing.
- World: inherited from root `DESIGN.md` ("The Docket"): ruled paper, near-black ink, one green, one red, one brass. Red means blocked or failed only. Green means valid, done, allowed. Brass-ink means warning, mock, replay, money.
- Libraries: none. No chart lib (the forecast chart is about 40 lines of SVG). No icon font: 8 inline SVG icons, 1.5 px stroke, one family (check, cross, clock, undo, mail, shield, refresh, alert).
- Theme: light only (ui-unified conflict 6: one theme fully designed).

## 2. Layout

### Desktop (>= 1024 px; designed at 1440)

```
+----------------------------------------------------------------------------------------------+
| [Skip to request]  ShopPilot+  · Fernhill Candle Co. (demo store)     Stripe TEST  |  $0.014 · 6.2k tok · cache 81%  [Reset demo store] |
+----------------------------------------------------------------------------------------------+
| MOCK MODE: plans are canned, not from Claude. Tools, guard and audit still run.   (only if mock) |
+----------------------------------------------------------------------------------------------+
| h1 Run the Sunday-night shop cleanup in one sentence.            | > Graders: try it in 60 seconds |
| Sub: plans the work, shows every change and dollar, waits for    |   (details, open on first visit) |
|      your OK before money moves.                                 |   1..5 steps, reset note        |
| "I'm spending 4 or 5 hours every single day just on packing      |                                 |
|  and shipping"  r/ecommerce, 2025 (small sample)                 |                                 |
+--------------------------------------------------+-------------------------------------------+
| TASK COLUMN (minmax(0, 2fr))                     | RAIL (minmax(320px, 1fr)), sticky top     |
|                                                  | [Inbox  1 blocked] [Outbox 0] [Audit 0]   |
| Ask ShopPilot+ ________________________________  | ----------------------------------------- |
| | Ship yesterday's orders, email buyers ...    | | | BLOCKED  "URGENT from support"           |
| |______________________________________________| | |  Tries to make the agent ignore rules    |
| [Plan it]   Ctrl+Enter                           | |  and refund every order. Never sent to   |
| Try: (Sunday cleanup) (Stockout check) (WISMO)   | |  the planner.          score 0.98        |
|                                                  | | ALLOWED  "Box arrived crushed" #1038     |
| PLAN  5 steps · 1 needs your approval   replay?  | | ALLOWED  "Where is my order?" #1041      |
| ! 1 inbox email was blocked from this plan. See it|                                          |
| ------------------------------------------------ |                                           |
| 1 mark_shipped                    [v] Valid      |                                           |
|   orders 1041, 1042, 1043 · USPS                 |                                           |
|   Why: paid yesterday, not shipped               |                                           |
|   Change: status paid -> shipped (3 orders)      |                                           |
|   [x] Run this step                              |                                           |
| 2 send_email (3 buyers, tracking)  [v] Valid     |                                           |
| 3 forecast_demand  P-07 Lavender tin [v] Valid   |                                           |
|   +-------------------------------------------+  |                                           |
|   | band p10-p90, p50 line, on-hand dashed,   |  |                                           |
|   | marker "runs out ~day 4 (3 to 6)"         |  |                                           |
|   +-------------------------------------------+  |                                           |
| 4 create_restock_po  48 units · est $312.00 [v]  |                                           |
| 5 refund_order  #1038  $24.00   [v] Valid        |                                           |
|   Money out: $24.00 to Dana R. (Stripe test)     |                                           |
|   [ ] Approve refund of $24.00 on order 1038     |                                           |
| ------------------------------------------------ |                                           |
| Money out if you run: $24.00      [Run approved steps] |                                    |
|                                                  |                                           |
| RUN LOG (aria-live)                              |                                           |
|  v 1 mark_shipped   3 orders marked shipped      |                                           |
|  v 2 send_email     3 emails in Outbox           |                                           |
|  o 5 refund_order   Running...                   |                                           |
+--------------------------------------------------+-------------------------------------------+
```

### Phone (390 px; works down to 320)

```
+--------------------------------+
| ShopPilot+   TEST  [$0.01 v]   |  cost chip is a <details>; opens tokens + cache %
| [Reset]                        |
| MOCK MODE banner (if mock)     |
+--------------------------------+
| h1 Run the Sunday-night shop   |
|    cleanup in one sentence.    |
| sub (1 line)                   |
| > Why this exists (quote)      |  details, closed
| > Graders: try it in 60 s      |  details, open first visit
+--------------------------------+
| Ask ShopPilot+                 |
| [ textarea, 16px font       ]  |
| [Plan it]                      |
| (Sunday cleanup) (Stockout)    |  chips wrap, never scroll sideways
| (WISMO)                        |
+--------------------------------+
| PLAN 5 steps                   |
| ! 1 email blocked. See it      |
| 1 mark_shipped   [v] Valid     |
|   > Arguments (details)        |
|   Why ...                      |
|   [x] Run this step            |
| ...                            |
| 3 forecast chart full width    |
| 5 refund_order $24.00          |
|   [ ] Approve refund ...       |
+--------------------------------+
| RUN LOG                        |
+--------------------------------+
| [Inbox 1] [Outbox] [Audit]     |  same tablist, below the task
| panel                          |
+--------------------------------+
| Money out $24.00 [Run approved steps] |  sticky bottom, safe-area inset, only when a plan is ready
+--------------------------------+
```

Breakpoints: one at 1024 px (two columns to one). Rail goes under the run log. No horizontal page scroll from 320 to 1920 px; long IDs wrap with `overflow-wrap: anywhere`.

## 3. Components mapped to the API

| Region | DOM id | API | Notes |
|---|---|---|---|
| Header store name, Stripe TEST tag | `#store-name`, `#stripe-tag` | `POST /api/session` on first load (no cookie) or `GET /api/store` | `stripe_mode` always "test"; tag is text, not a dot. |
| Mock banner | `#mode-banner` | `POST /api/session` → `llm_mode` | Also shown for `source:"replay"` plans and for fixture mode (different copy, §5). |
| Cost + cache meter | `#cost-meter` | `usage` on every `POST /api/plan` response | Session sum kept in `sessionStorage` (per-viewer convenience, OK to lose). Cache % = cache_read / (input + cache_read + cache_creation). |
| Reset demo store | `#reset-btn` | `POST /api/session` | Native `confirm()` is not used; a 2-step inline button: "Reset demo store" → "Click again to wipe your store" for 4 s. Then refetch all. |
| Problem strip + quick start | `#problem`, `#quickstart` | none (static) | Quick start `<details>` open unless `localStorage.qsSeen`. |
| Request box | `#request-form`, `#request-input`, `#plan-btn` | `POST /api/plan {request}` | `maxlength=500`, required, trimmed. Ctrl/Cmd+Enter submits. Disabled while a plan is loading. |
| Suggested prompts | `#suggestions button[data-prompt]` | fills `#request-input`, then submits | 3 buttons, §5. |
| Clarifying question | `#clarify` (form) | `POST /api/plan {request: original + "\n\nAnswer: " + answer}` | Option buttons + free text. No new endpoint. |
| Plan card | `#plan`, `#plan-heading`, `#steps` | `/api/plan` response: `plan.steps`, `validations`, `diff`, `tools` | `#plan[data-state]` = empty, loading, ready, clarify, error. Heading has `tabindex=-1`, gets focus when ready. |
| Blocked-input notice | `#plan-blocked` | `plan.blocked_inputs` | "See it" switches rail to Inbox and focuses that email. |
| Step row | `<template id="tpl-step">` | Step + Validation + DiffItem + tools[step.tool] | Tool name, args (`<details>`, mono JSON), tick/cross + reason, rationale, before/after, `amount_cents` as money, approve checkbox. |
| Forecast mini-chart | inside step where `tool == "forecast_demand"` | `diff[].after.{on_hand, days_to_stockout, band}` | Inline SVG, §6. |
| Run bar | `#run-bar`, `#run-btn`, `#money-out` | `POST /api/execute {plan_id, approved_step_ids:[id]}` once per step | Sum of `amount_cents` over approved money steps. |
| Run log | `#stream` (`<ol aria-live="polite">`) | each execute response | Rows: pending, running, done, failed, skipped, not run. Stops on first failure. |
| Inbox | `#tab-inbox`, `#inbox-list` | `GET /api/inbox` | Stamp BLOCKED (red) / ALLOWED (green) from `verdict.allowed`; label + reason + score. Body collapsed, rendered as text. |
| Outbox | `#tab-outbox`, `#outbox-list` | `GET /api/outbox` | "Never sent. Emails stay in this app." line at top. |
| Audit log | `#tab-audit`, `#audit-list` | `GET /api/audit`, `POST /api/undo/{audit_id}` | Undo button only when `undoable && !undone_at`. After undo: row shows "Undone 14:02"; refetch store, outbox. |
| Export | links in Audit panel | `GET /api/export/audit?fmt=csv` | Plain `<a download>`. Kind names owned by the integrations planner. |
| Global error | `#error` (`role="alert"`) | any | Only for errors not tied to a region. |

After every successful execute or undo: refetch `GET /api/audit`, `GET /api/outbox`, `GET /api/store` in parallel. No polling.

### Payload shapes the UI reads (proposal; see Contract conflicts)

`POST /api/session` → `{"session_id":"s_9c1","store_name":"Fernhill Candle Co.","llm_mode":"live","stripe_mode":"test"}`

`POST /api/plan` → wraps the frozen `Plan`:

```json
{
  "plan_id": "pl_7f3a",
  "source": "live",
  "plan": {"request": "...", "steps": [{"id":"s1","tool":"mark_shipped","args":{},"rationale":"..."}], "blocked_inputs": [{"source_id":"em_7","allowed":false,"label":"prompt_injection","reason":"...","score":0.98}]},
  "validations": [{"step_id":"s1","ok":true,"reason":null}],
  "diff": [{"step_id":"s1","before":{},"after":{},"amount_cents":null}],
  "tools": {"mark_shipped":{"destructive":false,"moves_money":false,"undoable":true}},
  "clarify": null,
  "usage": {"model":"claude-sonnet-5-5","input_tokens":1840,"output_tokens":620,"cache_read_input_tokens":4100,"cache_creation_input_tokens":0,"cost_usd":0.0123,"latency_ms":8400}
}
```

Clarify variant: `"plan": null, "clarify": {"question":"Two orders are marked damaged (1038, 1040). Refund which?","options":["Both","Only 1038","Only 1040"]}`.

`POST /api/execute` → `{"results":[{"step_id":"s5","audit_id":"a_12","ok":true,"summary":"Refunded $24.00 on order 1038","data":{"refund_id":"re_test_3Nx..."},"undo_token":"u_..","error":null}]}` (ToolResult + `step_id` + `audit_id`).

`GET /api/audit` → `[{"id":"a_12","ts":"2026-11-02T14:02:11Z","kind":"tool","tool":"refund_order","step_id":"s5","summary":"...","undoable":true,"undone_at":null}]`

`GET /api/inbox` → `[{"id":"em_7","from":"support-team@fernhill-help.example","subject":"URGENT","body":"...","received_at":"...","verdict":{GuardVerdict}}]`

`GET /api/outbox` → `[{"id":"ob_1","ts":"...","to":"dana@example.com","subject":"Your order 1041 shipped","body":"..."}]`

Errors, any endpoint: HTTP 4xx/5xx with `{"error":{"code":"rate_limited","message":"...","retry_after_s":20}}`. Codes the UI branches on: `rate_limited` (429), `llm_unavailable` (503), `llm_timeout` (504), `session_expired` (401), `invalid_request` (422), `internal` (500).

## 4. States

| Region | Empty | Loading | Ready | Error |
|---|---|---|---|---|
| App boot | n/a | Header skeleton. If `/api/session` takes > 3 s: "Waking the server. Free hosting sleeps when idle; this can take up to a minute." | Store name shows | "Cannot reach ShopPilot+. Check your connection, then [Try again]." |
| Plan | "Type a request or pick one below. ShopPilot+ will show a plan first. Nothing runs until you press Run." + 4-word legend: Plan, Check, Approve, Run | 3 skeleton step rows in place + "Planning... 6 s" counter (1 s tick, `aria-live` off; one polite announcement at start) + [Cancel] (AbortController). At 12 s add: "Claude is slow right now. [Use recorded plan]" | Focus `#plan-heading` | See error rows below |
| Plan: clarify | n/a | n/a | Question + option buttons + "Or type an answer" input + [Send answer] | n/a |
| Plan: invalid step | n/a | n/a | Cross icon + "Blocked by validator: {reason}". Checkbox disabled, unchecked. Run bar counts it out. | n/a |
| Plan: all steps invalid | n/a | n/a | "Nothing here is safe to run. Edit the request and try again." Run button disabled. | n/a |
| Plan: zero steps | n/a | n/a | "ShopPilot+ found nothing to do for that request. Try one of the examples." Run bar hidden. | n/a |
| Run log | hidden until first run | Row "Running..." with live icon (static under reduced motion) | Row tick + summary + mono ID (e.g. refund id) | Row cross + error text + [Retry from here]. Later rows "Not run: stopped after step 2 failed." |
| Inbox | "No customer emails yet." | 3 skeleton rows | List | "Inbox did not load. [Retry]" |
| Outbox | "Nothing sent yet. Emails the agent writes land here, never in a real inbox." | skeleton | List, newest first | inline retry |
| Audit | "No actions yet. Every action you approve is logged here with an undo button." | skeleton | List, newest first | inline retry |
| Undo | n/a | Button "Undoing..." disabled | "Undone at 14:02" | Inline: "Could not undo: {message}." Button re-enabled. |

Error copy by code (shown inline in the plan region):

| Code | Copy | Action |
|---|---|---|
| `rate_limited` | "Too many requests. You can plan again in {n} s." (countdown; submit disabled) | [Use recorded plan] |
| `llm_unavailable` / `llm_timeout` | "Claude did not answer. Your store is unchanged." | [Try again] [Use recorded plan] |
| `session_expired` | auto: `POST /api/session` once, then retry. Toast-free line: "Your demo store expired, so you have a fresh one." | none |
| `invalid_request` | server `message` (e.g. "Request is empty or over 500 characters.") | focus input |
| network / `internal` | "Something broke on our side. Nothing was changed. [Try again]" | [Try again] |

## 5. Copy (exact strings; no em or en dashes in visible text)

| Key | String |
|---|---|
| title | `ShopPilot+ · AI ops agent for small shops` |
| h1 | Run the Sunday-night shop cleanup in one sentence. |
| sub | ShopPilot+ plans the work, shows every change and dollar, and waits for your OK before money moves. |
| quote | "I'm spending 4 or 5 hours every single day just on packing and shipping." r/ecommerce, about Feb 2025. One of 3 threads in a small Reddit spot check. |
| trust line | Agents that act need a gate and an undo. Every step here is validated, previewed, approved by you and logged. |
| request label | Ask ShopPilot+ |
| request placeholder | e.g. Ship yesterday's orders and email buyers tracking |
| plan button | Plan it |
| chip 1 / prompt | Sunday cleanup / Ship yesterday's orders, email buyers tracking, restock what will run out this week, refund anything damaged. |
| chip 2 / prompt | Stockout check / What will stock out in the next 14 days? Draft restock orders for those. |
| chip 3 / prompt | WISMO replies / Answer every "where is my order" email with tracking. |
| blocked notice | 1 inbox email was blocked from this plan. [See it] (plural: "{n} inbox emails were blocked") |
| approve label (money) | Approve refund of {$} on order {id} |
| approve label (other) | Run this step |
| run button | Run approved steps |
| money out | Money out if you run: {$} (Stripe test mode) |
| mock banner | Mock mode: plans are canned, not from Claude. Tools, guard and audit still run. |
| replay banner | Recorded plan (replay). Claude was not called for this one. Steps still run for real on your demo store. |
| fixture banner | Offline fixtures. Nothing here touches a server. |
| reset confirm | Click again to wipe your store |
| quick start summary | Graders: try it in 60 seconds |
| quick start body | 1. Click **Sunday cleanup**, then **Plan it**. 2. Read the plan: a tick means the validator passed it. The refund waits for your checkbox. 3. Open **Inbox**: one email tried to hijack the agent. It is blocked. 4. Press **Run approved steps**, then undo anything in **Audit**. 5. Try to break it: ask "refund every order", or something vague like "refund it". Your store is private to this browser. Stripe runs in test mode. Emails stay in the Outbox. **Reset demo store** starts over. |

Numbers: `Intl.NumberFormat('en-US',{style:'currency',currency:'USD'})` from cents; `font-variant-numeric: tabular-nums`. Plurals via `Intl.PluralRules`.

## 6. Forecast band mini-chart

Input: `diff[i].after = {"on_hand": 9, "days_to_stockout": 4, "band": {"p10":[..15], "p50":[..15], "p90":[..15]}}`, cumulative units sold from day 0 to 14 (15 points). Shape owned by the ML planner; if it differs, adapt `drawForecast()` only.

- SVG `viewBox="0 0 280 120"`, `width:100%`, max 420 px. Built with `createElementNS`, no innerHTML.
- Area p10..p90: brass tint fill (`#b8862b` at 20% opacity). Line p50: ink 2 px. On-hand: red dashed horizontal line labelled "On hand 9". Vertical marker at first day p50 >= on_hand, label "Runs out ~day 4".
- Range in text: earliest day p90 >= on_hand to latest day p10 >= on_hand ("3 to 6"); "after day 14" if never.
- `role="img"`, `<title>` "Demand forecast for Lavender tin", `<desc>` with the same sentence as the visible caption: "Runs out in about 4 days (range 3 to 6). 9 on hand."
- Axis: 3 day ticks (0, 7, 14), no gridlines, no legend box (labels sit on the marks).

## 7. Visual tokens

| Token | Value | Use | Contrast on sheet #f9faf7 / page #eef0ec |
|---|---|---|---|
| `--page` | #eef0ec | body bg | n/a |
| `--sheet` | #f9faf7 | panels, inputs | n/a |
| `--ink` | #16181d | text, primary button fill, focus ring | 16.95 / 15.48 |
| `--ink-2` | #474c54 | secondary text | 8.25 / 7.54 |
| `--ink-3` | #5c6168 | hints, input borders (control boundary) | 5.96 / 5.44 |
| `--ok` | #1f7a3a | valid, done, ALLOWED | 5.14 / 4.69 |
| `--bad` | #b3261e | BLOCKED, failed, stockout line | 6.24 / 5.70 |
| `--warn` | #7a5a12 | mock/replay banner text, money | 6.08 / 5.55 |
| `--rule` | #c7ccc4 | dividers only (decorative, not a control edge) | 1.56, exempt |

Sheet text on ink button: 17.8:1. Type: `system-ui, -apple-system, "Segoe UI", Roboto, sans-serif`; mono `ui-monospace, "Cascadia Mono", Menlo, monospace` only for IDs, args JSON, refund ids. Scale (rem): 0.8125, 0.875, 1, 1.125, 1.375, 1.75 (h1 at 1.75 desktop, 1.375 phone). Radius: 4 px stamps, 6 px buttons/inputs, 8 px panels. Elevation: 1 px border, no shadows except the sticky phone run bar.

Stamps: BLOCKED = red text, 2 px red border, uppercase 700, `rotate(-2deg)` (static, not animated). ALLOWED = green, 1 px border, no rotation (quieter on purpose so BLOCKED pops).

## 8. Motion

- Plan ready: step rows fade in, opacity only, 150 ms, 40 ms stagger, capped at 300 ms total. Easing `cubic-bezier(.23,1,.32,1)`.
- Run log row status change: colour crossfade 150 ms.
- Running step: the clock icon rotates (a real live indicator, the only loop).
- Buttons: `:active { transform: scale(.97) }` 120 ms.
- `@media (prefers-reduced-motion: reduce)`: all transitions 0 ms, no rotation, "Running..." text carries state.
- Hover styles only inside `@media (hover:hover) and (pointer:fine)`.

## 9. Accessibility (never cut)

1. Landmarks: `header`, `main` (task column), `aside` (rail), skip link "Skip to request" first in tab order. One `h1`. `lang="en"`.
2. Every input has a visible `<label>` above it. Textarea font 16 px.
3. Focus ring: `:focus-visible { outline: 2px solid var(--ink); outline-offset: 2px }` on everything, including SVG-free buttons and summary elements.
4. Keyboard path: Tab → skip link → request → Plan it → chips → (plan) heading receives focus → each step's Arguments details → approve checkbox → Run → rail tabs (arrow keys inside tablist, roving tabindex) → Undo buttons. Ctrl/Cmd+Enter submits only from inside the textarea.
5. Live regions: `#plan-status` polite (one message per state change: "Planning", "Plan ready: 5 steps, 1 needs approval", "Blocked 1 email"); `#stream` polite, each row appended once; `#error` `role="alert"`.
6. Status never by colour alone: tick/cross icon + word ("Valid", "Blocked by validator", "BLOCKED", "Done", "Failed").
7. Targets: 44 x 44 hit area on touch (`@media (pointer:coarse)`), 24 px minimum with a fine pointer, 8 px gaps.
8. Contrast table §7; all text >= 4.5:1, control edges use `--ink-3` (5.4:1).
9. 200% zoom and 320 px: no horizontal scroll; the run button stays reachable (sticky bar).
10. `prefers-reduced-motion` honoured (§8).

Mobile baseline: `<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">`, `theme-color #eef0ec`, `padding-bottom: env(safe-area-inset-bottom)` on the run bar, `touch-action: manipulation` on buttons, `min-height: 100dvh` on body.

## 10. Security in the UI

- All server data rendered with `textContent` or attributes set via `setAttribute` on known names. No `innerHTML`, no `eval`, no inline handlers.
- Inbox bodies are shown collapsed with a "Show email" `<details>`; links inside are plain text (not clickable).
- Request: `maxlength=500`, trimmed, empty blocked client-side (server validates again).
- Recommended CSP from FastAPI (owned by `main.py`): `default-src 'self'; script-src 'self'; style-src 'self'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'`. Inline SVG via DOM APIs is CSP-safe.

## 11. Streaming decision (research, 2026-10-30)

| Host | SSE status | Limit that bites | Source | Page date |
|---|---|---|---|---|
| Render free | no official SSE doc; spins down after 15 min idle, wake "about one minute" | cold start mid-demo | https://render.com/docs/free | accessed 2026-10-30 |
| Fly.io | works, proxy closes idle connections at 60 s; no free tier for new orgs | 60 s idle | https://community.fly.io/t/request-timeouts-on-fly-io/5653 ; https://docs.fly.io/about/pricing | thread undated; pricing accessed 2026-10-30 |
| Railway | not documented; free plan $1/mo credit | unknown | https://docs.railway.com/reference/pricing/plans | accessed 2026-10-30 |
| Cloud Run | EventSource works; stream counts toward request timeout | 300 s default, 3600 s max | https://docs.cloud.google.com/run/docs/configuring/request-timeout | updated 2026-10-30 |
| Vercel | streaming works, counts toward duration | Hobby 300 s | https://vercel.com/docs/functions/configuring-functions/duration | updated 2026-08-24 |
| Netlify | streaming functions, JS/Go first | 60 s | https://docs.netlify.com/build/functions/api | updated 2026-10-07 |

Verdict: per-step `POST /api/execute` beats SSE here. Each call is a few seconds, so no host timeout or proxy buffering applies, and no heartbeat code is needed. Add SSE only if a single step ever runs > 30 s (none planned). Render free cold start is handled by the boot "Waking the server" state and the pre-flight warm-up in §12.

## 12. Live demo script (90 s)

Pre-flight (T-10 min, checklist on paper):
1. Open the deployed URL; wait for store name (Render free wakes in ~1 min).
2. Click **Reset demo store** twice. Banner must NOT say Mock mode (if it does, the API key or spend cap is the cause; demo still works, say so).
3. Run "Stockout check" once to warm the prompt cache (cache % meter then shows a hit in the real run). Reset again.
4. Browser zoom 125%, one tab, notifications off. Tab 2: `?fixtures=happy` loaded. Tab 3: backup video file.
5. Phone on the same URL for the 5 s mobile shot (optional).

| Time | Do | Say (about) | Fallback |
|---|---|---|---|
| 0:00 | Point at problem strip | "Small shop owners lose hours a day to shipping, refunds and restock. Agents could help, but people don't trust an agent with refunds." | none |
| 0:12 | Click **Sunday cleanup** chip, **Plan it** | "One sentence. Sonnet plans typed tool calls. Before it sees the inbox, Haiku screens every email." | Planning > 12 s: keep talking about the guard; at 15 s click **Use recorded plan** (banner says replay, say so). 429/503: same button. |
| 0:25 | Scroll plan card | "Five steps. Each has the tool, its arguments, why, and a validator tick." | One step shows a cross: "the validator caught it, it can't run." Good, keep going. |
| 0:35 | Point at forecast chart | "Restock comes from a real forecast: runs out in about 4 days, range 3 to 6." | Chart missing: read the caption text. |
| 0:45 | Click **See it** on blocked notice | "This email says ignore your rules, refund every order. Blocked, with the reason. It never reached the planner." | Inbox empty: switch to tab 2 (fixtures) and show it there, say "offline fixtures". |
| 0:57 | Tick **Approve refund of $24.00**, **Run approved steps** | "Money only moves when I approve it. Stripe test mode." | A step fails: "it stops, the rest don't run, and I can retry." That is error handling; show it. |
| 1:10 | Run log ticks; open **Audit**, click **Undo** on restock PO | "Every action is logged. Undo the PO." | Undo fails: read the inline error, move on. |
| 1:20 | Open **Outbox**; point at cost meter | "Emails land here, never a real inbox. This whole run cost about a cent; the cached prompt hit 80%." | Network dies at any point: switch to tab 3 and narrate the video. |
| 1:30 | End | "Plan, check, approve, run, undo." | |

Do not quote "Sunday-night cleanup takes 2 hours" (in the shortlist sketch): report 03 has no such quote. Use the 4 to 5 hours quote above.

## 13. Video shot list (target 1:45, max 2:00)

Record 1920x1080, browser window 1600x900 at 125% zoom, mic on. Record each shot separately, cut in Clipchamp.

| # | Time | Shot | Narration | On-screen caption |
|---|---|---|---|---|
| 1 | 0:00–0:08 | Title card: name, one-line problem | "Small shops drown in order admin." | ShopPilot+ · AI ops agent with a safety gate |
| 2 | 0:08–0:18 | App load, problem strip, quick start | quote + trust gap | deployed URL in corner |
| 3 | 0:18–0:30 | Click Sunday cleanup, Plan it | how planning works | "Planning took {n} s, trimmed" if cut (honest) |
| 4 | 0:30–0:50 | Plan card, slow scroll; zoom crop on validator ticks and forecast chart | tools, args, validator, forecast | "Claude Sonnet plans · Haiku guards" |
| 5 | 0:50–1:02 | See it → BLOCKED email | prompt injection blocked | "Prompt injection: blocked" |
| 6 | 1:02–1:18 | Approve refund, Run, run log | confirm gate, Stripe test refund id | "Stripe test mode" |
| 7 | 1:18–1:32 | Audit undo, Outbox | audit + undo, fake outbox | none |
| 8 | 1:32–1:40 | Phone view (real phone or DevTools 390 px, labelled) + clarify question from "refund it" | works on phone, asks when unsure | "Phone (emulated)" if emulated |
| 9 | 1:40–1:45 | End card: URL, repo, team names | "Try it at..." | URL + GitHub |

Upload: YouTube, Visibility **Unlisted**, Audience **No, it's not made for kids** (field is required). Under 15 min so no phone verification needed.

## 14. Free vs paid tools

| Job | Pick (free) | Paid option | Monthly $ | Notes | Source (accessed 2026-10-30) |
|---|---|---|---|---|---|
| Record | OBS Studio | Screen Studio (macOS only) | $9/mo yearly, $29 monthly | OBS: no time limit or watermark stated | https://obsproject.com/ ; https://screen.studio/ |
| Quick record | Snipping Tool (Win+Shift+R) | Loom Business | n/a | Snipping Tool audio support conflicts across sources: test 10 s first. Loom Starter: 5 min/video, 25 videos | https://pureinfotech.com/snipping-tool-screen-recording-windows-11/ (2022-12-09) ; https://www.loom.com/pricing |
| Edit + captions | Clipchamp (preinstalled Win 11) | Clipchamp Premium | n/a | Free 1080p export without watermark (third-party confirmation, re-check on export) | https://clipchamp.com/en/pricing/ ; https://support.microsoft.com/en-za/help/17205 |
| Host video | YouTube Unlisted | none | $0 | Anyone with link can watch; made-for-kids answer required | https://support.google.com/youtube/answer/157177 ; https://support.google.com/youtube/answer/9528076 ; https://support.google.com/youtube/answer/71673 |
| Xbox Game Bar | skip | n/a | n/a | Cannot capture desktop or File Explorer; fine for one browser window only | https://support.microsoft.com/en-US/Accessibility/windows/use-a-screen-reader-to-record-your-screen-with-xbox-game-bar |

Pick: OBS → Clipchamp → YouTube Unlisted. Total $0.

## 15. Fixture files (`app/static/fixtures/`)

| File | Content |
|---|---|
| `session.json` | session shape §3, `llm_mode:"live"` |
| `store.json` | 6 products (P-07 Lavender tin on_hand 9), 12 orders (1038 damaged, 1041–1043 paid yesterday), 8 customers. Names obviously fake ("Dana R.", `@example.com`) |
| `inbox.json` | 4 emails: em_7 injection (allowed false, label `prompt_injection`, score 0.98, body includes `<img src=x onerror=alert(1)>` to prove text rendering, subject is "URGENT" plus a 300-char unbroken run to prove wrapping), em_3 damaged box #1038, em_4 WISMO #1041, em_5 thank-you |
| `plan.json` | happy path, 5 steps s1..s5 exactly as §2 wireframe, `blocked_inputs:[em_7 verdict]`, all valid, refund `amount_cents:2400`, forecast band 15 points, `usage` filled |
| `plan-invalid.json` | same, plus s6 `refund_order` order 1012 invalid: "Order 1012 is 64 days old; refund window is 30 days." |
| `plan-clarify.json` | clarify variant §3 |
| `plan-replay.json` | `plan.json` with `source:"replay"` |
| `plan-empty.json` | `plan.steps: []`, no blocked inputs |
| `execute.json` | `{ "s1": {...}, ..., "s5": {...} }` one result per step id; s5 `data.refund_id:"re_test_fixture01"` |
| `execute-fail.json` | s2 fails: `"error":"Outbox write failed (fixture)"` |
| `audit.json` | 5 rows matching execute.json, all undoable |
| `undo.json` | `{"ok":true,"summary":"Restock PO cancelled"}` |
| `outbox.json` | 3 tracking emails |
| `error-429.json`, `error-503.json` | error envelopes §3 |

Scenarios (`?fixtures=` value → overrides): `happy` (default), `invalid` (plan → plan-invalid), `clarify` (first plan → clarify, second → plan), `ratelimit` (plan → 429, retry_after 5), `llmdown` (plan → 503), `fail` (execute s2 → fail), `slow` (plan resolves after 14 s, to test the 12 s fallback), `empty` (plan → plan-empty), `mock` (session `llm_mode:"mock"`). Fixture fetch keeps audit/outbox empty until the first execute (in-memory flag), adds 300 ms latency.

## Contract conflicts

1. **`Plan` has no id**, but `POST /api/execute` takes `plan_id`. Proposal: `/api/plan` response wraps the Plan as in §3 with `plan_id`.
2. **Execute granularity.** UI calls `/api/execute` once per step. Backend must accept repeated calls on one `plan_id` with disjoint step ids, and return the stored result (not re-run) for an already-executed step. If refused: UI sends all ids in one call and renders results together (no live rows).
3. **`ToolResult` lacks `step_id` and `audit_id`** for the run log and undo. Proposal: execute returns `results[i] = ToolResult + step_id + audit_id`.
4. **UI needs tool flags per step** (`destructive`, `moves_money`, `undoable`) to decide which steps need approval. Proposal: `tools` map in the plan response (from `get_tools()`), so the UI never hardcodes flags.
5. **Not in the frozen API but needed:** `usage` (token/cost/cache meter), `clarify` (question instead of plan), `source` ("live"/"replay"), `llm_mode` on session, a common error envelope with `code` and `retry_after_s`. All additive; no rename.
6. **Recorded-plan fallback:** proposal `POST /api/plan {request, replay:true}` returns a canned plan for the 3 suggested prompts with `source:"replay"`, executed for real. Owner: agent-core planner. If rejected, the fallback is fixture mode only.
7. **Forecast band shape** undefined in the brief. UI expects `diff.after = {on_hand, days_to_stockout, band:{p10,p50,p90}}` cumulative, 15 points. Owner: ML planner.
8. **CSP header** belongs to `main.py`; requested in §10.

## Sources

- Hosting/SSE and video tool URLs: §11 and §14 (Haiku search agents, 2026-10-30).
- Problem quote: `research/products/03-reddit-demand-signals.md` theme 3 (fetched mirror, 2025-12-23 snapshot).
- Design rules: `ui-unified` skill (Operate mode, quality floor), root `DESIGN.md` palette.
