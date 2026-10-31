import json
import sqlite3
from datetime import UTC, date, datetime

import pytest

from app.integrations import stripe_client as sc
from app.tools import create_payment_link as cpl
from app.tools.registry import Ctx


class FakeStripe:
    def __init__(self, fail_deactivate=False):
        self.calls, self.fail_deactivate = [], fail_deactivate

    def create(self, name, amount_cents, metadata, idempotency_key):
        self.calls.append(("create", idempotency_key, amount_cents, metadata))
        n = len(self.calls)
        return {"id": f"plink_test{n}", "url": f"https://buy.stripe.com/test_{n}"}

    def deactivate(self, link_id):
        self.calls.append(("deactivate", link_id))
        if self.fail_deactivate:
            raise sc.StripeFailure("stripe_unreachable", "Can't reach Stripe right now.")


@pytest.fixture
def fake(monkeypatch):
    f = FakeStripe()
    monkeypatch.setattr(sc, "create_payment_link", f.create)
    monkeypatch.setattr(sc, "deactivate_payment_link", f.deactivate)
    monkeypatch.setattr(sc, "mode", lambda: "test")
    return f


@pytest.fixture
def ctx(mem_conn):
    mem_conn.row_factory = sqlite3.Row  # mirror get_db
    mem_conn.execute(
        "INSERT INTO customers VALUES ('C0001','Ann','ann@example.com','US','2026-01-01')"
    )
    mem_conn.execute(
        "INSERT INTO orders (id, customer_id, created_at, status, total_cents, ship_country)"
        " VALUES ('O0001', 'C0001', '2026-10-14T10:00:00', 'paid', 4200, 'US')"
    )
    return Ctx("sid-test", mem_conn, datetime(2026, 10, 15, 9, 0, tzinfo=UTC), date(2026, 10, 15))


def args(**kw):
    return {
        "order_id": "O0001",
        "customer_id": None,
        "amount_cents": 4200,
        "description": "Replacement mug",
        **kw,
    }


def links(ctx):
    return [
        tuple(r)
        for r in ctx.db.execute(
            "SELECT order_id, customer_id, amount_cents, stripe_link_id, url, active, mode"
            " FROM payment_links ORDER BY created_at, id"
        )
    ]


def test_order_target_creates_row(ctx, fake):
    r = cpl.run(args(), ctx)
    assert r.ok, r.summary
    assert links(ctx) == [
        ("O0001", None, 4200, "plink_test1", "https://buy.stripe.com/test_1", 1, "test")
    ]
    assert r.data["link_id"].startswith("plink_") and r.data["url"]
    assert json.loads(r.undo_token) == {
        "link_id": "plink_test1",
        "post": {
            "active": 1,
            "amount_cents": 4200,
            "url": "https://buy.stripe.com/test_1",
            "order_id": "O0001",
            "customer_id": None,
        },
    }
    assert "Stripe TEST" in r.summary and not r.summary.startswith("[MOCK]")


def test_customer_target_and_idempotency_key(ctx, fake):
    assert cpl.run(args(order_id=None, customer_id="C0001", amount_cents=500), ctx).ok
    assert cpl.run(args(order_id=None, customer_id="C0001", amount_cents=500), ctx).ok
    keys = [c[1] for c in fake.calls]
    nonce = ctx.db.execute("SELECT value FROM meta WHERE key='store_nonce'").fetchone()[0]
    assert len(nonce) == 8
    assert keys[0].startswith("plink:") and keys[0].endswith(f":{nonce}:C0001:500:0")
    assert keys[1].endswith(f":{nonce}:C0001:500:1")
    assert "sid-test" not in keys[0] and "sid-test" not in json.dumps(fake.calls[0][3])


@pytest.mark.parametrize("o,c", [(None, None), ("O0001", "C0001")])
def test_bad_target(ctx, fake, o, c):
    r = cpl.run(args(order_id=o, customer_id=c), ctx)
    assert not r.ok and r.error == "bad_target"
    assert fake.calls == [] and links(ctx) == []


def test_unknown_target(ctx, fake):
    r = cpl.run(args(order_id="O9999"), ctx)
    assert not r.ok and r.error == "not_found" and fake.calls == []


@pytest.mark.parametrize("amount", [49, 100_001])
def test_bad_amount(ctx, fake, amount):
    r = cpl.run(args(amount_cents=amount), ctx)
    assert not r.ok and r.error == "bad_amount" and fake.calls == []


@pytest.mark.parametrize("desc", ["", "   ", "x" * 201])
def test_bad_description(ctx, fake, desc):
    r = cpl.run(args(description=desc), ctx)
    assert not r.ok and r.error == "bad_description" and fake.calls == []


def test_session_cap(ctx, fake, monkeypatch):
    monkeypatch.setenv("STRIPE_MAX_WRITES_PER_SESSION", "2")
    from app.config import get_settings

    get_settings.cache_clear()
    assert cpl.run(args(), ctx).ok and cpl.run(args(), ctx).ok
    r = cpl.run(args(), ctx)
    assert not r.ok and r.error == "stripe_cap_reached" and len(fake.calls) == 2


def test_create_failure_leaves_db_unchanged(ctx, monkeypatch):
    def boom(*_a, **_k):
        raise sc.StripeFailure("stripe_unreachable", "Can't reach Stripe right now.")

    monkeypatch.setattr(sc, "create_payment_link", boom)
    r = cpl.run(args(), ctx)
    assert not r.ok and r.error == "stripe_unreachable" and links(ctx) == []


def test_undo_deactivates(ctx, fake):
    token = cpl.run(args(), ctx).undo_token
    r = cpl.undo(token, ctx)
    assert r.ok
    assert fake.calls[-1] == ("deactivate", "plink_test1")
    assert links(ctx)[0][5] == 0


def test_undo_failure_keeps_row_active(ctx, fake):
    token = cpl.run(args(), ctx).undo_token
    fake.fail_deactivate = True
    r = cpl.undo(token, ctx)
    assert not r.ok and r.error == "stripe_unreachable"
    assert links(ctx)[0][5] == 1


def test_undo_twice_is_changed_since(ctx, fake):
    token = cpl.run(args(), ctx).undo_token
    assert cpl.undo(token, ctx).ok
    r = cpl.undo(token, ctx)
    assert not r.ok and r.error == "changed_since"


def test_store_reset_gets_new_key(ctx, fake):
    assert cpl.run(args(), ctx).ok
    # Simulate a reset: rows gone, rebuilt DB has no nonce yet (n_prior back to 0).
    ctx.db.execute("DELETE FROM payment_links")
    ctx.db.execute("DELETE FROM meta WHERE key='store_nonce'")
    assert cpl.run(args(), ctx).ok
    k1, k2 = fake.calls[0][1], fake.calls[1][1]
    assert k1.endswith(":O0001:4200:0") and k2.endswith(":O0001:4200:0") and k1 != k2


def test_undo_changed_amount_is_changed_since(ctx, fake):
    token = cpl.run(args(), ctx).undo_token
    ctx.db.execute("UPDATE payment_links SET amount_cents=999")
    r = cpl.undo(token, ctx)
    assert not r.ok and r.error == "changed_since"
    assert fake.calls[-1][0] == "create" and links(ctx)[0][5] == 1


@pytest.mark.parametrize("made,now", [("test", "mock"), ("mock", "test")])
def test_undo_mode_mismatch_is_changed_since(ctx, fake, monkeypatch, made, now):
    monkeypatch.setattr(sc, "mode", lambda: made)
    token = cpl.run(args(), ctx).undo_token
    monkeypatch.setattr(sc, "mode", lambda: now)
    r = cpl.undo(token, ctx)
    assert not r.ok and r.error == "changed_since" and "mode" in r.summary
    assert fake.calls[-1][0] == "create" and links(ctx)[0][5:] == (1, made)


def test_mock_mode_summary(ctx, monkeypatch):
    monkeypatch.setattr(sc, "mode", lambda: "mock")
    monkeypatch.setattr(sc, "_mode", "mock")
    r = cpl.run(args(), ctx)
    assert r.ok and r.summary.startswith("[MOCK]")
    assert links(ctx)[0][6] == "mock" and links(ctx)[0][3].startswith("plink_mock_")


def test_preview_no_writes_no_calls(ctx, fake):
    d = cpl.preview(args(), ctx)
    assert d.step_id == "" and d.before == {} and d.amount_cents == 4200
    assert d.after["description"] == "Replacement mug" and d.after["stripe_mode"] == "test"
    assert fake.calls == [] and links(ctx) == []


def test_spec_flags():
    s = cpl.SPEC
    assert (s.name, s.destructive, s.moves_money, s.undoable) == (
        "create_payment_link",
        True,
        True,
        True,
    )
