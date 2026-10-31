from datetime import date

import pytest

from app.ml.forecast import forecast_demand, forecast_series

FIRST = date(2026, 4, 18)  # 180 days before the 2026-10-15 anchor


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
