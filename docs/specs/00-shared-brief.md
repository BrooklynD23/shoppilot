# ShopPilot+ — shared planning brief (frozen contract)

Written 2026-10-30 by the orchestrator. Every planner reads this first. Do not change a name in this file inside your own plan; if one is wrong, add it to your plan's **Contract conflicts** section and the integrator resolves it.

## Product

ShopPilot+: an AI operations agent for a small online shop. The owner types a natural-language request ("Ship yesterday's orders, email buyers tracking, restock what will run out this week, refund anything damaged"). The agent plans typed tool calls, validates them, shows a dry-run diff, asks for confirmation on anything destructive or money-moving, executes, logs every action with undo.

Source research: `../../../research/products/00-shortlist.md` (layers, demo) and `01`–`04` reports in the same folder. Binding brief: `../../../ASSIGNMENT.md`.

## Grading (drives priorities)

| Criterion | Weight |
|---|---|
| Problem identification | 10% |
| Design & implementation | 30% |
| Prompt engineering | 20% |
| UI/UX | 10% |
| Presentation & live demo | 30% |

Deliverables: GitHub repo URL, **deployed URL graders can use**, 1–2 min demo video.

## Hard constraints

1. One deployable web app at one public URL. Graders use it unauthenticated (anonymous per-browser session).
2. Free or near-free. Every paid item must list a free alternative and a monthly $ estimate.
3. No GPU anywhere. CPU-only, fits a small free/cheap container (assume 512 MB–1 GB RAM until the hosting plan says otherwise; flag any library that breaks this).
4. LLM: Anthropic Claude via API. Planner `claude-sonnet-5-5`, router/judge `claude-haiku-5-5`. Verify current prices before quoting.
5. Payments: Stripe **test mode only**. Never live keys.
6. Emails never leave the app: they go to a visible fake outbox.
7. Each grader session gets its own seeded store (data isolation); resettable.
8. Secrets only in env vars. Spend caps on every paid API.

## Frozen stack (planners may flag, not swap)

- Backend: Python 3.12, FastAPI, Pydantic v2, SQLite (one DB file per session or session_id-scoped rows — architecture planner decides which, others treat `get_db(session_id)` as opaque).
- Frontend: static HTML/CSS/vanilla JS served by FastAPI from `app/static/`. No build step.
- Tests: pytest. One Docker image.
- Repo root: `shoppilot/` (this folder becomes the GitHub repo).

## Frozen repo layout

```
shoppilot/
  app/
    main.py            # FastAPI app, routes, static mount
    config.py          # env settings
    db.py              # get_db(session_id), schema, seed
    seed/              # seed data generators (deterministic, seeded RNG)
    llm/               # client.py (retries, rate limit, caching), prompts/
    agent/             # planner.py, validator.py, dryrun.py, executor.py, audit.py
    tools/             # one module per tool; registry.py
    ml/                # forecast.py, anomaly.py
    safety/            # inbound_guard.py, policy.py
    integrations/      # stripe_client.py, outbox.py, export.py
    static/            # index.html, app.js, styles.css
  tests/               # mirrors app/
  docs/specs/  docs/plans/
  Dockerfile  pyproject.toml  .env.example  README.md
```

## Frozen interfaces (names, not bodies)

```python
# app/tools/registry.py
class ToolSpec(BaseModel):
    name: str                 # snake_case, matches Claude tool name
    description: str
    input_schema: dict        # JSON Schema, strict
    destructive: bool         # True => needs user confirm
    moves_money: bool         # True => confirm + amount shown in diff
    undoable: bool

class ToolResult(BaseModel):
    ok: bool
    summary: str
    data: dict = {}
    undo_token: str | None = None
    error: str | None = None

def register(spec: ToolSpec, run: Callable[[dict, "Ctx"], ToolResult],
             preview: Callable[[dict, "Ctx"], "DiffItem"],
             undo: Callable[[str, "Ctx"], ToolResult] | None = None) -> None
def get_tools() -> list[ToolSpec]

# app/agent/*
class Step(BaseModel):  id: str; tool: str; args: dict; rationale: str
class Plan(BaseModel):  request: str; steps: list[Step]; blocked_inputs: list["GuardVerdict"] = []
class DiffItem(BaseModel): step_id: str; before: dict; after: dict; amount_cents: int | None = None
class Validation(BaseModel): step_id: str; ok: bool; reason: str | None = None

def make_plan(request: str, ctx) -> Plan                  # planner.py
def validate_plan(plan: Plan, ctx) -> list[Validation]    # validator.py
def dry_run(plan: Plan, ctx) -> list[DiffItem]            # dryrun.py
def execute(plan: Plan, approved_step_ids: set[str], ctx) -> list[ToolResult]  # executor.py
def log_action(ctx, kind: str, payload: dict) -> str      # audit.py, returns audit id

# app/safety/inbound_guard.py
class GuardVerdict(BaseModel): source_id: str; allowed: bool; label: str; reason: str; score: float | None = None
def screen(text: str, source_id: str) -> GuardVerdict

# app/ml
def forecast_demand(product_id: str, ctx, horizon_days: int = 14) -> dict  # days_to_stockout, band
def flag_anomalies(ctx) -> list[dict]                                       # order_id, score, reason
```

## Frozen HTTP API

| Method | Path | Purpose |
|---|---|---|
| POST | `/api/session` | create/reset seeded store, set cookie |
| GET | `/api/store` | products, orders, customers snapshot |
| GET | `/api/inbox` | inbound emails with guard verdicts |
| POST | `/api/plan` | body `{request}` → Plan + validations + diff |
| POST | `/api/execute` | body `{plan_id, approved_step_ids}` → results |
| POST | `/api/undo/{audit_id}` | undo one action |
| GET | `/api/audit` | audit log |
| GET | `/api/outbox` | fake sent emails |
| GET | `/api/export/{kind}` | CSV/PDF export |
| GET | `/healthz` | liveness |

## Initial tool list (planners may add, must not rename)

`list_orders`, `mark_shipped`, `send_email`, `forecast_demand`, `create_restock_po`, `flag_anomalies`, `refund_order` (Stripe test, moves_money), `create_payment_link` (Stripe test), `export_report`.

## Wave model (every plan uses it)

| Wave | Meaning |
|---|---|
| W0 | Repo bootstrap: skeleton, CI, Dockerfile, deploy "hello" to the chosen host |
| W1 | Foundations: db + seed, llm client, tool registry, audit |
| W2 | Features in parallel: agent core, ML, safety, integrations, UI |
| W3 | Integration: end-to-end demo flow, eval set, hardening |
| W4 | Deploy, demo script, video, submission |

Each task carries: wave, depends-on task ids, files it **owns** (no two tasks in the same wave own the same file), test, and an estimate in hours.
