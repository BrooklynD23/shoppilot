import sqlite3
from datetime import UTC, date, datetime

import pytest

from app.integrations import stripe_client as sc
from app.tools import refund_order as ro
from app.tools.registry import Ctx, get_tool


class FakeStripe:
    """Records calls; refund id is a function of the idempotency key, like Stripe replay."""

    def __init__(self):
        self.calls, self.fail, self.status = [], None, "succeeded"

    def ensure_pi(self, session_hash, order_id, amount_cents):
        self.calls.append(("pi", session_hash, order_id, amount_cents))
        return f"pi_test_{order_id}"

    def refund(self, pi, amount_cents, reason, idempotency_key):
        self.calls.append(("refund", pi, amount_cents, reason, idempotency_key))
        if self.fail:
            raise sc.StripeFailure(self.fail, "Can't reach Stripe right now.")
        return {
            "id": "re_test_" + str(abs(hash(idempotency_key)) % 10**8),
            "status": self.status,
            "amount": amount_cents,
        }


@pytest.fixture
def fake(monkeypatch):
    f = FakeStripe()
    monkeypatch.setattr(sc, "ensure_payment_intent", f.ensure_pi)
    monkeypatch.setattr(sc, "refund", f.refund)
    monkeypatch.setattr(sc, "mode", lambda: "test")
    return f


def make_ctx(conn):
    conn.row_factory = sqlite3.Row  # mirror get_db
    conn.execute("INSERT INTO customers VALUES ('C0001','Ann','ann@example.com','US','2026-01-01')")
    conn.execute(
        "INSERT INTO orders (id, customer_id, created_at, status, total_cents, ship_country)"
        " VALUES ('O0001', 'C0001', '2026-10-11T10:00:00', 'shipped', 4200, 'US')"
    )
    return Ctx("sid-test", conn, datetime(2026, 10, 15, 9, 0, tzinfo=UTC), date(2026, 10, 15))


@pytest.fixture
def ctx(mem_conn):
    return make_ctx(mem_conn)


def args(**kw):
    return {"order_id": "O0001", "amount_cents": None, "reason": "requested_by_customer", **kw}


def order(ctx):
    return tuple(
        ctx.db.execute(
            "SELECT status, refunded_cents, stripe_payment_intent_id FROM orders WHERE id='O0001'"
        ).fetchone()
    )


def refunds(ctx):
    return [
        tuple(r)
        for r in ctx.db.execute(
            "SELECT order_id, amount_cents, reason, stripe_refund_id, mode FROM refunds"
        )
    ]


def test_full_refund(ctx, fake):
    r = ro.run(args(), ctx)
    assert r.ok, r.summary
    assert order(ctx) == ("refunded", 4200, "pi_test_O0001")
    [(oid, amt, reason, re_id, mode)] = refunds(ctx)
    assert (oid, amt, reason, mode) == ("O0001", 4200, "requested_by_customer", "test")
    assert re_id.startswith("re_") and r.data["stripe_refund_id"] == re_id
    assert r.data["amount_cents"] == 4200 and r.data["undoable"] is False
    assert r.data["irreversible_reason"] and r.undo_token is None
    assert "$42.00" in r.summary and "Stripe TEST" in r.summary


def test_partial_refund_keeps_status(ctx, fake):
    r = ro.run(args(amount_cents=1000), ctx)
    assert r.ok and order(ctx)[:2] == ("shipped", 1000)


@pytest.mark.parametrize(
    "amount,code", [(4201, "amount_exceeds_refundable"), (0, "bad_amount"), (-5, "bad_amount")]
)
def test_bad_amount_no_calls(ctx, fake, amount, code):
    r = ro.run(args(amount_cents=amount), ctx)
    assert not r.ok and r.error == code
    assert fake.calls == [] and refunds(ctx) == [] and order(ctx) == ("shipped", 0, None)


def test_same_state_same_key_and_duplicate_row(mem_conn, fake):
    ctx1 = make_ctx(mem_conn)
    other = sqlite3.connect(":memory:")
    from app.db import init_schema

    init_schema(other)
    ctx2 = make_ctx(other)
    r1, r2 = ro.run(args(), ctx1), ro.run(args(), ctx2)
    keys = [c[4] for c in fake.calls if c[0] == "refund"]
    assert keys[0] == keys[1] and keys[0].endswith(":O0001:0:4200")
    assert "sid-test" not in keys[0]
    assert r1.data["stripe_refund_id"] == r2.data["stripe_refund_id"]
    other.close()


def test_duplicate_refund_row_is_done(ctx, fake, monkeypatch):
    monkeypatch.setattr(
        sc, "refund", lambda *a, **k: {"id": "re_dup", "status": "succeeded", "amount": 1000}
    )
    ctx.db.execute(
        "INSERT INTO orders (id, customer_id, created_at, status, total_cents,"
        " ship_country) VALUES ('O0002','C0001','2026-10-11T10:00:00','paid',900,'US')"
    )
    ctx.db.execute(
        "INSERT INTO refunds VALUES ('RF1','O0002',900,'x','re_dup','test','2026-10-15')"
    )
    r = ro.run(args(amount_cents=1000), ctx)
    assert r.ok and r.data["duplicate"] is True
    assert order(ctx)[:2] == ("shipped", 0)  # nothing new written
    assert len(refunds(ctx)) == 1


def test_payment_intent_created_once(ctx, fake):
    assert ro.run(args(amount_cents=1000), ctx).ok
    assert ro.run(args(amount_cents=1000), ctx).ok
    assert [c[0] for c in fake.calls] == ["pi", "refund", "refund"]
    assert fake.calls[0][1] != "sid-test" and fake.calls[0][3] == 4200
    keys = [c[4] for c in fake.calls if c[0] == "refund"]
    assert keys[0].endswith(":0:1000") and keys[1].endswith(":1:1000")
    assert order(ctx) == ("shipped", 2000, "pi_test_O0001")


def test_stripe_failure_leaves_db_unchanged(ctx, fake):
    fake.fail = "stripe_unreachable"
    r = ro.run(args(), ctx)
    assert not r.ok and r.error == "stripe_unreachable"
    assert refunds(ctx) == [] and order(ctx) == ("shipped", 0, None)


@pytest.mark.parametrize("status", ["failed", "canceled"])
def test_failed_refund_status_not_recorded(ctx, fake, status):
    fake.status = status
    r = ro.run(args(), ctx)
    assert not r.ok and r.error == "stripe_error"
    assert refunds(ctx) == [] and order(ctx)[:2] == ("shipped", 0)


@pytest.mark.parametrize("status", ["pending", "succeeded"])
def test_pending_or_succeeded_refund_recorded(ctx, fake, status):
    fake.status = status
    assert ro.run(args(), ctx).ok and len(refunds(ctx)) == 1


def test_session_write_cap(ctx, fake, monkeypatch):
    monkeypatch.setenv("STRIPE_MAX_WRITES_PER_SESSION", "20")
    from app.config import get_settings

    get_settings.cache_clear()
    ctx.db.execute("UPDATE orders SET total_cents=100000 WHERE id='O0001'")
    # PI create counts as 1 write; 19 refunds fill the cap of 20.
    for _ in range(19):
        assert ro.run(args(amount_cents=100), ctx).ok
    r = ro.run(args(amount_cents=100), ctx)
    assert not r.ok and r.error == "stripe_cap_reached"
    assert sum(1 for c in fake.calls if c[0] == "refund") == 19


@pytest.mark.parametrize(
    "status,code", [("refunded", "already_refunded"), ("cancelled", "not_refundable")]
)
def test_status_checks(ctx, fake, status, code):
    refunded = 4200 if status == "refunded" else 0
    ctx.db.execute(
        "UPDATE orders SET status=?, refunded_cents=? WHERE id='O0001'", (status, refunded)
    )
    r = ro.run(args(), ctx)
    assert not r.ok and r.error == code and fake.calls == []


def test_unknown_order(ctx, fake):
    r = ro.run(args(order_id="O9999"), ctx)
    assert not r.ok and r.error == "not_found" and fake.calls == []


def test_policy_cap_and_window(ctx, fake):
    ctx.db.execute("UPDATE orders SET total_cents=30000 WHERE id='O0001'")
    r = ro.run(args(), ctx)
    assert not r.ok and r.error == "over_cap" and fake.calls == []
    ctx.db.execute("UPDATE orders SET total_cents=4200, created_at='2026-09-01T10:00:00'")
    r = ro.run(args(), ctx)
    assert not r.ok and r.error == "outside_window" and fake.calls == []


def test_mock_mode_summary(ctx, monkeypatch):
    monkeypatch.setattr(sc, "_mode", "mock")
    monkeypatch.setattr(sc, "mode", lambda: "mock")
    r = ro.run(args(), ctx)
    assert r.ok and r.summary.startswith("[MOCK]")
    assert refunds(ctx)[0][3].startswith("re_mock_") and refunds(ctx)[0][4] == "mock"


def test_preview(ctx, fake):
    d = ro.preview(args(amount_cents=1500), ctx)
    assert d.step_id == "" and d.amount_cents == 1500
    assert d.before == {"order_id": "O0001", "refunded_cents": 0, "status": "shipped"}
    assert d.after["irreversible"] is True and d.after["refunded_cents"] == 1500
    assert d.after["status"] == "shipped" and d.after["stripe_mode"] == "test"
    assert ro.preview(args(), ctx).after["status"] == "refunded"
    assert fake.calls == [] and refunds(ctx) == []


def test_registry_entry():
    t = get_tool("refund_order")
    assert t.undo is None
    s = t.spec
    assert (s.destructive, s.moves_money, s.undoable) == (True, True, False)
