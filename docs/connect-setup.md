# Stripe Connect sample: setup guide (humans)

Sandbox only. Off unless `CONNECT_ENABLED=1`, so the 2026-11-05 demo is unaffected. Design: `docs/specs/10-stripe-connect.md`.

What it does: a browser creates a connected account (Accounts v2), onboards with Stripe, adds products, sells them from a storefront (Direct Charge + $1.23 platform fee) and can subscribe to the platform plan "ShopPilot+ Pro" (product limit 3 → 20).

## Already done (2026-11-02)

| Item | State |
|---|---|
| `.env` line endings | LF (no `\r`), checked |
| Platform price | `price_1UXT6UAjPfce7GIjThhrPC3u`, $9.00/month, lookup key `shoppilot_pro_monthly` |
| Test user account | `acct_1UXQy4AjPf69rvVR`: card payments active, nothing due. The live tests use it |
| Live tests | 6 pass; the portal test skips until step 1 below |

## Local run (about 10 minutes)

1. **Optional: adjust the Customer portal.** Stripe creates a default portal configuration on the first "Manage billing" call (verified 2026-11-02: cancel at period end, plan switching off). To make cancellation take effect at once, open Settings → Billing → Customer portal in the sandbox, set cancellation to "Immediately", and **Save**.

2. **Start the two webhook listeners** in two terminals (keep both open). Stripe can't send thin and snapshot events to one destination.

   Terminal A, thin v2 account events:
   ```bash
   stripe listen --thin-events 'v2.core.account[requirements].updated,v2.core.account[configuration.recipient].capability_status_updated,v2.core.account[configuration.merchant].capability_status_updated,v2.core.account[configuration.customer].capability_status_updated' --forward-thin-to localhost:8000/api/connect/webhooks/thin
   ```
   Terminal B, billing (snapshot) events:
   ```bash
   stripe listen --latest --events customer.subscription.created,customer.subscription.updated,customer.subscription.deleted,payment_method.attached,payment_method.detached,customer.updated,customer.tax_id.created,customer.tax_id.deleted,customer.tax_id.updated,billing_portal.configuration.created,billing_portal.configuration.updated,billing_portal.session.created --forward-to localhost:8000/api/connect/webhooks/billing
   ```
   Each prints `Your webhook signing secret is whsec_...`. CLI 1.55.6 marks `--thin-events` as deprecated but it works.

3. **Add these lines to `.env`** in an editor (never `echo` secrets into a terminal):
   ```
   CONNECT_ENABLED=1
   PUBLIC_BASE_URL=http://localhost:8000
   STRIPE_PLATFORM_PRICE_ID=price_1UXT6UAjPfce7GIjThhrPC3u
   STRIPE_CONNECT_THIN_WEBHOOK_SECRET=whsec_...   # from terminal A
   STRIPE_BILLING_WEBHOOK_SECRET=whsec_...        # from terminal B
   ```
   Lost the price id? `set -a; . ./.env; set +a; uv run python scripts/create_platform_price.py` prints it again and creates nothing new.

4. **Run the app** (terminal C):
   ```bash
   cd web && npm run build:app && cd .. && set -a; . ./.env; set +a; .venv/bin/uvicorn app.main:app --port 8000
   ```
   Open http://localhost:8000/connect/

5. **Walk through it:**
   1. Create your shop (any name, any email).
   2. "Onboard to collect payments". In Stripe's form use Stripe's test data (docs.stripe.com/connect/testing), for example phone `000 000 0000` with SMS code `000-000`, bank routing `110000000` and account `000123456789`.
   3. Back on the dashboard, both pills should read "active" and "complete". Terminal A shows `[200]` lines.
   4. Add a product, then "Open your storefront", Buy, and pay with `4242 4242 4242 4242`, any future date, any CVC. You land on the success page.
   5. "Subscribe to ShopPilot+ Pro", pay with the same card. Terminal B shows `[200]`; Refresh status shows Pro on and 20 products.
   6. "Manage billing", cancel the plan. With the default portal, cancellation waits until the period ends, so Pro and the 20-product limit stay until then; with "Immediately" (step 1) the limit drops back to 3 after the webhook.

## When something is missing, the app says so

| You see | Fix |
|---|---|
| "Connect demo is disabled on this server." | `CONNECT_ENABLED=1` in `.env`, restart |
| 503 "X is not set: ..." (also in the server log) | Add X to `.env` as the message says, restart |
| 503 "Invalid Connect setting: X" | Fix the format of X (see `.env.example`), restart |
| 429 | Rate limit or the 20-accounts-a-day cap; wait |

## Live tests against the sandbox

```bash
set -a; . ./.env; set +a
RUN_LIVE=1 CONNECT_TEST_ACCOUNT_ID=acct_1UXQy4AjPf69rvVR uv run pytest tests/connect/test_live_connect.py -m live -v -p no:cacheprovider
```
Each run creates one product on the test account and archives it. `CONNECT_LIVE_CREATE=1` also creates a new connected account (off by default).

## Render (only when Connect should be live there)

Keep it off for the 2026-11-05 demo. To turn it on later:

1. Stripe Dashboard → Workbench → Webhooks → "Create an event destination", twice:
   - **Thin**: Events from **Your account**, payload **Thin**, events `v2.core.account[requirements].updated`, `v2.core.account[configuration.merchant].capability_status_updated`, `v2.core.account[configuration.customer].capability_status_updated`; URL `https://<service>.onrender.com/api/connect/webhooks/thin`.
   - **Snapshot**: Events from **Your account**, payload **Snapshot**, API version `2026-10-28.endive`, the 12 events from terminal B; URL `https://<service>.onrender.com/api/connect/webhooks/billing`.
2. Render Dashboard → shoppilot → Environment: add `CONNECT_ENABLED=1`, `PUBLIC_BASE_URL=https://<service>.onrender.com`, `STRIPE_PLATFORM_PRICE_ID=price_1UXT6UAjPfce7GIjThhrPC3u`, and each destination's signing secret as `STRIPE_CONNECT_THIN_WEBHOOK_SECRET` / `STRIPE_BILLING_WEBHOOK_SECRET`. Save and deploy. `render.yaml` stays unchanged.
3. Check: after one onboarding on Render, the thin destination's "Event deliveries" tab shows 200s. Nothing there? Add the same thin destination with Events from **Connected accounts**.
4. Off switch: delete `CONNECT_ENABLED` on Render and redeploy.

Note: on Render, `connect.db` lives in `/tmp`, so a restart forgets which browser owns which account (the Stripe objects stay).
