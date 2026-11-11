# ShopPilot+

**Autopilot for your shop. You approve every dollar.**

ShopPilot+ is an AI agent for small online shops. You type one sentence ("refund the customer who complained about a broken mug"), and it turns that into a checked plan of typed actions, shows you every change and every dollar before anything happens, runs only the steps you approve, and logs each one with an undo.

Built for CS4680 Prompt Engineering, A4 (AI Agent Project).

| | |
|---|---|
| Live app | `<DEPLOYED_URL>` |
| Demo video | `<YOUTUBE_URL>` |
| Pitch | [docs/PITCH.md](docs/PITCH.md) · [deck](docs/presentation/ShopPilot-pitch.pptx) |

## Try it

Open the live app, go to the console, and type one of these:

1. `refund the customer who complained about a broken mug`
2. `Mark the oldest unshipped order as shipped and email the customer`
3. `what sold best last week?`
4. `Delete all customers` (watch it refuse)

Each browser gets its own private copy of **Fern & Kiln**, a seeded demo store with 20 products, 400 customers, 2,732 orders and 4 inbox emails (one is a planted prompt injection). Reset it any time. Refunds go to Stripe test mode, and emails land in an in-app outbox. Nothing real is charged or sent.

## The problem

Small shop owners lose hours a day to admin: shipping yesterday's orders, answering "where is my order" emails, refunding damaged items, restocking the bestseller. AI agents could take this work, but owners don't trust them with money. ShopPilot+ puts a gate in front of the money and an undo behind it. See [docs/PITCH.md](docs/PITCH.md) for the research.

## How it works

```
request ─► inbound guard ─► router ─► planner (tool loop) ─► validator ─► dry run ─► judge
                                                                                     │
         audit log + undo ◄── executor (approved steps only) ◄── you approve ◄───────┘
```

| Stage | What it does | Where |
|---|---|---|
| Inbound guard | Screens customer emails for prompt injection (heuristics, then an LLM check) | `app/safety/inbound_guard.py` |
| Router | Decides if the request is in scope | `app/llm/prompts/router.md` |
| Planner | Calls read-only tools to gather facts, then stages write steps as a structured JSON plan | `app/agent/planner.py` |
| Validator | Schema checks plus business rules the model can't talk past (refund caps, refund windows, evidence) | `app/agent/validator.py`, `app/safety/policy.py` |
| Dry run | Before/after diff with dollar amounts read from the database | `app/agent/dryrun.py` |
| Judge | A second LLM pass that reviews the plan. It can only add warnings, never approve | `planner.py` `judge()`, `app/llm/prompts/judge.md` |
| Executor | Runs approved steps one at a time in a database savepoint, stops at the first failure | `app/agent/executor.py` |
| Audit log | Append-only, SHA-256 hash-chained log with single-step undo | `app/agent/audit.py` |

## Assignment requirements

| Requirement | How ShopPilot+ meets it |
|---|---|
| **LLM integration** | One provider-agnostic door to the model (`app/llm/client.py`). Gemini on Vertex AI by default, Claude as an option (`LLM_PROVIDER`). Retries with backoff that honor `retry-after`, error classification (rate limited, overloaded, unreachable, not configured), per-session and daily spend caps (`app/llm/budget.py`), and a fallback to recorded plans when live AI is unavailable. |
| **Action interpreter / executor** | The model's output is a JSON plan matching a strict schema. Each step names a tool and its arguments, which are validated against that tool's JSON schema (`app/tools/registry.py`) before execution. |
| **Multiple domains** | Database (SQLite orders, stock, purchase orders), external API (Stripe test-mode refunds and payment links), email (outbox), file export (CSV reports), analytics (demand forecast, anomaly flags). 11 tools in `app/tools/`. Shell access is left out on purpose: a shop assistant has no reason to run commands. |
| **User interface** | Web console: type a request, watch each stage, review the plan with ticks/crosses and a dollar diff, approve steps, run, see per-step results, browse the audit log and undo. |
| **Error handling & safety** | Validation before execution, explicit approval for destructive or money-moving steps, hard policy caps (for example $200 per refund, $500 per plan, 3 refunds per plan), graceful error envelopes, rate limits on API routes, and an audit log for every action. |

## Prompt engineering techniques

| Technique | Where |
|---|---|
| Role-specific system prompts, one file per stage | `app/llm/prompts/*.md` |
| Few-shot examples with full multi-turn tool traces | `app/llm/prompts/examples.md` |
| Structured output with JSON schemas (router, plan, judge, guard) | `planner.py`, `inbound_guard.py` |
| Tool use with strict schemas, read tools before write tools | `app/tools/registry.py`, `planner_system.md` |
| Required `rationale` and `evidence` on every step | `planner_system.md` |
| Clarifying questions when a request is ambiguous (`needs_clarification`) | `planner.py` |
| LLM-as-judge self-check with 4 named checks | `app/llm/prompts/judge.md` |
| Prompt-injection defense: untrusted emails wrapped in tags and treated as data | `planner_system.md`, `inbound_guard.py` |
| Model routing: Gemini 3.8 Flash plans; Gemini 3.1 Flash-Lite routes, guards and judges | `app/config.py` |
| Record/replay eval suite: 24/24 cases pass (safety, refusal, ambiguity) | `tests/eval/` |

## Run locally

Requires Python 3.12, [uv](https://docs.astral.sh/uv/) and Node 22.

```bash
cp .env.example .env              # fill in GOOGLE_CLOUD_PROJECT, or leave empty for replay mode
uv sync
(cd web && npm ci && npm run build && cp -r dist/. ../app/static/)
uv run uvicorn app.main:app --reload
```

Open <http://localhost:8000>. With no LLM credentials, the app replays recorded plans for the demo requests.

For live Gemini on your machine, run `gcloud auth application-default login` and set `GOOGLE_CLOUD_PROJECT` and `GOOGLE_CLOUD_LOCATION=global` in `.env`.

Tests: `uv run pytest -q` (offline, replay mode).

## Deploy (Render)

`render.yaml` defines one Docker web service. Set these environment variables in the Render dashboard:

| Key | Value |
|---|---|
| `LLM_PROVIDER` | `gemini` |
| `GOOGLE_CLOUD_PROJECT` | your GCP project id |
| `GOOGLE_CLOUD_LOCATION` | `global` |
| `GOOGLE_APPLICATION_CREDENTIALS_JSON` | service-account key JSON (role `roles/aiplatform.user`) |
| `STRIPE_SECRET_KEY` | optional, `sk_test_...` only |

Leave `PLANNER_MODEL` and `JUDGE_MODEL` unset to use the per-stage defaults.

## Stripe Connect sample (optional, sandbox only)

A separate Stripe Connect integration at `/connect/`: create a connected account (Accounts v2), onboard, add products, sell them from a storefront with a platform fee, and subscribe to a platform plan. It is off unless `CONNECT_ENABLED=1`; when off, every `/api/connect/*` route returns 404 and the demo is unchanged. Code: `app/connect/`. Setup and test steps: `docs/connect-setup.md`. Design: `docs/specs/10-stripe-connect.md`.

## Known limits

- Prompts were first tuned on Claude; plan quality on Gemini is measured by the eval suite in `tests/eval/`.
- `sales_by_product` counts paid and shipped orders only.
- Image size and idle RSS: not yet measured (no Docker locally; CI builds the image).
