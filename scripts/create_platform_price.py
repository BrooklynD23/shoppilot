"""Create (or reuse) the sandbox price for the "ShopPilot+ Pro" platform plan. Safe to re-run.

Usage, from the repo root:
    set -a; . ./.env; set +a
    uv run python scripts/create_platform_price.py

It prints one line to add to .env: STRIPE_PLATFORM_PRICE_ID=price_...  (an id, not a secret).
A re-run reuses the price (lookup_key shoppilot_pro_monthly) and the product tagged with
metadata shoppilot_platform=1, so it never makes duplicates. Sandbox keys only.
"""

import os
import sys
from typing import Any

import stripe

from app.integrations.stripe_client import resolve_mode

LOOKUP_KEY = "shoppilot_pro_monthly"
TAG = "shoppilot_platform"
PRODUCT = {"name": "ShopPilot+ Pro (sandbox)", "metadata": {TAG: "1"}}
PRICE = {
    "currency": "usd",
    "unit_amount": 900,  # $9.00 a month
    "recurring": {"interval": "month"},
    "lookup_key": LOOKUP_KEY,
}


def ensure_platform_price(client: Any) -> tuple[str, bool]:
    """Return (price id, whether it was created now). Platform level: no Stripe-Account header."""
    # 1. A price from an earlier run, found by its lookup key (exact and instant, unlike search).
    found = client.v1.prices.list({"lookup_keys": [LOOKUP_KEY], "active": True, "limit": 1}).data
    if found:
        return found[0].id, False
    # 2. A product from an earlier run, tagged in its metadata; otherwise create it.
    # ponytail: checks the newest 100 active products; page through them if the sandbox grows.
    products = client.v1.products.list({"active": True, "limit": 100}).data
    product = next((p for p in products if getattr(p.metadata, TAG, None) == "1"), None)
    if product is None:
        product = client.v1.products.create(PRODUCT)
    # 3. The monthly price on that product.
    return client.v1.prices.create({"product": product.id, **PRICE}).id, True


def main() -> int:
    # PLACEHOLDER: STRIPE_SECRET_KEY=sk_test_... in .env, exported with `set -a; . ./.env; set +a`.
    key = os.environ.get("STRIPE_SECRET_KEY", "").strip()
    if not key:
        print(
            "STRIPE_SECRET_KEY is not set: run `set -a; . ./.env; set +a` first.", file=sys.stderr
        )
        return 2
    try:
        resolve_mode(key, None)  # the app's own guard: sandbox keys only, a live key never runs
    except RuntimeError:
        print(
            "STRIPE_SECRET_KEY must be a sandbox key (sk_test_... or rk_test_...).", file=sys.stderr
        )
        return 2
    try:
        price_id, created = ensure_platform_price(stripe.StripeClient(key))
    except stripe.AuthenticationError:  # Stripe's message would show part of the key
        print(
            "Stripe rejected STRIPE_SECRET_KEY: copy a current sandbox key into .env.",
            file=sys.stderr,
        )
        return 1
    what = "Created" if created else "Reusing"
    print(f"{what} the ShopPilot+ Pro price. Add this line to .env:", file=sys.stderr)
    print(f"STRIPE_PLATFORM_PRICE_ID={price_id}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
