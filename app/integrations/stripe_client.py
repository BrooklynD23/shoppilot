"""Thin Stripe wrapper: test mode or mock mode, chosen once at import (spec 05 §4, §7, §8).

Never logs or returns the key. Raw Stripe messages never reach the UI.
"""

import hashlib
import logging
from collections.abc import Callable
from typing import Any, Literal

import stripe

from app.config import get_settings

log = logging.getLogger(__name__)

Mode = Literal["test", "mock"]
ERROR_CODES = (
    "already_refunded",
    "amount_exceeds_refundable",
    "stripe_invalid_request",
    "stripe_rate_limited",
    "stripe_auth",
    "stripe_unreachable",
    "idempotency_conflict",
    "stripe_error",
    "live_mode_blocked",
)
_MESSAGES = {
    "already_refunded": "Order already fully refunded.",
    "amount_exceeds_refundable": "Refund larger than what is left on the charge.",
    "stripe_invalid_request": "Stripe rejected the request.",
    "stripe_rate_limited": "Stripe test API busy, try again in a few seconds.",
    "stripe_auth": "Payments are misconfigured; the admin has been notified.",
    "stripe_unreachable": "Can't reach Stripe right now. Nothing was charged or refunded.",
    "idempotency_conflict": "This action was already submitted with different details.",
    "stripe_error": "Payment provider error.",
    "live_mode_blocked": "Live mode detected — blocked.",
}
_INVALID_CODES = {
    "charge_already_refunded": "already_refunded",
    "amount_too_large": "amount_exceeds_refundable",
}
# Order matters: first isinstance match wins; StripeError is the catch-all.
_EXC_CODES: tuple[tuple[type[stripe.StripeError], str], ...] = (
    (stripe.InvalidRequestError, "stripe_invalid_request"),
    (stripe.RateLimitError, "stripe_rate_limited"),
    (stripe.AuthenticationError, "stripe_auth"),
    (stripe.PermissionError, "stripe_auth"),
    (stripe.APIConnectionError, "stripe_unreachable"),
    (stripe.APIError, "stripe_unreachable"),
    (stripe.IdempotencyError, "idempotency_conflict"),
    (stripe.StripeError, "stripe_error"),
)


class StripeFailure(Exception):
    def __init__(self, code: str, user_message: str, request_id: str | None = None):
        super().__init__(code)
        self.code = code
        self.user_message = user_message
        self.request_id = request_id


def resolve_mode(key: str | None, override: str | None) -> Mode:
    """Pure. Empty key -> mock; test key -> test unless override is mock; else refuse boot."""
    if not key:
        return "mock"
    if not key.startswith(("sk_test_", "rk_test_")):
        raise RuntimeError("STRIPE_SECRET_KEY must be a test key")
    return "mock" if override == "mock" else "test"


def _boot() -> tuple[Mode, Any]:
    s = get_settings()
    key = s.stripe_secret_key.get_secret_value() if s.stripe_secret_key else None
    m = resolve_mode(key, s.stripe_mode)
    client = stripe.StripeClient(key, max_network_retries=2) if m == "test" and key else None
    return m, client


_mode, _client = _boot()


def mode() -> Mode:
    return _mode


def _mock_id(prefix: str, key: str) -> str:
    return f"{prefix}_mock_{hashlib.sha1(key.encode()).hexdigest()[:14]}"  # noqa: S324 - id, not security


def _code_for(e: stripe.StripeError) -> str:
    if isinstance(e, stripe.InvalidRequestError) and e.code in _INVALID_CODES:
        return _INVALID_CODES[e.code]
    return next(code for cls, code in _EXC_CODES if isinstance(e, cls))


def _call(fn: Callable[[], Any]) -> Any:
    """Run one Stripe call; map errors to StripeFailure and block any live-mode response."""
    try:
        obj = fn()
    except stripe.StripeError as e:
        code = _code_for(e)
        level = logging.ERROR if code == "stripe_auth" else logging.WARNING
        log.log(level, "stripe call failed code=%s request_id=%s", code, e.request_id)
        raise StripeFailure(code, _MESSAGES[code], e.request_id) from None
    if getattr(obj, "livemode", False):
        log.error("stripe live-mode response blocked")
        raise StripeFailure("live_mode_blocked", _MESSAGES["live_mode_blocked"])
    return obj


def ensure_payment_intent(session_hash: str, order_id: str, amount_cents: int) -> str:
    key = f"pi:{session_hash}:{order_id}"
    if _mode == "mock":
        return _mock_id("pi", key)
    params = {
        "amount": amount_cents,
        "currency": "usd",
        "payment_method": "pm_card_visa",
        "payment_method_types": ["card"],
        "confirm": True,
        "metadata": {"session_hash": session_hash, "order_id": order_id},
        "description": f"ShopPilot+ demo order {order_id}",
    }
    pi = _call(
        lambda: _client.v1.payment_intents.create(params=params, options={"idempotency_key": key})
    )
    return pi.id


def refund(payment_intent_id: str, amount_cents: int, reason: str, idempotency_key: str) -> dict:
    if _mode == "mock":
        return {
            "id": _mock_id("re", idempotency_key),
            "status": "succeeded",
            "amount": amount_cents,
        }
    params = {"payment_intent": payment_intent_id, "amount": amount_cents, "reason": reason}
    r = _call(
        lambda: _client.v1.refunds.create(
            params=params, options={"idempotency_key": idempotency_key}
        )
    )
    return {"id": r.id, "status": r.status, "amount": r.amount}


def create_payment_link(name: str, amount_cents: int, metadata: dict, idempotency_key: str) -> dict:
    if _mode == "mock":
        link_id = _mock_id("plink", idempotency_key)
        return {"id": link_id, "url": "about:blank#mock-" + link_id}
    params = {
        "line_items": [
            {
                "quantity": 1,
                "price_data": {
                    "currency": "usd",
                    "unit_amount": amount_cents,
                    "product_data": {"name": name},
                },
            }
        ],
        "metadata": dict(metadata),
    }
    link = _call(
        lambda: _client.v1.payment_links.create(
            params=params, options={"idempotency_key": idempotency_key}
        )
    )
    return {"id": link.id, "url": link.url}


def deactivate_payment_link(link_id: str) -> None:
    if _mode == "mock":
        return
    _call(lambda: _client.v1.payment_links.update(link_id, params={"active": False}))
