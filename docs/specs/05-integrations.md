# 05 — Layer 4: real APIs (Stripe test mode, fake outbox, export)

Planner P5, 2026-10-30. Reads `00-shared-brief.md` (frozen). Owns `app/integrations/*` and five tool modules: `refund_order`, `create_payment_link`, `send_email`, `mark_shipped`, `export_report`.

Research note: the Haiku search agents could not start (the concurrent-subagent limit was reached). P5 fetched every source below with WebFetch/WebSearch on 2026-10-30. "fetched" means the page was opened. "search-only" means the figure came from search snippets.

## 1. Decisions

| # | Decision | Why |
|---|---|---|
| D1 | **Use the direct Stripe Python SDK (`stripe~=16.0`) for every Stripe write. Do not use the Stripe MCP server in the core product.** | See section 2. In short, the Anthropic MCP connector runs tool calls inside the API with no approval hook, so our validator, dry-run and confirm gate cannot sit in front of a refund. Stripe's own approval link opens in the shop owner's Dashboard, which graders cannot reach. |
| D2 | **Create the Stripe PaymentIntent lazily, on the first refund of an order.** Seeding makes 0 Stripe calls. | Graders creating many sessions cost nothing. Each refund costs 2 writes (PaymentIntent + refund). The sandbox allows 25 req/s per account, so roughly 12 refunds per second across all graders. |
| D3 | **Derive idempotency keys from business state,** not from the plan: `refund:{session_id}:{order_id}:{n_prior_refunds}:{amount_cents}`. | The `Plan` model has no id field. A double-click, a retry, or two plans that refund the same order all collapse to one Stripe refund. `UNIQUE(stripe_refund_id)` in SQLite catches a concurrent duplicate insert. |
| D4 | **Choose mock mode once, at boot.** No key means mock mode with a MOCK badge on every screen. A live key (`sk_live_`/`rk_live_`) means the app refuses to start. A runtime Stripe error never falls back to mock silently. | A refund that quietly turns into a fake refund would lie to the user. Errors surface as `ToolResult(ok=False)`. |
| D5 | **Use reportlab 5.1 for the PDF and stdlib `csv` for CSV.** | reportlab is the lightest option measured (10.4 MB of wheels with deps), is BSD-licensed, and needs no system libraries. fpdf2 is 13.9 MB (it adds fontTools) and LGPL. WeasyPrint needs Pango/HarfBuzz from apt and has a high memory ceiling. |
| D6 | **Refunds are irreversible and the UI says so plainly.** `undoable=False`, no undo callable, a red "Irreversible" pill, and `/api/undo` returns 409. The suggested way to recover the money is a `create_payment_link` step. | Stripe cannot reverse a card refund through the API. It can be cancelled only in the Dashboard, within 30 minutes in test environments. |
| D7 | **Use a restricted sandbox key (`rk_test_…`) that is not agent-tagged.** | Agent-tagged keys fall under Stripe approval rules, which by default require a human reviewer to approve refunds in the Dashboard. That would block every grader. |

## 2. MCP vs SDK — verdict

**Verdict: use the SDK for writes. MCP is a presentation talking point, not a dependency.** It is an optional read-only stretch goal (S1), off by default.

| Factor | Stripe MCP via Anthropic MCP connector | Direct Stripe SDK in our tools |
|---|---|---|
| Our confirm gate | The connector executes `mcp_tool_use` server-side and returns `mcp_tool_result` in the same response. Per-tool config is only `enabled` and `defer_loading`, with no approval hook. Anthropic's docs suggest denylisting write tools "when you want a human confirmation step". | The tool runs only after `execute()` receives `approved_step_ids`. Our dry-run diff shows the dollar amount first. |
| Stripe's own human-confirm | `Create refund` is marked "Human confirmation". Approval happens in the account owner's Dashboard, the agent must retry with a token, and the request expires in 24 hours. **Graders cannot approve.** | Not applicable. Our own gate is the human confirmation. |
| Auth timing | Stripe MCP stops accepting non-agent keys after **2026-11-30**. Agent-tagged keys get approval rules on refunds, and OAuth is interactive. The deadline falls inside our build window. | A plain `rk_test_` restricted key with 4 write permissions. |
| Blast radius | `stripe_api_write` covers **every** POST/PATCH/DELETE method. Strict schemas do not cover it. | Two typed tools with strict JSON Schemas: `refund_order(order_id, amount_cents, reason)` and `create_payment_link`. |
| Stability | The connector is in beta (`mcp-client-2026-09-15`), is not ZDR-eligible, and needs a public HTTPS server. | Stable GA SDK. |
| Grading value | "Uses MCP" counts as a design point. It is not a prompt-engineering technique. | "Evaluated MCP and rejected it for money moves because the gate must be ours" is a stronger design story for the slides. |

**Shortlist correction:** `00-shortlist.md` says to use the "Stripe sandbox MCP with its own human-confirm gate". That gate cannot work for anonymous graders (see the table), so this spec replaces that line.

**S1 (stretch, about 2 h, only after W3 is green):** add the MCP connector with an allowlist of `stripe_api_read` and `search_stripe_documentation` only, behind `STRIPE_MCP_READONLY=1`, authenticated with a read-only agent key. Request example: *"Double-check refund re_… in Stripe."* The agent verifies its own action against Stripe, and the read-only scope cannot move money. Skip S1 if time is short.

## 3. Stripe data mapping

| ShopPilot object | Stripe object | When created | Stored in |
|---|---|---|---|
| Seeded order (synthetic, `total_cents`) | none | At seed time, nothing is sent to Stripe | `orders` |
| Order being refunded | `PaymentIntent` (`pi_…`): `amount=total_cents`, `currency="usd"`, `payment_method="pm_card_visa"`, `payment_method_types=["card"]`, `confirm=True`, `metadata={session_id, order_id}`, `description="ShopPilot+ demo order {order_id}"` | Lazily, on the first refund. Idempotency key `pi:{session_id}:{order_id}` | `orders.stripe_payment_intent_id` |
| Refund | `Refund` (`re_…`): `payment_intent`, `amount`, `reason ∈ {duplicate, fraudulent, requested_by_customer}`, `metadata` | When `refund_order.run` executes | `refunds` row |
| Payment request | `PaymentLink` (`plink_…`, URL `https://buy.stripe.com/test_…`): one line item with `price_data{currency, unit_amount, product_data{name}}` | When `create_payment_link.run` executes. Idempotency key `plink:{session_id}:{order_id or customer_id}:{amount_cents}:{n_prior_links}` | `payment_links` row |
| Undo of a payment link | `PaymentLink.modify(id, active=False)` | When `undo` runs | `payment_links.active=0` |

The UI marks order rows as "synthetic order — Stripe charge created at refund time (test mode)". That makes the lazy mapping visible instead of hidden.

Read calls: **none**. Every Stripe id is kept locally. Stripe allows at least 10,000 read requests per month per account, so we never list or retrieve.

### Schema request (DDL lives in `db.py`, owned by the architecture plan)

Add `session_id TEXT NOT NULL` to each table if the architecture plan picks session-scoped rows.

```sql
-- add to orders
stripe_payment_intent_id TEXT, refunded_cents INTEGER NOT NULL DEFAULT 0,
carrier TEXT, tracking_number TEXT, shipped_at TEXT          -- status already exists

CREATE TABLE refunds (
  id TEXT PRIMARY KEY, order_id TEXT NOT NULL, amount_cents INTEGER NOT NULL CHECK (amount_cents > 0),
  reason TEXT NOT NULL, stripe_refund_id TEXT NOT NULL UNIQUE,
  mode TEXT NOT NULL CHECK (mode IN ('test','mock')), created_at TEXT NOT NULL);
CREATE TABLE payment_links (
  id TEXT PRIMARY KEY, order_id TEXT, customer_id TEXT, amount_cents INTEGER NOT NULL CHECK (amount_cents > 0),
  stripe_link_id TEXT NOT NULL UNIQUE, url TEXT NOT NULL, active INTEGER NOT NULL DEFAULT 1,
  mode TEXT NOT NULL, created_at TEXT NOT NULL);
CREATE TABLE outbox (
  id TEXT PRIMARY KEY, to_email TEXT NOT NULL, subject TEXT NOT NULL, body TEXT NOT NULL,
  template TEXT NOT NULL, order_id TEXT, created_at TEXT NOT NULL, recalled_at TEXT);
```

## 4. Module interfaces

```python
# app/integrations/stripe_client.py
Mode = Literal["test", "mock"]
class StripeFailure(Exception):            # code: one of ERROR_CODES; user_message: safe for UI; request_id: str | None
def mode() -> Mode                         # fixed at import from config
def ensure_payment_intent(session_id: str, order_id: str, amount_cents: int) -> str   # returns pi id
def refund(payment_intent_id: str, amount_cents: int, reason: str, idempotency_key: str) -> dict  # {id, status, amount}
def create_payment_link(name: str, amount_cents: int, metadata: dict, idempotency_key: str) -> dict  # {id, url}
def deactivate_payment_link(link_id: str) -> None

# app/integrations/outbox.py
def send(ctx, to_email: str, subject: str, body: str, template: str, order_id: str | None) -> str  # outbox id
def recall(ctx, outbox_id: str) -> None    # sets recalled_at; row is never deleted
def list_outbox(ctx) -> list[dict]         # newest first; backs GET /api/outbox

# app/integrations/export.py
EXPORT_KINDS = ("orders_csv", "refunds_csv", "report_pdf")
def render(kind: str, ctx) -> tuple[bytes, str, str]   # (body, media_type, filename); backs GET /api/export/{kind}
```

Every tool module exposes `SPEC`, `run`, `preview` and (if undoable) `undo`, and calls `register(SPEC, run, preview, undo)` at import time.

## 5. Tools

| Tool | destructive | moves_money | undoable | Strict input (all `required`, `additionalProperties:false`) | Business checks in `run()` (repeated in validator) |
|---|---|---|---|---|---|
| `mark_shipped` | False | False | True | `order_ids: string[]`, `carrier: enum[usps, ups, fedex]` | Each order exists, status is `paid`, at most 50 ids |
| `send_email` | False | False | True (recall) | `order_ids: string[]`, `template: enum[tracking, refund_confirmation, payment_request, custom]`, `custom_body: string \| null` | `custom_body` is required only when the template is `custom`, max 2,000 chars, at most 50 ids |
| `refund_order` | **True** | **True** | **False** | `order_id: string`, `amount_cents: integer \| null` (null means the full refundable amount), `reason: enum[duplicate, fraudulent, requested_by_customer]` | Order is paid or shipped, `0 < amount ≤ total − refunded`, cap from `safety/policy.py`, per-session Stripe write cap |
| `create_payment_link` | False | **True** (so it gets a confirm and the amount shows) | True (deactivate) | `order_id: string \| null`, `customer_id: string \| null`, `amount_cents: integer`, `description: string` | Exactly one of order/customer is set, `amount_cents` between 50 and 100,000, per-session write cap |
| `export_report` | False | False | False (read-only) | `kind: enum[orders_csv, refunds_csv, report_pdf]` | None. Returns `data.url = "/api/export/{kind}"` |

Strict mode does not support min/max/length limits, so `run()` and the validator enforce them in code. Batch arguments (`order_ids`) keep a "ship yesterday's 8 orders" request to one step. Refunds take one order per step, so each refund gets its own dollar line and its own approval checkbox.

### preview() → DiffItem

| Tool | `before` | `after` | `amount_cents` |
|---|---|---|---|
| `mark_shipped` | `{order_id: status}` | `{order_id: "shipped (carrier)"}` | None |
| `send_email` | `{}` | `{order_id: {to, subject}}` (first 3 bodies inline, rest counted) | None |
| `refund_order` | `{order_id, refunded_cents, status}` | `{refunded_cents', status', "irreversible": true, "stripe_mode"}` | amount |
| `create_payment_link` | `{}` | `{amount, description, "stripe_mode"}` | amount |
| `export_report` | `{}` | `{file: filename}` | None |

`preview` cannot see the step id (see contract conflict C1). It returns `step_id=""`, and `dry_run` fills in the id with `model_copy(update={"step_id": step.id})`.

### undo tokens

The undo token is JSON with the prior state, stored server-side in the audit row and read only through `/api/undo/{audit_id}`. A token never comes from the client, so we skip HMAC.

| Tool | Token | Undo effect |
|---|---|---|
| `mark_shipped` | `{"orders":[{id, status, carrier, tracking_number, shipped_at}]}` | Restores those fields |
| `send_email` | `{"outbox_ids":[…]}` | Sets `recalled_at`. The UI strikes the email through with the label "recalled (fake outbox; real email could not be unsent)" |
| `create_payment_link` | `{"link_id": "plink_…"}` | `deactivate_payment_link`, sets `active=0` |
| `refund_order` | `undo_token=None` | None. `/api/undo` returns 409 `{"error":"irreversible"}` |

### Irreversible refund: how it shows in the UI and audit log

1. Confirm card: red text reads "Refund $42.00 for order #1042 — Stripe TEST mode — cannot be undone". The approve checkbox is unchecked by default.
2. The audit row stores `{"undoable": false, "irreversible_reason": "card refunds cannot be reversed via API", "stripe_refund_id": "re_…"}`.
3. The audit log UI swaps the Undo button for a grey "Irreversible" pill. Hovering it shows the tooltip "Money was returned to the card. To recover it, ask the agent to create a payment link."
4. A forced call to `/api/undo/{id}` returns 409 and writes an audit entry `undo_rejected`.

## 6. Idempotency

| Call | Key | Collision behaviour |
|---|---|---|
| PaymentIntent create | `pi:{session_id}:{order_id}` | Same order always maps to the same PaymentIntent |
| Refund create | `refund:{session_id}:{order_id}:{n_prior_refunds}:{amount_cents}` | A retry or double approval returns the same `re_`. The DB `UNIQUE` turns a duplicate insert into a "done" result |
| PaymentLink create | `plink:{session_id}:{target_id}:{amount_cents}:{n_prior_links}` | Same |
| Deactivate link | none (the call is idempotent by nature) | — |

Facts (fetched from https://docs.stripe.com/api/idempotent_requests): keys go in the `Idempotency-Key` header and can be up to 255 chars. Stripe keeps a key for at least 24 h and replays the saved response, **including 500s**. Reusing a key with different parameters returns an error. Keys must not contain PII, so we use the session UUID and order id, never an email. In mock mode the fake id is `{prefix}_mock_{sha1(key)[:14]}`, which makes mock mode idempotent too.

## 7. Error mapping → `ToolResult(ok=False, summary=user_message, error=code)`

| Stripe exception / condition | `error` code | `summary` (shown in UI) | Retry? |
|---|---|---|---|
| `InvalidRequestError` with code `charge_already_refunded` | `already_refunded` | "Order already fully refunded." | No |
| `InvalidRequestError` with code `amount_too_large` | `amount_exceeds_refundable` | "Refund larger than what is left on the charge." | No |
| other `InvalidRequestError` | `stripe_invalid_request` | "Stripe rejected the request." | No |
| `RateLimitError` (429 with `Stripe-Rate-Limited-Reason`) | `stripe_rate_limited` | "Stripe test API busy, try again in a few seconds." | SDK `max_network_retries=2` first |
| 429 `lock_timeout` | handled by SDK retries | — | SDK |
| `AuthenticationError` / `PermissionError` | `stripe_auth` | "Payments are misconfigured; the admin has been notified." | No. Logged at ERROR |
| `APIConnectionError` / 5xx `APIError` | `stripe_unreachable` | "Can't reach Stripe right now. Nothing was charged or refunded." | SDK retries, then fail. The idempotency key makes a manual retry safe |
| `IdempotencyError` | `idempotency_conflict` | "This action was already submitted with different details." | No |
| any other `StripeError` | `stripe_error` | "Payment provider error." | No |
| response with `livemode == True` | `live_mode_blocked` (raise, abort) | "Live mode detected — blocked." | Never |
| per-session write cap hit | `stripe_cap_reached` | "Demo limit: 20 Stripe actions per session. Reset the store to continue." | No |

The server log records `code`, `request_id`, tool and order_id, never the key. The UI never shows raw Stripe messages.

## 8. Mock mode and fallback

| Env | Result |
|---|---|
| `STRIPE_SECRET_KEY` unset or empty | `mode()="mock"` |
| starts with `sk_test_` or `rk_test_` | `mode()="test"`, unless `STRIPE_MODE=mock` forces mock |
| anything else (`sk_live_`, `rk_live_`, junk) | **App refuses to boot**: `RuntimeError("STRIPE_SECRET_KEY must be a test key")` |

- **Labelling:** `GET /api/store` adds `meta.stripe_mode` (an additive field, see C3). The header shows a badge: green "Stripe TEST mode" or amber "Stripe MOCK — no real API calls". A mock `ToolResult.summary` starts with `[MOCK]`, and ids look like `re_mock_…`.
- **Stripe down during a live demo:** the call fails visibly (`stripe_unreachable`, "nothing was charged"). The presenter sets `STRIPE_MODE=mock` on the host and restarts, which takes about 1 minute. The demo video is pre-recorded in test mode.
- **CI:** no key means mock mode, and tests monkeypatch `stripe_client._client` with a fake. The one live test (`tests/integrations/test_stripe_live.py`) runs only when a `*_test_` key is present.

## 9. Fake outbox

- Every email goes to the `outbox` table. Nothing sends SMTP or HTTP. `From: orders@shoppilot.test` and the reserved TLD make that obvious.
- The UI tab "Outbox (fake — never sent)" lists to, subject, a body preview and the recalled state. **The UI must render bodies with `textContent`, never `innerHTML`**, because `custom_body` is LLM-written and may echo inbound email text.
- Templates use stdlib `string.Template`: `tracking` (carrier, tracking number), `refund_confirmation` (amount, `re_` id), `payment_request` (link URL), `custom`.
- Seed customers use `@example.com` addresses (RFC 2606). This is a request to the seed owner.

## 10. Export

- `orders_csv` and `refunds_csv` use stdlib `csv`. **CSV-injection guard:** prefix a `'` to any cell starting with `= + - @ \t \r`, because customer names and notes can come from attacker-controlled inbound email.
- `report_pdf` uses reportlab platypus: a title, the store/session date, an orders table (id, customer, status, total, refunded), a refunds table with `re_` ids and mode, and totals. Everything is built in a `BytesIO`, with no disk writes.
- The standard Helvetica font is latin-1 only, so text is passed through `s.encode("latin-1", "replace").decode("latin-1")` (`# ponytail: latin-1 only; embed DejaVuSans TTF if non-Latin names appear`).
- Generated on request and not cached. A 50-order report is roughly 50 ms and well under 20 MB of RAM [INFERENCE, check in the export task].

## 11. Rate limits and caps

| Limit | Value | Our handling |
|---|---|---|
| Stripe sandbox, global | 25 req/s per account (live is 100) | 0 calls at seed. 1–2 writes per action |
| Stripe endpoint default | 25 req/s | Same |
| PaymentIntent updates | 1,000 per PaymentIntent per hour | We never update a PaymentIntent |
| Read allocation | at least 10,000 GETs per month | We make 0 GETs |
| Our own cap | `STRIPE_MAX_WRITES_PER_SESSION=20` | Counted from `refunds` + `payment_links` rows plus PaymentIntents created, not from new state |
| SDK | `max_network_retries=2` | Retries 429 lock timeouts and connection errors safely with idempotency keys |

## 12. Free vs paid

| Item | Cost | Free alternative / note |
|---|---|---|
| Stripe sandbox (test mode) | $0, no business verification needed for test keys | Mock mode (no account) |
| Stripe MCP server | $0 in sandbox | Not used for writes (D1). S1 read-only stretch |
| reportlab 5.1 (BSD) | $0 | fpdf2 2.9 (LGPL), $0 |
| Fake outbox | $0, in-app | — |
| Resend (optional real email) | Free 3,000/mo, 100/day, 1 domain. Pro reported at $20/mo (search-only, third-party) | Not needed. Brief rule 6 says emails never leave the app |
| Mailtrap Email Sandbox (optional) | Free 50 test emails/mo, 1 sandbox (search-only, Mailtrap docs) | Mailpit self-hosted (MIT, extra container) [search-only, not verified] |
| **Layer 4 total** | **$0/month** | — |

Recommendation on real email: **do not add it.** It breaks brief rule 6 and adds a domain-verification chore. If the team ever wants it, Mailtrap Sandbox captures mail without delivering it, which keeps rule 6.

## 13. Security checklist (Layer 4)

1. Keys come from env only. `.env.example` has `STRIPE_SECRET_KEY=` empty. The app refuses non-test keys at boot and aborts on any `livemode: true` response.
2. The restricted key has 5 write permissions only: PaymentIntents, Refunds, Payment Links, Prices, Products. `price_data`/`product_data` create Prices and Products inline [INFERENCE: confirm the permission set in the Stripe smoke test].
3. Money tools require `approved_step_ids` (executor), re-check refundable amounts inside `run()`, and are capped per session.
4. Outbox bodies render as text and CSV cells are escaped, so there is no XSS and no formula injection.
5. Error summaries never include Stripe raw messages or keys. `request_id` goes to the server log only.

## 14. Contract conflicts

| # | Conflict | Proposed resolution |
|---|---|---|
| C1 | `preview(args, ctx) -> DiffItem`, but `DiffItem.step_id` is required and preview gets no step id | Tools return `step_id=""`. `dry_run` sets it with `model_copy`. No rename needed |
| C2 | `Ctx` fields are not frozen. Tools need `ctx.session_id` and `ctx.db` | The integrator freezes `Ctx(session_id: str, db: sqlite3.Connection)` minimum |
| C3 | Mock and test mode must be visible, but the frozen API has no field for it | Additive: `GET /api/store` → `meta.stripe_mode`. No path or name changes |
| C4 | The shortlist says Stripe MCP provides the human-confirm gate | Superseded by D1. The confirm gate is ours (executor). Update the slides and README wording |
| C5 | Tables and env vars that Layer 4 needs live in files other planners own (`db.py`, `config.py`, `.env.example`, `main.py` routes) | DDL in §3; env `STRIPE_SECRET_KEY`, `STRIPE_MODE`, `STRIPE_MAX_WRITES_PER_SESSION`. Routes call `outbox.list_outbox` / `export.render`. Owners add them in their W1 tasks |

## 15. Sources (all fetched 2026-10-30 unless marked)

| Fact | URL |
|---|---|
| Stripe MCP: remote `https://mcp.stripe.com`; OAuth or agent API key; tools `stripe_api_read/write/search/details`; `Create refund` needs Human confirmation (Dashboard approve, retry with token, 24 h expiry); non-agent keys rejected from 2026-12 (migrate by 2026-11-30) | https://docs.stripe.com/mcp |
| Agent-tagged keys fall under approval rules (default rules cover refunds); key prefixes `sk_test_`/`rk_test_`/`pk_test_` | https://docs.stripe.com/keys |
| Sandbox 25 req/s global, endpoints 25 req/s, 429 + `Stripe-Rate-Limited-Reason`, lock_timeout retried by SDKs, at least 10k reads/month allocation | https://docs.stripe.com/rate-limits |
| `pm_card_visa`; `pm_card_refundFail` (async fail), `pm_card_pendingRefund`; refunds cancellable only in the Dashboard within 30 min in test environments | https://docs.stripe.com/testing |
| Idempotency: header, 255 chars, at least 24 h, replays 500s, param mismatch errors | https://docs.stripe.com/api/idempotent_requests |
| Payment Links accept `price_data` + `product_data` inline; up to 20 line items | https://docs.stripe.com/api/payment-link/create.md?query=line_items |
| Anthropic MCP connector: beta `mcp-client-2026-09-15`, tools only, public HTTPS, not ZDR, config only `enabled`/`defer_loading`, `mcp_tool_use`/`mcp_tool_result` blocks; client-side helper `anthropic.lib.tools.mcp.async_mcp_tool` | https://platform.claude.com/docs/en/agents-and-tools/mcp-connector |
| stripe 16.1.0 (2026-10-29), Python ≥ 3.9, 2.6 MB wheel | https://pypi.org/project/stripe/ + `pip download` measurement |
| reportlab 5.1.0 (2026-10-22), BSD, needs pillow + charset-normalizer: 10.4 MB of wheels | https://pypi.org/project/reportlab/ + `pip download` |
| fpdf2 2.9.0 (2026-10-29), LGPL-3.0, Pillow + fontTools: 13.9 MB of wheels, has tables | https://pypi.org/project/fpdf2/ + `pip download` |
| WeasyPrint needs `libpango-1.0-0 libpangoft2-1.0-0 libharfbuzz-subset0`; warns of high CPU/memory | https://doc.courtbouillon.org/weasyprint/stable/first_steps.html |
| Resend free 3,000/mo, 100/day (search-only, third-party) | https://costbench.com/software/email-api/resend/free-plan/ |
| Mailtrap sandbox free 50/mo (search-only) | https://docs.mailtrap.io/email-sandbox/help/features-and-limits |
