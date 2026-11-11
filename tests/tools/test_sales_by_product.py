from collections import defaultdict

import pytest

from app.tools import sales_by_product as sbp
from app.tools.registry import _check_strict, get_tool, validate_args

WEEK = {"created_from": "2026-10-08", "created_to": "2026-10-14", "sort_by": "units", "limit": None}


def _expected(ctx, lo, hi):
    """Naive per-row aggregation to check the GROUP BY against."""
    rows = ctx.db.execute(
        "SELECT i.product_id, i.qty, i.unit_price_cents, o.id, o.status, o.created_at"
        " FROM order_items i JOIN orders o ON o.id = i.order_id"
    ).fetchall()
    agg = defaultdict(lambda: {"units": 0, "revenue_cents": 0, "orders": set()})
    for pid, qty, price, oid, status, created in rows:
        if status in ("paid", "shipped") and lo <= created[:10] <= hi:
            a = agg[pid]
            a["units"] += qty
            a["revenue_cents"] += qty * price
            a["orders"].add(oid)
    return agg


def test_registered_read_only_and_strict():
    spec = get_tool("sales_by_product").spec
    assert not spec.destructive and not spec.moves_money and not spec.undoable
    _check_strict(spec.input_schema)
    assert validate_args("sales_by_product", WEEK) is None


def test_week_matches_naive_aggregation(ctx):
    r = sbp.run(WEEK, ctx)
    assert r.ok and r.summary.endswith("products")
    want = _expected(ctx, "2026-10-08", "2026-10-14")
    got = r.data["products"]
    assert len(got) == min(sbp.DEFAULT_LIMIT, len(want))
    for p in got:
        w = want[p["product_id"]]
        assert (p["units"], p["revenue_cents"], p["orders"]) == (
            w["units"],
            w["revenue_cents"],
            len(w["orders"]),
        )
        assert p["sku"] and p["name"]
    units = [p["units"] for p in got]
    assert units == sorted(units, reverse=True)
    assert units[0] == max(w["units"] for w in want.values())
    assert r.data["range"] == {"from": "2026-10-08", "to": "2026-10-14"}
    assert r.data["orders_counted"] == len(set().union(*(w["orders"] for w in want.values())))


def test_sort_by_revenue_and_limit(ctx):
    r = sbp.run({**WEEK, "sort_by": "revenue", "limit": 3}, ctx)
    rev = [p["revenue_cents"] for p in r.data["products"]]
    assert len(rev) == 3 and rev == sorted(rev, reverse=True)


def test_open_range_reports_covered_dates(ctx):
    r = sbp.run({**WEEK, "created_from": None, "created_to": None}, ctx)
    lo, hi = r.data["range"]["from"], r.data["range"]["to"]
    assert lo and hi and lo <= hi and r.data["orders_counted"] > 0


def test_empty_range(ctx):
    r = sbp.run({**WEEK, "created_from": "2030-01-01", "created_to": "2030-01-31"}, ctx)
    assert r.ok and r.data["products"] == [] and r.data["orders_counted"] == 0
    assert r.data["range"] == {"from": "2030-01-01", "to": "2030-01-31"}


@pytest.mark.parametrize(
    "bad",
    [
        {"created_from": "2026-10-01' OR 1=1 --"},
        {"created_to": "2026-10-14; DROP TABLE orders"},
        {"sort_by": "units DESC; DROP TABLE orders"},
        {"sort_by": "qty"},
        {"limit": 0},
        {"limit": 51},
        {"limit": True},
        {"limit": "5"},
    ],
)
def test_bad_args_rejected_without_sql(ctx, bad):
    r = sbp.run({**WEEK, **bad}, ctx)
    assert not r.ok and r.error == "invalid"
    assert ctx.db.execute("SELECT COUNT(*) FROM orders").fetchone()[0] > 0  # table intact


def test_refunded_orders_not_counted(ctx):
    oid, pid, qty = ctx.db.execute(
        "SELECT o.id, i.product_id, i.qty FROM orders o JOIN order_items i ON i.order_id = o.id"
        " WHERE o.status = 'shipped' AND substr(o.created_at, 1, 10) BETWEEN ? AND ? LIMIT 1",
        ("2026-10-08", "2026-10-14"),
    ).fetchone()
    args = {**WEEK, "limit": sbp.MAX_LIMIT}
    before = {p["product_id"]: p["units"] for p in sbp.run(args, ctx).data["products"]}
    ctx.db.execute("UPDATE orders SET status = 'refunded' WHERE id = ?", (oid,))
    after = {p["product_id"]: p["units"] for p in sbp.run(args, ctx).data["products"]}
    assert after.get(pid, 0) == before[pid] - qty
