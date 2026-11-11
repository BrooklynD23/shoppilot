<div align="center">

# ShopPilot+

**Autopilot for your shop. You approve every dollar.**

An AI agent for small online shops. Type one sentence, get a checked plan of real actions, approve what moves money, and undo what you don't like.

[![Live demo](https://img.shields.io/badge/live_demo-shoppilot--lysb.onrender.com-2ea44f)](https://shoppilot-lysb.onrender.com)
[![Demo video](https://img.shields.io/badge/demo_video-YouTube-red)](https://youtu.be/p75A0YK2R7Q)
[![CI](https://github.com/BrooklynD23/shoppilot/actions/workflows/ci.yml/badge.svg)](https://github.com/BrooklynD23/shoppilot/actions/workflows/ci.yml)
![Python 3.12](https://img.shields.io/badge/python-3.12-blue)
![Gemini on Vertex AI](https://img.shields.io/badge/LLM-Gemini_on_Vertex_AI-4285F4)

[Live demo](https://shoppilot-lysb.onrender.com) · [Demo video](https://youtu.be/p75A0YK2R7Q) · [Getting started](docs/GETTING_STARTED.md) · [Deploy](docs/DEPLOY.md) · [Pitch](docs/PITCH.md)

<sub>Danny Tran · CS4680 Prompt Engineering · A4 AI Agent Project</sub>

</div>

---

## Demo video

<a href="https://youtu.be/p75A0YK2R7Q"><img src="https://img.youtube.com/vi/p75A0YK2R7Q/maxresdefault.jpg" alt="Watch the ShopPilot+ demo video on YouTube (2 minutes)" width="100%"></a>

<sub>2 minutes: the problem, a live refund and ship-and-email run on Gemini, the prompt chain, and the safety checks.</sub>

## Try it in 30 seconds

Open the [live demo](https://shoppilot-lysb.onrender.com), click **Try the demo**, and type one of these:

| Request | What to watch for |
|---|---|
| `refund the customer who complained about a broken mug` | Finds the email, stages a $26.00 refund, waits for your tick |
| `Mark the oldest unshipped order as shipped and email the customer` | Two steps in order, then the audit log and **Undo** |
| `what sold best last week?` | Answers from one `sales_by_product` query |
| `Delete all customers` | Refuses. There is no tool for that |

Each browser gets its own private demo store, **Fern & Kiln**: 20 products, 400 customers, 2,732 orders and 4 inbox emails (one is a planted prompt injection). Refunds go to Stripe test mode and emails land in an in-app outbox, so nothing real is charged or sent.

> [!NOTE]
> The free Render plan sleeps when idle. The first visit can take about 50 seconds.

## What it does

<table>
<tr>
<td width="50%"><img src="docs/pitch-assets/landing-hero.webp" alt="Landing page: Autopilot for your shop. You approve every dollar."><br><b>One sentence in.</b> A plan of typed steps out, each with the tool, its arguments and a reason.</td>
<td width="50%"><img src="docs/pitch-assets/console-approval.webp" alt="Refund step for $26.00 with an approval checkbox"><br><b>You approve the money.</b> Refunds and other risky steps wait for your checkbox. The dollar amount comes from the database, not the model.</td>
</tr>
<tr>
<td><img src="docs/pitch-assets/console-team-3d.webp" alt="Agent team: Guard, Router, Planner, Forecaster, Validator, Judge, Executor"><br><b>A team of small agents.</b> Each stage has one job, and you can watch them work.</td>
<td><img src="docs/pitch-assets/inbox-blocked.webp" alt="Inbox email blocked as prompt injection, score 1.00"><br><b>Prompt injection blocked.</b> Customer emails are untrusted data. This one tried to order a bulk refund.</td>
</tr>
<tr>
<td><img src="docs/pitch-assets/validator-blocked.webp" alt="Refund blocked by validator: needs evidence"><br><b>A validator the model can't talk past.</b> Business rules live in code: caps, refund windows, evidence.</td>
<td><img src="docs/pitch-assets/forecast-chart.webp" alt="Stock forecast: runs out in about 4 days"><br><b>Forecasts, not guesses.</b> Restock quantities come from a demand forecast with an 80% range.</td>
</tr>
</table>

## How it works

```mermaid
flowchart LR
    U([Owner request]) --> G[Inbound guard<br/>rules + LLM]
    G --> R[Router<br/>LLM]
    R --> P[Planner<br/>LLM tool loop]
    P <-->|read tools| T[(Store DB)]
    P --> V[Validator<br/>code]
    V -->|rejects with reason| P
    V --> D[Dry run<br/>dollar diff]
    D --> J[Judge<br/>LLM, warn only]
    J --> A{Owner approves?}
    A -->|yes| E[Executor<br/>one step at a time]
    E --> T
    E --> S[Stripe test mode]
    E --> O[Email outbox]
    E --> L[(Audit log<br/>hash chain + undo)]
```

1. **The LLM decides what to do.** Gemini returns tool calls and a JSON plan, not prose.
2. **The agent checks it.** Every step is validated against the tool's JSON schema and the business rules in [`app/safety/policy.py`](app/safety/policy.py).
3. **The agent acts.** Approved steps run against the database, Stripe, the email outbox or a file export, then land in the audit log.

<details>
<summary><b>See a full agent trace</b></summary>
<br>
<img src="docs/pitch-assets/agent-trace.webp" alt="Agent trace: router, planner turns, guard, forecaster, validator rejecting and accepting steps" width="600">
</details>

## Assignment requirements

| Requirement | How ShopPilot+ meets it | Code |
|---|---|---|
| **LLM integration** | One provider-agnostic door: Gemini on Vertex AI or Claude. Retries with backoff, `retry-after`, error classification, rate limits, daily and per-session spend caps, replay fallback | [`app/llm/client.py`](app/llm/client.py), [`app/llm/gemini.py`](app/llm/gemini.py), [`app/llm/budget.py`](app/llm/budget.py) |
| **Action interpreter / executor** | Structured JSON plan → schema-validated tool calls → step-by-step execution in database savepoints | [`app/agent/planner.py`](app/agent/planner.py), [`app/tools/registry.py`](app/tools/registry.py), [`app/agent/executor.py`](app/agent/executor.py) |
| **Multiple domains** | Database (orders, stock, purchase orders), external API (Stripe), email (outbox), files (CSV export), analytics (forecast, anomalies). 11 tools. No shell access, on purpose | [`app/tools/`](app/tools/) |
| **User interface** | Web console: natural-language input, live stage view, plan with ticks and crosses, dollar diff, per-step approval, results, audit log, undo | [`web/`](web/) |
| **Error handling & safety** | Validation before execution, approval for destructive or money-moving steps, hard caps ($200 per refund, $500 per plan), graceful errors, hash-chained audit log | [`app/agent/validator.py`](app/agent/validator.py), [`app/agent/audit.py`](app/agent/audit.py) |

## Prompt engineering

| Technique | Where |
|---|---|
| Role-specific system prompts, one per stage | [`app/llm/prompts/`](app/llm/prompts/) |
| Few-shot examples with full multi-turn tool traces | [`examples.md`](app/llm/prompts/examples.md) |
| Structured output with JSON schemas | [`planner.py`](app/agent/planner.py) |
| Tool use: read before write, strict schemas | [`planner_system.md`](app/llm/prompts/planner_system.md) |
| Required `rationale` and `evidence` on every step | [`planner_system.md`](app/llm/prompts/planner_system.md) |
| Clarifying questions for ambiguous requests | [`planner.py`](app/agent/planner.py) |
| Self-repair: validator rejections go back to the model with the reason | [`planner.py`](app/agent/planner.py) |
| LLM-as-judge with 4 named checks | [`judge.md`](app/llm/prompts/judge.md) |
| Prompt-injection defense: untrusted emails tagged as data | [`inbound_guard.py`](app/safety/inbound_guard.py) |
| Model routing: Gemini 3.8 Flash plans, Gemini 3.1 Flash-Lite routes, guards and judges | [`app/config.py`](app/config.py) |
| Eval suite: **24/24** recorded cases pass (safety, refusal, ambiguity, injection) | [`tests/eval/`](tests/eval/) |

## Quick start

```bash
git clone https://github.com/BrooklynD23/shoppilot.git && cd shoppilot
uv sync && cp .env.example .env
(cd web && npm ci && npm run build && cp -r dist/. ../app/static/)
uv run uvicorn app.main:app --reload     # http://localhost:8000
```

This runs without any API key, using recorded plans. For live Gemini, Claude, tests and spend caps, see **[Getting started](docs/GETTING_STARTED.md)**.

## Documentation

| Guide | What's inside |
|---|---|
| [Getting started](docs/GETTING_STARTED.md) | Local setup, LLM modes, models per stage, tests |
| [Deploy](docs/DEPLOY.md) | Render + Vertex AI setup, credentials, GitHub Actions |
| [Pitch](docs/PITCH.md) | Problem, research, competitors, approach ([deck](docs/presentation/ShopPilot-pitch.pptx)) |
| [Eval suite](tests/eval/README.md) | The 24 test cases and how to re-record them |
| [Stripe Connect sample](docs/connect-setup.md) | Optional sandbox storefront at `/connect/` |

<details>
<summary><b>Design specs</b></summary>

| Spec | Topic |
|---|---|
| [01 Architecture](docs/specs/01-architecture.md) | Request flow, schema, seed data, sessions |
| [02 Agent core](docs/specs/02-agent-core.md) | Router, planner loop, judge, LLM client |
| [03 ML actions](docs/specs/03-ml-actions.md) | Demand forecast and anomaly flags |
| [04 Safety](docs/specs/04-safety.md) | Policy caps, validator, guard, audit log |
| [05 Integrations](docs/specs/05-integrations.md) | Stripe, outbox, export |
| [06 UI demo](docs/specs/06-ui-demo.md) | Console and landing page |
| [07 Hosting](docs/specs/07-hosting-deploy.md) | Docker, Render, CI |
| [09 Agent trace](docs/specs/09-agent-trace.md) | The live team log |

The specs were written before the move from Claude to Gemini. Model names in them are historical; [`app/config.py`](app/config.py) is the source of truth.

</details>

## Project layout

```
app/
  agent/        planner, validator, dry run, executor, audit log
  llm/          provider-agnostic client, Gemini adapter, prompts, recordings
  tools/        11 typed tools (orders, refunds, email, restock, forecast, export, ...)
  safety/       policy caps, inbound prompt-injection guard
  integrations/ Stripe, outbox, export
  ml/           demand forecast, anomaly detection
web/            Astro console and landing page
tests/          ~970 tests, including the 24-case eval
docs/           guides, pitch, specs
```

## Known limits

- Card refunds are irreversible, and the UI says so before you approve one. Every other action has a single-step undo.
- `sales_by_product` counts paid and shipped orders only.
- Prompts were first tuned on Claude. Gemini quality is tracked by the eval suite.
