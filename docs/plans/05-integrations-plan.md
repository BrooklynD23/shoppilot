# Layer 4 Integrations Implementation Plan

> Amended by 00-contract-resolutions.md (2026-10-30): R1, R2, R5, R6, R18, R20, R21, R22, R23, R24, R26, R29, R31, R38

> **For agentic workers:** REQUIRED SUB-SKILL: use superpowers:subagent-driven-development (or superpowers:executing-plans when running inline). Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Real cross-domain actions for ShopPilot+: Stripe test-mode refunds and payment links, a visible fake email outbox, and CSV/PDF export. Five tools are built on top: `mark_shipped`, `send_email`, `refund_order`, `create_payment_link`, `export_report`.

**Architecture:** A thin `stripe_client.py` wraps the official Stripe SDK. It uses idempotency keys, picks mock or test mode once at boot, and maps errors to codes. The tool modules call it and register with `registry.register(spec, run, preview, undo)`. No Stripe calls happen at seed time. A PaymentIntent is created lazily on the first refund. The Stripe MCP server is not used for writes (spec §2).

**Tech Stack:** Python 3.12, FastAPI, `stripe==16.1.0`, `reportlab==5.1.0` (R29), stdlib `csv` / `string.Template` / `hashlib`, SQLite, pytest.

**Spec:** `docs/specs/05-integrations.md`. Brief: `docs/specs/00-shared-brief.md`.

## Global Constraints

1. Stripe runs in **test mode only**. The app refuses to boot unless `STRIPE_SECRET_KEY` is empty or starts with `sk_test_` / `rk_test_`. Any response with `livemode: true` aborts the call.
2. Secrets come from env only. Never log a key. `.env.example` keeps `STRIPE_SECRET_KEY=` empty.
3. CI makes **zero network calls**. Tests monkeypatch `stripe_client._client` or run in mock mode. The live smoke test skips unless a test key is set.
4. Seeding makes no Stripe calls. Every Stripe POST carries an idempotency key from spec §6.
5. Emails never leave the app. Nothing imports SMTP or sends over HTTP.
6. Money tools enforce limits inside `run()` as well as in the validator: refundable amount (`policy.refundable_cents`), `policy.REFUND_CAP_PER_ORDER_CENTS`, `STRIPE_MAX_WRITES_PER_SESSION` (default 20). Tools never call `log_action` and never commit (R23).
9. The raw session id never goes to Stripe: metadata and idempotency keys use `db.session_hash(ctx.session_id)` (R21).
7. Use immutable patterns: build new dicts and rows, never mutate args. Functions stay under 50 lines and files under 400.
8. Files owned by other plans (`db.py`, `config.py`, `main.py`, `.env.example`, `static/*`) are **requested, never edited** here. See the spec, C5.

## Review Focus

1. **Money path:** can a refund run without approval, run twice, or exceed the refundable amount? Check the idempotency key derivation and the `UNIQUE(stripe_refund_id)` handling.
2. **Live-key guard:** test the boot refusal and the `livemode` abort.
3. **Mock honesty:** a runtime Stripe failure must not turn into a fake success. Every mock result must be labelled `[MOCK]`.
4. **Injection surfaces:** CSV formula escaping, outbox rendered as text, `custom_body` length cap.
5. **Irreversible refund UX:** `undo=None`, the audit payload has `undoable:false`, and `/api/undo` returns 409.

## Task map

| ID | Task | Wave | Depends-on | Owns-files | Est. h |
|---|---|---|---|---|---|
| I1 | Stripe client: modes, guard, error map, calls | W2 | W1 config + db (other plans) | `app/integrations/stripe_client.py`, `tests/integrations/test_stripe_client.py` | 3 |
| I2 | Fake outbox | W2 | W1 db | `app/integrations/outbox.py`, `tests/integrations/test_outbox.py` | 1 |
| I3 | Export CSV + PDF | W2 | W1 db | `app/integrations/export.py`, `tests/integrations/test_export.py` | 2 |
| I4 | `mark_shipped` tool | W2 | W1 registry, db | `app/tools/mark_shipped.py`, `tests/tools/test_mark_shipped.py` | 1.5 |
| I5 | `send_email` tool | W2 | I2, W1 registry | `app/tools/send_email.py`, `tests/tools/test_send_email.py` | 1.5 |
| I6 | `refund_order` tool | W2 | I1, W1 registry, P4-T2 `policy` | `app/tools/refund_order.py`, `tests/tools/test_refund_order.py` | 3 |
| I7 | `create_payment_link` tool | W2 | I1, W1 registry | `app/tools/create_payment_link.py`, `tests/tools/test_create_payment_link.py` | 2 |
| I8 | `export_report` tool | W2 | I3, W1 registry | `app/tools/export_report.py`, `tests/tools/test_export_report.py` | 0.5 |
| I9 | Live Stripe sandbox smoke test (account created on day 1 in P7-D0) | W3 | I1, I6, I7 | `tests/integrations/test_stripe_live.py`, `docs/specs/05-stripe-setup.md` | 1.5 |
| I10 | End-to-end refund demo check (with agent core and UI owners) | W3 | I4–I8, agent executor, UI | `tests/e2e/test_layer4_flow.py` | 1.5 |
| I11 | Deploy: set host env, verify badge and `re_` id on the public URL | W4 | I9, I10, deploy plan | none (host env only) | 0.5 |
| S1 | *Stretch:* read-only Stripe MCP lookup (`STRIPE_MCP_READONLY=1`) | W3 (optional) | I10 green | `app/integrations/stripe_mcp.py` | 2 |

**Total:** 18 h core (20 h with S1).

**Requests to other plans — resolved in `00-contract-resolutions.md`:**
1. DDL → R5 (P1-T2; `orders.stripe_payment_intent_id`, `refunded_cents`, `carrier`; P5 `refunds`/`payment_links`/`outbox`).
2. Settings `STRIPE_SECRET_KEY`, `STRIPE_MODE` (`auto|mock`), `STRIPE_MAX_WRITES_PER_SESSION` → R31 (P1-T2), `.env.example` P1-T1.
3. Routes `/api/outbox`, `/api/export/{kind}` → P1-T6; `stripe_mode` is a **top-level** field of `/api/session` and `/api/store` (R26).
4. Seed: `@example.com` emails yes; "damaged" order **notes dropped** — damage arrives via inbox `E001`, notes are NULL (R24).
5. Deps `stripe==16.1.0`, `reportlab==5.1.0` → R29 (P1-T1).

---

## I1 — Stripe client

**Files:** create `app/integrations/stripe_client.py`, `tests/integrations/test_stripe_client.py`.

**Interfaces (from spec §4):**
```python
Mode = Literal["test", "mock"]
ERROR_CODES = ("already_refunded", "amount_exceeds_refundable", "stripe_invalid_request", "stripe_rate_limited",
               "stripe_auth", "stripe_unreachable", "idempotency_conflict", "stripe_error", "live_mode_blocked")
class StripeFailure(Exception):
    def __init__(self, code: str, user_message: str, request_id: str | None = None): ...
def resolve_mode(key: str | None, override: str | None) -> Mode   # pure; raises RuntimeError on non-test key
def mode() -> Mode
def ensure_payment_intent(session_id: str, order_id: str, amount_cents: int) -> str
def refund(payment_intent_id: str, amount_cents: int, reason: str, idempotency_key: str) -> dict
def create_payment_link(name: str, amount_cents: int, metadata: dict, idempotency_key: str) -> dict
def deactivate_payment_link(link_id: str) -> None
```
Implementation notes:
- Build `_client = stripe.StripeClient(key, max_network_retries=2)` only in test mode, otherwise `None`.
- Use `client.v1.payment_intents.create(params={...}, options={"idempotency_key": k})`. Check the exact v16 call shape against the installed SDK before writing it.
- Send PaymentIntent params from spec §3 (`payment_method="pm_card_visa"`, `payment_method_types=["card"]`, `confirm=True`); `metadata={session_hash, order_id}` — never the raw session id (R21). `ensure_payment_intent(session_hash, order_id, amount_cents)`.
- Mock ids are `f"{prefix}_mock_{sha1(key).hexdigest()[:14]}"`. The mock link URL is `"about:blank#mock-" + id`, and the UI shows it as "mock link (not payable)".
- Use one `_call(fn)` wrapper that catches `stripe.StripeError` subclasses and raises `StripeFailure` per spec §7. It logs `request_id` and never the key.
- `_check_live(obj)` raises `StripeFailure("live_mode_blocked", ...)` when `obj.livemode` is true.

- [ ] **Step 1: write failing tests**
```python
import pytest
from app.integrations import stripe_client as sc

@pytest.mark.parametrize("key,override,expected", [
    (None, None, "mock"), ("", None, "mock"), ("sk_test_x", None, "test"),
    ("rk_test_x", None, "test"), ("sk_test_x", "mock", "mock")])
def test_resolve_mode(key, override, expected):
    assert sc.resolve_mode(key, override) == expected

@pytest.mark.parametrize("key", ["sk_live_x", "rk_live_x", "garbage"])
def test_live_or_junk_key_refuses(key):
    with pytest.raises(RuntimeError):
        sc.resolve_mode(key, None)

def test_mock_refund_is_idempotent(monkeypatch):
    monkeypatch.setattr(sc, "_mode", "mock")
    a = sc.refund("pi_mock_1", 500, "duplicate", "refund:s:o:0:500")
    b = sc.refund("pi_mock_1", 500, "duplicate", "refund:s:o:0:500")
    assert a["id"] == b["id"] and a["id"].startswith("re_mock_")

def test_rate_limit_maps_to_code(monkeypatch, fake_client_raising):   # fixture: fake whose .v1.refunds.create raises stripe.RateLimitError
    monkeypatch.setattr(sc, "_mode", "test"); monkeypatch.setattr(sc, "_client", fake_client_raising)
    with pytest.raises(sc.StripeFailure) as e:
        sc.refund("pi_1", 500, "duplicate", "k")
    assert e.value.code == "stripe_rate_limited" and "sk_" not in e.value.user_message

def test_livemode_response_blocked(monkeypatch, fake_client_livemode):
    ...  # expect code == "live_mode_blocked"

def test_idempotency_key_passed(monkeypatch, recording_fake_client):
    ...  # assert options["idempotency_key"] == "k" on refunds.create
```
Also add one parametrized test that covers each row of the spec §7 table (exception class + code → our code).
- [ ] **Step 2:** `pytest tests/integrations/test_stripe_client.py -q` should FAIL (module missing).
- [ ] **Step 3:** implement the minimal module.
- [ ] **Step 4:** `pytest tests/integrations/test_stripe_client.py -q --cov=app/integrations/stripe_client --cov-report=term-missing` should PASS with at least 80% coverage.
- [ ] **Step 5:** `ruff check app/integrations && mypy app/integrations/stripe_client.py`
- [ ] **Step 6:** commit `feat: stripe test-mode client with mock mode and error map`

## I2 — Fake outbox

**Files:** create `app/integrations/outbox.py`, `tests/integrations/test_outbox.py`.

**Interfaces:** `send(ctx, to_email, subject, body, template, order_id) -> str`, `recall(ctx, outbox_id) -> None`, `list_outbox(ctx) -> list[dict]`.

- [ ] **Step 1: failing tests:**
  1. `send` then `list_outbox` returns 1 row with `recalled_at is None`.
  2. `recall` sets `recalled_at` and keeps the row.
  3. `recall` of an unknown id raises `KeyError`.
  4. `list_outbox` returns newest first.
  5. Rows from session A are not visible from session B (uses `get_db(session_id)` fixture).
- [ ] **Step 2:** `pytest tests/integrations/test_outbox.py -q` should FAIL.
- [ ] **Step 3:** implement with parameterized SQL only, ids from `uuid4().hex`, and UTC ISO timestamps.
- [ ] **Step 4:** run the tests again, they should PASS.
- [ ] **Step 5:** commit `feat: fake email outbox`

## I3 — Export CSV + PDF

**Files:** create `app/integrations/export.py`, `tests/integrations/test_export.py`.

**Interfaces:** `EXPORT_KINDS`, `render(kind, ctx) -> (bytes, media_type, filename)`, and a private `_safe_cell(v) -> str`.

- [ ] **Step 1: failing tests**
```python
@pytest.mark.parametrize("v,out", [("=1+1", "'=1+1"), ("+x", "'+x"), ("-x", "'-x"), ("@x", "'@x"), ("ok", "ok")])
def test_csv_injection_guard(v, out): assert export._safe_cell(v) == out

def test_orders_csv_header_and_rows(seeded_ctx):
    body, mt, fn = export.render("orders_csv", seeded_ctx)
    assert mt == "text/csv" and fn.endswith(".csv") and body.splitlines()[0].startswith(b"order_id,")

def test_report_pdf_is_pdf(seeded_ctx):
    body, mt, _ = export.render("report_pdf", seeded_ctx)
    assert body[:5] == b"%PDF-" and mt == "application/pdf"

def test_pdf_survives_non_latin_name(seeded_ctx_with_name_emoji): ...   # no exception
def test_unknown_kind_raises(seeded_ctx): ...                           # ValueError
```
- [ ] **Step 2:** `pytest tests/integrations/test_export.py -q` should FAIL.
- [ ] **Step 3:** implement. Use `csv.writer` over `io.StringIO`. Build the PDF with reportlab `SimpleDocTemplate(BytesIO)` + `Table`, using the latin-1 sanitize from spec §10 with a `# ponytail:` comment.
- [ ] **Step 4:** PASS. Then measure: `python -c "import time,tracemalloc;..."` on 200 orders and record time and peak memory in the PR body. The target is under 1 s and under 50 MB.
- [ ] **Step 5:** commit `feat: csv and pdf export`

## I4 — `mark_shipped`

**Files:** create `app/tools/mark_shipped.py`, `tests/tools/test_mark_shipped.py`.

**Interfaces:**
```python
SPEC = ToolSpec(name="mark_shipped", destructive=False, moves_money=False, undoable=True,
                input_schema={"type": "object", "additionalProperties": False, "required": ["order_ids", "carrier"],
                              "properties": {"order_ids": {"type": "array", "items": {"type": "string"}},
                                             "carrier": {"type": "string", "enum": ["usps", "ups", "fedex"]}}}, ...)
def run(args, ctx) -> ToolResult; def preview(args, ctx) -> DiffItem; def undo(token, ctx) -> ToolResult
```
The tracking number is deterministic: `carrier.upper() + sha1(session_hash+order_id).hexdigest()[:12].upper()`. Undo token = prior **and** post fields per order; `undo` returns `ok=False, error="changed_since"` if any order no longer matches the post state (R22).

- [ ] **Step 1: failing tests:**
  1. A paid order becomes shipped with carrier and tracking set.
  2. A non-paid order fails with `ok=False`, `error="invalid_status"`, and the DB is unchanged.
  3. 51 ids fail with `error="too_many"`.
  4. `undo(token)` restores the exact prior fields; after a manual edit of the order it returns `error="changed_since"` and changes nothing (R22).
  5. `preview` does not write to the DB and returns `step_id=""`.
- [ ] **Step 2:** `pytest tests/tools/test_mark_shipped.py -q` should FAIL.
- [ ] **Step 3:** implement inside the request transaction (no commit, R23). The token is the JSON of the prior and post rows.
- [ ] **Step 4:** PASS. Commit `feat: mark_shipped tool with undo`.

## I5 — `send_email`

**Files:** create `app/tools/send_email.py`, `tests/tools/test_send_email.py`.

**Interfaces:** `SPEC` per spec §5, plus `TEMPLATES: dict[str, string.Template]`, `run`, `preview`, `undo` (recall).

- [ ] **Step 1: failing tests:**
  1. `tracking` on 2 shipped orders creates 2 outbox rows with the tracking number in the body.
  2. `custom` with a null `custom_body` fails with `error="missing_body"`.
  3. A `custom_body` over 2,000 chars fails with `error="too_long"`.
  4. `undo` sets `recalled_at` on every row created and deletes none.
  5. `preview` creates no rows.
  6. `tracking` on an unshipped order fails with `error="no_tracking"`.
- [ ] **Step 2:** FAIL. **Step 3:** implement. Use `Template.safe_substitute` so a stray `$` in a name cannot crash. **Step 4:** PASS. Commit `feat: send_email tool to fake outbox`.

## I6 — `refund_order`

**Files:** create `app/tools/refund_order.py`, `tests/tools/test_refund_order.py`.

**Interfaces:** `SPEC(destructive=True, moves_money=True, undoable=False)`, `run`, `preview`, with **no `undo`** (`register(SPEC, run, preview, None)`).

Flow inside `run`:
1. Load the order and compute `refundable = total_cents - refunded_cents`. Set `amount = args.amount_cents or refundable`.
2. Check status, `0 < amount <= refundable`, the policy cap, and the session write cap. On failure, return `ok=False` with a code.
3. Get the PaymentIntent from `orders.stripe_payment_intent_id`. If it is null, call `stripe_client.ensure_payment_intent` and store the id.
4. Call `stripe_client.refund(pi, amount, reason, key)` with key `refund:{session_hash}:{order_id}:{n_prior_refunds}:{amount_cents}` (spec §6 with R20/R21).
5. INSERT the refund row and UPDATE `orders.refunded_cents` (and status when fully refunded) in one transaction. An `IntegrityError` on the unique `stripe_refund_id` means the refund is already recorded, so return `ok=True` with `data.duplicate=True`.
6. Return `ToolResult(ok=True, summary="Refunded $X.XX on order N (Stripe TEST re_…)" or "[MOCK] …", data={stripe_refund_id, payment_intent_id, amount_cents, mode, undoable: False, irreversible_reason})`.
7. Map `StripeFailure` to `ToolResult(ok=False, summary=e.user_message, error=e.code)`, and **leave the DB unchanged**.

- [ ] **Step 1: failing tests** (mock mode plus a recording fake client):
  1. A full refund stores a `re_` id, sets refunded_cents = total, and status becomes `refunded`.
  2. A partial refund leaves status unchanged.
  3. An amount larger than refundable fails with `error="amount_exceeds_refundable"` and **0 client calls**.
  4. Running twice with identical state uses the same idempotency key, gives one refund row, and the second result has `duplicate=True`.
  5. The PaymentIntent is created once per order across two partial refunds.
  6. `StripeFailure("stripe_unreachable")` gives `ok=False` and the DB is unchanged.
  7. The session cap is reached at 21 writes, giving `error="stripe_cap_reached"`.
  8. `preview` shows `amount_cents` and `after.irreversible is True`, with 0 client calls.
  9. The registry entry has `undo is None`.
- [ ] **Step 2:** `pytest tests/tools/test_refund_order.py -q` should FAIL.
- [ ] **Step 3:** implement. Keep `run` under 50 lines by splitting out `_checks` and `_record`.
- [ ] **Step 4:** PASS with at least 90% coverage (money path). `pytest tests/tools/test_refund_order.py --cov=app/tools/refund_order --cov-report=term-missing`
- [ ] **Step 5:** run the `security-reviewer` agent on the I1 + I6 diff. Fix CRITICAL and HIGH findings before merge.
- [ ] **Step 6:** commit `feat: refund_order via stripe test mode, irreversible`

## I7 — `create_payment_link`

**Files:** create `app/tools/create_payment_link.py`, `tests/tools/test_create_payment_link.py`.

**Interfaces:** `SPEC(destructive=True, moves_money=True, undoable=True)` (R6: registry requires `moves_money ⇒ destructive`), `run`, `preview`, `undo`. `undo` calls `stripe_client.deactivate_payment_link` and sets `active=0`.

- [ ] **Step 1: failing tests:**
  1. A valid order target creates a row with a `plink_` id and URL.
  2. Both targets null, or both set, fails with `error="bad_target"`.
  3. Amounts of 49 and 100,001 fail with `error="bad_amount"`.
  4. `undo` deactivates the link (fake client records the call) and sets `active=0`.
  5. A deactivate failure gives `ok=False` and the row stays active.
  6. The mock-mode summary starts with `[MOCK]`.
- [ ] **Step 2:** FAIL. **Step 3:** implement. **Step 4:** PASS. Commit `feat: create_payment_link tool with deactivate undo`.

## I8 — `export_report`

**Files:** create `app/tools/export_report.py`, `tests/tools/test_export_report.py`.

- [ ] **Step 1: failing tests:**
  1. Each kind returns `ok=True` with `data.url == f"/api/export/{kind}"`.
  2. An unknown kind fails with `ok=False`.
  3. `SPEC.destructive is False`.
- [ ] **Step 2:** FAIL. **Step 3:** implement as a pure function that does not render (the route renders). **Step 4:** PASS. Commit `feat: export_report tool`.

## I9 — Live sandbox smoke test + Stripe account setup (W3)

**Files:** create `tests/integrations/test_stripe_live.py`, `docs/specs/05-stripe-setup.md`.

Steps:
1. **Owner (team decides, see open questions):** create a free Stripe account, open Dashboard, then Sandboxes, then create "shoppilot". Create a **restricted key, not agent-tagged**, with write permission on PaymentIntents, Refunds, Payment Links, Prices, Products. Store it in a password manager and the host's env. Never put it in the repo or chat.
2. Write `05-stripe-setup.md` covering steps 1–3, under 30 lines with screenshots optional.
3. The test is skipped unless `STRIPE_SECRET_KEY` starts with `sk_test_` or `rk_test_`. It creates a $5 PaymentIntent, refunds $2, then $3, and asserts the ids start with `re_`, the second refund succeeds, and a third returns `already_refunded`. It also creates and deactivates a payment link.
4. Command: `RUN_LIVE=1 STRIPE_SECRET_KEY=rk_test_... pytest tests/integrations/test_stripe_live.py -q -m live   # marker `live` (R29)`
5. Confirm the restricted-key permission set is sufficient. If `price_data` needs more, update spec §13.

- [ ] Commit `test: opt-in stripe sandbox smoke test + setup doc`

## I10 — End-to-end Layer 4 flow (W3)

**Files:** create `tests/e2e/test_layer4_flow.py`. It uses FastAPI `TestClient` in mock mode.

1. `POST /api/session`, then `POST /api/plan` with a stubbed planner. The plan is: mark 2 orders shipped, email tracking, refund damaged order D, create a payment link.
2. Assert the diff has `amount_cents` on the refund and the link, and the refund diff has `after.irreversible`.
3. `POST /api/execute` with all step ids except the refund. Assert the refund did not run (no `refunds` row).
4. Execute the refund. Assert `/api/audit` holds a refund entry with `undoable:false` and a `re_mock_` id, and `/api/outbox` has 2 emails.
5. `POST /api/undo/{refund_audit_id}` returns 409 `not_undoable` (R38). Undoing `mark_shipped` restores status.
6. `GET /api/export/report_pdf` returns `%PDF-`.
7. `GET /api/store` returns top-level `stripe_mode == "mock"` (R26).

Execute in this test is per step (`approved_step_ids` = one id per call, R1).

- [ ] `pytest tests/e2e/test_layer4_flow.py -q` should PASS. Commit `test: layer 4 end-to-end flow`.

## I11 — Deploy check (W4)

1. Set `STRIPE_SECRET_KEY` (rk_test) on the host with no `STRIPE_MODE`.
2. Open the public URL and check the badge reads "Stripe TEST mode".
3. Refund the damaged order and check that the `re_…` id shows and the same id appears in the Stripe sandbox Dashboard.
4. Record the demo-video segment, then reset the session.

## S1 — Stretch: read-only Stripe MCP lookup (optional)

- Only after I10 is green and the demo video is recorded.
- Add `app/integrations/stripe_mcp.py` (planner request option): `mcp_servers=[{"type":"url","url":"https://mcp.stripe.com","name":"stripe","authorization_token": env STRIPE_MCP_AGENT_KEY}]` plus an `mcp_toolset` allowlist of `stripe_api_read` and `search_stripe_documentation`. Use beta header `mcp-client-2026-09-15`.
- Use a separate read-only agent key, so write tools cannot run even if they are enabled.
- Test: a mocked Anthropic response carrying `mcp_tool_use` / `mcp_tool_result` blocks is rendered in the timeline.
- Skip if the time budget is short. The slides explain why writes stay on the SDK.

## Commands summary

```bash
pytest tests/integrations tests/tools -q                      # CI, mock mode, no network
pytest --cov=app/integrations --cov=app/tools --cov-report=term-missing
RUN_LIVE=1 STRIPE_SECRET_KEY=rk_test_... pytest -m live -q    # manual, never in CI
ruff check app && mypy app/integrations app/tools
```
