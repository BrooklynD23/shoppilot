import pytest

from app.seed.generate import AT_RISK_PRODUCT_IDS, HERO_PRODUCT_ID
from app.tools import forecast_demand as fd
from app.tools.registry import _check_strict

ALL7 = {"product_id": None, "horizon_days": 7, "only_at_risk": True}


def _hero_name(ctx) -> str:
    row = ctx.db.execute("SELECT name FROM products WHERE id = ?", (HERO_PRODUCT_ID,)).fetchone()
    return row[0]


def test_single_product(ctx):
    r = fd.run({"product_id": HERO_PRODUCT_ID, "horizon_days": 14, "only_at_risk": True}, ctx)
    assert r.ok, r.error
    f = r.data["forecast"]
    assert f["product_id"] == HERO_PRODUCT_ID and "days_to_stockout" in f
    assert len(f["band"]["mean"]) == 14


def test_all_at_risk_sorted(ctx):
    r = fd.run(ALL7, ctx)
    assert r.ok, r.error
    items = r.data["items"]
    ids = [it["product_id"] for it in items]
    assert set(ids) <= set(AT_RISK_PRODUCT_IDS) and HERO_PRODUCT_ID in ids
    days = [it["days_to_stockout"] for it in items]
    assert None not in days and days == sorted(days) and max(days) <= 7


def test_all_not_only_at_risk_includes_more(ctx):
    r = fd.run({"product_id": None, "horizon_days": 7, "only_at_risk": False}, ctx)
    assert r.ok and len(r.data["items"]) > len(fd.run(ALL7, ctx).data["items"])
    days = [it["days_to_stockout"] for it in r.data["items"]]
    known = [d for d in days if d is not None]
    assert days[: len(known)] == sorted(known)  # None (no stockout) sorts last


def test_unknown_product_error(ctx):
    r = fd.run({"product_id": "nope", "horizon_days": 14, "only_at_risk": True}, ctx)
    assert r.ok is False and "unknown product" in r.error


@pytest.mark.parametrize("h", [0, 61, True, "7", None])
def test_horizon_bounds(h, ctx):
    r = fd.run({"product_id": None, "horizon_days": h, "only_at_risk": True}, ctx)
    assert r.ok is False and r.error == "invalid"


def test_bad_product_skipped_not_fatal(ctx, monkeypatch):
    real = fd.forecast.forecast_demand

    def flaky(pid, c, horizon_days=14):
        if pid == HERO_PRODUCT_ID:
            raise ValueError("boom")
        return real(pid, c, horizon_days)

    monkeypatch.setattr(fd.forecast, "forecast_demand", flaky)
    r = fd.run(ALL7, ctx)
    assert r.ok
    assert {"product_id": HERO_PRODUCT_ID, "error": "boom"} in r.data["skipped"]
    assert HERO_PRODUCT_ID not in [it["product_id"] for it in r.data["items"]]


def test_schema_rejects_extra():
    s = fd.SPEC
    assert s.input_schema["additionalProperties"] is False
    assert set(s.input_schema["required"]) == {"product_id", "horizon_days", "only_at_risk"}
    assert (s.destructive, s.moves_money, s.undoable) == (False, False, False)
    _check_strict(s.input_schema)


def test_summary_names_products(ctx):
    r = fd.run(ALL7, ctx)
    assert _hero_name(ctx) in r.summary and "d)" in r.summary
    assert r.summary.startswith(f"{len(r.data['items'])} products run out within 7 days: ")


def test_preview_read_only(ctx):
    d = fd.preview(ALL7, ctx)
    assert d.step_id == "" and d.before == {}
    assert d.after["read_only"] is True and "7 days" in d.after["summary"]
