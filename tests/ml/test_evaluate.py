"""Spec 03 §6 gates on P1's real seed. Fix the seed or the model, never loosen a gate."""

import time

import pytest

from app.ml.evaluate import anomaly_eval, backtest, markdown_table
from app.ml.forecast import forecast_demand
from app.seed.generate import AT_RISK_PRODUCT_IDS, HERO_PRODUCT_ID


@pytest.fixture
def bt(ctx):
    return backtest(ctx)


def test_backtest_shape(bt):
    assert set(bt["mae"]) == {"model", "snaive", "mean28"}
    assert set(bt["coverage"]) == {"daily", "cumulative"}
    assert bt["n_products"] >= 12


def test_mae_beats_baselines(bt):
    mae = bt["mae"]
    assert mae["model"] <= mae["snaive"]
    assert mae["model"] <= 1.05 * mae["mean28"]


@pytest.mark.parametrize("kind", ["daily", "cumulative"])
def test_band_coverage(bt, kind):
    assert 0.70 <= bt["coverage"][kind] <= 0.95


def test_anomaly_gates(ctx):
    ev = anomaly_eval(ctx)
    assert ev["recall"] == 1.0
    assert ev["precision"] >= 0.8
    assert ev["decoy_max_score"] < 3.5
    assert ev["flagged"] >= 8


def test_speed(ctx):
    from app.ml.anomaly import flag_anomalies

    ids = [r[0] for r in ctx.db.execute("SELECT id FROM products")]
    t0 = time.perf_counter()
    for pid in ids:
        forecast_demand(pid, ctx)
    flag_anomalies(ctx)
    assert time.perf_counter() - t0 < 0.5


def test_at_risk_matches_seed(ctx):
    from app.tools.forecast_demand import run

    r = run({"product_id": None, "horizon_days": 7, "only_at_risk": True}, ctx)
    assert r.ok
    assert sorted(f["product_id"] for f in r.data["items"]) == sorted(AT_RISK_PRODUCT_IDS)
    hero = forecast_demand(HERO_PRODUCT_ID, ctx, horizon_days=7)
    assert 3 <= hero["days_to_stockout"] <= 5


def test_markdown_table(ctx):
    md = markdown_table(backtest(ctx), anomaly_eval(ctx))
    assert md.startswith("| Metric |")
    assert "Daily MAE" in md and "Decoy" in md
