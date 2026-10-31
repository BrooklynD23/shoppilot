# 09 — Agent trace on the plan response (proposed)

Console team, 2026-10-31. Status: **proposed**, for the backend team to implement next. The UI already reads it when present, and falls back to today's fields when it is missing. Nothing in `app/` changed for this.

## 1. Why

The console's team stage shows each real module as a teammate (Router, Planner, Guard, Forecaster, Validator, Judge, Executor) and replays what each one did. Today the UI rebuilds that story only from fields `POST /api/plan` already returns:

| Shown on stage | Source today |
|---|---|
| Router: in scope, or declined | `usage.calls[].stage == "router"`, then planner calls or `plan.status == "refused"` |
| Planner: turns, steps drafted, clarify question | count of `usage.calls[].stage == "planner"`, `plan.steps`, `clarify.question` |
| Guard: emails kept out of this plan | `plan.blocked_inputs` (and `GET /api/inbox` verdicts on boot) |
| Forecaster: days to stockout | `diff[].before.forecast` on restock steps |
| Validator: pass, or blocked with the reason | `validations[]` (final whole-plan check) |
| Judge: pass, warning or fail | `plan.judge` |
| Executor | per-step `POST /api/execute` results, live |
| Real times in the log | `usage.calls[].ms` |

What it cannot show: which read tools ran, the validator's in-loop `REJECTED` self-repair (the best part of the design, spec 02 D1), guard blocks met during planning in order, and when each event happened. The trace adds exactly that.

## 2. Contract

`POST /api/plan` 200 response gains one top-level field, next to `usage`:

```json
"trace": [
  {"agent": "router",    "event": "pass",   "detail": "Shop work. Routed to the planner.", "t_ms": 610,  "step_id": null},
  {"agent": "validator", "event": "reject", "detail": "Rejected: tracking email before the order is shipped.", "t_ms": 6095, "step_id": null},
  {"agent": "validator", "event": "pass",   "detail": "s4 passes: $26.00, under the $200.00 per-order cap.", "t_ms": 7586, "step_id": "s4"}
]
```

| Field | Type | Rule |
|---|---|---|
| `agent` | `"router" \| "planner" \| "guard" \| "forecaster" \| "validator" \| "judge" \| "executor"` | The module that acted. `executor` is reserved; execution stays live per step. |
| `event` | `"start" \| "read" \| "staged" \| "pass" \| "reject" \| "block" \| "warn" \| "ask" \| "done" \| "error"` | See §3. Unknown values are dropped by the UI. |
| `detail` | string, 1 to 160 chars, plain text | Built by our code from templates, ids, counts and validator or guard reasons. Never an email body, subject or sender. Never model free text. |
| `t_ms` | integer >= 0 | Milliseconds since `make_plan` started (`time.monotonic()`), non-decreasing. |
| `step_id` | `"s1".."sN"` or `null` | Set on `staged`, `pass` and `reject` for a staged step that got an id. A rejected write has no id (it was never appended). |

Limits: at most 60 events (drop extra `read` events first). The UI reads the first 40, checks every field, and treats a malformed trace as absent.

## 3. Where to emit (backend map)

| Where | Events |
|---|---|
| `planner.route()` | `router start` before the call; `router pass` on `route == "plan"`; `router reject` with the reply on `route == "reject"` |
| `planner._loop()` each turn | `planner start` ("Turn n: ...") |
| `planner._run_read()` | `planner read` ("list_orders: 3 paid orders"); for each new blocked verdict `guard block` ("E002 blocked as injection"); for `forecast_demand` and `flag_anomalies` a `forecaster read` with days to stockout or the anomaly count |
| `planner._stage()` | `planner staged`, then `validator pass` or `validator reject` with `v.reason`, and `planner` gets `REJECTED again` as today |
| `planner.judge()` | `judge start`; then `judge pass`, or `judge warn` for `warn` and `fail` with the failing check names; `judge warn` "Review unavailable" on the fallback |
| `planner._plan()` end | `planner done` (ready), `planner ask` (needs_clarification), `planner reject` (refused) or `planner error` |

Sketch: add `events: list[dict]` and `t0: float` to `Trace`, a helper `emit(trace, agent, event, detail, step_id=None)` that clips `detail` to 160 chars, add `trace: list[dict] = []` to `Plan`, and return `plan.trace` from the route as `"trace"`. Replay mode emits the same events because they come from the recorded responses; only `t_ms` differs.

## 4. Safety

- The trace is display data. It never feeds back into a prompt, an approval or a validation.
- `detail` holds no customer text, so a hostile email cannot speak through a teammate. Blocked emails are named by id and guard label only.
- The UI renders every `detail` with `textContent`, clips to 160 chars and removes em and en dashes.
- No session ids, cookies, keys or token counts in the trace (`usage` already carries cost).

## 5. Fixtures and UI

- `web/public/fixtures/plan-trace.json`: the happy plan with four planner turns in `usage.calls` and a 21-event trace, including one in-loop rejection and repair. Open `/app/?fixtures=trace`.
- `web/public/fixtures/plan.json` (`?fixtures=happy`) stays without a trace, so it shows exactly what today's backend allows.
- Reader: `readTrace()` and `fromTrace()` in `web/src/scripts/console/team.ts`. Replay keeps the real order and compresses the real gaps to 300 to 800 ms per line.

## 6. Tests to add with the backend change

1. A happy plan has `router`, `planner` and `judge` events, ordered by `t_ms`.
2. A recorded self-repair produces a `validator reject` followed by a `planner staged` for the fixed step.
3. An inbox with a blocked email produces one `guard block` naming the email id and label only.
4. No `detail` contains any inbox email body or subject (assert against the seeded inbox).
5. Every `detail` is 1 to 160 chars; at most 60 events.
