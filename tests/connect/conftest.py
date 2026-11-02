"""Connect fixtures (spec 10 §14.1): env, a real offline StripeClient with recorded calls, signing.

Stripe is never reached: the root `no_network` fixture blocks sockets, and every network method
of the real client is swapped for a `Rec` that checks the call against the SDK's own signature.
"""

import hashlib
import hmac
import inspect
import itertools
import json
import operator
import time
from types import SimpleNamespace

import pytest

ACCT = "acct_1Test0000000001"
PROD = "prod_Test0000000001"
CONNECT_VARS = (
    "CONNECT_ENABLED",
    "PUBLIC_BASE_URL",
    "STRIPE_CONNECT_THIN_WEBHOOK_SECRET",
    "STRIPE_BILLING_WEBHOOK_SECRET",
    "STRIPE_PLATFORM_PRICE_ID",
    "CONNECT_APPLICATION_FEE_CENTS",
)
ENV = {
    "CONNECT_ENABLED": "1",
    "STRIPE_SECRET_KEY": "sk_test_dummy",
    "PUBLIC_BASE_URL": "http://testserver",
    "STRIPE_CONNECT_THIN_WEBHOOK_SECRET": "whsec_thin_test",
    "STRIPE_BILLING_WEBHOOK_SECRET": "whsec_billing_test",
    "STRIPE_PLATFORM_PRICE_ID": "price_test1",
}
OWNER = {"display_name": "Fern & Kiln", "contact_email": "owner@example.com"}
# Every SDK method the sample may call: name -> (service path on StripeClient, method).
METHODS = {
    "accounts.create": ("v2.core.accounts", "create"),
    "accounts.retrieve": ("v2.core.accounts", "retrieve"),
    "account_links.create": ("v2.core.account_links", "create"),
    "events.retrieve": ("v2.core.events", "retrieve"),
    "products.create": ("v1.products", "create"),
    "products.list": ("v1.products", "list"),
    "products.retrieve": ("v1.products", "retrieve"),
    "checkout.create": ("v1.checkout.sessions", "create"),
    "portal.create": ("v1.billing_portal.sessions", "create"),
    "subscriptions.list": ("v1.subscriptions", "list"),
    "subscriptions.retrieve": ("v1.subscriptions", "retrieve"),
}


def obj(**kw):
    """Stripe-like object. Not MagicMock: its truthy `livemode` would trip the live-mode guard."""
    return SimpleNamespace(livemode=False, **kw)


def account_obj(card="active", req="eventually_due"):
    caps = obj(card_payments=obj(status=card))
    return obj(
        id=ACCT,
        display_name="Fern & Kiln",
        contact_email="owner@example.com",
        configuration=obj(merchant=obj(capabilities=caps)),
        requirements=obj(summary=obj(minimum_deadline=obj(status=req))),
    )


def price_obj(amount=1500, kind="one_time", currency="usd"):
    return obj(id="price_Shop000001", type=kind, unit_amount=amount, currency=currency)


def product_obj(pid=PROD, active=True, price=None):
    price = price_obj() if price is None else price
    return obj(id=pid, name="Mug", description="Stoneware", active=active, default_price=price)


def sub_obj(status="active", price="price_test1", quantity=1, cancel=False, paused=False):
    item = obj(price=obj(id=price), quantity=quantity)
    return obj(
        id="sub_Test000001",
        status=status,
        customer_account=ACCT,
        cancel_at_period_end=cancel,
        pause_collection=obj(behavior="void") if paused else None,
        items=obj(data=[item]),
    )


def plan(status="active", paused=False, cancel=False) -> dict:
    """A stored platform plan, as `stripe_calls.plan_summary` returns it."""
    return {
        "sub_id": "sub_Test000001",
        "sub_status": status,
        "sub_price_id": "price_test1",
        "sub_quantity": 1,
        "sub_cancel_at_period_end": cancel,
        "sub_paused": paused,
    }


_ACCOUNT_IDS = itertools.count(1)


def _new_account_id(_call):
    return obj(id=f"acct_1Test{next(_ACCOUNT_IDS):010d}")


DEFAULTS = {
    "accounts.create": _new_account_id,  # a fresh id per create, like Stripe
    "accounts.retrieve": account_obj(),
    "account_links.create": obj(url="https://connect.stripe.com/setup/e/acct_x/abc"),
    "products.create": obj(id=PROD),
    "products.list": obj(data=[product_obj()]),
    "products.retrieve": product_obj(),
    "checkout.create": obj(url="https://checkout.stripe.com/c/pay/cs_test_x"),
    "portal.create": obj(url="https://billing.stripe.com/p/session/test_x"),
    "subscriptions.list": obj(data=[]),
}


class Rec:
    """Records each call (bound to the real SDK signature, so a wrong call shape fails the test)."""

    def __init__(self, original, result):
        self.signature = inspect.signature(original)
        self.result = result
        self.calls: list[dict] = []

    def __call__(self, *args, **kwargs):
        call = dict(self.signature.bind(*args, **kwargs).arguments)
        self.calls.append(call)
        result = self.result(call) if callable(self.result) else self.result
        if isinstance(result, BaseException):
            raise result
        return result


def sign(payload: str, secret: str, t: int | None = None) -> str:
    """A Stripe-Signature header: HMAC-SHA256 of "<t>.<payload>" (what Stripe sends)."""
    t = int(time.time()) if t is None else t
    mac = hmac.new(secret.encode(), f"{t}.{payload}".encode(), hashlib.sha256).hexdigest()
    return f"t={t},v1={mac}"


def thin_payload(event_id="evt_test_thin1", etype="v2.core.account[requirements].updated", **kw):
    return json.dumps(
        {
            "id": event_id,
            "object": "v2.core.event",
            "type": etype,
            "created": "2026-11-02T00:00:00.000Z",
            "livemode": False,
            "related_object": {
                "id": ACCT,
                "type": "v2.core.account",
                "url": f"/v2/core/accounts/{ACCT}",
            },
            **kw,
        }
    )


def snapshot_payload(etype, data_object, event_id="evt_test_snap1", livemode=False):
    return json.dumps(
        {
            "id": event_id,
            "object": "event",
            "type": etype,
            "api_version": "2026-10-28.endive",
            "created": 1_762_000_000,
            "livemode": livemode,
            "data": {"object": data_object},
        }
    )


def clear_caches():
    from app.config import get_settings
    from app.connect import stripe_calls
    from app.connect.config import connect_settings

    get_settings.cache_clear()
    connect_settings.cache_clear()
    stripe_calls.client.cache_clear()


@pytest.fixture(autouse=True)
def hermetic_connect_env(request, monkeypatch):
    """A developer's exported .env never leaks into the mocked tests (live tests keep it)."""
    if request.node.get_closest_marker("live"):
        return
    for name in CONNECT_VARS:
        monkeypatch.delenv(name, raising=False)
    clear_caches()


@pytest.fixture
def connect_env(monkeypatch):
    for k, v in ENV.items():
        monkeypatch.setenv(k, v)
    clear_caches()
    return ENV


@pytest.fixture
def set_env(monkeypatch):
    """Change Connect env mid-test. Keeps the cached (faked) Stripe client."""

    def _set(**kw):
        from app.config import get_settings
        from app.connect.config import connect_settings

        for k, v in kw.items():
            if v is None:
                monkeypatch.delenv(k, raising=False)
            else:
                monkeypatch.setenv(k, v)
        get_settings.cache_clear()
        connect_settings.cache_clear()

    return _set


@pytest.fixture
def fake_stripe(connect_env, monkeypatch):
    """The app's real cached StripeClient (offline signature checks work) with recorded calls."""
    from app.connect import stripe_calls

    c = stripe_calls.client()
    recs = {}
    for name, (path, method) in METHODS.items():
        service = operator.attrgetter(path)(c)
        recs[name] = Rec(getattr(service, method), DEFAULTS.get(name))
        monkeypatch.setattr(service, method, recs[name])
    return SimpleNamespace(client=c, rec=recs)


@pytest.fixture
def account(client, fake_stripe):
    """A connected account created through the API; the client now holds its sp_connect cookie."""
    r = client.post("/api/connect/accounts", json=OWNER)
    assert r.status_code == 200, r.text
    return r.json()["account_id"]


@pytest.fixture
def db_rows(tmp_data_dir):
    import sqlite3
    from contextlib import closing

    def _rows(sql="SELECT * FROM accounts"):
        with closing(sqlite3.connect(tmp_data_dir / "connect.db")) as conn:
            conn.row_factory = sqlite3.Row
            return [dict(r) for r in conn.execute(sql)]

    return _rows
