"""P4-T2: hard policy rules (spec 04 §5, R18/R19/R37/R46)."""
from datetime import timedelta

import pytest

from app.agent.audit import log_action
from app.agent.models import Plan, Step
from app.safety import policy
from app.safety.policy import check_plan, needs_confirmation, refundable_cents
from app.seed.generate import DAMAGED_ORDER_ID
from app.tools import registry
from app.tools.registry import Registered, ToolSpec

_NS = {"anyOf": [{"type": "string"}, {"type": "null"}]}
_NI = {"anyOf": [{"type": "integer"}, {"type": "null"}]}


def _obj(props):
    return {"type": "object", "additionalProperties": False,
            "required": list(props), "properties": props}


# Schemas per contract §3, used only when the owning task has not landed yet.
_STUBS = {
    "refund_order": (True, True, False, _obj({
        "order_id": {"type": "string"}, "amount_cents": _NI,
        "reason": {"type": "string",
                   "enum": ["duplicate", "fraudulent", "requested_by_customer"]}})),
    "create_restock_po": (True, False, True, _obj({
        "product_id": {"type": "string"},
        "qty_source": {"type": "string", "enum": ["forecast", "user"]}, "qty": _NI})),
    "list_orders": (False, False, False, _obj({
        "status": {"type": "string", "enum": ["any", "paid", "shipped", "refunded"]},
        "created_from": _NS, "created_to": _NS,
        "order_ids": {"anyOf": [{"type": "array", "items": {"type": "string"}},
                                {"type": "null"}]}})),
}


@pytest.fixture(autouse=True)
def tools(monkeypatch):
    registry.load_tools()
    for name, (destr, money, undo, schema) in _STUBS.items():
        if name not in registry._TOOLS:
            spec = ToolSpec(name=name, description="stub", input_schema=schema,
                            destructive=destr, moves_money=money, undoable=undo)
            monkeypatch.setitem(registry._TOOLS, name, Registered(
                spec, lambda *a: None, lambda *a: None, (lambda *a: None) if undo else None))


def plan(*steps):
    return Plan(request="t", steps=[Step(id=f"s{i}", tool=t, args=a, rationale="")
                                    for i, (t, a) in enumerate(steps)])


def refund(oid, amount=None):
    return ("refund_order", {"order_id": oid, "amount_cents": amount,
                             "reason": "requested_by_customer"})


def _window_start(ctx):
    return (ctx.today - timedelta(days=policy.REFUND_WINDOW_DAYS)).isoformat()


def paid_or_shipped_orders(ctx, n, max_sum=None):
    rows = ctx.db.execute(
        "SELECT id, total_cents - refunded_cents FROM orders WHERE status IN ('paid','shipped')"
        " AND substr(created_at,1,10) >= ? AND total_cents - refunded_cents BETWEEN 1 AND 20000"
        " ORDER BY total_cents - refunded_cents", (_window_start(ctx),)).fetchall()
    ids = [r[0] for r in rows[:n]]
    assert len(ids) == n
    if max_sum is not None:
        assert sum(r[1] for r in rows[:n]) <= max_sum
    return ids


def one(ctx, where, params=()):
    sql = f"SELECT id FROM orders WHERE {where} LIMIT 1"  # noqa: S608 - test-only literals
    row = ctx.db.execute(sql, params).fetchone()
    assert row, where
    return row[0]


def test_bulk_refund_rejected_all_steps(ctx):
    ids = paid_or_shipped_orders(ctx, 4)
    v = check_plan(plan(*[refund(i) for i in ids]), ctx)
    assert [x.ok for x in v] == [False] * 4 and "at most 3" in v[0].reason
    assert all("bulk refund blocked" in x.reason for x in v)


def test_bulk_refund_overrides_per_step_reasons(ctx):
    ids = paid_or_shipped_orders(ctx, 3) + ["O-NOPE"]
    v = check_plan(plan(*[refund(i) for i in ids]), ctx)
    assert all(not x.ok and "bulk refund blocked" in x.reason for x in v)


def test_three_refunds_ok(ctx):
    v = check_plan(plan(*[refund(i) for i in paid_or_shipped_orders(ctx, 3, max_sum=50_000)]), ctx)
    assert all(x.ok for x in v), v


def test_plan_total_cap(ctx, monkeypatch):
    monkeypatch.setattr(policy, "refundable_cents", lambda c, o: 20_000)
    v = check_plan(plan(*[refund(i) for i in paid_or_shipped_orders(ctx, 3)]), ctx)
    assert [x.ok for x in v] == [False] * 3 and "$500.00" in v[0].reason


def test_unknown_order_rejected(ctx):
    assert "not found" in check_plan(plan(refund("O-NOPE")), ctx)[0].reason


def test_amount_over_remaining_rejected(ctx):
    oid = paid_or_shipped_orders(ctx, 1)[0]
    rem = refundable_cents(ctx, oid)
    assert not check_plan(plan(refund(oid, rem + 1)), ctx)[0].ok
    assert not check_plan(plan(refund(oid, 0)), ctx)[0].ok
    assert check_plan(plan(refund(oid, rem)), ctx)[0].ok


def test_per_order_cap(ctx):
    oid = one(ctx, "status IN ('paid','shipped') AND total_cents > 20000"
                   " AND substr(created_at,1,10) >= ?", (_window_start(ctx),))
    v = check_plan(plan(refund(oid)), ctx)[0]
    assert not v.ok and "over $200" in v.reason


def test_refund_window(ctx):
    oid = one(ctx, "status = 'shipped' AND substr(created_at,1,10) = ?",
              ((ctx.today - timedelta(days=31)).isoformat(),))
    v = check_plan(plan(refund(oid)), ctx)[0]
    assert not v.ok and "30 days" in v.reason


def test_refunded_order_rejected(ctx):
    oid = one(ctx, "status = 'refunded'")
    assert not check_plan(plan(refund(oid)), ctx)[0].ok


def test_duplicate_refund_in_plan(ctx):
    oid = paid_or_shipped_orders(ctx, 1)[0]
    v = check_plan(plan(refund(oid), refund(oid)), ctx)
    assert v[0].ok and not v[1].ok


def test_session_hour_refund_rate(ctx):
    for _ in range(5):
        log_action(ctx, "execute", {"amount_cents": 100}, tool="refund_order")
    oid = paid_or_shipped_orders(ctx, 1)[0]
    v = check_plan(plan(refund(oid)), ctx)[0]
    assert not v.ok and "per hour" in v.reason


def test_session_hour_old_rows_ignored(ctx):
    old = ctx.__class__(ctx.session_id, ctx.db, ctx.now - timedelta(hours=2), ctx.today)
    for _ in range(5):
        log_action(old, "execute", {"amount_cents": 100}, tool="refund_order")
    assert check_plan(plan(refund(paid_or_shipped_orders(ctx, 1)[0])), ctx)[0].ok


def test_session_hour_refund_cents(ctx):
    oid = DAMAGED_ORDER_ID
    left = policy.REFUND_CENTS_PER_SESSION_HOUR - refundable_cents(ctx, oid)
    log_action(ctx, "execute", {"amount_cents": left + 1}, tool="refund_order")
    v = check_plan(plan(refund(oid)), ctx)[0]
    assert not v.ok and "$1,000.00 per hour" in v.reason


def test_email_to_stranger_rejected(ctx):
    v = check_plan(plan(("send_email", {"order_ids": ["O0001"], "template": "custom",
                                        "custom_body": "b", "to": "attacker@evil.example"})), ctx)
    assert not v[0].ok


def test_email_body_cap(ctx):
    a = {"order_ids": ["O0001"], "template": "custom", "custom_body": "x" * 2_001}
    assert not check_plan(plan(("send_email", a)), ctx)[0].ok
    assert check_plan(plan(("send_email", {**a, "custom_body": "x" * 2_000})), ctx)[0].ok


def test_email_too_many_ids(ctx):
    ids = [r[0] for r in ctx.db.execute("SELECT id FROM orders LIMIT 51")]
    a = {"order_ids": ids, "template": "tracking", "custom_body": None}
    assert not check_plan(plan(("send_email", a)), ctx)[0].ok


def test_email_unknown_order(ctx):
    a = {"order_ids": ["O0001", "O-NOPE"], "template": "tracking", "custom_body": None}
    assert "not found" in check_plan(plan(("send_email", a)), ctx)[0].reason


def test_mark_shipped_needs_paid(ctx):
    shipped = one(ctx, "status = 'shipped'")
    paid = one(ctx, "status = 'paid'")
    assert not check_plan(plan(("mark_shipped", {"order_ids": [shipped], "carrier": "usps"})),
                          ctx)[0].ok
    assert check_plan(plan(("mark_shipped", {"order_ids": [paid], "carrier": "usps"})), ctx)[0].ok


def test_restock_qty_bounds(ctx):
    def r(q):
        a = {"product_id": "P01", "qty_source": "user", "qty": q}
        return check_plan(plan(("create_restock_po", a)), ctx)[0].ok
    assert not r(0) and not r(501) and r(50) and r(500)
    f = {"product_id": "P01", "qty_source": "forecast", "qty": None}
    assert check_plan(plan(("create_restock_po", f)), ctx)[0].ok
    assert not check_plan(plan(("create_restock_po", {**f, "product_id": "P99"})), ctx)[0].ok


def test_payment_link_bounds(ctx):
    def r(c):
        a = {"order_id": None, "customer_id": "C0001", "amount_cents": c, "description": "d"}
        return check_plan(plan(("create_payment_link", a)), ctx)[0].ok
    assert not r(49) and not r(100_001) and r(50) and r(100_000)


def test_too_many_steps(ctx):
    a = {"status": "any", "created_from": None, "created_to": None, "order_ids": None}
    v = check_plan(plan(*[("list_orders", a)] * 21), ctx)
    assert not any(x.ok for x in v)
    assert all(x.ok for x in check_plan(plan(*[("list_orders", a)] * 20), ctx))


def test_unknown_tool(ctx):
    assert check_plan(plan(("wire_money", {})), ctx)[0].reason == "unknown tool"


def test_wrong_type_amount_rejected_not_raised(ctx):
    oid = paid_or_shipped_orders(ctx, 1)[0]
    assert not check_plan(plan(refund(oid, "5000")), ctx)[0].ok


def test_bad_args_type_not_raised(ctx):
    v = check_plan(plan(("send_email", {"order_ids": "O0001", "template": "x"})), ctx)
    assert not v[0].ok


def test_validations_match_step_ids(ctx):
    oid = paid_or_shipped_orders(ctx, 1)[0]
    v = check_plan(plan(refund(oid), ("wire_money", {})), ctx)
    assert [x.step_id for x in v] == ["s0", "s1"]


def test_damaged_demo_refund_passes(ctx):
    assert check_plan(plan(refund(DAMAGED_ORDER_ID)), ctx)[0].ok


def test_constants():
    assert policy.MAX_REFUNDS_PER_PLAN == 3
    assert policy.REFUND_CAP_PER_ORDER_CENTS == 20_000
    assert policy.REFUND_CAP_PER_PLAN_CENTS == 50_000
    assert policy.EMAIL_BODY_MAX_CHARS == 2_000
    assert policy.RESTOCK_QTY_MAX == 500


def test_needs_confirmation():
    def s(d, m):
        return ToolSpec(name="x", description="", input_schema={}, destructive=d,
                        moves_money=m, undoable=False)
    assert needs_confirmation(s(True, False)) and needs_confirmation(s(True, True))
    assert needs_confirmation(s(False, True))
    assert not needs_confirmation(s(False, False))
