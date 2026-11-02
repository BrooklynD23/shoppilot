"""Connect HTTP API under /api/connect (spec 10 §7). Every route 404s unless CONNECT_ENABLED=1.

A "user" is one browser holding an sp_connect cookie; only POST /accounts sets it and the server
keeps only its hash. Browser POSTs keep the app's CSRF header check (X-ShopPilot: 1). The two
webhooks are exempt in app/safety/web.py and verify Stripe-Signature instead.
"""

import hashlib
import secrets
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Request, Response
from fastapi import Path as PathParam
from pydantic import BaseModel, Field, StringConstraints

from app.config import get_settings, session_hash
from app.connect import store, stripe_calls, webhooks
from app.connect.config import connect_settings, fail, flag_on, require
from app.db import SESSION_ID_RE

COOKIE = "sp_connect"
ACCOUNT_ID = r"^acct_[A-Za-z0-9]{8,64}$"
PRODUCT_ID = r"^prod_[A-Za-z0-9]{8,64}$"
EMAIL = r"^[^@\s]+@[^@\s]+\.[^@\s]+$"  # Stripe validates it properly
FREE_PRODUCTS, PRO_PRODUCTS = 3, 20  # what the platform plan grants (spec 10 §9.3)
# Abuse caps for a public URL (spec 10 §10).
# ponytail: in-process buckets reset on restart (R48); it's a sandbox, no real money moves.
ACCOUNTS_PER_IP_HOUR, ACCOUNTS_PER_DAY = 3, 20


def _hit_ip(request: Request, bucket: str, limit: int, window_s: float) -> None:
    from app.main import _hit, client_ip  # lazy: app.main imports this module

    _hit((bucket, client_ip(request)), limit, window_s)


def per_ip(bucket: str, limit: int, window_s: float = 60.0):
    def dep(request: Request) -> None:
        _hit_ip(request, bucket, limit, window_s)

    return dep


def gate() -> None:
    """Off by default: every Connect route, webhooks included, is the API's normal 404."""
    if not flag_on():
        fail(404, "not_found", "Unknown API route.")
    connect_settings()  # a bad value -> 503 connect_misconfigured, on Connect routes only


# Order matters: the gate runs before the rate limit, the database and any Stripe call.
router = APIRouter(
    prefix="/api/connect", dependencies=[Depends(gate), Depends(per_ip("connect", 60))]
)
WRITE = [Depends(per_ip("connect_write", 10))]  # browser POSTs: 10 a minute per IP


# ---------- identity and plan helpers ----------
def _token(request: Request) -> str | None:
    token = request.cookies.get(COOKIE, "")
    return token if SESSION_ID_RE.fullmatch(token) else None  # a bad cookie never reaches the DB


def _mapping(request: Request) -> dict | None:
    token = _token(request)
    return store.get_account(session_hash(token)) if token else None


def _need_account(request: Request) -> dict:
    row = _mapping(request)
    if row is None:
        fail(404, "no_account", "Create a connected account first.")
    return row


def _base_url() -> str:
    # Redirect URLs come from PUBLIC_BASE_URL, never the Host header (uvicorn trusts no proxy).
    return require(connect_settings().public_base_url, "PUBLIC_BASE_URL")


def _has_pro(row: dict) -> bool:
    # Brief: customers get only what they're actively subscribed to. Paused = no access.
    return row["sub_status"] in ("active", "trialing") and not row["sub_paused"]


def _product_limit(row: dict) -> int:
    return PRO_PRODUCTS if _has_pro(row) else FREE_PRODUCTS


def _plan(row: dict) -> dict | None:
    if row["sub_id"] is None:
        return None
    return {
        "status": row["sub_status"],
        "price_id": row["sub_price_id"],
        "quantity": row["sub_quantity"],
        "cancel_at_period_end": bool(row["sub_cancel_at_period_end"]),
        "paused": bool(row["sub_paused"]),
        "has_pro": _has_pro(row),
    }


# ---------- routes ----------
@router.get("/account")
def get_account(request: Request) -> dict:
    cs = connect_settings()
    out = {
        "fee_cents": cs.connect_application_fee_cents,
        "plan_available": cs.stripe_platform_price_id is not None,
    }
    row = _mapping(request)
    if row is None:
        return {"account": None, **out}  # no account yet: nothing to ask Stripe
    account_id = row["account_id"]
    return {
        "account": {
            "id": account_id,
            **stripe_calls.account_status(account_id),  # live from Stripe, every time (brief)
            "products_created": row["products_created"],
            "product_limit": _product_limit(row),
            "plan": _plan(row),
            "storefront_path": f"/connect/store/?account={account_id}",
            "events": store.recent_events(account_id),
        },
        **out,
    }


class NewAccount(BaseModel):
    display_name: Annotated[
        str, StringConstraints(strip_whitespace=True, min_length=1, max_length=80)
    ]
    contact_email: Annotated[
        str, StringConstraints(strip_whitespace=True, max_length=254, pattern=EMAIL)
    ]


@router.post("/accounts", dependencies=WRITE)
def create_account(body: NewAccount, request: Request, response: Response) -> dict:
    # 1. Who is asking: the cookie's token, or a new one (43 chars, like the demo's sessions).
    token = _token(request) or secrets.token_urlsafe(32)
    sh = session_hash(token)  # only the hash is stored (R21)
    # 2. One account per user: an existing mapping is returned without calling Stripe.
    row = store.get_account(sh)
    if row is not None:
        return {"account_id": row["account_id"], "created": False}
    # 3. Caps, counted only when a new account is about to be made.
    if store.accounts_created_today() >= ACCOUNTS_PER_DAY:
        fail(429, "connect_capacity", "The demo has made enough accounts today. Try tomorrow.")
    _hit_ip(request, "connect_create", ACCOUNTS_PER_IP_HOUR, 3600.0)
    # 4. Create the V2 account at Stripe, then store the user -> account mapping (brief).
    account_id = stripe_calls.create_account(sh, body.display_name, body.contact_email)
    store.insert_account(sh, account_id, body.display_name)
    # 5. The cookie: HttpOnly, only sent to /api/connect, Secure on the deployed site.
    s = get_settings()
    response.set_cookie(
        COOKIE,
        token,
        max_age=s.session_ttl_hours * 3600,
        httponly=True,
        samesite="lax",
        secure=s.app_env == "prod",
        path="/api/connect",
    )
    return {"account_id": account_id, "created": True}


@router.post("/onboard", dependencies=WRITE)
def onboard(request: Request) -> dict:
    """A fresh single-use onboarding link (brief: "Onboard to collect payments")."""
    row = _need_account(request)
    return {"url": stripe_calls.onboarding_link(row["account_id"], _base_url())}


class NewProduct(BaseModel):
    name: Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=80)]
    description: Annotated[str, StringConstraints(strip_whitespace=True, max_length=500)] = ""
    price_cents: int = Field(ge=100, le=100_000)  # $1.00 to $1,000.00
    currency: Literal["usd"] = "usd"


@router.post("/products", dependencies=WRITE)
def create_product(body: NewProduct, request: Request) -> dict:
    row = _need_account(request)
    fee = connect_settings().connect_application_fee_cents
    if body.price_cents <= fee:  # the shop must earn something after the platform fee
        fail(422, "price_below_fee", f"Set a price above the ${fee / 100:.2f} platform fee.")
    cap = _product_limit(row)
    if row["products_created"] >= cap:
        more = "" if _has_pro(row) else f" ShopPilot+ Pro raises it to {PRO_PRODUCTS}."
        fail(403, "product_limit", f"Your plan allows {cap} products.{more}")
    account_id = row["account_id"]
    # Same user, same count, same form -> same key: a double click replays, never duplicates.
    digest = hashlib.sha256(body.model_dump_json().encode()).hexdigest()[:12]
    idem = f"connect-prod:{account_id}:{row['products_created']}:{digest}"
    product_id = stripe_calls.create_product(
        account_id, body.name, body.description, body.price_cents, body.currency, idem
    )
    count = store.bump_products(row["session_hash"])
    return {"id": product_id, "products_created": count, "product_limit": cap}


# Demo: the shop is picked by its Stripe account ID (the brief allows this). In production, use
# your own shop slug or ID in URLs instead of the Stripe account ID.
@router.get("/store/{account_id}")
def storefront(account_id: Annotated[str, PathParam(pattern=ACCOUNT_ID)]) -> dict:
    row = store.get_by_account_id(account_id)
    if row is None:  # only shops made here, so this can't probe other platform accounts
        fail(404, "not_found", "Unknown shop.")
    return {
        "account_id": account_id,
        "display_name": row["display_name"],
        "products": stripe_calls.list_products(account_id),
    }


class NewCheckout(BaseModel):
    account_id: Annotated[str, StringConstraints(pattern=ACCOUNT_ID)]
    product_id: Annotated[str, StringConstraints(pattern=PRODUCT_ID)]
    quantity: int = Field(1, ge=1, le=10)


@router.post("/checkout", dependencies=WRITE)
def checkout(body: NewCheckout) -> dict:
    """A shopper buys from a storefront: no cookie needed."""
    if store.get_by_account_id(body.account_id) is None:
        fail(404, "not_found", "Unknown shop.")
    fee = connect_settings().connect_application_fee_cents
    url = stripe_calls.product_checkout(
        body.account_id, body.product_id, body.quantity, fee, _base_url()
    )
    return {"url": url}


@router.post("/subscribe", dependencies=WRITE)
def subscribe(request: Request) -> dict:
    """The connected account subscribes to the platform's plan (hosted Checkout)."""
    row = _need_account(request)
    if row["sub_status"] in stripe_calls.OPEN:
        fail(409, "already_subscribed", "You already have a plan. Use Manage billing to change it.")
    # PLACEHOLDER: STRIPE_PLATFORM_PRICE_ID=price_... printed by scripts/create_platform_price.py.
    price_id = require(connect_settings().stripe_platform_price_id, "STRIPE_PLATFORM_PRICE_ID")
    return {"url": stripe_calls.subscription_checkout(row["account_id"], price_id, _base_url())}


@router.post("/portal", dependencies=WRITE)
def billing_portal(request: Request) -> dict:
    """Stripe's billing portal, where the account manages its plan."""
    row = _need_account(request)
    return {"url": stripe_calls.portal(row["account_id"], _base_url())}


router.include_router(webhooks.router)  # POST /webhooks/thin and /webhooks/billing
