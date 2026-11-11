"""Spec 10 §14.1 tests 1-13: flag, config, caps, identity and every Stripe call shape (mocked)."""

import logging
from types import SimpleNamespace

import pytest
import stripe
from fastapi.testclient import TestClient

from app.config import session_hash
from tests.connect.conftest import (
    ACCT,
    OWNER,
    PROD,
    account_obj,
    obj,
    plan,
    price_obj,
    product_obj,
    sub_obj,
)

BRIEF_PARAMS = {  # the brief's V2 account properties, exactly
    "display_name": "Fern & Kiln",
    "contact_email": "owner@example.com",
    "identity": {"country": "us"},
    "dashboard": "full",
    "defaults": {"responsibilities": {"fees_collector": "stripe", "losses_collector": "stripe"}},
    "configuration": {
        "customer": {},
        "merchant": {"capabilities": {"card_payments": {"requested": True}}},
    },
}
ROUTES = [
    ("GET", "/api/connect/account"),
    ("POST", "/api/connect/accounts"),
    ("POST", "/api/connect/onboard"),
    ("POST", "/api/connect/products"),
    ("GET", f"/api/connect/store/{ACCT}"),
    ("POST", "/api/connect/checkout"),
    ("POST", "/api/connect/subscribe"),
    ("POST", "/api/connect/portal"),
    ("POST", "/api/connect/webhooks/thin"),
    ("POST", "/api/connect/webhooks/billing"),
]
PRODUCT = {"name": "Mug", "description": "", "price_cents": 1500, "currency": "usd"}


def err(r) -> dict:
    return r.json()["error"]


# ---------- 1-3: flag, routing, config ----------
@pytest.mark.parametrize("method,path", ROUTES)
def test_flag_off_every_route_is_404(client, tmp_data_dir, monkeypatch, method, path):
    from app.connect import stripe_calls

    built = []
    monkeypatch.setattr(stripe_calls, "client", lambda: built.append(1))
    r = client.request(method, path, json={} if method == "POST" else None)
    assert r.status_code == 404 and err(r)["code"] == "not_found"
    assert built == [] and not (tmp_data_dir / "connect.db").exists()


@pytest.mark.parametrize("path", ["/api/connect/webhooks/thin", "/api/connect/webhooks/billing"])
def test_flag_off_webhook_without_csrf_header_is_404(tmp_data_dir, path):
    from app.main import app

    with TestClient(app) as stripe_like:  # no X-ShopPilot, like Stripe
        r = stripe_like.post(path, content=b"{}", headers={"stripe-signature": "t=1,v1=x"})
    assert r.status_code == 404 and not (tmp_data_dir / "connect.db").exists()


@pytest.mark.parametrize("value", ["", "0", "false", "off", "2"])
def test_only_on_values_enable_connect(client, set_env, value):
    set_env(CONNECT_ENABLED=value)
    assert client.get("/api/connect/account").status_code == 404


@pytest.mark.parametrize("value", ["1", "true", "YES", " on "])
def test_on_values_enable_connect(client, connect_env, set_env, value):
    set_env(CONNECT_ENABLED=value)
    assert client.get("/api/connect/account").status_code == 200


def test_connect_routes_are_registered_before_the_api_catch_all(client, connect_env):
    from app.connect.routes import router as connect_router
    from app.main import api, app

    included = [getattr(r, "original_router", None) for r in app.routes]  # FastAPI 0.162 shape
    assert included.index(connect_router) < included.index(api)
    assert client.get("/api/connect/account").status_code == 200
    for path in ("/api/nope", "/api/connect/nope"):
        r = client.get(path)
        assert r.status_code == 404 and err(r)["code"] == "not_found"


def test_bad_setting_is_a_503_naming_it_and_the_app_still_runs(client, connect_env, set_env):
    set_env(PUBLIC_BASE_URL="ftp://evil.example/path")
    r = client.get("/api/connect/account")
    assert r.status_code == 503 and err(r)["code"] == "connect_misconfigured"
    assert "PUBLIC_BASE_URL" in err(r)["message"] and "evil" not in r.text
    assert client.get("/healthz").status_code == 200
    set_env(CONNECT_ENABLED=None)
    assert client.get("/api/connect/account").status_code == 404


@pytest.mark.parametrize(
    "name,value",
    [
        ("PUBLIC_BASE_URL", "http://testserver/"),
        ("PUBLIC_BASE_URL", "testserver"),
        ("STRIPE_CONNECT_THIN_WEBHOOK_SECRET", "not_a_whsec"),
        ("STRIPE_BILLING_WEBHOOK_SECRET", "sk_test_oops"),
        ("STRIPE_PLATFORM_PRICE_ID", "prod_123"),
        ("CONNECT_APPLICATION_FEE_CENTS", "-1"),
        ("CONNECT_APPLICATION_FEE_CENTS", "10001"),
        ("CONNECT_APPLICATION_FEE_CENTS", "abc"),
    ],
)
def test_invalid_values_are_named_never_echoed(client, connect_env, set_env, name, value):
    set_env(**{name: value})
    r = client.get("/api/connect/account")
    assert r.status_code == 503 and err(r)["code"] == "connect_misconfigured"
    assert name in err(r)["message"] and value not in r.text


def test_prod_needs_an_https_base_url():
    from pydantic import ValidationError

    from app.connect.config import ConnectSettings

    with pytest.raises(ValidationError):
        ConnectSettings(app_env="prod", public_base_url="http://shop.example")
    assert ConnectSettings(app_env="prod", public_base_url="https://shop.onrender.com")
    assert ConnectSettings(app_env="dev", public_base_url="http://localhost:8000")


def test_values_are_stripped_and_empty_means_unset(connect_env, set_env):
    from app.connect.config import connect_settings

    set_env(PUBLIC_BASE_URL="http://testserver\r", STRIPE_PLATFORM_PRICE_ID="  ")
    cs = connect_settings()
    assert cs.public_base_url == "http://testserver" and cs.stripe_platform_price_id is None
    assert cs.connect_application_fee_cents == 123  # the brief's sample fee


def test_missing_price_is_a_503_with_the_fix_and_a_log_line(client, account, set_env, caplog):
    set_env(STRIPE_PLATFORM_PRICE_ID=None)
    with caplog.at_level(logging.WARNING):
        r = client.post("/api/connect/subscribe")
    want = "STRIPE_PLATFORM_PRICE_ID is not set: run scripts/create_platform_price.py"
    assert r.status_code == 503 and err(r)["code"] == "connect_not_configured"
    assert want in err(r)["message"] and want in caplog.text
    assert client.get("/api/connect/account").json()["plan_available"] is False


def test_missing_base_url_is_named(client, account, set_env):
    set_env(PUBLIC_BASE_URL=None)
    r = client.post("/api/connect/onboard")
    assert r.status_code == 503 and "PUBLIC_BASE_URL is not set" in err(r)["message"]


def test_missing_secret_key_is_named(client, connect_env, set_env):
    from app.connect import stripe_calls

    set_env(STRIPE_SECRET_KEY=None)
    stripe_calls.client.cache_clear()
    r = client.post("/api/connect/accounts", json=OWNER)
    assert r.status_code == 503 and "STRIPE_SECRET_KEY is not set" in err(r)["message"]


def test_client_refuses_a_live_key_even_past_the_boot_check(monkeypatch, connect_env):
    from pydantic import SecretStr

    from app.config import Settings
    from app.connect import stripe_calls

    made = []
    monkeypatch.setattr(stripe_calls.stripe, "StripeClient", lambda *a, **k: made.append(a))
    live = Settings.model_construct(stripe_secret_key=SecretStr("sk_live_x"))
    monkeypatch.setattr(stripe_calls, "get_settings", lambda: live)
    with pytest.raises(RuntimeError, match="test key"):
        stripe_calls.client()
    assert made == []


def test_client_strips_the_key_and_pins_no_api_version(monkeypatch, connect_env, set_env):
    from app.connect import stripe_calls

    made = []
    monkeypatch.setattr(
        stripe_calls.stripe, "StripeClient", lambda *a, **k: made.append((a, k)) or "C"
    )
    set_env(STRIPE_SECRET_KEY="sk_test_abc\r")
    stripe_calls.client.cache_clear()
    assert stripe_calls.client() == "C" and stripe_calls.client() == "C"
    assert made == [(("sk_test_abc",), {"max_network_retries": 2})]  # built once, cached


# ---------- 4-5: create account, identity, caps ----------
def test_create_account_sends_exactly_the_brief_params(client, fake_stripe, db_rows, tmp_data_dir):
    r = client.post("/api/connect/accounts", json=OWNER)
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["created"] is True and body["account_id"].startswith("acct_1Test")
    [call] = fake_stripe.rec["accounts.create"].calls
    token = client.cookies.get("sp_connect")
    assert call["params"] == BRIEF_PARAMS
    assert call["options"] == {"idempotency_key": f"connect-acct:{session_hash(token)}"}
    cookie = r.headers["set-cookie"].lower()
    assert "httponly" in cookie and "path=/api/connect" in cookie and "samesite=lax" in cookie
    assert "secure" not in cookie  # APP_ENV=test; prod adds Secure
    [row] = db_rows()
    assert row["session_hash"] == session_hash(token) and row["account_id"] == body["account_id"]
    assert row["display_name"] == "Fern & Kiln"
    raw = (tmp_data_dir / "connect.db").read_bytes()
    assert token.encode() not in raw and b"owner@example.com" not in raw
    again = client.post("/api/connect/accounts", json=OWNER)
    assert again.json() == {"account_id": body["account_id"], "created": False}
    assert len(fake_stripe.rec["accounts.create"].calls) == 1


def test_create_account_per_ip_cap(client, fake_stripe):
    codes = []
    for _ in range(4):
        client.cookies.clear()  # a new browser each time
        codes.append(client.post("/api/connect/accounts", json=OWNER).status_code)
    assert codes == [200, 200, 200, 429]


def test_create_account_global_daily_cap(client, fake_stripe, monkeypatch):
    from app.connect import routes

    monkeypatch.setattr(routes, "ACCOUNTS_PER_DAY", 1)
    assert client.post("/api/connect/accounts", json=OWNER).status_code == 200
    client.cookies.clear()
    r = client.post("/api/connect/accounts", json=OWNER)
    assert r.status_code == 429 and err(r)["code"] == "connect_capacity"
    assert len(fake_stripe.rec["accounts.create"].calls) == 1


@pytest.mark.parametrize(
    "body",
    [
        {**OWNER, "contact_email": "not-an-email"},
        {**OWNER, "contact_email": "a@b.co" + "x" * 250},
        {**OWNER, "display_name": "x" * 81},
        {**OWNER, "display_name": "   "},
        {"display_name": "Shop"},
    ],
)
def test_account_input_is_validated_without_echo(client, fake_stripe, body):
    r = client.post("/api/connect/accounts", json=body)
    assert r.status_code == 422 and err(r)["code"] == "bad_request"
    assert "not-an-email" not in r.text and fake_stripe.rec["accounts.create"].calls == []


def test_a_garbage_cookie_is_ignored(client, fake_stripe):
    r = client.get("/api/connect/account", headers={"Cookie": "sp_connect=garbage"})
    assert r.status_code == 200 and r.json()["account"] is None


# ---------- 6: live status ----------
@pytest.mark.parametrize(
    "card,req,ready,complete",
    [
        ("active", "eventually_due", True, True),
        ("active", None, True, True),
        ("pending", "currently_due", False, False),
        ("restricted", "past_due", False, False),
    ],
)
def test_status_is_read_live_and_never_stored(
    client, account, fake_stripe, db_rows, card, req, ready, complete
):
    fake_stripe.rec["accounts.retrieve"].result = account_obj(card=card, req=req)
    before = db_rows()
    r = client.get("/api/connect/account")
    assert r.status_code == 200
    a = r.json()["account"]
    [call] = fake_stripe.rec["accounts.retrieve"].calls
    assert call["id"] == account
    assert call["params"] == {"include": ["configuration.merchant", "requirements"]}
    assert a["ready_to_process_payments"] is ready and a["onboarding_complete"] is complete
    assert a["card_payments_status"] == card and a["requirements_status"] == req
    assert a["id"] == account and a["display_name"] == "Fern & Kiln"
    assert a["products_created"] == 0 and a["product_limit"] == 3 and a["plan"] is None
    assert a["storefront_path"] == f"/connect/store/?account={account}" and a["events"] == []
    assert db_rows() == before


def test_no_account_yet_needs_no_stripe_call(client, fake_stripe):
    r = client.get("/api/connect/account")
    assert r.json() == {"account": None, "fee_cents": 123, "plan_available": True}
    assert fake_stripe.rec["accounts.retrieve"].calls == []


def test_account_view_shows_the_plan_and_recent_events(client, account, fake_stripe):
    from app.connect import store

    store.set_plan(account, plan(status="active"))
    store.record_event("evt_1", "customer.subscription.created", account)
    a = client.get("/api/connect/account").json()["account"]
    assert a["plan"] == {
        "status": "active",
        "price_id": "price_test1",
        "quantity": 1,
        "cancel_at_period_end": False,
        "paused": False,
        "has_pro": True,
    }
    assert a["product_limit"] == 20
    assert [e["type"] for e in a["events"]] == ["customer.subscription.created"]


# ---------- 7: onboarding link ----------
def test_onboarding_link_params(client, account, fake_stripe):
    r = client.post("/api/connect/onboard", headers={"host": "evil.example"})
    assert r.status_code == 200 and r.json() == {
        "url": "https://connect.stripe.com/setup/e/acct_x/abc"
    }
    [call] = fake_stripe.rec["account_links.create"].calls
    assert call["params"] == {  # no `configurations`: removed from the API (spec F3)
        "account": account,
        "use_case": {
            "type": "account_onboarding",
            "account_onboarding": {
                "refresh_url": "http://testserver/connect/?refresh=1",
                "return_url": f"http://testserver/connect/?accountId={account}",
            },
        },
    }


@pytest.mark.parametrize(
    "path,body",
    [
        ("/api/connect/onboard", None),
        ("/api/connect/subscribe", None),
        ("/api/connect/portal", None),
        ("/api/connect/products", PRODUCT),
    ],
)
def test_routes_that_need_an_account_say_so(client, fake_stripe, path, body):
    r = client.post(path, json=body)
    assert r.status_code == 404 and err(r)["code"] == "no_account"


# ---------- 8: products ----------
def test_create_product_on_the_connected_account(client, account, fake_stripe):
    r = client.post("/api/connect/products", json=PRODUCT)
    assert r.status_code == 200, r.text
    assert r.json() == {"id": PROD, "products_created": 1, "product_limit": 3}
    [call] = fake_stripe.rec["products.create"].calls
    assert call["params"] == {  # empty description omitted: Stripe rejects ""
        "name": "Mug",
        "default_price_data": {"unit_amount": 1500, "currency": "usd"},
    }
    assert call["options"]["stripe_account"] == account  # the Stripe-Account header (brief)
    assert call["options"]["idempotency_key"].startswith(f"connect-prod:{account}:0:")


def test_product_description_is_sent_when_given(client, account, fake_stripe):
    client.post("/api/connect/products", json={**PRODUCT, "description": "Stoneware"})
    [call] = fake_stripe.rec["products.create"].calls
    assert call["params"]["description"] == "Stoneware"


def test_product_cap_is_3_free_and_20_with_pro(client, account, fake_stripe):
    from app.connect import store

    for i in range(3):
        r = client.post("/api/connect/products", json={**PRODUCT, "name": f"P{i}"})
        assert r.status_code == 200
    r = client.post("/api/connect/products", json=PRODUCT)
    assert r.status_code == 403 and err(r)["code"] == "product_limit"
    store.set_plan(account, plan(status="active"))
    r = client.post("/api/connect/products", json=PRODUCT)
    assert r.status_code == 200 and r.json() == {
        "id": PROD,
        "products_created": 4,
        "product_limit": 20,
    }
    store.set_plan(account, plan(status="active", paused=True))
    assert client.post("/api/connect/products", json=PRODUCT).status_code == 403


@pytest.mark.parametrize(
    "patch,code",
    [
        ({"price_cents": 123}, "price_below_fee"),
        ({"price_cents": 99}, "bad_request"),
        ({"price_cents": 100_001}, "bad_request"),
        ({"currency": "eur"}, "bad_request"),
        ({"name": ""}, "bad_request"),
        ({"name": "x" * 81}, "bad_request"),
        ({"description": "x" * 501}, "bad_request"),
    ],
)
def test_product_input_is_validated(client, account, fake_stripe, patch, code):
    r = client.post("/api/connect/products", json={**PRODUCT, **patch})
    assert r.status_code == 422 and err(r)["code"] == code
    assert fake_stripe.rec["products.create"].calls == []


# ---------- 9: storefront ----------
def test_storefront_lists_one_time_products_on_the_account(client, account, fake_stripe):
    recurring = product_obj("prod_Recurring0001", price=price_obj(kind="recurring"))
    no_price = obj(id="prod_NoPrice000001", name="X", description=None, default_price=None)
    fake_stripe.rec["products.list"].result = obj(data=[product_obj(), recurring, no_price])
    client.cookies.clear()  # public: shoppers have no cookie
    r = client.get(f"/api/connect/store/{account}")
    assert r.status_code == 200
    assert r.json() == {
        "account_id": account,
        "display_name": "Fern & Kiln",
        "products": [
            {
                "id": PROD,
                "name": "Mug",
                "description": "Stoneware",
                "unit_amount": 1500,
                "currency": "usd",
            }
        ],
    }
    [call] = fake_stripe.rec["products.list"].calls
    assert call["params"] == {"limit": 20, "active": True, "expand": ["data.default_price"]}
    assert call["options"] == {"stripe_account": account}


def test_storefront_only_serves_accounts_made_here(client, fake_stripe):
    r = client.get("/api/connect/store/acct_1Unknown00000000")
    assert r.status_code == 404 and err(r)["code"] == "not_found"
    assert client.get("/api/connect/store/not-an-account").status_code == 422
    assert fake_stripe.rec["products.list"].calls == []


# ---------- 10: storefront checkout (direct charge) ----------
def test_checkout_is_a_direct_charge_with_the_platform_fee(client, account, fake_stripe, set_env):
    set_env(CONNECT_APPLICATION_FEE_CENTS="250")
    client.cookies.clear()
    body = {"account_id": account, "product_id": PROD, "quantity": 2}
    r = client.post("/api/connect/checkout", json=body)
    assert r.status_code == 200 and r.json() == {
        "url": "https://checkout.stripe.com/c/pay/cs_test_x"
    }
    [got] = fake_stripe.rec["products.retrieve"].calls
    assert got["id"] == PROD and got["params"] == {"expand": ["default_price"]}
    assert got["options"] == {"stripe_account": account}
    [call] = fake_stripe.rec["checkout.create"].calls
    assert call["params"] == {
        "line_items": [
            {
                "price_data": {"currency": "usd", "unit_amount": 1500, "product": PROD},
                "quantity": 2,
            }
        ],
        "payment_intent_data": {"application_fee_amount": 250},
        "mode": "payment",
        "success_url": (
            f"http://testserver/connect/success/?session_id={{CHECKOUT_SESSION_ID}}&account={account}"
        ),
        "cancel_url": f"http://testserver/connect/store/?account={account}",
    }
    assert "{CHECKOUT_SESSION_ID}" in call["params"]["success_url"]
    assert call["options"] == {"stripe_account": account}


@pytest.mark.parametrize(
    "product,code",
    [
        (product_obj(active=False), "product_unavailable"),
        (product_obj(price=price_obj(kind="recurring")), "product_unavailable"),
        (product_obj(price=price_obj(amount=None)), "product_unavailable"),
        (product_obj(price=price_obj(amount=100)), "price_below_fee"),
    ],
)
def test_checkout_refuses_what_it_cannot_sell(client, account, fake_stripe, product, code):
    fake_stripe.rec["products.retrieve"].result = product
    r = client.post("/api/connect/checkout", json={"account_id": account, "product_id": PROD})
    assert r.status_code == 422 and err(r)["code"] == code
    assert fake_stripe.rec["checkout.create"].calls == []


@pytest.mark.parametrize(
    "body,status",
    [
        ({"account_id": "acct_1Unknown00000000", "product_id": PROD}, 404),
        ({"account_id": ACCT, "product_id": "price_123456789"}, 422),
        ({"account_id": ACCT, "product_id": PROD, "quantity": 0}, 422),
        ({"account_id": ACCT, "product_id": PROD, "quantity": 11}, 422),
    ],
)
def test_checkout_input(client, fake_stripe, body, status):
    assert client.post("/api/connect/checkout", json=body).status_code == status
    assert fake_stripe.rec["products.retrieve"].calls == []


# ---------- 11-12: platform subscription and billing portal ----------
def test_subscribe_uses_customer_account_at_platform_level(client, account, fake_stripe):
    r = client.post("/api/connect/subscribe")
    assert r.status_code == 200 and r.json()["url"].startswith("https://checkout.stripe.com/")
    [call] = fake_stripe.rec["checkout.create"].calls
    assert call["params"] == {  # never `customer`, never a Stripe-Account header
        "customer_account": account,
        "mode": "subscription",
        "line_items": [{"price": "price_test1", "quantity": 1}],
        "success_url": "http://testserver/connect/?subscribed=1&session_id={CHECKOUT_SESSION_ID}",
        "cancel_url": "http://testserver/connect/",
        "expires_at": call["params"]["expires_at"],
    }
    # No Stripe-Account header; only an idempotency key, so repeat clicks reuse one session.
    assert set(call["options"]) == {"idempotency_key"}


@pytest.mark.parametrize("status", ["active", "trialing", "past_due", "incomplete", "paused"])
def test_subscribe_is_409_while_a_plan_is_open(client, account, fake_stripe, status):
    from app.connect import store

    store.set_plan(account, plan(status=status))
    fake_stripe.rec["subscriptions.list"].result = obj(data=[sub_obj(status=status)])
    r = client.post("/api/connect/subscribe")
    assert r.status_code == 409 and err(r)["code"] == "already_subscribed"
    assert fake_stripe.rec["checkout.create"].calls == []


def test_subscribe_again_after_a_cancel(client, account, fake_stripe):
    from app.connect import store

    store.set_plan(account, plan(status="canceled"))
    assert client.post("/api/connect/subscribe").status_code == 200


def test_portal_sends_only_customer_account_and_return_url(client, account, fake_stripe):
    r = client.post("/api/connect/portal")
    assert r.status_code == 200 and r.json()["url"].startswith("https://billing.stripe.com/")
    [call] = fake_stripe.rec["portal.create"].calls
    assert call["params"] == {
        "customer_account": account,
        "return_url": "http://testserver/connect/",
    }
    assert call.get("options") is None


# ---------- 13: Stripe failures ----------
def test_a_live_mode_object_is_blocked(client, account, fake_stripe):
    fake_stripe.rec["account_links.create"].result = SimpleNamespace(livemode=True, url="https://x")
    r = client.post("/api/connect/onboard")
    assert r.status_code == 503 and err(r)["code"] == "live_mode_blocked"


def test_a_stripe_rejection_is_422_without_stripe_text(client, account, fake_stripe):
    fake_stripe.rec["portal.create"].result = stripe.InvalidRequestError("RAW_DETAIL", param="x")
    r = client.post("/api/connect/portal")
    assert r.status_code == 422 and err(r)["code"] == "stripe_invalid_request"
    assert "RAW_DETAIL" not in r.text
    assert "Customer portal" in err(r)["message"]  # the likely cause, from the route


@pytest.mark.parametrize(
    "exc,status,code",
    [
        (stripe.RateLimitError("x"), 429, "stripe_rate_limited"),
        (stripe.AuthenticationError("x"), 503, "stripe_auth"),
        (stripe.APIConnectionError("x"), 503, "stripe_unreachable"),
        (stripe.IdempotencyError("x"), 409, "idempotency_conflict"),
        (stripe.StripeError("x"), 502, "stripe_error"),
    ],
)
def test_stripe_errors_map_to_safe_envelopes(client, fake_stripe, db_rows, exc, status, code):
    fake_stripe.rec["accounts.create"].result = exc
    r = client.post("/api/connect/accounts", json=OWNER)
    assert r.status_code == status and err(r)["code"] == code
    assert db_rows() == [] and "sp_connect" not in r.headers.get("set-cookie", "")


def test_plan_summary_picks_the_subscription_that_grants_access(fake_stripe):
    from app.connect import stripe_calls

    fake_stripe.rec["subscriptions.list"].result = obj(
        data=[sub_obj(status="canceled", price="price_old"), sub_obj(status="active", quantity=3)]
    )
    assert stripe_calls.plan_summary(ACCT) == {
        "sub_id": "sub_Test000001",
        "sub_status": "active",
        "sub_price_id": "price_test1",
        "sub_quantity": 3,
        "sub_cancel_at_period_end": False,
        "sub_paused": False,
    }
    fake_stripe.rec["subscriptions.list"].result = obj(data=[])
    assert stripe_calls.plan_summary(ACCT) is None


# ---------- review fixes (2026-11-02) ----------
def test_subscribe_rechecks_stripe_before_the_webhook_arrives(client, account, fake_stripe):
    # Fix 1: the stored row is empty (webhook not here yet) but Stripe already has a plan.
    fake_stripe.rec["subscriptions.list"].result = obj(data=[sub_obj(status="active")])
    r = client.post("/api/connect/subscribe")
    assert r.status_code == 409 and err(r)["code"] == "already_subscribed"
    assert fake_stripe.rec["checkout.create"].calls == []
    assert client.get("/api/connect/account").json()["account"]["plan"]["has_pro"] is True


def test_repeat_subscribe_clicks_share_one_idempotency_key(
    client, account, fake_stripe, monkeypatch
):
    # Fix 1: two clicks in the same hour ask Stripe for the same Checkout Session, with
    # identical params (Stripe rejects a reused idempotency key with different params).
    import time

    from app.connect import stripe_calls

    hour = int(time.time()) // 3600 * 3600  # frozen in the current hour (sessions stay valid)
    now = [hour + 5]
    monkeypatch.setattr(stripe_calls.time, "time", lambda: now[0])
    client.post("/api/connect/subscribe")
    now[0] = hour + 3540  # 59th minute of the same hour
    client.post("/api/connect/subscribe")
    a, b = fake_stripe.rec["checkout.create"].calls
    assert a["options"]["idempotency_key"] == b["options"]["idempotency_key"]
    assert a["params"]["expires_at"] == b["params"]["expires_at"]
    ttl = a["params"]["expires_at"] - (hour + 3540)
    assert 30 * 60 <= ttl <= 24 * 3600  # Stripe's expires_at window, even for the late click


def test_pro_needs_the_platform_price(client, account, fake_stripe):
    # Fix 2: an active subscription to any other price grants nothing.
    from app.connect import store

    for i in range(3):
        client.post("/api/connect/products", json={**PRODUCT, "name": f"P{i}"})
    store.set_plan(account, plan(status="active", price="price_SomethingElse"))
    r = client.post("/api/connect/products", json=PRODUCT)
    assert r.status_code == 403 and err(r)["code"] == "product_limit"
    store.set_plan(account, plan(status="active", price="price_test1"))
    assert client.post("/api/connect/products", json=PRODUCT).status_code == 200


@pytest.mark.parametrize("card", ["restricted", "inactive", "pending"])
def test_checkout_refuses_a_shop_that_cannot_take_cards(client, account, fake_stripe, card):
    # Fix 3: Buy waits until the connected account's card_payments capability is active.
    fake_stripe.rec["accounts.retrieve"].result = account_obj(card=card)
    r = client.post("/api/connect/checkout", json={"account_id": account, "product_id": PROD})
    assert r.status_code == 422 and err(r)["code"] == "not_onboarded"
    assert fake_stripe.rec["checkout.create"].calls == []
