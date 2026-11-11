# Getting started

Run ShopPilot+ on your own machine, with or without a live LLM.

← Back to the [README](../README.md)

## Requirements

| Tool | Version |
|---|---|
| Python | 3.12 |
| [uv](https://docs.astral.sh/uv/) | 0.9 or newer |
| Node.js | 22 (only to build the web console) |
| gcloud CLI | optional, for live Gemini on Vertex AI |

## 1. Install

```bash
git clone https://github.com/BrooklynD23/shoppilot.git
cd shoppilot
uv sync
cp .env.example .env
```

## 2. Build the web console

The FastAPI app serves the built Astro site from `app/static/`.

```bash
cd web
npm ci
npm run build
cp -r dist/. ../app/static/
cd ..
```

## 3. Pick an LLM mode

| Mode | What you need | What you get |
|---|---|---|
| **Replay** (no credentials) | nothing | Recorded plans for the demo requests. Anything else shows "Live AI is not configured". |
| **Gemini on Vertex AI** (default) | a GCP project with the Vertex AI API enabled | Live plans for any request |
| **Claude** | an Anthropic API key | Live plans, all stages on Claude Haiku |

### Gemini on Vertex AI, using your own gcloud login

```bash
gcloud auth application-default login
```

Then set these in `.env`:

```bash
LLM_PROVIDER=gemini
GOOGLE_CLOUD_PROJECT=your-project-id
GOOGLE_CLOUD_LOCATION=global
```

Use `global`. Gemini 3.x models return 404 in `us-central1`.

### Claude instead

```bash
LLM_PROVIDER=anthropic
ANTHROPIC_API_KEY=sk-ant-...
```

### Models per stage

Leave `PLANNER_MODEL` and `JUDGE_MODEL` empty to use the defaults:

| Stage | Gemini default | Claude default |
|---|---|---|
| Planner | `gemini-3.8-flash` | `claude-haiku-5-5` |
| Router, judge, inbound guard | `gemini-3.1-flash-lite` | `claude-haiku-5-5` |

Only models on the allowlist in `app/config.py` (`CHEAP_MODELS`) are accepted. This is a spend guard.

## 4. Run

```bash
uv run uvicorn app.main:app --reload
```

Open <http://localhost:8000>, then go to the console and try `refund the customer who complained about a broken mug`.

## 5. Test

```bash
uv run pytest -q            # about 970 tests, offline, replay mode
uv run ruff check .
uv run ruff format --check .
```

The eval suite (`tests/eval/`) replays 24 recorded cases: safety, refusal, ambiguity and prompt injection. To re-record against a live model, see [tests/eval/README.md](../tests/eval/README.md).

## Spend caps

Live calls are capped by `LLM_DAILY_BUDGET_USD` (default $5) and `LLM_SESSION_BUDGET_USD` (default $0.25). When a cap is hit, the app falls back to recorded plans.

## Optional: Stripe test mode

Set `STRIPE_SECRET_KEY=sk_test_...` to send refunds to Stripe test mode. Without it, refunds use a labelled mock. Live keys are rejected at startup.
