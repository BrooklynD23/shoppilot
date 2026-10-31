from datetime import UTC, date, datetime

import pytest

from app.seed.generate import DECOY_ORDER_IDS, PLANTED_ANOMALY_ORDER_IDS
from app.tools import flag_anomalies as fa
from app.tools.registry import Ctx, _check_strict

ARGS = {"since_days": 7, "limit": 50}


def test_finds_planted(ctx):
    r = fa.run(ARGS, ctx)
    assert r.ok, r.error
    ids = {it["order_id"] for it in r.data["items"]}
    assert set(PLANTED_ANOMALY_ORDER_IDS) <= ids
    assert not ids & set(DECOY_ORDER_IDS)
    assert r.data["threshold"] == 3.5
    assert r.data["total_flagged"] == len(r.data["items"])


def test_limit_respected(ctx):
    r = fa.run({"since_days": 7, "limit": 2}, ctx)
    assert r.ok and len(r.data["items"]) == 2
    assert r.data["total_flagged"] >= 2


def test_too_few_orders_ok_true(seeded):
    seeded.execute("DELETE FROM orders WHERE id NOT IN (SELECT id FROM orders LIMIT 5)")
    small = Ctx("sid-test", seeded, datetime(2026, 10, 15, 9, 0, tzinfo=UTC), date(2026, 10, 15))
    r = fa.run(ARGS, small)
    assert r.ok
    assert "too few orders" in r.summary
    assert r.data["items"] == [] and r.data["total_flagged"] == 0


@pytest.mark.parametrize("args", [
    {"since_days": 0, "limit": 10}, {"since_days": 91, "limit": 10},
    {"since_days": 7, "limit": 0}, {"since_days": 7, "limit": 51},
    {"since_days": True, "limit": 10},
])
def test_bounds(args, ctx):
    r = fa.run(args, ctx)
    assert r.ok is False and r.error == "invalid"


def test_summary_human(ctx):
    r = fa.run(ARGS, ctx)
    top = r.data["items"][0]
    assert r.summary.startswith(f"{r.data['total_flagged']} suspicious orders this week; top: ")
    assert top["order_id"] in r.summary and "$" in r.summary
    r30 = fa.run({"since_days": 30, "limit": 5}, ctx)
    assert "in the last 30 days" in r30.summary


def test_preview_read_only_writes_nothing(ctx):
    d = fa.preview(ARGS, ctx)
    assert d.step_id == "" and d.before == {}
    assert d.after["read_only"] is True and "7 days" in d.after["summary"]


def test_spec_strict_read_only():
    s = fa.SPEC
    assert s.name == "flag_anomalies"
    assert (s.destructive, s.moves_money, s.undoable) == (False, False, False)
    assert set(s.input_schema["required"]) == {"since_days", "limit"}
    _check_strict(s.input_schema)
