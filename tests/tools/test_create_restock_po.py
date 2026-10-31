import json
from datetime import date, timedelta

import pytest

from app.ml.forecast import forecast_demand
from app.safety.policy import RESTOCK_QTY_MAX
from app.seed.generate import HERO_PRODUCT_ID
from app.tools import create_restock_po as po
from app.tools.registry import _check_strict

NEW_PRODUCT_ID = "P18"  # seed kind "new": too little history to forecast
FC = {"product_id": HERO_PRODUCT_ID, "qty_source": "forecast", "qty": None}


def _count(ctx) -> int:
    return ctx.db.execute("SELECT COUNT(*) FROM purchase_orders").fetchone()[0]


def _status(ctx, po_id) -> str:
    return ctx.db.execute("SELECT status FROM purchase_orders WHERE id=?", (po_id,)).fetchone()[0]


def test_spec_flags_and_schema():
    s = po.SPEC
    assert (s.name, s.destructive, s.moves_money, s.undoable) == (
        "create_restock_po",
        True,
        False,
        True,
    )
    assert set(s.input_schema["required"]) == {"product_id", "qty_source", "qty"}
    _check_strict(s.input_schema)


def test_forecast_qty_matches_forecast(ctx):
    want = forecast_demand(HERO_PRODUCT_ID, ctx)["reorder_qty"]
    r = po.run(FC, ctx)
    assert r.ok, r.error
    assert r.data["qty"] == want > 0
    row = ctx.db.execute(
        "SELECT product_id, qty, status, unit_cost_cents FROM purchase_orders WHERE id=?",
        (r.data["po_id"],),
    ).fetchone()
    assert row[:3] == (HERO_PRODUCT_ID, want, "open") and row[3] > 0
    assert json.loads(r.undo_token) == {"po_id": r.data["po_id"], "status": "open"}


def test_forecast_source_rejects_qty(ctx):
    r = po.run({**FC, "qty": 5}, ctx)
    assert r.ok is False and _count(ctx) == 0


@pytest.mark.parametrize("qty", [None, 0, RESTOCK_QTY_MAX + 1, -3, True, "5"])
def test_user_source_bad_qty(ctx, qty):
    r = po.run({"product_id": HERO_PRODUCT_ID, "qty_source": "user", "qty": qty}, ctx)
    assert r.ok is False and _count(ctx) == 0


def test_user_source_ok(ctx):
    r = po.run({"product_id": HERO_PRODUCT_ID, "qty_source": "user", "qty": 40}, ctx)
    assert r.ok and r.data["qty"] == 40


def test_unknown_product_and_bad_source(ctx):
    assert po.run({**FC, "product_id": "nope"}, ctx).ok is False
    assert po.run({**FC, "qty_source": "guess"}, ctx).ok is False


def test_preview_shape(ctx):
    d = po.preview(FC, ctx)
    f = d.before["forecast"]
    assert len(f["band"]["mean"]) == 14
    assert d.before["on_hand"] == f["on_hand"] and "days_to_stockout" in d.before
    qty, cost = d.after["qty"], d.after["unit_cost_cents"]
    assert qty == f["reorder_qty"] and d.amount_cents == qty * cost
    lead = ctx.db.execute(
        "SELECT lead_time_days FROM products WHERE id=?", (HERO_PRODUCT_ID,)
    ).fetchone()[0]
    assert d.after["arrives_on"] == (ctx.today + timedelta(days=lead)).isoformat()
    assert d.after["po"] == "new" and d.after["status"] == "open" and d.step_id == ""


def test_preview_writes_nothing(ctx):
    n = _count(ctx)
    po.preview(FC, ctx)
    po.preview({**FC, "qty": 5}, ctx)  # invalid args still give a DiffItem, no raise
    assert _count(ctx) == n


def test_preview_and_run_agree(ctx):
    d = po.preview(FC, ctx)
    r = po.run(FC, ctx)
    assert r.data["qty"] == d.after["qty"] and r.data["amount_cents"] == d.amount_cents


def test_no_double_order(ctx):
    assert po.run(FC, ctx).ok
    r = po.run(FC, ctx)
    assert r.ok is False and "already covered by open PO" in r.error
    assert _count(ctx) == 1


def test_insufficient_history_needs_user_qty(ctx):
    f = forecast_demand(NEW_PRODUCT_ID, ctx)
    assert f["reorder_qty"] is None
    r = po.run({"product_id": NEW_PRODUCT_ID, "qty_source": "forecast", "qty": None}, ctx)
    assert r.ok is False and "quantity" in r.error


def test_undo_cancels(ctx):
    r = po.run(FC, ctx)
    u = po.undo(r.undo_token, ctx)
    assert u.ok and _status(ctx, r.data["po_id"]) == "cancelled"
    again = po.undo(r.undo_token, ctx)
    assert again.ok is False and again.error == "changed_since"


def test_undo_received_refused(ctx):
    r = po.run(FC, ctx)
    ctx.db.execute("UPDATE purchase_orders SET status='received' WHERE id=?", (r.data["po_id"],))
    u = po.undo(r.undo_token, ctx)
    assert u.ok is False and u.error == "changed_since"
    assert _status(ctx, r.data["po_id"]) == "received"


def test_undo_bad_token(ctx):
    assert po.undo("not json", ctx).ok is False
    assert po.undo(json.dumps({"po_id": "po_missing", "status": "open"}), ctx).ok is False


def test_tool_does_not_log_or_commit(ctx, monkeypatch):
    import app.agent.audit as audit

    def boom(*_a, **_k):
        raise AssertionError("tool must not log")

    monkeypatch.setattr(audit, "log_action", boom)
    assert po.run(FC, ctx).ok
    assert ctx.db.in_transaction


def test_expected_at_is_lead_time(ctx):
    r = po.run(FC, ctx)
    exp = ctx.db.execute(
        "SELECT expected_at FROM purchase_orders WHERE id=?", (r.data["po_id"],)
    ).fetchone()[0]
    assert date.fromisoformat(exp[:10]) > ctx.today


def test_forecast_over_cap_rejected_not_clamped(ctx, monkeypatch):
    real = po.forecast.forecast_demand

    def big(pid, c, *a, **k):
        return {**real(pid, c, *a, **k), "reorder_qty": 600}

    monkeypatch.setattr(po.forecast, "forecast_demand", big)
    r = po.run(FC, ctx)
    assert r.ok is False and "600" in r.error and "quantity" in r.error and _count(ctx) == 0
    assert "600" in po.preview(FC, ctx).after["error"]
