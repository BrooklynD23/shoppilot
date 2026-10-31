from datetime import date, timedelta

import pytest

from app.ml.forecast import _load_series, forecast_demand, forecast_series

FIRST = date(2026, 4, 18)  # 180 days before the 2026-10-15 anchor
TODAY = date(2026, 10, 15)
HERO = "P01"


def fs(units, on_hand=100, on_order=0, lead=5, horizon=14, first=FIRST):
    return forecast_series(units, first, on_hand, on_order, lead, horizon)


def test_regular_series_uses_ses_dow(synth):
    r = fs(synth(6))
    assert r["method"] == "ses_dow"
    assert len(r["band"]["mean"]) == 14
    assert r["as_of"] == "2026-10-14"
    assert r["band"]["dates"][0] == "2026-10-15"


def test_weekend_higher(synth):
    r = fs(synth(6))
    b = r["band"]
    by_wd = {date.fromisoformat(d).weekday(): m for d, m in zip(b["dates"], b["mean"], strict=True)}
    assert by_wd[5] > by_wd[0]


def test_intermittent_uses_croston():
    units = [2.0 if i % 6 == 0 else 0.0 for i in range(180)]
    r = fs(units)
    assert r["method"] == "croston_sba"
    assert len(set(r["band"]["mean"])) == 1


def test_all_zero_is_no_demand():
    r = fs([0.0] * 180)
    assert r["method"] == "no_demand"
    assert r["days_to_stockout"] is None
    assert r["reorder_qty"] == 0


def test_short_history():
    r = fs([3.0, 2.0, 4.0, 1.0, 2.0])
    assert r["method"] == "insufficient_history"
    assert r["reorder_qty"] is None
    assert r["days_to_stockout"] is None
    assert "quantity" in r["explanation"]


def test_zero_on_hand(synth):
    r = fs(synth(6), on_hand=0)
    assert r["days_to_stockout"] == 0
    assert r["stockout_range"] == [0, 0]


def test_nan_negative_dropped(synth):
    units = synth(6)
    units[10], units[20] = float("nan"), -3.0
    r = fs(units)
    assert r["method"] == "ses_dow"
    assert len(r["warnings"]) == 1


def test_band_ordering(synth):
    r = fs(synth(6), on_hand=40)
    b = r["band"]
    for lo, m, hi in zip(b["lo"], b["mean"], b["hi"], strict=True):
        assert 0 <= lo <= m <= hi
    lo, hi = r["stockout_range"]
    assert lo <= r["days_to_stockout"] <= hi


def test_no_stockout_in_horizon(synth):
    r = fs(synth(6), on_hand=100_000)
    assert r["days_to_stockout"] is None
    assert r["stockout_range"] is None
    assert "not within" in r["explanation"]


def test_reorder_subtracts_on_order(synth):
    q0 = fs(synth(6), on_hand=20)["reorder_qty"]
    q50 = fs(synth(6), on_hand=20, on_order=50)["reorder_qty"]
    assert q0 > 0
    assert q50 == max(0, q0 - 50)


def test_gap_warning(synth):
    r = fs(synth(6), on_hand=12, lead=10)
    assert r["days_to_stockout"] < 10
    assert "before the PO arrives" in r["explanation"]


@pytest.mark.parametrize("h", [0, 61])
def test_horizon_bounds(synth, h):
    with pytest.raises(ValueError):
        fs(synth(6), horizon=h)


def test_bad_on_hand(synth):
    with pytest.raises(ValueError):
        fs(synth(6), on_hand=-1)


def test_unknown_product(ctx):
    with pytest.raises(ValueError):
        forecast_demand("nope", ctx)


def test_hero_from_seed(ctx):
    from app.seed.generate import HERO_PRODUCT_ID

    r = forecast_demand(HERO_PRODUCT_ID, ctx)
    assert r["product_id"] == HERO_PRODUCT_ID
    assert r["sku"] and r["name"]
    assert r["as_of"] == "2026-10-14"
    assert r["days_to_stockout"] in range(3, 6)
    assert r["reorder_cost_cents"] == r["reorder_qty"] * r["unit_cost_cents"]


def test_seed_edge_products(ctx):
    assert forecast_demand("P18", ctx)["method"] == "insufficient_history"  # new
    assert forecast_demand("P19", ctx)["method"] == "no_demand"  # dead
    assert forecast_demand("P03", ctx)["days_to_stockout"] == 0  # already out


# --- #42 input guards ---------------------------------------------------------------


def test_inf_dropped(synth):
    units = synth(6)
    units[10] = float("inf")
    r = fs(units)
    assert r["method"] == "ses_dow"
    assert len(r["warnings"]) == 1


@pytest.mark.parametrize("kw", [{"horizon": 7.5}, {"lead": None}, {"lead": -1}, {"lead": 2.5}])
def test_bad_args_value_error(synth, kw):
    with pytest.raises(ValueError):
        fs(synth(6), **kw)


# --- #40/#41 SQL contract of _load_series / forecast_demand -------------------------


def _sale(ctx, oid, pid, day, qty=1, status="shipped"):
    cust = ctx.db.execute("SELECT id FROM customers LIMIT 1").fetchone()[0]
    ctx.db.execute(
        "INSERT INTO orders (id, customer_id, created_at, status, total_cents, ship_country)"
        " VALUES (?,?,?,?,?, 'US')",
        (oid, cust, f"{day.isoformat()}T12:00:00Z", status, 100 * qty),
    )
    ctx.db.execute("INSERT INTO order_items VALUES (?,?,?,100)", (oid, pid, qty))


def test_series_starts_at_window_for_lapsed_product(ctx):
    ctx.db.execute(
        "INSERT INTO products (id, sku, name, category, price_cents, cost_cents, stock,"
        " lead_time_days, supplier_email) VALUES ('PX', 'X-1', 'Lapsed', 'mugs', 1000, 400,"
        " 5, 7, 's@example.com')"
    )
    _sale(ctx, "OX1", "PX", TODAY - timedelta(400), 3)  # outside the window
    _sale(ctx, "OX2", "PX", TODAY - timedelta(10), 2)
    _, units, first, _ = _load_series(ctx, "PX")
    assert first == TODAY - timedelta(180)
    assert len(units) == 180 and sum(units) == 2
    assert forecast_demand("PX", ctx)["method"] == "croston_sba"


def test_series_starts_at_first_sale_ever(ctx):
    _, units, first, _ = _load_series(ctx, "P18")  # new product, first sale today-5
    assert first == TODAY - timedelta(5)
    assert len(units) == 5 and units[0] > 0


def test_cancelled_and_today_excluded(ctx):
    before = _load_series(ctx, HERO)[1:3]
    _sale(ctx, "OC1", HERO, TODAY - timedelta(3), 50, status="cancelled")
    _sale(ctx, "OC2", HERO, TODAY, 50)
    _sale(ctx, "OC3", HERO, TODAY - timedelta(181), 50)  # before the 180-day cutoff
    assert _load_series(ctx, HERO)[1:3] == before


def test_on_order_counts_open_pos_only(ctx):
    q0 = forecast_demand(HERO, ctx)["reorder_qty"]
    assert q0 > 10
    for i, (qty, status) in enumerate([(7, "open"), (100, "received"), (100, "cancelled")]):
        ctx.db.execute(
            "INSERT INTO purchase_orders (id, product_id, qty, unit_cost_cents, status,"
            " created_at) VALUES (?,?,?,100,?, '2026-10-14T00:00:00Z')",
            (f"PO{i}", HERO, qty, status),
        )
    r = forecast_demand(HERO, ctx)
    assert r["on_order"] == 7
    assert r["reorder_qty"] == q0 - 7
