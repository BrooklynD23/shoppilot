"""Every Stripe call the Connect sample makes, through one StripeClient (spec 10 §8).

Brief: "Use a Stripe Client for all requests". stripe-python 16.1.0 pins API version
2026-10-28.endive itself, so no stripe_version is set anywhere.
Each network call goes through call(): a Stripe error becomes a safe JSON error (Stripe's own
message never reaches the browser) and any live-mode object is blocked.
"""

import functools
import time
from collections.abc import Callable
from typing import Any

import stripe

from app.config import get_settings
from app.connect.config import fail, require
from app.integrations.stripe_client import StripeFailure, _call, resolve_mode

# Shared wrapper's failure code -> HTTP status. Anything else (stripe_auth, stripe_unreachable,
# live_mode_blocked) is the server's problem, not the user's: 503.
STATUS = {
    "stripe_invalid_request": 422,
    "stripe_rate_limited": 429,
    "idempotency_conflict": 409,
    "stripe_error": 502,
}
# Subscription statuses that mean "has a plan to manage": Subscribe is hidden, /subscribe is 409.
OPEN = ("active", "trialing", "past_due", "unpaid", "incomplete", "paused")


@functools.cache
def client() -> stripe.StripeClient:
    """The one StripeClient for every Connect request. Built on first use, never at import."""
    # PLACEHOLDER: STRIPE_SECRET_KEY=sk_test_... (your sandbox secret key) in .env / Render env.
    key = require(get_settings().stripe_secret_key, "STRIPE_SECRET_KEY")
    raw = key.get_secret_value().strip()  # a CRLF .env leaves a hidden \r on the key
    resolve_mode(raw, None)  # reused guard: raises unless sk_test_/rk_test_; live keys never work
    return stripe.StripeClient(raw, max_network_retries=2)  # no stripe_version: the SDK pins it


def call(fn: Callable[[], Any], hint: str = "") -> Any:
    """Run one Stripe call. On failure: a JSON error; a rejected request also gets `hint`."""
    try:
        return _call(fn)  # reused from the demo: safe error codes, blocks any livemode object
    except StripeFailure as e:
        message = e.user_message
        if e.code == "stripe_invalid_request" and hint:
            message = f"{message} {hint}"  # the likely cause, in our words, not Stripe's
        fail(STATUS.get(e.code, 503), e.code, message)


def dig(obj: Any, *path: str) -> Any:
    """obj.a.b.c, or None when a step is missing (stripe-python 16 objects are not dicts)."""
    for name in path:
        obj = getattr(obj, name, None)
        if obj is None:
            return None
    return obj


# ---------- 1. Create a connected account (Accounts v2) ----------
def create_account(session_hash: str, display_name: str, contact_email: str) -> str:
    params = {
        # Exactly the brief's properties. Never a top-level `type` (express/standard/custom).
        "display_name": display_name,  # from the user's form
        "contact_email": contact_email,  # from the user's form; sent to Stripe, not stored here
        "identity": {"country": "us"},
        "dashboard": "full",  # the account gets the full Stripe Dashboard
        "defaults": {
            # Stripe collects Stripe's fees from the account and covers its losses.
            "responsibilities": {"fees_collector": "stripe", "losses_collector": "stripe"},
        },
        "configuration": {
            "customer": {},  # the same acct_ id can also be charged as a customer (the plan)
            "merchant": {"capabilities": {"card_payments": {"requested": True}}},  # sell by card
        },
    }
    # One account per user: the key is tied to the user, so a retry or a double click replays
    # the same account instead of creating a second one.
    options = {"idempotency_key": f"connect-acct:{session_hash}"}
    return call(lambda: client().v2.core.accounts.create(params, options)).id


# ---------- 2. Onboarding status: read from the API every time, never stored (brief) ----------
def account_status(account_id: str) -> dict:
    include = {"include": ["configuration.merchant", "requirements"]}  # v2 omits these by default
    account = call(lambda: client().v2.core.accounts.retrieve(account_id, include))
    # Ready to take payments once the merchant's card_payments capability is active.
    card = dig(account, "configuration", "merchant", "capabilities", "card_payments", "status")
    # Onboarding is complete unless some requirement is currently due or past due.
    req = dig(account, "requirements", "summary", "minimum_deadline", "status")
    return {
        "display_name": dig(account, "display_name"),
        "contact_email": dig(account, "contact_email"),
        "card_payments_status": card,
        "requirements_status": req,
        "ready_to_process_payments": card == "active",
        "onboarding_complete": req not in ("currently_due", "past_due"),
    }


# ---------- 3. Onboarding link (Account Links v2) ----------
def onboarding_link(account_id: str, base_url: str) -> str:
    params = {
        "account": account_id,
        "use_case": {
            "type": "account_onboarding",
            "account_onboarding": {
                # The brief also sends configurations: ['merchant', 'customer']. API
                # 2026-09-30.endive removed it (400 "Unknown field", spec 10 F3); Stripe now
                # onboards the configurations the account already has.
                # refresh_url: the link expired or was used; the dashboard makes a fresh one.
                "refresh_url": f"{base_url}/connect/?refresh=1",
                # return_url: the user is back from Stripe; the dashboard re-reads status live.
                "return_url": f"{base_url}/connect/?accountId={account_id}",
            },
        },
    }
    hint = "Check that PUBLIC_BASE_URL is an address Stripe accepts."
    return call(lambda: client().v2.core.account_links.create(params), hint).url


# ---------- 4. Products on the connected account (Stripe-Account header) ----------
def create_product(
    account_id: str,
    name: str,
    description: str,
    price_cents: int,
    currency: str,
    idempotency_key: str,
) -> str:
    params: dict[str, Any] = {
        "name": name,
        # A one-time price made with the product; it becomes the product's default_price.
        "default_price_data": {"unit_amount": price_cents, "currency": currency},
    }
    if description:
        params["description"] = description  # Stripe rejects an empty string
    # stripe_account sends the Stripe-Account header: the product lives on the connected
    # account, not on the platform.
    options = {"stripe_account": account_id, "idempotency_key": idempotency_key}
    return call(lambda: client().v1.products.create(params, options), "Check the price.").id


def _sellable(product: Any) -> bool:
    """A one-time price with a fixed amount; subscriptions and pay-what-you-want are skipped."""
    price = dig(product, "default_price")
    return dig(price, "type") == "one_time" and dig(price, "unit_amount") is not None


def list_products(account_id: str) -> list[dict]:
    """The storefront: active products on the connected account, with their prices."""
    params = {"limit": 20, "active": True, "expand": ["data.default_price"]}  # brief, verbatim
    found = call(lambda: client().v1.products.list(params, {"stripe_account": account_id}))
    return [
        {
            "id": p.id,
            "name": p.name,
            "description": p.description,
            "unit_amount": p.default_price.unit_amount,
            "currency": p.default_price.currency,
        }
        for p in found.data
        if _sellable(p)
    ]


# ---------- 5. Storefront purchase: Direct Charge + application fee, hosted Checkout ----------
def product_checkout(
    account_id: str, product_id: str, quantity: int, fee_cents: int, base_url: str
) -> str:
    on_account = {"stripe_account": account_id}
    # Read the product and its price from Stripe: the amount never comes from the browser.
    product = call(
        lambda: client().v1.products.retrieve(
            product_id, {"expand": ["default_price"]}, on_account
        ),
        "The product may have been removed from the shop.",
    )
    if not dig(product, "active") or not _sellable(product):
        fail(422, "product_unavailable", "This product is not for sale right now.")
    price = product.default_price
    if fee_cents >= price.unit_amount * quantity:
        fail(422, "price_below_fee", "The order total must be above the platform fee.")
    params = {
        "line_items": [
            {
                # price_data rebuilt from the price stored at Stripe (brief: price_data).
                "price_data": {
                    "currency": price.currency,
                    "unit_amount": price.unit_amount,
                    "product": product.id,
                },
                "quantity": quantity,
            }
        ],
        # The platform's cut. Stripe moves it to the platform; the rest stays with the shop.
        "payment_intent_data": {"application_fee_amount": fee_cents},
        "mode": "payment",
        # Stripe fills in {CHECKOUT_SESSION_ID}; the double braces escape the f-string.
        "success_url": (
            f"{base_url}/connect/success/?session_id={{CHECKOUT_SESSION_ID}}&account={account_id}"
        ),
        "cancel_url": f"{base_url}/connect/store/?account={account_id}",
    }
    # stripe_account makes it a Direct Charge: the payment is created on the connected account.
    hint = "The shop may not take card payments yet: finish onboarding first."
    return call(lambda: client().v1.checkout.sessions.create(params, on_account), hint).url


# ---------- 6. Platform subscription: the connected account pays the platform ----------
SUBSCRIBE_SESSION_TTL_S = 3600  # >= 30 min (Stripe minimum), >= the 1-hour key bucket


def subscription_checkout(account_id: str, price_id: str, base_url: str) -> str:
    params = {
        # V2 accounts: one id is both the connected account and the customer.
        # Brief: use customer_account (acct_...), never `customer` (cus_...).
        "customer_account": account_id,
        "mode": "subscription",
        "line_items": [{"price": price_id, "quantity": 1}],  # STRIPE_PLATFORM_PRICE_ID
        "success_url": f"{base_url}/connect/?subscribed=1&session_id={{CHECKOUT_SESSION_ID}}",
        "cancel_url": f"{base_url}/connect/",
    }
    # Repeat clicks before paying must not open several sessions (two paid tabs = two plans).
    # One idempotency key per account, price and clock hour makes Stripe return the SAME
    # Checkout Session. Stripe rejects a reused key with different params, so expires_at comes
    # from the hour bucket too: the end of the bucket + TTL, 1 to 2 hours after creation.
    bucket = int(time.time()) // 3600
    params["expires_at"] = (bucket + 1) * 3600 + SUBSCRIBE_SESSION_TTL_S
    options = {"idempotency_key": f"subscribe:{account_id}:{price_id}:{bucket}"}
    # No stripe_account option: the subscription lives on the platform account.
    hint = "Check that STRIPE_PLATFORM_PRICE_ID is a recurring price in this sandbox."
    return call(lambda: client().v1.checkout.sessions.create(params, options), hint).url


def portal(account_id: str, base_url: str) -> str:
    """Billing portal where the connected account manages its platform subscription."""
    params = {"customer_account": account_id, "return_url": f"{base_url}/connect/"}
    hint = (
        "Most likely the Customer portal settings are not saved yet: Stripe Dashboard, "
        "Settings, Billing, Customer portal, Save (docs/connect-setup.md, step H2)."
    )
    return call(lambda: client().v1.billing_portal.sessions.create(params), hint).url


# ---------- 7. Webhook helpers ----------
def parse_thin(raw: bytes, sig: str | None, secret: str) -> Any:
    """Verify Stripe-Signature (HMAC-SHA256, 300 s tolerance), then parse a thin notification.

    The brief's sample calls it parseThinEvent; stripe-python 16 names it
    parse_event_notification. No network call.
    """
    return client().parse_event_notification(raw, sig, secret)


def parse_snapshot(raw: bytes, sig: str | None, secret: str) -> stripe.Event:
    """Verify Stripe-Signature, then build a snapshot (v1) Event with the full object inside."""
    return client().construct_event(raw, sig, secret)


def fetch_event(event_id: str, context: Any = None) -> Any:
    """A thin event carries only ids: fetch the full event (brief: v2.core.events.retrieve).

    `context` is set when the event came from a connected account's scope; it must go with
    the request or Stripe can't find the event.
    """
    options = {"stripe_context": context} if context else None
    return call(lambda: client().v2.core.events.retrieve(event_id, options=options))


def subscription_account(subscription_id: str) -> str | None:
    """For a payload without customer_account (an older API version), ask Stripe."""
    return dig(
        call(lambda: client().v1.subscriptions.retrieve(subscription_id)), "customer_account"
    )


def plan_summary(account_id: str) -> dict | None:
    """The account's platform plan as Stripe sees it right now, or None if it never subscribed.

    Webhooks re-read this instead of trusting the event body, so duplicate or out-of-order
    deliveries still settle on the right answer.
    """
    params = {"customer_account": account_id, "status": "all", "limit": 10}
    subs = call(lambda: client().v1.subscriptions.list(params)).data
    # Prefer the subscription that grants access, then any open one, then the newest.
    best = (
        next((s for s in subs if s.status in ("active", "trialing")), None)
        or next((s for s in subs if s.status in OPEN), None)
        or (subs[0] if subs else None)
    )
    if best is None:
        return None
    item = best.items.data[0]  # brief: subscription.items.data[0].price / .quantity
    return {
        "sub_id": best.id,
        "sub_status": best.status,
        "sub_price_id": item.price.id,  # upgrade or downgrade: the price changes
        "sub_quantity": item.quantity,  # quantity change: grant the new quantity
        "sub_cancel_at_period_end": bool(best.cancel_at_period_end),  # false again = reactivated
        "sub_paused": dig(best, "pause_collection") is not None,  # null = resumed
    }
