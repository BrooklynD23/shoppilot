from types import SimpleNamespace

import pytest
import stripe

from app.integrations import stripe_client as sc


@pytest.mark.parametrize(
    "key,override,expected",
    [
        (None, None, "mock"),
        ("", None, "mock"),
        ("sk_test_x", None, "test"),
        ("rk_test_x", None, "test"),
        ("sk_test_x", "mock", "mock"),
        ("sk_test_x", "auto", "test"),
    ],
)
def test_resolve_mode(key, override, expected):
    assert sc.resolve_mode(key, override) == expected


@pytest.mark.parametrize("key", ["sk_live_x", "rk_live_x", "garbage"])
def test_live_or_junk_key_refuses(key):
    with pytest.raises(RuntimeError, match="test key"):
        sc.resolve_mode(key, None)


def test_mode_defaults_to_mock_without_key():
    assert sc.mode() == "mock"


@pytest.fixture
def mock_mode(monkeypatch):
    monkeypatch.setattr(sc, "_mode", "mock")
    monkeypatch.setattr(sc, "_client", None)


def test_mock_refund_is_idempotent(mock_mode):
    a = sc.refund("pi_mock_1", 500, "duplicate", "refund:s:o:0:500")
    b = sc.refund("pi_mock_1", 500, "duplicate", "refund:s:o:0:500")
    c = sc.refund("pi_mock_1", 500, "duplicate", "refund:s:o:1:500")
    assert (
        a["id"] == b["id"]
        and a["id"].startswith("re_mock_")
        and len(a["id"]) == len("re_mock_") + 14
    )
    assert c["id"] != a["id"]
    assert a["amount"] == 500 and a["status"] == "succeeded"


def test_mock_payment_intent_and_link(mock_mode):
    pi = sc.ensure_payment_intent("abcd1234abcd1234", "o1", 4200)
    assert pi == sc.ensure_payment_intent("abcd1234abcd1234", "o1", 4200)
    assert pi.startswith("pi_mock_")
    link = sc.create_payment_link("Order o1", 4200, {"order_id": "o1"}, "plink:s:o1:4200:0")
    assert link["id"].startswith("plink_mock_")
    assert link["url"] == "about:blank#mock-" + link["id"]
    assert sc.deactivate_payment_link(link["id"]) is None


class Recorder:
    """Fake StripeClient: records calls, returns or raises per resource."""

    def __init__(self, result=None, exc=None):
        self.calls = []
        res = self

        def method(name):
            def call(*args, params=None, options=None):
                res.calls.append((name, args, params, options))
                if exc is not None:
                    raise exc
                return result

            return call

        def resource(prefix):
            return SimpleNamespace(
                create=method(f"{prefix}.create"), update=method(f"{prefix}.update")
            )

        self.v1 = SimpleNamespace(
            payment_intents=resource("payment_intents"),
            refunds=resource("refunds"),
            payment_links=resource("payment_links"),
        )


def obj(**kw):
    return SimpleNamespace(livemode=False, **kw)


@pytest.fixture
def use_client(monkeypatch):
    def _use(fake):
        monkeypatch.setattr(sc, "_mode", "test")
        monkeypatch.setattr(sc, "_client", fake)
        return fake

    return _use


def test_idempotency_key_passed_on_refund(use_client):
    fake = use_client(Recorder(obj(id="re_1", status="succeeded", amount=500)))
    out = sc.refund("pi_1", 500, "duplicate", "k")
    assert out == {"id": "re_1", "status": "succeeded", "amount": 500}
    name, _, params, options = fake.calls[0]
    assert name == "refunds.create" and options == {"idempotency_key": "k"}
    assert (
        params["payment_intent"] == "pi_1"
        and params["amount"] == 500
        and params["reason"] == "duplicate"
    )


def test_payment_intent_params(use_client):
    fake = use_client(Recorder(obj(id="pi_1")))
    assert sc.ensure_payment_intent("sh16", "o1", 4200) == "pi_1"
    name, _, params, options = fake.calls[0]
    assert name == "payment_intents.create" and options == {"idempotency_key": "pi:sh16:o1"}
    assert params["amount"] == 4200 and params["currency"] == "usd" and params["confirm"] is True
    assert params["payment_method"] == "pm_card_visa" and params["payment_method_types"] == ["card"]
    assert params["metadata"] == {"session_hash": "sh16", "order_id": "o1"}


def test_payment_link_create_and_deactivate(use_client):
    fake = use_client(Recorder(obj(id="plink_1", url="https://buy.stripe.com/test_x")))
    out = sc.create_payment_link("Order o1", 4200, {"order_id": "o1"}, "plink:k")
    assert out == {"id": "plink_1", "url": "https://buy.stripe.com/test_x"}
    _, _, params, options = fake.calls[0]
    assert options == {"idempotency_key": "plink:k"}
    item = params["line_items"][0]
    assert item["quantity"] == 1 and item["price_data"]["unit_amount"] == 4200
    assert item["price_data"]["product_data"]["name"] == "Order o1"
    sc.deactivate_payment_link("plink_1")
    name, args, params, _ = fake.calls[1]
    assert name == "payment_links.update" and args == ("plink_1",) and params == {"active": False}


def test_livemode_response_blocked(use_client):
    use_client(Recorder(SimpleNamespace(livemode=True, id="re_live", status="succeeded", amount=1)))
    with pytest.raises(sc.StripeFailure) as e:
        sc.refund("pi_1", 1, "duplicate", "k")
    assert e.value.code == "live_mode_blocked"


def _err(cls, code=None):
    hdr = {"request-id": "req_123"}
    if cls is stripe.InvalidRequestError:
        return cls("raw sk_test_secret msg", None, code=code, headers=hdr)
    return cls("raw sk_test_secret msg", headers=hdr, code=code)


@pytest.mark.parametrize(
    "exc,expected",
    [
        (_err(stripe.InvalidRequestError, "charge_already_refunded"), "already_refunded"),
        (_err(stripe.InvalidRequestError, "amount_too_large"), "amount_exceeds_refundable"),
        (_err(stripe.InvalidRequestError, "resource_missing"), "stripe_invalid_request"),
        (_err(stripe.RateLimitError), "stripe_rate_limited"),
        (_err(stripe.AuthenticationError), "stripe_auth"),
        (_err(stripe.PermissionError), "stripe_auth"),
        (_err(stripe.APIConnectionError), "stripe_unreachable"),
        (_err(stripe.APIError), "stripe_unreachable"),
        (_err(stripe.IdempotencyError), "idempotency_conflict"),
        (_err(stripe.StripeError), "stripe_error"),
    ],
)
def test_error_map(use_client, exc, expected):
    use_client(Recorder(exc=exc))
    with pytest.raises(sc.StripeFailure) as e:
        sc.refund("pi_1", 500, "duplicate", "k")
    assert e.value.code == expected
    assert e.value.code in sc.ERROR_CODES
    assert e.value.request_id == "req_123"
    assert "sk_" not in e.value.user_message and "raw" not in e.value.user_message


def test_error_map_covers_every_call(use_client):
    use_client(Recorder(exc=_err(stripe.RateLimitError)))
    calls = [
        lambda: sc.ensure_payment_intent("s", "o", 1),
        lambda: sc.create_payment_link("n", 100, {}, "k"),
        lambda: sc.deactivate_payment_link("plink_1"),
    ]
    for call in calls:
        with pytest.raises(sc.StripeFailure) as e:
            call()
        assert e.value.code == "stripe_rate_limited"
