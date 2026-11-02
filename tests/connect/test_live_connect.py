"""Spec 10 §14.2: the Connect Stripe calls against the real sandbox, using the test user account.

    set -a; . ./.env; set +a
    RUN_LIVE=1 CONNECT_TEST_ACCOUNT_ID=acct_1UXQy4AjPf69rvVR \
        uv run pytest tests/connect/test_live_connect.py -m live -v -p no:cacheprovider

Writes to the sandbox: one product per run (archived at the end), unpaid Checkout and portal
sessions (they expire), single-use onboarding links. CONNECT_LIVE_CREATE=1 also creates one new
connected account with the brief's params (off by default: every run would add an account).
"""

import os
import uuid

import pytest

from app.connect import stripe_calls

pytestmark = pytest.mark.live
ACCT = os.environ.get("CONNECT_TEST_ACCOUNT_ID", "acct_1UXQy4AjPf69rvVR")  # the onboarded test user
BASE = "http://localhost:8000"  # Stripe accepts http redirect URLs in a sandbox
FEE = 123


@pytest.fixture(autouse=True)
def sandbox_key():
    if not os.environ.get("STRIPE_SECRET_KEY", "").strip():
        pytest.skip("STRIPE_SECRET_KEY is not set: run `set -a; . ./.env; set +a` first")
    stripe_calls.client.cache_clear()  # build the client from the exported sandbox key


def test_test_account_is_ready_and_onboarded():
    status = stripe_calls.account_status(ACCT)
    assert status["card_payments_status"] == "active"
    assert status["ready_to_process_payments"] is True and status["onboarding_complete"] is True


def test_onboarding_link_points_at_stripe():
    assert stripe_calls.onboarding_link(ACCT, BASE).startswith("https://connect.stripe.com/")


def test_product_lifecycle_and_storefront_checkout():
    idem = f"connect-live-test:{uuid.uuid4().hex}"
    pid = stripe_calls.create_product(ACCT, "Live test mug", "", 1500, "usd", idem)
    try:
        listed = {p["id"]: p for p in stripe_calls.list_products(ACCT)}
        assert listed[pid]["unit_amount"] == 1500 and listed[pid]["currency"] == "usd"
        url = stripe_calls.product_checkout(ACCT, pid, 1, FEE, BASE)
        assert url.startswith("https://checkout.stripe.com/")
    finally:  # archive it so the shop does not fill up with test products
        stripe_calls.client().v1.products.update(pid, {"active": False}, {"stripe_account": ACCT})


def test_platform_subscription_checkout():
    price = os.environ.get("STRIPE_PLATFORM_PRICE_ID", "").strip()
    if not price:
        pytest.skip("STRIPE_PLATFORM_PRICE_ID is not set: run scripts/create_platform_price.py")
    url = stripe_calls.subscription_checkout(ACCT, price, BASE)
    assert url.startswith("https://checkout.stripe.com/")


def test_billing_portal():
    configs = stripe_calls.client().v1.billing_portal.configurations.list({"limit": 1})
    if not configs.data:
        pytest.skip("No Customer portal settings saved yet (docs/connect-setup.md, step H2)")
    assert stripe_calls.portal(ACCT, BASE).startswith("https://billing.stripe.com/")


def test_plan_summary_reads_the_test_account():
    summary = stripe_calls.plan_summary(ACCT)
    assert summary is None or summary["sub_id"].startswith("sub_")


def test_http_routes_end_to_end_with_the_test_account(monkeypatch):
    """The real /api/connect routes against the sandbox, as a browser that owns the test account.

    Test-only shortcut: the mapping is written straight into a temp connect.db, so no new
    connected account is created.
    """
    import secrets

    from fastapi.testclient import TestClient

    from app.config import session_hash
    from app.connect import store
    from app.connect.config import connect_settings
    from app.main import app

    monkeypatch.setenv("CONNECT_ENABLED", "1")
    monkeypatch.setenv("PUBLIC_BASE_URL", BASE)
    connect_settings.cache_clear()
    token = secrets.token_urlsafe(32)
    store.insert_account(session_hash(token), ACCT, "Test connected account")
    browser = {"X-ShopPilot": "1", "Cookie": f"sp_connect={token}"}
    with TestClient(app, headers=browser) as c:
        a = c.get("/api/connect/account").json()["account"]
        assert a["id"] == ACCT and a["ready_to_process_payments"] and a["onboarding_complete"]
        assert (
            c.post("/api/connect/onboard").json()["url"].startswith("https://connect.stripe.com/")
        )
        new = {"name": f"Route mug {uuid.uuid4().hex[:6]}", "price_cents": 1500}
        r = c.post("/api/connect/products", json=new)
        assert r.status_code == 200, r.text
        pid = r.json()["id"]
        try:
            shop = c.get(f"/api/connect/store/{ACCT}").json()
            assert pid in [p["id"] for p in shop["products"]]
            r = c.post("/api/connect/checkout", json={"account_id": ACCT, "product_id": pid})
            assert r.json()["url"].startswith("https://checkout.stripe.com/"), r.text
            if os.environ.get("STRIPE_PLATFORM_PRICE_ID", "").strip():
                r = c.post("/api/connect/subscribe")
                assert r.json()["url"].startswith("https://checkout.stripe.com/"), r.text
        finally:
            stripe_calls.client().v1.products.update(
                pid, {"active": False}, {"stripe_account": ACCT}
            )


def test_create_account_with_the_brief_params():
    if os.environ.get("CONNECT_LIVE_CREATE") != "1":
        pytest.skip("opt-in: CONNECT_LIVE_CREATE=1 creates a new sandbox account each run")
    acct = stripe_calls.create_account(
        f"live-test-{os.getpid()}", "ShopPilot live test", "connect-live-test@example.com"
    )
    assert acct.startswith("acct_")
    print(f"created sandbox account {acct}")  # not a secret; shown with -s
