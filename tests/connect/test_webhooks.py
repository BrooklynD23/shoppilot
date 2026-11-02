"""Spec 10 §14.1 tests 14-17: thin and snapshot webhooks, the exact CSRF exemption, the body cap."""

import logging

import pytest
import stripe
from fastapi.testclient import TestClient

from tests.connect.conftest import (
    ACCT,
    obj,
    plan,
    sign,
    snapshot_payload,
    sub_obj,
    thin_payload,
)

THIN = "/api/connect/webhooks/thin"
BILLING = "/api/connect/webhooks/billing"
THIN_SECRET, BILLING_SECRET = "whsec_thin_test", "whsec_billing_test"
REQS = "v2.core.account[requirements].updated"


def err(r) -> dict:
    return r.json()["error"]


@pytest.fixture
def stripe_post(fake_stripe):
    """Posts like Stripe: raw JSON, a Stripe-Signature header, no X-ShopPilot, cookie or Origin."""
    from app.main import app

    with TestClient(app) as raw:

        def _post(path, payload, secret, sig=None):
            headers = {
                "content-type": "application/json; charset=utf-8",
                "stripe-signature": sig if sig is not None else sign(payload, secret),
            }
            return raw.post(path, content=payload.encode(), headers=headers)

        yield _post


def full_event(event_id="evt_test_thin1", etype=REQS, **data):
    return obj(
        id=event_id,
        type=etype,
        related_object=obj(id=ACCT, type="v2.core.account"),
        data=obj(**data) if data else None,
    )


def sub_data(account, **kw):
    """A customer.subscription.* data.object. `customer` is set on purpose: never use it."""
    return {
        "id": "sub_Test000001",
        "object": "subscription",
        "customer": "cus_NEVER_USED",
        "customer_account": account,
        "status": "active",
        **kw,
    }


# ---------- 14: thin events (v2 account updates) ----------
def test_thin_event_is_verified_fetched_handled_and_recorded(
    stripe_post, fake_stripe, db_rows, monkeypatch
):
    from app.connect import webhooks

    handled = []
    monkeypatch.setitem(webhooks.THIN_HANDLERS, REQS, lambda e, a: handled.append((e.id, a)))
    fake_stripe.rec["events.retrieve"].result = full_event()
    payload = thin_payload()
    r = stripe_post(THIN, payload, THIN_SECRET)
    assert r.status_code == 200 and r.json() == {"received": True}
    [call] = fake_stripe.rec["events.retrieve"].calls
    assert call["id"] == "evt_test_thin1" and call.get("options") is None
    assert handled == [("evt_test_thin1", ACCT)]
    assert db_rows("SELECT id, type, account_id FROM events") == [
        {"id": "evt_test_thin1", "type": REQS, "account_id": ACCT}
    ]
    again = stripe_post(THIN, payload, THIN_SECRET)
    assert again.status_code == 200 and again.json() == {"received": True, "duplicate": True}
    assert len(fake_stripe.rec["events.retrieve"].calls) == 1 and len(handled) == 1


def test_default_handlers_log_each_update(stripe_post, fake_stripe, caplog):
    fake_stripe.rec["events.retrieve"].result = full_event()
    with caplog.at_level(logging.INFO, logger="app.connect"):
        assert stripe_post(THIN, thin_payload(), THIN_SECRET).status_code == 200
    assert f"requirements updated account={ACCT}" in caplog.text


@pytest.mark.parametrize("config", ["merchant", "customer", "recipient"])
def test_capability_events_share_one_handler(stripe_post, fake_stripe, db_rows, caplog, config):
    etype = f"v2.core.account[configuration.{config}].capability_status_updated"
    fake_stripe.rec["events.retrieve"].result = full_event(
        "evt_cap1", etype, updated_capability="card_payments"
    )
    with caplog.at_level(logging.INFO, logger="app.connect"):
        r = stripe_post(THIN, thin_payload("evt_cap1", etype), THIN_SECRET)
    assert r.status_code == 200 and "card_payments" in caplog.text
    assert db_rows("SELECT type FROM events") == [{"type": etype}]


def test_unknown_thin_type_is_recorded_and_ignored(stripe_post, fake_stripe, db_rows):
    etype = "v2.core.account.updated"
    fake_stripe.rec["events.retrieve"].result = full_event("evt_unk1", etype)
    assert stripe_post(THIN, thin_payload("evt_unk1", etype), THIN_SECRET).status_code == 200
    assert db_rows("SELECT type FROM events") == [{"type": etype}]


def test_connected_account_scope_event_is_fetched_in_its_context(stripe_post, fake_stripe):
    fake_stripe.rec["events.retrieve"].result = full_event()
    r = stripe_post(THIN, thin_payload(context=ACCT), THIN_SECRET)
    assert r.status_code == 200
    [call] = fake_stripe.rec["events.retrieve"].calls
    assert str(call["options"]["stripe_context"]) == ACCT


@pytest.mark.parametrize(
    "sig",
    [
        "",
        "t=1,v1=deadbeef",
        sign(thin_payload(), "whsec_wrong"),
        sign(thin_payload(), THIN_SECRET, 1),
    ],
)
def test_thin_bad_or_stale_signature_is_400(stripe_post, fake_stripe, tmp_data_dir, sig):
    r = stripe_post(THIN, thin_payload(), THIN_SECRET, sig=sig)
    assert r.status_code == 400 and err(r)["code"] == "bad_signature"
    assert fake_stripe.rec["events.retrieve"].calls == []
    assert not (tmp_data_dir / "connect.db").exists()  # rejected before any DB work


@pytest.mark.parametrize(
    "payload",
    [
        thin_payload(livemode=True),
        snapshot_payload("customer.updated", {"id": "cus_1", "object": "customer"}),
        "not json",
    ],
)
def test_thin_live_or_wrong_shape_payload_is_400(stripe_post, fake_stripe, payload):
    r = stripe_post(THIN, payload, THIN_SECRET)
    assert r.status_code == 400 and err(r)["code"] == "bad_signature"
    assert fake_stripe.rec["events.retrieve"].calls == []


def test_thin_secret_unset_is_503_naming_it(stripe_post, set_env, caplog):
    set_env(STRIPE_CONNECT_THIN_WEBHOOK_SECRET=None)
    with caplog.at_level(logging.WARNING):
        r = stripe_post(THIN, thin_payload(), THIN_SECRET)
    assert r.status_code == 503 and err(r)["code"] == "connect_not_configured"
    assert "STRIPE_CONNECT_THIN_WEBHOOK_SECRET is not set" in err(r)["message"]
    assert "STRIPE_CONNECT_THIN_WEBHOOK_SECRET is not set" in caplog.text


def test_failed_fetch_is_5xx_and_records_nothing(stripe_post, fake_stripe, db_rows):
    fake_stripe.rec["events.retrieve"].result = stripe.APIConnectionError("down")
    r = stripe_post(THIN, thin_payload(), THIN_SECRET)
    assert r.status_code == 503 and db_rows("SELECT * FROM events") == []  # Stripe retries


# ---------- 15: snapshot billing events ----------
def test_subscription_update_syncs_the_plan_from_stripe(
    account, stripe_post, fake_stripe, db_rows, client
):
    fake_stripe.rec["subscriptions.list"].result = obj(
        data=[sub_obj(status="active", quantity=2, cancel=True)]
    )
    payload = snapshot_payload("customer.subscription.updated", sub_data(account))
    r = stripe_post(BILLING, payload, BILLING_SECRET)
    assert r.status_code == 200 and r.json() == {"received": True}
    [call] = fake_stripe.rec["subscriptions.list"].calls
    assert call["params"] == {"customer_account": account, "status": "all", "limit": 10}
    [row] = db_rows()
    assert row["sub_id"] == "sub_Test000001" and row["sub_status"] == "active"
    assert row["sub_price_id"] == "price_test1" and row["sub_quantity"] == 2
    assert row["sub_cancel_at_period_end"] == 1 and row["sub_paused"] == 0
    assert row["sub_updated_at"]
    assert db_rows("SELECT type, account_id FROM events") == [
        {"type": "customer.subscription.updated", "account_id": account}  # never cus_...
    ]
    assert client.get("/api/connect/account").json()["account"]["plan"]["has_pro"] is True


@pytest.mark.parametrize(
    "etype,sub,has_pro",
    [
        ("customer.subscription.created", sub_obj(status="active"), True),
        ("customer.subscription.updated", sub_obj(status="active", paused=True), False),
        ("customer.subscription.deleted", sub_obj(status="canceled"), False),
    ],
)
def test_each_subscription_event_settles_on_stripes_state(
    account, stripe_post, fake_stripe, client, etype, sub, has_pro
):
    from app.connect import store

    store.set_plan(account, plan(status="active"))
    fake_stripe.rec["subscriptions.list"].result = obj(data=[sub])
    r = stripe_post(BILLING, snapshot_payload(etype, sub_data(account)), BILLING_SECRET)
    assert r.status_code == 200
    a = client.get("/api/connect/account").json()["account"]
    assert a["plan"]["status"] == sub.status and a["plan"]["has_pro"] is has_pro
    assert a["product_limit"] == (20 if has_pro else 3)


def test_old_api_version_payload_falls_back_to_the_subscription(
    account, stripe_post, fake_stripe, db_rows
):
    fake_stripe.rec["subscriptions.retrieve"].result = obj(
        id="sub_Test000001", customer_account=account
    )
    fake_stripe.rec["subscriptions.list"].result = obj(data=[sub_obj()])
    data = sub_data(account)
    del data["customer_account"]
    r = stripe_post(
        BILLING, snapshot_payload("customer.subscription.updated", data), BILLING_SECRET
    )
    assert r.status_code == 200
    [got] = fake_stripe.rec["subscriptions.retrieve"].calls
    assert got["subscription_exposed_id"] == "sub_Test000001"
    assert db_rows()[0]["sub_status"] == "active"


def test_unknown_account_is_recorded_without_asking_stripe(stripe_post, fake_stripe, db_rows):
    payload = snapshot_payload("customer.subscription.updated", sub_data("acct_1NotOurs00000000"))
    assert stripe_post(BILLING, payload, BILLING_SECRET).status_code == 200
    assert fake_stripe.rec["subscriptions.list"].calls == []
    assert db_rows("SELECT account_id FROM events") == [{"account_id": "acct_1NotOurs00000000"}]


@pytest.mark.parametrize(
    "etype,data",
    [
        ("payment_method.attached", {"id": "pm_1", "object": "payment_method"}),
        ("payment_method.detached", {"id": "pm_1", "object": "payment_method"}),
        ("customer.updated", {"id": "cus_1", "object": "customer"}),
        ("customer.tax_id.created", {"id": "txi_1", "object": "tax_id"}),
        ("billing_portal.configuration.updated", {"id": "bpc_1", "object": "configuration"}),
        ("billing_portal.session.created", {"id": "bps_1", "object": "session"}),
    ],
)
def test_other_billing_events_are_recorded_only(
    account, stripe_post, fake_stripe, db_rows, etype, data
):
    payload = snapshot_payload(etype, {**data, "customer_account": account})
    assert stripe_post(BILLING, payload, BILLING_SECRET).status_code == 200
    assert fake_stripe.rec["subscriptions.list"].calls == []
    assert db_rows("SELECT type, account_id FROM events") == [
        {"type": etype, "account_id": account}
    ]
    assert db_rows()[0]["sub_status"] is None


def test_billing_duplicate_is_skipped(account, stripe_post, fake_stripe):
    fake_stripe.rec["subscriptions.list"].result = obj(data=[sub_obj()])
    payload = snapshot_payload("customer.subscription.updated", sub_data(account))
    assert stripe_post(BILLING, payload, BILLING_SECRET).json() == {"received": True}
    again = stripe_post(BILLING, payload, BILLING_SECRET)
    assert again.json() == {"received": True, "duplicate": True}
    assert len(fake_stripe.rec["subscriptions.list"].calls) == 1


@pytest.mark.parametrize(
    "payload,sig_secret",
    [
        (snapshot_payload("customer.updated", {"id": "cus_1", "object": "customer"}), "whsec_x"),
        (
            snapshot_payload("customer.updated", {"id": "c", "object": "customer"}, livemode=True),
            None,
        ),
        (thin_payload(), None),
    ],
)
def test_billing_bad_signature_live_or_thin_is_400(stripe_post, fake_stripe, payload, sig_secret):
    r = stripe_post(BILLING, payload, sig_secret or BILLING_SECRET)
    assert r.status_code == 400 and err(r)["code"] == "bad_signature"


def test_billing_secret_unset_is_503_naming_it(stripe_post, set_env):
    set_env(STRIPE_BILLING_WEBHOOK_SECRET=None)
    payload = snapshot_payload("customer.updated", {"id": "cus_1", "object": "customer"})
    r = stripe_post(BILLING, payload, BILLING_SECRET)
    assert r.status_code == 503 and "STRIPE_BILLING_WEBHOOK_SECRET is not set" in err(r)["message"]


def test_failed_plan_sync_is_5xx_and_records_nothing(account, stripe_post, fake_stripe, db_rows):
    fake_stripe.rec["subscriptions.list"].result = stripe.APIConnectionError("down")
    payload = snapshot_payload("customer.subscription.updated", sub_data(account))
    assert stripe_post(BILLING, payload, BILLING_SECRET).status_code == 503
    assert db_rows("SELECT * FROM events") == [] and db_rows()[0]["sub_status"] is None


# ---------- 16-17: CSRF exemption and body cap (app/safety/web.py) ----------
@pytest.mark.parametrize(
    "path",
    [
        "/api/connect/webhooks/thin/",
        "/api/connect/webhooksX",
        "/api/connect/webhooks/thinx",
        "/api/connect/products",
        "/api/connect/accounts",
    ],
)
def test_csrf_exemption_is_exact(connect_env, path):
    from app.main import app

    with TestClient(app) as no_header:
        r = no_header.post(path, content=b"{}", headers={"content-type": "application/json"})
    assert r.status_code == 403 and err(r)["code"] == "csrf"


def test_webhooks_get_a_64k_body_cap_and_the_rest_keep_16k(fake_stripe):
    from app.main import app

    padded = '{"pad": "' + "x" * 40_000 + '"}'
    with TestClient(app) as raw:
        r = raw.post(THIN, content=padded, headers={"stripe-signature": "t=1,v1=bad"})
        assert r.status_code == 400 and err(r)["code"] == "bad_signature"  # reached the route
        r = raw.post(BILLING, content="x" * 70_000, headers={"stripe-signature": "t=1,v1=bad"})
        assert r.status_code == 413 and err(r)["code"] == "too_large"
        headers = {"X-ShopPilot": "1", "content-type": "application/json"}
        r = raw.post("/api/connect/products", content="{" + " " * 20_000 + "}", headers=headers)
        assert r.status_code == 413
