# 10 — Stripe Connect sample (separate, feature-flagged)

Design by Opus 5.5, 2026-11-02. Status: **built 2026-11-02** (see §18 for what changed while building; human steps in `docs/connect-setup.md`). Binding brief: `10-stripe-connect-brief.md`. The demo on 2026-11-05 runs with Connect **off**. When `CONNECT_ENABLED` is unset, nothing in the demo path changes.

**Verdict:** add one new package, `app/connect/`, served under `/api/connect/*`. Every route returns 404 unless `CONNECT_ENABLED=1`. The package has its own SQLite file (`DATA_DIR/connect.db`), its own cookie (`sp_connect`) and three static Astro pages under `/connect/`. Existing files touched: `app/main.py` (2 lines), `app/safety/web.py` (an exact-path webhook CSRF exemption and a 64 KiB body cap, about 6 lines), `tests/conftest.py` (2 lines) and `.env.example`. Unchanged: `render.yaml`, `app/config.py`, `Dockerfile` and the CSP. Connect makes no LLM calls, so the Haiku-only rule (2026-11-02) is not affected.

## 1. Verified facts (2026-11-02)

| # | Fact | Evidence |
|---|---|---|
| F1 | `stripe==16.1.0` is the latest stable release (29 Oct; 16.2.0a1/b1 are pre-releases). It pins API `2026-10-28.endive`. Never set `stripe_version`. | github.com/stripe/stripe-python/releases; `.venv/.../stripe/_api_version.py` |
| F2 | 16.1.0 has **no `parse_thin_event`**. To parse a thin event, call `StripeClient.parse_event_notification(raw, sig_header, secret, tolerance=300)`. It returns a typed `EventNotification` with `.id`, `.type`, `.livemode`, `.context` and `.related_object.id`. To get the full event, call `client.v2.core.events.retrieve(id, params=None, options=None)`. | `stripe/_stripe_client.py:255`; Python sample at docs.stripe.com/webhooks.md?snapshot-or-thin=thin |
| F3 | On endive, V2 Account Links accept only `refresh_url` (required), `return_url` and `collection_options` under `use_case.account_onboarding`. **`configurations` was removed** (stripe-python 16.0.0 changelog). Live sandbox test: sending `configurations` returns 400 `invalid_fields` "use_case.account_onboarding.configurations: Unknown field". Without it the call returns 200 with a URL on `connect.stripe.com`. `http://localhost` refresh and return URLs work in the sandbox (the docs say HTTP is allowed in testing). | `params/v2/core/_account_link_create_params.py`; API reference; sandbox calls on 2026-11-02 |
| F4 | Thin event type names (SDK `LOOKUP_TYPE`): `v2.core.account[requirements].updated` and `v2.core.account[configuration.merchant\|customer\|recipient].capability_status_updated`. The brief's `stripe listen` line has a typo, `v2.core.account[.recipient]...`, and its Dashboard step says `v2.account[...]`. | `stripe/events/_v2_core_account_including_*.py` |
| F5 | Event scope: "For events triggered by connected accounts, v2 Events use the **Your account** scope, while v1 Events use the Connected accounts scope." The brief's "Events from: Connected accounts" is wrong for these thin events. | docs.stripe.com/connect/webhooks.md?accounts-namespace=v2 |
| F6 | Stripe CLI 1.55.6 still accepts the brief's `--thin-events` and `--forward-thin-to` flags but marks them deprecated (use `--events ... --forward-to`). "Snapshot and thin events cannot share one destination", so local testing needs two listeners. | `stripe listen --help` |
| F7 | `customer_account` exists as a parameter on Checkout Session create and Billing Portal Session create, as a filter on `subscriptions.list`, and as a field on Subscription, Invoice, PaymentMethod, TaxId and Customer. | `params/checkout/_session_create_params.py:147`, `params/billing_portal/_session_create_params.py:21`, `params/_subscription_list_params.py:39`, `_subscription.py:986` |
| F8 | Sandbox `acct_1UXEC4AjPfce7GIj` (read-only probe): Accounts v2 is enabled and there are 2 connected accounts. **`acct_1UXQy4AjPf69rvVR`** has the full dashboard, fees and losses collected by Stripe, customer and merchant configurations, `card_payments` active and no requirements due. This is the "test user account" the live tests use. The sandbox has 0 recurring prices, 0 billing-portal configurations and 0 event destinations. | probe, 2026-11-02 |
| F9 | `.env` has CRLF line endings. After `set -a; . ./.env`, both keys end in `\r`, so every Stripe and Anthropic call fails with "Invalid leading whitespace ... in header value". Fix this before any live run (§16 H1). | `file .env`: "with CRLF line terminators" |
| F10 | In stripe-python 16, `StripeObject` is not a dict (`.get` raises). Use attributes, `getattr(o, "x", None)` or `.to_dict()`. `sub.items.data[0].price.id` works. A payload signed locally with HMAC parses with `construct_event` and `parse_event_notification` without any network call. | offline check, 2026-11-02 |

## 2. How each brief rule maps to the design

| Brief rule | Design | Note |
|---|---|---|
| Use a StripeClient for all requests | One cached `StripeClient`, `stripe_calls.client()`, serves every call, including `construct_event` and `parse_event_notification` | |
| Create V2 accounts with exactly the given properties, never a top-level `type` | `create_account()` sends exactly those 6 keys. CI asserts the dict equals the brief's | No `metadata`, no `include` |
| Store a user-to-account mapping (a DB exists) | `connect.db`, table `accounts` | §6 |
| Onboard with V2 account links, plus a status UI | `POST /api/connect/onboard`, a button "Onboard to collect payments" and status pills | `configurations` dropped (F3) |
| Read status from the API every time, never store it | `GET /api/connect/account` retrieves with `include: ["configuration.merchant", "requirements"]` on each call | There is no status column |
| Use thin events for v2 account updates: parse, then `events.retrieve`, one handler per type | `/api/connect/webhooks/thin` | Method name per F2, scope per F5 |
| Create products with the `Stripe-Account` header | `products.create(..., {"stripe_account": acct})` | |
| One storefront page per account, account ID in the URL, plus a comment | `/connect/store/?account=acct_...` | The comment goes in the page and the route |
| Direct charge with an application fee, using hosted Checkout | `checkout.sessions.create(..., {"stripe_account": acct})` with `payment_intent_data.application_fee_amount` | `price_data` is built from the price stored at Stripe |
| Platform subscription through Checkout with `customer_account` | `POST /api/connect/subscribe` | Price comes from `STRIPE_PLATFORM_PRICE_ID` (created with the CLI, §15 step 2) |
| Billing portal with `customer_account` | `POST /api/connect/portal` | The portal settings must be saved first (F8, H2) |
| Snapshot webhooks for the brief's event table; store subscription status | `/api/connect/webhooks/billing` | Adds `customer.subscription.created` (§9.2) |
| Use `.customer_account`, never `.customer` | Every read and every parameter | CI asserts `customer` is never sent |
| Placeholder comments and helpful errors for missing values | `# PLACEHOLDER` lines in `.env.example`. `require()` returns a 503 that names the missing variable | |
| Detailed code comments | Every Stripe call and every webhook step gets a short "what and why" comment | |

## 3. Why Connect cannot break the demo

1. **Flag.** With `CONNECT_ENABLED` unset, the router gate returns the same 404 envelope as `/api/{_rest:path}` for every `/api/connect/*` route, including the webhooks. This happens before any rate-limit hit, database open or Stripe call.
2. **Lazy config.** Connect env vars are read by their own pydantic model in `app/connect/config.py`, on the first Connect request. A bad value returns 503 `connect_misconfigured` on `/api/connect/*` only. `app/config.py` never reads them, so boot can't fail because of them.
3. **No import-time side effects.** Importing `app.connect.*` builds no client and opens no file. `connect.db` is created on first use, behind the gate. `sweep_sessions()` ignores it because its stem is not 32 hex characters.
4. **Separate identity.** The `sp_connect` cookie only covers `/api/connect`. Reusing `sp_session` would seed a demo store for every Connect visitor and count against `MAX_SESSIONS=100`, which evicts other demo stores.
5. **Small, tested diff to existing files** (§4). `render.yaml` stays unchanged because `tests/deploy/test_render_yaml.py` pins its 4 keys. The CSP stays unchanged (§11).
6. **Off switch.** Unset `CONNECT_ENABLED` on Render and restart. The pages stay but show "Connect is off on this server."
7. **Merge rule.** CI must be green (ruff, pytest at 80% or more, docker smoke) before main. Keep the flag unset on Render through the 2026-11-05 demo unless the user decides to show Connect.

## 4. Module layout

```
app/connect/__init__.py      one-line docstring
app/connect/config.py        ConnectSettings, connect_settings() (cached), flag_on(), fail(), require()
app/connect/store.py         connect.db: accounts + events tables, ~8 small functions
app/connect/stripe_calls.py  client(), call(), every Stripe call (§8), commented per the brief
app/connect/webhooks.py      APIRouter: POST /webhooks/thin, /webhooks/billing (§9)
app/connect/routes.py        APIRouter(prefix="/api/connect"): gate, limits, cookie identity, §7 routes;
                             router.include_router(webhooks.router)
web/src/pages/connect/index.astro          dashboard
web/src/pages/connect/store/index.astro    storefront (?account=acct_...)
web/src/pages/connect/success/index.astro  Checkout success
web/src/scripts/connect/{api,dashboard,store,success}.ts
web/src/styles/page-connect.css
tests/connect/{__init__,conftest,test_routes,test_webhooks,test_live_connect}.py
```

Import rule: `app.main` imports `app.connect.routes`, and Connect never imports `app.main` at module level. `fail()` and `limit()` import `ApiError`, `_hit` and `client_ip` lazily inside the function, the same way `safety/web.py._add_headers` does. Reused as they are: `app.config.get_settings` and `session_hash`, `app.db.SESSION_ID_RE`, and `resolve_mode`, `_call` and `StripeFailure` from `app.integrations.stripe_client`.

Diff to `app/main.py`:

```python
from app.connect.routes import router as connect_router  # spec 10: every route 404s unless CONNECT_ENABLED
...
web.install(app)
app.include_router(connect_router)  # before `api`: its /api/{_rest:path} catch-all would shadow /api/connect/*
app.include_router(api)
```

Diff to `app/safety/web.py`:

```python
WEBHOOK_PATHS = frozenset({"/api/connect/webhooks/thin", "/api/connect/webhooks/billing"})  # spec 10
WEBHOOK_MAX_BODY_BYTES = 65_536  # snapshot events can pass 16 KiB; Stripe retries a 413 then gives up
# _body_too_large: cap = WEBHOOK_MAX_BODY_BYTES if request.url.path in WEBHOOK_PATHS else MAX_BODY_BYTES
# _csrf_error, after the /api/ check:
#     if request.url.path in WEBHOOK_PATHS:  # Stripe sends no header or cookie; route verifies Stripe-Signature
#         return None
```

## 5. Config and env vars

| Env var | Default | Validation | Needed by | Value |
|---|---|---|---|---|
| `CONNECT_ENABLED` | unset (off) | `1/true/yes/on`, case-insensitive; read raw by `flag_on()` so a broken model can't turn "off" into a 503 | all of `/api/connect/*` | `1` locally; on Render only when wanted |
| `STRIPE_SECRET_KEY` | — | existing boot check (`sk_test_`/`rk_test_` only), plus `resolve_mode(key, None)` again before building the client | every Stripe call | already in `.env` and Render |
| `PUBLIC_BASE_URL` | — | `http(s)://host[:port]`, no path, query or trailing slash; must be `https` when `APP_ENV=prod` | onboard, checkout, subscribe, portal | `http://localhost:8000`; `https://<service>.onrender.com` |
| `STRIPE_CONNECT_THIN_WEBHOOK_SECRET` | — | starts with `whsec_` | `/webhooks/thin` | from the thin `stripe listen` or the thin destination |
| `STRIPE_BILLING_WEBHOOK_SECRET` | — | starts with `whsec_` | `/webhooks/billing` | from the snapshot `stripe listen` or the snapshot destination |
| `STRIPE_PLATFORM_PRICE_ID` | — | `^price_[A-Za-z0-9]+$` | `/subscribe` | §15 step 2 |
| `CONNECT_APPLICATION_FEE_CENTS` | `123` (the brief's sample) | int, 0..10000 | `/checkout`, product minimum price | optional |

Rules:

- Values are `.strip()`ed, which makes them safe against CRLF. An empty value counts as unset. `ConnectSettings` is `frozen` with `hide_input_in_errors=True`, and secrets are `SecretStr`. Logs and errors name variables, never values.
- `require(value, "NAME", hint)` returns 503 `connect_not_configured` with "Set NAME (hint) to use this feature." This is the brief's helpful error. `client()` uses it for `STRIPE_SECRET_KEY`.
- An invalid value returns 503 `connect_misconfigured` with "Invalid Connect setting: NAME", built from the field names in the `ValidationError`, never the input.
- `.env.example` gets the 6 keys, each with a `# PLACEHOLDER: ...` comment saying where the value comes from.

## 6. User identity and the mapping store

**A "user" is one browser:**

- The `sp_connect` cookie holds `secrets.token_urlsafe(32)` (43 characters, checked with `app.db.SESSION_ID_RE`). It is HttpOnly, SameSite=Lax, Secure when `APP_ENV=prod`, path `/api/connect`, with max-age `SESSION_TTL_HOURS`. Only `POST /api/connect/accounts` sets it. A GET never creates a cookie.
- The server stores only `session_hash(token)` (R21). The raw token never leaves the `Set-Cookie` header.
- The display name and contact email come from the form and go to Stripe as `display_name` and `contact_email`. Only the display name is kept locally, as the public shop name on the storefront. The email is not stored or logged.
- Each user gets one account. There is no login, so clearing cookies creates a new user; the caps in §10 bound the cost.

**Schema** for `DATA_DIR/connect.db`. Open it like `llm/budget.py` does: `sqlite3.connect(path, timeout=5)`, `CREATE TABLE IF NOT EXISTS` on open, and `with closing(conn), conn:`.

```sql
CREATE TABLE IF NOT EXISTS accounts (
  session_hash TEXT PRIMARY KEY,         -- the user (hash of sp_connect)
  account_id   TEXT NOT NULL UNIQUE,     -- acct_...: connected account AND customer (customer_account)
  display_name TEXT NOT NULL,            -- storefront header
  products_created INTEGER NOT NULL DEFAULT 0,
  created_at   TEXT NOT NULL,            -- UTC ISO; the global daily cap counts these
  -- platform plan, written only by the billing webhook (brief: store subscription status)
  sub_id TEXT, sub_status TEXT, sub_price_id TEXT, sub_quantity INTEGER,
  sub_cancel_at_period_end INTEGER, sub_paused INTEGER, sub_updated_at TEXT);
CREATE TABLE IF NOT EXISTS events (      -- webhook dedupe + "recent Stripe events" on the dashboard
  id TEXT PRIMARY KEY,                   -- evt_... (snapshot) or the v2 event id (thin)
  type TEXT NOT NULL,
  account_id TEXT,                       -- related_object.id (thin) or customer_account (snapshot)
  received_at TEXT NOT NULL);
CREATE INDEX IF NOT EXISTS ix_events_account ON events(account_id, received_at);
```

**Never stored:** onboarding, requirement or capability status (the brief forbids it), the contact email, the raw cookie, webhook bodies and keys.

**Ephemeral on Render:** the file lives in `/tmp`, so a restart or deploy forgets every mapping and plan status, while the objects stay in the sandbox. While the cookie lives (24 h), creating again with the same details replays the same account through the idempotency key `connect-acct:{session_hash}`, which restores the mapping. (V2 idempotency keys last 30 days per account; the 24 h cookie is the tighter bound.)

## 7. HTTP API

All routes live under `/api/connect` and use the JSON error envelope `{"error": {"code", "message"}}`. `web.py` already sets `Cache-Control: no-store`. Browser POSTs send `X-ShopPilot: 1` (the existing CSRF check). The two webhooks are exempt and check the signature instead.

| Method and path | Caller | Input | What it does | 200 body |
|---|---|---|---|---|
| GET `/account` | cookie, optional | — | No mapping: return `{"account": null}` without calling Stripe. Otherwise: live `accounts.retrieve`, plus the plan from the DB and the last 5 events | `{"account": {...} or null, "fee_cents", "plan_available"}` |
| POST `/accounts` | sets the cookie | `{display_name: 1-80, contact_email: ≤254}` | If a mapping exists, return it with no Stripe call. Otherwise check caps, create the V2 account, insert the mapping | `{"account_id", "created"}` |
| POST `/onboard` | cookie + account | — | Create a V2 account link | `{"url"}` |
| POST `/products` | cookie + account | `{name: 1-80, description: 0-500, price_cents: 100-100000 and > fee, currency: "usd"}` | Check the plan cap, `products.create` on the account, add 1 to the counter | `{"id", "products_created", "product_limit"}` |
| GET `/store/{account_id}` | public | `^acct_[A-Za-z0-9]{8,64}$`; the account must be in `accounts` | `products.list` on the account | `{"account_id", "display_name", "products": [{id, name, description, unit_amount, currency}]}` |
| POST `/checkout` | public | `{account_id, product_id: ^prod_..., quantity: 1-10}` | For a known account: retrieve the product and price on the account, then create a Checkout direct charge | `{"url"}` |
| POST `/subscribe` | cookie + account | — | Return 409 if a plan is already open. Otherwise create a platform Checkout session with `customer_account` | `{"url"}` |
| POST `/portal` | cookie + account | — | Create a Billing Portal session with `customer_account` | `{"url"}` |
| POST `/webhooks/thin` | Stripe | raw body + `Stripe-Signature` | §9.1 | `{"received": true}` |
| POST `/webhooks/billing` | Stripe | raw body + `Stripe-Signature` | §9.2 | `{"received": true}` |

The `account` object returned by GET has: `id`, `display_name` and `contact_email` (from Stripe), `card_payments_status`, `requirements_status`, `ready_to_process_payments`, `onboarding_complete`, `products_created`, `product_limit`, `plan` (`status`, `price_id`, `quantity`, `cancel_at_period_end`, `paused`, `has_pro`, or null), `storefront_path` and `events` (5 items of `type` and `received_at`). Redirect URLs always come from `PUBLIC_BASE_URL`, never from the `Host` header (uvicorn runs without proxy headers, R45).

## 8. Stripe calls (exact names for stripe-python 16.1.0)

This is a sketch. The real file adds the brief's step-by-step comments. Every call goes through `call()`. In an f-string, `{{CHECKOUT_SESSION_ID}}` becomes the literal `{CHECKOUT_SESSION_ID}` that Stripe fills in.

```python
@functools.cache
def client() -> stripe.StripeClient:
    # PLACEHOLDER: STRIPE_SECRET_KEY=sk_test_... (sandbox) in .env / Render env.
    key = require(get_settings().stripe_secret_key, "STRIPE_SECRET_KEY", "a sandbox key, sk_test_...")
    raw = key.get_secret_value().strip()
    resolve_mode(raw, None)  # reused guard: raises unless sk_test_/rk_test_; live keys never work
    return stripe.StripeClient(raw, max_network_retries=2)  # no stripe_version: SDK pins 2026-10-28.endive

STATUS = {"stripe_invalid_request": 422, "stripe_rate_limited": 429, "idempotency_conflict": 409,
          "stripe_error": 502}  # everything else (auth, unreachable, live_mode_blocked) -> 503

def call(fn):
    try:
        return _call(fn)  # reused: safe error codes/messages, blocks any livemode object
    except StripeFailure as e:
        fail(STATUS.get(e.code, 503), e.code, e.user_message)

def create_account(sh: str, display_name: str, contact_email: str) -> str:
    params = {  # exactly the brief's properties; never a top-level "type"
        "display_name": display_name,
        "contact_email": contact_email,
        "identity": {"country": "us"},
        "dashboard": "full",
        "defaults": {"responsibilities": {"fees_collector": "stripe", "losses_collector": "stripe"}},
        "configuration": {
            "customer": {},
            "merchant": {"capabilities": {"card_payments": {"requested": True}}},
        },
    }
    return call(lambda: client().v2.core.accounts.create(
        params, {"idempotency_key": f"connect-acct:{sh}"})).id

def account_status(acct: str) -> dict:
    a = call(lambda: client().v2.core.accounts.retrieve(
        acct, {"include": ["configuration.merchant", "requirements"]}))
    card = dig(a, "configuration", "merchant", "capabilities", "card_payments", "status")
    req = dig(a, "requirements", "summary", "minimum_deadline", "status")
    return {"display_name": a.display_name, "contact_email": a.contact_email,
            "card_payments_status": card, "requirements_status": req,
            "ready_to_process_payments": card == "active",
            "onboarding_complete": req not in ("currently_due", "past_due")}

def onboarding_link(acct: str, base: str) -> str:
    return call(lambda: client().v2.core.account_links.create({
        "account": acct,
        "use_case": {"type": "account_onboarding", "account_onboarding": {
            # The brief also passes configurations: ['merchant', 'customer']; API 2026-09-30.endive
            # removed it (400 "Unknown field", F3). Stripe uses the account's applied configurations.
            "refresh_url": f"{base}/connect/?refresh=1",
            "return_url": f"{base}/connect/?accountId={acct}",
        }},
    })).url

def create_product(acct, name, description, price_cents, currency, idem) -> str:
    params = {"name": name, "default_price_data": {"unit_amount": price_cents, "currency": currency}}
    if description:
        params["description"] = description  # Stripe rejects an empty string
    return call(lambda: client().v1.products.create(
        params, {"stripe_account": acct, "idempotency_key": idem})).id
    # idem = f"connect-prod:{acct}:{products_created}:{sha256(body)[:12]}": a double click replays

def list_products(acct: str) -> list[dict]:
    res = call(lambda: client().v1.products.list(
        {"limit": 20, "active": True, "expand": ["data.default_price"]}, {"stripe_account": acct}))
    return [{"id": p.id, "name": p.name, "description": p.description,
             "unit_amount": p.default_price.unit_amount, "currency": p.default_price.currency}
            for p in res.data if p.default_price and p.default_price.type == "one_time"]

def product_checkout(acct, product_id, quantity, fee, base) -> str:
    p = call(lambda: client().v1.products.retrieve(
        product_id, {"expand": ["default_price"]}, {"stripe_account": acct}))
    price = p.default_price  # the amount comes from Stripe, never from the browser
    # 422 product_unavailable unless p.active and price.type == "one_time";
    # 422 price_below_fee if fee >= price.unit_amount * quantity
    return call(lambda: client().v1.checkout.sessions.create({
        "line_items": [{"price_data": {"currency": price.currency, "unit_amount": price.unit_amount,
                                       "product": p.id}, "quantity": quantity}],
        "payment_intent_data": {"application_fee_amount": fee},  # direct charge, platform fee
        "mode": "payment",
        "success_url": f"{base}/connect/success/?session_id={{CHECKOUT_SESSION_ID}}&account={acct}",
        "cancel_url": f"{base}/connect/store/?account={acct}",
    }, {"stripe_account": acct})).url

def subscription_checkout(acct, price_id, base) -> str:
    return call(lambda: client().v1.checkout.sessions.create({  # platform level: no stripe_account
        "customer_account": acct,  # V2: the connected account IS the customer; never `customer`
        "mode": "subscription",
        "line_items": [{"price": price_id, "quantity": 1}],
        "success_url": f"{base}/connect/?subscribed=1&session_id={{CHECKOUT_SESSION_ID}}",
        "cancel_url": f"{base}/connect/",
    })).url

def portal(acct, base) -> str:
    return call(lambda: client().v1.billing_portal.sessions.create(
        {"customer_account": acct, "return_url": f"{base}/connect/"})).url

def parse_thin(raw, sig, secret):      return client().parse_event_notification(raw, sig, secret)
def parse_snapshot(raw, sig, secret):  return client().construct_event(raw, sig, secret)
def fetch_event(event_id):             return call(lambda: client().v2.core.events.retrieve(event_id))
def subscription_account(sub_id):      return call(lambda: client().v1.subscriptions.retrieve(sub_id)).customer_account

OPEN = ("active", "trialing", "past_due", "unpaid", "incomplete", "paused")  # "has a plan to manage"

def plan_summary(acct: str) -> dict | None:
    subs = call(lambda: client().v1.subscriptions.list(
        {"customer_account": acct, "status": "all", "limit": 10})).data
    best = (next((s for s in subs if s.status in ("active", "trialing")), None)
            or next((s for s in subs if s.status in OPEN), None) or (subs[0] if subs else None))
    if best is None:
        return None
    item = best.items.data[0]  # brief: items.data[0].price / .quantity
    return {"sub_id": best.id, "sub_status": best.status, "sub_price_id": item.price.id,
            "sub_quantity": item.quantity, "sub_cancel_at_period_end": best.cancel_at_period_end,
            "sub_paused": best.pause_collection is not None}  # null pause_collection = resumed

# dig(obj, *path): getattr(obj, p, None) down the path, None if any step is missing (F10)
```

## 9. Webhooks

Both routes are `async def`. Each one reads `raw = await request.body()` (the untouched raw bytes that the signature covers), then runs `await run_in_threadpool(handler, raw, request.headers.get("stripe-signature"))`. The Stripe SDK is synchronous and must not block the event loop. If any Stripe call fails, the route returns 5xx, nothing is recorded, and Stripe retries (in the sandbox: 3 times over a few hours).

### 9.1 Thin: `/api/connect/webhooks/thin`

1. Secret: `require(cs.stripe_connect_thin_webhook_secret, "STRIPE_CONNECT_THIN_WEBHOOK_SECRET", ...)`. If it's missing, return 503.
2. `notif = parse_thin(raw, sig, secret)`. `stripe.SignatureVerificationError`, `ValueError` or `KeyError` → 400 `bad_signature`. `notif.livemode` → 400.
3. If `store.seen(notif.id)`, return 200 `{"received": true, "duplicate": true}`.
4. `event = fetch_event(notif.id)`: the brief's `v2.core.events.retrieve`.
5. `account = dig(event, "related_object", "id")`, then call `THIN_HANDLERS.get(event.type, on_unknown)(event, account)`.
6. `store.record_event(notif.id, event.type, account)` and return 200.

| Type | Handler | Action |
|---|---|---|
| `v2.core.account[requirements].updated` | `on_requirements_updated` | Log only. The dashboard reads requirements live and shows "Onboard to collect payments" again on `currently_due` or `past_due`. That is how the app collects updated requirements |
| `v2.core.account[configuration.merchant].capability_status_updated` | `on_capability_updated` | Log only; `card_payments` status is read live |
| `v2.core.account[configuration.customer].capability_status_updated` | `on_capability_updated` | Log only |
| `v2.core.account[configuration.recipient].capability_status_updated` | `on_capability_updated` | Log only. It is in the brief's listen list, but our accounts have no recipient configuration |

### 9.2 Snapshot: `/api/connect/webhooks/billing`

1. Secret: `STRIPE_BILLING_WEBHOOK_SECRET`; return 503 if it is missing.
2. `event = parse_snapshot(raw, sig, secret)`. Signature or parse errors → 400. `event.livemode` → 400.
3. Skip duplicates with `store.seen(event.id)`.
4. `account = getattr(event.data.object, "customer_account", None)`. Never read `.customer`. For a `customer.subscription.*` event without `customer_account` (a destination on an older API version), fall back to `subscription_account(obj.id)`.
5. For `customer.subscription.created`, `.updated` and `.deleted`: call `store.set_plan(account, plan_summary(account))`. Re-reading Stripe's current state makes out-of-order events, duplicates, upgrades, downgrades, quantity changes, cancellations and pauses all settle on the right answer.
6. Every other type: record it and log one line naming the check the brief describes.
7. `store.record_event(event.id, event.type, account)` and return 200.

| Event | Handling |
|---|---|
| `customer.subscription.created` (**added**: the first status after Checkout, which an update doesn't always follow) | Sync the plan |
| `customer.subscription.updated` | Sync the plan: price `items.data[0].price.id`, quantity, `cancel_at_period_end` (false again means reactivated), `pause_collection` (null means resumed) |
| `customer.subscription.deleted` | Sync the plan to `canceled`, which revokes access |
| `payment_method.attached`, `payment_method.detached` | Record |
| `customer.updated` | Record. Billing information only; never a login credential (identity is the cookie) |
| `customer.tax_id.created`, `.deleted`, `.updated` | Record |
| `billing_portal.configuration.created`, `.updated` | Record |
| `billing_portal.session.created` | Record |

### 9.3 Plan and access

- `has_pro = sub_status in ("active", "trialing") and not sub_paused`.
- What Pro grants (the "products or services they're actively subscribed to"): a product cap of 20 instead of 3. After a downgrade, cancellation or pause the cap drops back to 3. Existing products stay; new ones are blocked.
- The Subscribe button is hidden, and `POST /subscribe` returns 409, while `sub_status` is in `OPEN`. "Manage billing" is shown whenever `sub_id` is set.

## 10. Abuse caps (public URL)

| Cap | Value | Where |
|---|---|---|
| All `/api/connect/*` per IP | 60/min | router dependency `limit("connect", 60)`, using main's `_hit` and `client_ip` (rightmost XFF, R45) |
| Browser POSTs per IP | 10/min | `limit("connect_write", 10)` on the 6 non-webhook POSTs |
| Account creation per IP | 3/hour | counted only when a new account is about to be created |
| Accounts per UTC day, global | 20 | `COUNT(*) FROM accounts WHERE created_at >= today` → 429 `connect_capacity` |
| Accounts per user | 1 | mapping check, plus the idempotency key `connect-acct:{sh}` |
| Products per account | 3 (20 with Pro) | `products_created` counter → 403 `product_limit` |
| Product price | $1.00 to $1,000.00, above the fee, USD only | pydantic validation plus a check |
| Checkout quantity | 1 to 10 | pydantic |
| Storefront and checkout scope | accounts in `connect.db` only | 404 otherwise, so the API can't be used to probe other platform accounts |
| Text fields | name 80, description 500, display name 80, email 254 | pydantic (errors never echo input) |
| Webhook body | 64 KiB (every other path stays at 16 KiB) | `web.py` |
| Kill switch | unset `CONNECT_ENABLED` | Render env |

`# ponytail:` the per-IP buckets and the daily count reset on restart (R48). It's a sandbox, so no real money is at stake.

## 11. CSP, CSRF and cookies

- **The CSP stays as it is.** Pages run bundled scripts from `/_astro/` (`script-src 'self'`) and fetch only `/api/connect/*` (`connect-src 'self'`). To reach a Stripe page, the browser calls `location.assign(url)` after a fetch. That is a top-level navigation, and CSP does not govern it. `web.py` does set `form-action 'self'`, but no form posts to Stripe: every form calls `preventDefault()` and uses fetch, which it must do anyway to send `X-ShopPilot`. So no Stripe host is added. If a future change posted an HTML form that 303-redirects to Stripe, `form-action` would need `https://checkout.stripe.com https://connect.stripe.com https://billing.stripe.com`. Keep the fetch flow instead.
- Before navigating, `goStripe(url)` in `api.ts` requires `https:` and a hostname of `stripe.com` or one ending in `.stripe.com`; otherwise it shows an error. This prevents an open redirect from a bad response.
- **CSRF.** Browser POSTs keep the existing checks: `X-ShopPilot: 1`, Origin and JSON content type. The exemption covers exactly `/api/connect/webhooks/thin` and `/api/connect/webhooks/billing`, with no prefix match and no trailing slash. Stripe sends no custom header and no cookie, so those routes verify `Stripe-Signature` instead (HMAC-SHA256, 300 s tolerance).
- **Cookie:** see §6. SameSite=Lax still lets our own same-site fetches carry it after Stripe redirects back.

## 12. Pages (Astro)

| URL | Files | Content |
|---|---|---|
| `/connect/` | `pages/connect/index.astro`, `scripts/connect/dashboard.ts` | 1) Create-account form: display name and contact email. 2) Account card: id, name and live pills ("Payments: active / pending / restricted", "Onboarding: complete / currently due / past due"). "Onboard to collect payments" shows unless the account is both ready and complete. A "Refresh status" button. 3) Create-product form: name, description, price in dollars (sent as cents) and a currency select with only USD. Below it, the product list and "Open your storefront". 4) Platform plan: a status line, "Subscribe to ShopPilot+ Pro" and "Manage billing". 5) The 5 most recent Stripe events. URL parameters: `refresh=1` requests a fresh link once (call `history.replaceState` first); `accountId` shows "Back from Stripe; status below is live"; `subscribed=1` shows "Your plan updates when Stripe's webhook arrives". |
| `/connect/store/?account=acct_...` | `pages/connect/store/index.astro`, `scripts/connect/store.ts` | Shop name and product cards (name, description, price). Buy calls POST `/checkout`, then goes to Stripe Checkout. The page carries the comment `<!-- Demo: the shop is picked by its Stripe account ID. In production use your own shop slug or ID, not the Stripe account ID. -->`. The route has a matching Python comment. |
| `/connect/success/?session_id=...&account=...` | `pages/connect/success/index.astro`, `scripts/connect/success.ts` | "Payment received (sandbox)", the session id and a "Back to the shop" link. The page is not proof of payment (§17). |

- Use `Site.astro` with `surface="morning"` and the existing `.wrap`, `.btn`, `.btn-primary`, `.btn-line` and `.pill--done|running|approval|failed` classes. `page-connect.css` adds about 50 lines of token-only styles for fields, cards and the product grid. This meets the brief's "clean, simple HTML with basic styling ... use the current style of my application".
- Render every piece of user or Stripe text with `textContent`, never `innerHTML`. Product names are public user input.
- `api.ts` is a new 20-line fetch helper: JSON, `X-ShopPilot: 1` on POST, envelope errors, and `goStripe()`. The console's `api.ts` is not reused: it swaps in console fixtures when `?fixtures=` is set, and it recovers from `no_session` by creating a demo store.
- If the first GET returns 404 `not_found`, show "Connect is off on this server." If it returns 503 `connect_not_configured`, show the message, which names the env var.
- Every input has a label. Notices go in an `aria-live="polite"` region. Buttons are disabled while a request is running. The pages are not linked from the nav or footer, and existing pages are unchanged.

## 13. Errors

| Status | Code | When |
|---|---|---|
| 404 | `not_found` | flag off; unknown shop |
| 404 | `no_account` | the route needs an account and this cookie has none |
| 403 | `csrf` | existing check: a non-webhook POST without the header |
| 403 | `product_limit` | plan cap reached |
| 409 | `already_subscribed` | a plan is already open |
| 409 | `idempotency_conflict` | the same cookie re-submits an account create with different details (V2 keys last 30 days; the 24 h cookie bounds it) |
| 400 | `bad_signature` | invalid webhook signature or payload, or a live-mode event |
| 422 | `bad_request` | validation (the input is never echoed) |
| 422 | `price_below_fee` | price is at or below the fee, at create or at checkout |
| 422 | `product_unavailable` | the product is inactive or has no one-time default price |
| 422 | `stripe_invalid_request` | Stripe rejected the call, for example a shop that isn't onboarded or a portal that isn't saved. The UI adds the likely cause |
| 429 | `rate_limited`, `connect_capacity`, `stripe_rate_limited` | caps |
| 502 | `stripe_error` | any other Stripe error |
| 503 | `connect_not_configured`, `connect_misconfigured` | an env var is missing or invalid; the message names it |
| 503 | `stripe_unreachable`, `stripe_auth`, `live_mode_blocked` | mapped by `_call` |

## 14. Test plan

### 14.1 CI (mocked; the `no_network` fixture stays on)

Fixtures in `tests/connect/conftest.py`:

- `connect_env`: sets `CONNECT_ENABLED=1`, `STRIPE_SECRET_KEY=sk_test_dummy`, `PUBLIC_BASE_URL=http://testserver`, `STRIPE_CONNECT_THIN_WEBHOOK_SECRET=whsec_thin_test`, `STRIPE_BILLING_WEBHOOK_SECRET=whsec_billing_test` and `STRIPE_PLATFORM_PRICE_ID=price_test1`, then clears the `get_settings`, `connect_settings` and `stripe_calls.client` caches.
- `fake_stripe`: a real `stripe.StripeClient("sk_test_dummy")` set as `stripe_calls.client`, so `parse_event_notification` and `construct_event` really verify signatures offline. Network methods are replaced with recorders, for example `monkeypatch.setattr(c.v2.core.accounts, "create", rec)`. Recorders return `SimpleNamespace(..., livemode=False)`. Do not use MagicMock: its `livemode` attribute is truthy and trips `_call`'s live-mode guard.
- `sign(payload, secret)` returns `f"t={t},v1={hmac_sha256(secret, f'{t}.{payload}')}"`.
- In the root `tests/conftest.py`, `tmp_data_dir` also clears the `connect_settings` and `client` caches, so test order never matters.

| # | File | Test |
|---|---|---|
| 1 | test_routes | With the flag unset, GET and POST on every Connect route, webhooks included, return 404 `not_found`. No Stripe call is made and no `connect.db` file appears |
| 2 | test_routes | Connect routes are registered before `/api/{_rest:path}`, and `/api/nope` still returns a JSON 404 |
| 3 | test_routes | With the flag on and a bad `PUBLIC_BASE_URL`, Connect returns 503 `connect_misconfigured` while `/healthz` stays 200. With the flag off and the same bad value, Connect returns 404 |
| 4 | test_routes | Create account: params equal the brief's dict exactly (no `type`, no extra keys) and the idempotency key is `connect-acct:<hash>`. The cookie is HttpOnly with path `/api/connect`. The DB holds the hash, not the token. A second POST returns the same id without a Stripe call |
| 5 | test_routes | Caps: the 4th create from one IP within an hour → 429. With the daily cap monkeypatched to 1 → 429 `connect_capacity`. A bad email or an 81-character name → 422 |
| 6 | test_routes | Status: retrieve is called with `include == ["configuration.merchant", "requirements"]`. `active` plus `eventually_due` → ready and complete; `currently_due` → not complete. The DB is unchanged after the GET |
| 7 | test_routes | Onboard: params equal `{account, use_case: {type, account_onboarding: {refresh_url, return_url}}}`, with no `configurations`, and the URLs come from `PUBLIC_BASE_URL` |
| 8 | test_routes | Product: sent with the `{"stripe_account": acct}` option and `default_price_data`. An empty description is omitted. The 4th product → 403, but it is allowed with a Pro plan in the DB. A price at or below the fee → 422 |
| 9 | test_routes | Storefront: list params are `{limit: 20, active: True, expand: ["data.default_price"]}` plus `stripe_account`. A product with a recurring price is filtered out. An unknown or malformed account → 404 or 422 |
| 10 | test_routes | Checkout: the product is retrieved with `stripe_account`; `price_data` comes from the Stripe price; `application_fee_amount` equals the env fee; `mode` is `payment`; the success URL contains the literal `{CHECKOUT_SESSION_ID}`; the `stripe_account` option is set. A fee at or above the amount → 422 |
| 11 | test_routes | Subscribe: sends `customer_account`, mode `subscription` and the price from env, with no `stripe_account` and no `customer`. A missing price env → 503 naming it. An open plan → 409 |
| 12 | test_routes | Portal sends only `{customer_account, return_url}` |
| 13 | test_routes | A live-mode object from any call → 503 `live_mode_blocked`. A Stripe `InvalidRequestError` → 422 envelope without Stripe's raw message |
| 14 | test_webhooks | Thin: a signed payload without `X-ShopPilot` → 200. `events.retrieve` is called once with the id, the right handler runs and the event row is stored. A replay → duplicate, with no second retrieve. A bad signature → 400. Secret unset → 503. A failed retrieve → 5xx and no row |
| 15 | test_webhooks | Billing: a signed `customer.subscription.updated` triggers `subscriptions.list(customer_account=...)`, and the row gets status, price, quantity, `cancel_at_period_end` and paused. `deleted` → canceled, and the product cap drops back to 3. `payment_method.attached` is recorded only. A missing `customer_account` falls back to `subscriptions.retrieve`. `.customer` is never read |
| 16 | test_webhooks | The CSRF exemption is exact: `/api/connect/webhooks/thin/` and `/api/connect/webhooksX` without the header → 403, and `/api/connect/products` without the header → 403 |
| 17 | test_webhooks | Body cap: 40 KiB sent to a webhook path reaches the signature check (400, not 413). 20 KiB sent to `/api/connect/products` → 413 |

### 14.2 Live (`tests/connect/test_live_connect.py`, `pytestmark = pytest.mark.live`)

These tests call `stripe_calls` directly against the sandbox, using the test user account from F8.

```bash
set -a; . ./.env; set +a
RUN_LIVE=1 CONNECT_TEST_ACCOUNT_ID=acct_1UXQy4AjPf69rvVR uv run pytest tests/connect/test_live_connect.py -m live -v
```

1. `account_status(test account)` reports ready and complete.
2. `onboarding_link` returns a `https://connect.stripe.com/...` URL.
3. `create_product`, then `list_products` shows it; afterwards archive it with `products.update(id, {"active": False}, {"stripe_account": ...})`.
4. `product_checkout` returns a `https://checkout.stripe.com/...` URL.
5. `subscription_checkout` (needs `STRIPE_PLATFORM_PRICE_ID`) and `portal` (needs H2) return Stripe URLs. Each skips with a named reason when its prerequisite is missing.
6. Opt-in only, with `CONNECT_LIVE_CREATE=1`: `create_account` with the brief's params creates a new sandbox account. It doesn't run by default because every run would add an account.

### 14.3 Manual end-to-end (local, §16 H3 to H5, about 10 minutes)

1. Create an account, then onboard with Stripe's Connect test data (docs.stripe.com/connect/testing).
2. Check that the status changes live and that listener A shows 200s.
3. Create a product, open the storefront and pay with `4242 4242 4242 4242`; the success page appears.
4. Subscribe: the plan becomes active and listener B shows 200s.
5. Use "Manage billing" to cancel: the plan updates and the product cap returns to 3.

Gates: `uv run ruff check . && uv run ruff format --check . && uv run pytest -m "not live" --cov-fail-under=80`. `cd web && npm run build:app` must build the 3 pages. The CI docker smoke is unchanged.

## 15. Build order (implementer)

1. Do H1 (fix CRLF) first, or every live call fails.
2. Create the platform price. The brief says to create it when tools allow, and the Stripe CLI is logged in to the sandbox:
   `stripe prices create --currency=usd --unit-amount=900 -d "recurring[interval]=month" -d "product_data[name]=ShopPilot+ Pro (sandbox)" -d "lookup_key=shoppilot_pro_monthly"`
   Put the returned `price_...` id in `.env` as `STRIPE_PLATFORM_PRICE_ID`. It is not a secret.
3. Follow the repo's TDD rule: write §14.1 tests 1 to 17 first. Then build `config.py`, `store.py`, `stripe_calls.py`, `webhooks.py` and `routes.py`, then make the `main.py`, `web.py`, `conftest.py` and `.env.example` edits.
4. Frontend: pages, scripts and CSS, then `cd web && npm run build:app`.
5. Run the gates (§14.1), the live tests (§14.2) and the manual check (§14.3).
6. Don't commit; report back.

## 16. Human steps (exact)

**H1.** Fix the `.env` line endings. Values are unchanged and nothing is printed:
`cd "/mnt/c/Users/DangT/curseforge/Downloads/A4 Prompt Engineering/shoppilot" && sed -i 's/\r$//' .env`
(Optional separate hardening: strip values in `Settings._empty_is_none` in `app/config.py`.)

**H2.** Save the sandbox's Customer portal settings once. In the Stripe Dashboard (sandbox "A4-PromptEngineering-ShopPilot"), go to Settings, Billing, Customer portal. Turn on "Cancel subscriptions" and "Update payment methods", then Save. Today the sandbox has 0 portal configurations, and portal sessions fail until one exists.

**H3.** Add these lines to `.env` in an editor (don't echo them):

```
CONNECT_ENABLED=1
PUBLIC_BASE_URL=http://localhost:8000
STRIPE_PLATFORM_PRICE_ID=price_...          # from §15 step 2
STRIPE_CONNECT_THIN_WEBHOOK_SECRET=whsec_... # printed by H4 terminal A
STRIPE_BILLING_WEBHOOK_SECRET=whsec_...      # printed by H4 terminal B
```

**H4.** Start the local listeners in two terminals and keep both running.

Terminal A uses the brief's command, with the `[.recipient]` typo fixed. CLI 1.55.6 prints a deprecation notice but works:

```bash
stripe listen --thin-events 'v2.core.account[requirements].updated,v2.core.account[configuration.recipient].capability_status_updated,v2.core.account[configuration.merchant].capability_status_updated,v2.core.account[configuration.customer].capability_status_updated' --forward-thin-to localhost:8000/api/connect/webhooks/thin
```

The newer syntax does the same thing: `stripe listen --events '<same list>' --forward-to localhost:8000/api/connect/webhooks/thin`.

Terminal B receives the snapshot billing events. `--latest` makes the payloads carry `customer_account`:

```bash
stripe listen --latest --events customer.subscription.created,customer.subscription.updated,customer.subscription.deleted,payment_method.attached,payment_method.detached,customer.updated,customer.tax_id.created,customer.tax_id.deleted,customer.tax_id.updated,billing_portal.configuration.created,billing_portal.configuration.updated,billing_portal.session.created --forward-to localhost:8000/api/connect/webhooks/billing
```

Each listener prints "Ready! Your webhook signing secret is whsec_...". Paste A's secret into `STRIPE_CONNECT_THIN_WEBHOOK_SECRET` and B's into `STRIPE_BILLING_WEBHOOK_SECRET`.

**H5.** Run the app:
`cd web && npm run build:app && cd .. && set -a; . ./.env; set +a; .venv/bin/uvicorn app.main:app --port 8000`
Then open http://localhost:8000/connect/.

**H6.** Render. Do this only when Connect should be live there; otherwise leave it unset for the 2026-11-05 demo. In the Render Dashboard, open shoppilot, then Environment, and add `CONNECT_ENABLED=1`, `PUBLIC_BASE_URL=https://<service>.onrender.com`, `STRIPE_PLATFORM_PRICE_ID`, and the two webhook secrets from H7 (`STRIPE_CONNECT_THIN_WEBHOOK_SECRET`, `STRIPE_BILLING_WEBHOOK_SECRET`). `CONNECT_APPLICATION_FEE_CENTS` is optional. Save and deploy. `render.yaml` stays unchanged.

**H7.** Create the Stripe event destinations for Render. With the sandbox selected, go to Workbench, Webhooks, "Create an event destination".

a. **Thin:**
   1. Events from: **Your account** (see F5; the brief says Connected accounts).
   2. Payload: **Thin**.
   3. Events: `v2.core.account[requirements].updated`, `v2.core.account[configuration.merchant].capability_status_updated` and `v2.core.account[configuration.customer].capability_status_updated`.
   4. Destination type: Webhook endpoint. URL: `https://<service>.onrender.com/api/connect/webhooks/thin`.
   5. Reveal the secret and set it as Render's `STRIPE_CONNECT_THIN_WEBHOOK_SECRET`.

b. **Snapshot:**
   1. Events from: **Your account**.
   2. Payload: **Snapshot**, API version **2026-10-28.endive**.
   3. Events: the 12 from H4 terminal B.
   4. URL: `https://<service>.onrender.com/api/connect/webhooks/billing`.
   5. Set the secret as Render's `STRIPE_BILLING_WEBHOOK_SECRET`.

Check: after one onboarding on Render, the thin destination's Event deliveries tab should show 200s. If it shows nothing, add the same thin destination with Events from set to **Connected accounts**. On the free plan the instance sleeps, so the first delivery may time out; Stripe retries.

## 17. Known limits and later work

| Limit | Upgrade when needed |
|---|---|
| `connect.db` sits in Render's `/tmp`, so a restart or deploy forgets mappings and plan status | Render disk or Postgres |
| Anonymous cookie identity with no recovery; clearing cookies creates a new account | Real login, with the mapping keyed by user id |
| The storefront is keyed by the Stripe account ID (the brief allows this) | A shop slug |
| The success page is not proof of payment, and there is no fulfillment | `checkout.session.completed` from the Connected accounts scope |
| One platform price; Pro only raises the product cap to 20 | A price-to-tier map |
| Sandbox accounts pile up (there is no delete route), and in-process limits reset on restart (R48) | An admin cleanup script |

## 18. Implementation notes (2026-11-02)

Built as designed, with these changes:

| # | Change | Why |
|---|---|---|
| I1 | FastAPI 0.162 keeps included routers as `_IncludedRouter` entries in `app.routes`; test 2 checks `original_router` order, plus a live GET | `app.routes` is no longer flattened |
| I2 | `call(fn, hint)`: a 422 `stripe_invalid_request` message gets a route-specific likely cause (portal: "save the Customer portal settings", checkout: "finish onboarding", subscribe: "check STRIPE_PLATFORM_PRICE_ID") | §13 said the UI adds it; server-side is one place and tested |
| I3 | `fetch_event(id, context)` passes `stripe_context` when the thin notification has one | makes the H7 "Connected accounts" fallback destination work |
| I4 | `require(value, NAME)` reads the hint from one `HINTS` table; message and log line: `NAME is not set: <hint>.` | e.g. `STRIPE_PLATFORM_PRICE_ID is not set: run scripts/create_platform_price.py and put the price_... id it prints in .env.` |
| I5 | Platform price made by `scripts/create_platform_price.py` (idempotent: lookup key `shoppilot_pro_monthly`, product tagged `metadata.shoppilot_platform=1`), not the §15 CLI line | re-runs reuse it. Result: `price_1UXT6UAjPfce7GIjThhrPC3u` ($9.00/month) |
| I6 | `app/config.py` unchanged; `tests/conftest.py` +4 lines; `.env.example` LLM budgets aligned to the code defaults (2.0 / 0.25) | copying the old example would have raised the Anthropic caps |
| I7 | Buy buttons are `.btn-line` | BRAND rule 4: one primary button per screen |
| I8 | Astro strips HTML comments from the build, so the storefront's "use your own shop ID" comment lives in `store/index.astro`, `store.ts` and `routes.py` | brief's comment is for developers reading the code |

Known limit added: the gate is a router dependency, and FastAPI parses a JSON body before dependencies, so with the flag off a POST with malformed JSON gets 422 instead of 404. No side effects (no DB, no Stripe).

Verified on 2026-11-02: `pytest -m "not live"` 936 passed (142 of them in `tests/connect/`), coverage 97.63%, `ruff check` and `ruff format --check` clean, `npm run build:app` builds the 3 pages; live tests against `acct_1UXQy4AjPf69rvVR` 6 pass, 2 skip (portal waits for H2; account create is opt-in). The opt-in create ran once and made `acct_1UXTAGAjPfD2a3nU` (not onboarded). A real `stripe trigger customer.updated` through `stripe listen` reached `/api/connect/webhooks/billing` with a 200 and was recorded. `.env` already had LF endings (H1 done).
