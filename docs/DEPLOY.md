# Deploying to Render with Gemini on Vertex AI

How the live demo at <https://shoppilot-lysb.onrender.com> is set up.

← Back to the [README](../README.md)

## Overview

- **Hosting:** one Docker web service on Render's free plan, defined in [`render.yaml`](../render.yaml). The Dockerfile builds the Astro console, then the Python app.
- **LLM:** Gemini on Vertex AI, billed to a GCP project.
- **Auth:** an API key bound to a service account with `roles/aiplatform.user`. Vertex AI rejects API keys that are not bound to a service account.

## 1. GCP project and Vertex AI

```bash
gcloud projects create YOUR_PROJECT --name="ShopPilot Vertex"
gcloud billing projects link YOUR_PROJECT --billing-account=YOUR_BILLING_ACCOUNT
gcloud services enable aiplatform.googleapis.com apikeys.googleapis.com --project YOUR_PROJECT
```

## 2. Service account

```bash
gcloud iam service-accounts create shoppilot-llm --project YOUR_PROJECT
gcloud projects add-iam-policy-binding YOUR_PROJECT \
  --member=serviceAccount:shoppilot-llm@YOUR_PROJECT.iam.gserviceaccount.com \
  --role=roles/aiplatform.user --condition=None
```

## 3. API key bound to the service account

```bash
gcloud services api-keys create --project YOUR_PROJECT \
  --display-name=shoppilot-render \
  --service-account=shoppilot-llm@YOUR_PROJECT.iam.gserviceaccount.com \
  --api-target=service=aiplatform.googleapis.com \
  --format="value(response.keyString)" > ~/shoppilot-vertex-key.txt
```

The key can only call Vertex AI. Keep the file out of git.

### If key creation fails with `FAILED_PRECONDITION`

Organizations created recently enforce `iam.managed.disableServiceAccountApiKeyCreation` by default. An Org Policy Administrator can turn it off for this one project:

```yaml
# policy.yaml
name: projects/YOUR_PROJECT/policies/iam.managed.disableServiceAccountApiKeyCreation
spec:
  rules:
  - enforce: false
```

```bash
gcloud services enable orgpolicy.googleapis.com --project YOUR_PROJECT
gcloud org-policies set-policy policy.yaml --billing-project YOUR_PROJECT
```

Service-account JSON keys are blocked by a separate policy (`iam.disableServiceAccountKeyCreation`). The app also accepts one in `GOOGLE_APPLICATION_CREDENTIALS_JSON`, but the bound API key is the narrower credential.

## 4. Render service

1. Render dashboard → **New** → **Blueprint** → pick this repo. Render reads `render.yaml`.
2. Under **Environment**, set:

| Key | Value |
|---|---|
| `APP_ENV` | `prod` (set by `render.yaml`) |
| `LLM_PROVIDER` | `gemini` |
| `GOOGLE_CLOUD_PROJECT` | your project id |
| `GOOGLE_CLOUD_LOCATION` | `global` |
| `GOOGLE_API_KEY` | contents of `~/shoppilot-vertex-key.txt` |
| `STRIPE_SECRET_KEY` | optional, `sk_test_...` only |

Leave `PLANNER_MODEL` and `JUDGE_MODEL` unset. A model name from another provider stops the app at boot.

3. Deploy. `autoDeployTrigger` is off in `render.yaml`, so either deploy from the dashboard or with the CLI:

```bash
render deploys create <service-id> --commit <sha> --wait
```

4. Check: `curl https://<your-service>.onrender.com/healthz` returns `{"ok":true,"version":"<sha>"}`.

## 5. Optional: deploy from GitHub Actions

`.github/workflows/deploy.yml` triggers a deploy after CI passes on `main`, then runs `scripts/smoke.sh`. It needs:

| Name | Kind | Value |
|---|---|---|
| `RENDER_DEPLOY_HOOK_URL` | repository secret | Render → service → Settings → Deploy Hook |
| `APP_URL` | repository variable | `https://<your-service>.onrender.com` |

## Notes

- **Cold starts:** the free plan sleeps after about 15 minutes idle. The first request takes about 50 s.
- **Cost:** live plans cost about $0.04–0.05 each with `gemini-3.8-flash` planning. The app's daily cap is `LLM_DAILY_BUDGET_USD` (default $5). Also set a GCP budget alert, because the app only counts spend it records itself.
