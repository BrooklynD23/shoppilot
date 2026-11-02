"""Stripe webhooks for the Connect sample (spec 10 §9): thin v2 account events, billing events.

Stripe sends no X-ShopPilot header and no cookie, so app/safety/web.py exempts exactly these two
paths from the CSRF check; each route verifies the Stripe-Signature header instead (HMAC-SHA256
of the raw body, 300 s tolerance). If a Stripe call fails, the route returns 5xx, records
nothing, and Stripe retries the delivery later.
"""

import logging
from typing import Any

import stripe
from fastapi import APIRouter, Request
from starlette.concurrency import run_in_threadpool

from app.connect import store, stripe_calls
from app.connect.config import connect_settings, fail, require
from app.connect.stripe_calls import dig

log = logging.getLogger(__name__)
# Included by routes.router, so it inherits /api/connect, the CONNECT_ENABLED gate and the IP cap.
router = APIRouter()
BAD_PAYLOAD = (stripe.SignatureVerificationError, ValueError, KeyError)


# ---------- thin events: v2 account updates (brief: "use thin events for V2 accounts") ----------
def on_requirements_updated(event: Any, account_id: str | None) -> None:
    # Brief: "respond to update events by collecting any updated requirements". Nothing is
    # stored here: the dashboard reads requirements live and, when something is currently_due
    # or past_due, shows "Onboard to collect payments" again. That opens a fresh Account Link
    # where the user gives Stripe what it now needs.
    log.info("connect thin event: requirements updated account=%s", account_id)


def on_capability_updated(event: Any, account_id: str | None) -> None:
    # A capability (card_payments for merchants) changed status. The dashboard reads it live.
    capability = dig(event, "data", "updated_capability")
    log.info("connect thin event: %s %s account=%s", event.type, capability, account_id)


def on_unknown(event: Any, account_id: str | None) -> None:
    log.info("connect thin event not handled: %s account=%s", event.type, account_id)


THIN_HANDLERS = {
    "v2.core.account[requirements].updated": on_requirements_updated,
    "v2.core.account[configuration.merchant].capability_status_updated": on_capability_updated,
    "v2.core.account[configuration.customer].capability_status_updated": on_capability_updated,
    # In the brief's listen list; these accounts have no recipient configuration.
    "v2.core.account[configuration.recipient].capability_status_updated": on_capability_updated,
}


@router.post("/webhooks/thin")
async def thin_webhook(request: Request) -> dict:
    raw = await request.body()  # the exact bytes Stripe signed: never re-encode before verifying
    # The Stripe SDK is synchronous: run it off the event loop.
    return await run_in_threadpool(handle_thin, raw, request.headers.get("stripe-signature"))


def handle_thin(raw: bytes, sig: str | None) -> dict:
    # 1. The signing secret.
    # PLACEHOLDER: STRIPE_CONNECT_THIN_WEBHOOK_SECRET=whsec_... (thin `stripe listen` output).
    secret = require(
        connect_settings().stripe_connect_thin_webhook_secret, "STRIPE_CONNECT_THIN_WEBHOOK_SECRET"
    )
    # 2. Verify the signature and parse the thin notification: just ids, no account data.
    try:
        notif = stripe_calls.parse_thin(raw, sig, secret.get_secret_value())
    except BAD_PAYLOAD:
        fail(400, "bad_signature", "Invalid Stripe signature or payload.")
    if notif.livemode:
        fail(400, "bad_signature", "Live-mode events are not accepted.")
    # 3. Stripe can deliver the same event twice.
    if store.seen(notif.id):
        return {"received": True, "duplicate": True}
    # 4. Fetch the full event (brief: client.v2.core.events.retrieve(thinEvent.id)).
    event = stripe_calls.fetch_event(notif.id, notif.context)
    # 5. One handler per event type; the related object is the connected account.
    account_id = dig(event, "related_object", "id")
    THIN_HANDLERS.get(event.type, on_unknown)(event, account_id)
    # 6. Record it last, so a failure above leaves no row and Stripe's retry runs it again.
    store.record_event(notif.id, event.type, account_id)
    return {"received": True}


# ---------- snapshot events: the platform subscription (brief: "not thin events") ----------
SUBSCRIPTION_EVENTS = frozenset(
    {
        "customer.subscription.created",  # added: the first status after Checkout
        "customer.subscription.updated",  # upgrades, downgrades, quantity, cancel, pause
        "customer.subscription.deleted",  # canceled: revoke access
    }
)
# The rest of the brief's table: recorded, plus one log line saying what to check.
RECORD_ONLY = {
    "payment_method.attached": "a customer added a payment method",
    "payment_method.detached": "a customer removed a payment method",
    "customer.updated": (
        "billing details changed: check invoice_settings.default_payment_method "
        "(billing info only, never a login credential)"
    ),
    "customer.tax_id.created": "a customer added a tax ID",
    "customer.tax_id.deleted": "a customer removed a tax ID",
    "customer.tax_id.updated": "a tax ID's verification changed",
    "billing_portal.configuration.created": "a billing portal configuration was created",
    "billing_portal.configuration.updated": "a billing portal configuration was updated",
    "billing_portal.session.created": "a billing portal session was opened",
}


@router.post("/webhooks/billing")
async def billing_webhook(request: Request) -> dict:
    raw = await request.body()
    return await run_in_threadpool(handle_billing, raw, request.headers.get("stripe-signature"))


def handle_billing(raw: bytes, sig: str | None) -> dict:
    # 1. The signing secret.
    # PLACEHOLDER: STRIPE_BILLING_WEBHOOK_SECRET=whsec_... (billing `stripe listen` output).
    secret = require(
        connect_settings().stripe_billing_webhook_secret, "STRIPE_BILLING_WEBHOOK_SECRET"
    )
    # 2. Verify the signature and parse the snapshot event (the full object is inside).
    try:
        event = stripe_calls.parse_snapshot(raw, sig, secret.get_secret_value())
    except BAD_PAYLOAD:
        fail(400, "bad_signature", "Invalid Stripe signature or payload.")
    if event.livemode:
        fail(400, "bad_signature", "Live-mode events are not accepted.")
    # 3. Dedupe.
    if store.seen(event.id):
        return {"received": True, "duplicate": True}
    # 4. Which account is it about? V2: customer_account holds the acct_ id; the brief says
    #    never use .customer.
    obj = event.data.object
    account_id = dig(obj, "customer_account")
    if event.type in SUBSCRIPTION_EVENTS:
        if account_id is None:  # a destination on an older API version: ask Stripe
            account_id = stripe_calls.subscription_account(obj.id)
        # 5. Grant or revoke access: re-read the plan from Stripe and store it, so access
        #    matches what is paid for now (price, quantity, cancel_at_period_end, pause).
        if account_id and store.get_by_account_id(account_id):
            store.set_plan(account_id, stripe_calls.plan_summary(account_id))
            log.info("connect billing event %s: plan synced account=%s", event.type, account_id)
    else:
        what = RECORD_ONLY.get(event.type, "not handled")
        log.info("connect billing event %s: %s account=%s", event.type, what, account_id)
    # 6. Record it last (see handle_thin).
    store.record_event(event.id, event.type, account_id)
    return {"received": True}
