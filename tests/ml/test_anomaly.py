import random
from datetime import UTC, datetime, timedelta

import pytest

from app.ml.anomaly import (
    THRESHOLD,
    InsufficientData,
    flag_anomalies,
    modified_z,
    score_orders,
)

ANCHOR = datetime(2026, 10, 15, tzinfo=UTC)
SINCE = ANCHOR - timedelta(days=7)
PRICES = (1500, 2400, 3200, 4900)


def order(oid, cust, when, lines, ship="US", bill="US"):
    """lines: [(qty, unit_price_cents, price_cents)]"""
    return {
        "id": oid,
        "customer_id": cust,
        "created_at": when.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "total_cents": sum(q * u for q, u, _ in lines),
        "ship_country": ship,
        "bill_country": bill,
        "lines": [{"qty": q, "unit_price_cents": u, "price_cents": p} for q, u, p in lines],
    }


def base_orders(n=300):
    rng = random.Random(4680)  # noqa: S311 - deterministic test data
    out = []
    for i in range(n):
        when = ANCHOR - timedelta(minutes=rng.randint(60, 180 * 24 * 60))
        lines = []
        for _ in range(rng.randint(1, 3)):
            p = rng.choice(PRICES)
            paid = round(0.8 * p) if rng.random() < 0.1 else p
            lines.append((rng.choice((1, 1, 1, 2)), paid, p))
        out.append(order(f"b{i}", f"c{rng.randrange(150)}", when, lines))
    return out


def ids(items):
    return {it["order_id"] for it in items}


def recent(minutes=30):
    return ANCHOR - timedelta(days=1, minutes=minutes)


def test_base_orders_are_clean():
    assert score_orders(base_orders(), ANCHOR - timedelta(days=180)) == []


def test_modified_z_known():
    z = modified_z([1, 2, 3, 4, 100])
    assert z[-1] > 3.5
    assert z[2] == 0


def test_mad_zero_fallback():
    assert modified_z([5] * 20 + [50])[-1] > 3.5
    assert modified_z([5] * 21) == [0.0] * 21


def test_bulk_flagged():
    o = order("bulk", "c1", recent(), [(25, 1500, 1500)])
    items = score_orders(base_orders() + [o], SINCE)
    assert ids(items) == {"bulk"}
    assert "25 units in one order" in items[0]["reason"]


def test_price_glitch_flagged():
    o = order("glitch", "c2", recent(), [(1, 98, 4900)])
    items = score_orders(base_orders() + [o], SINCE)
    assert ids(items) == {"glitch"}
    it = items[0]
    assert it["signals"]["price"] == 9.8
    assert "Paid $0.98 for an item listed at $49.00 (2% of price)" in it["reason"]


def test_velocity_flags_all_burst():
    burst = [
        order(f"v{i}", "cnew", recent() + timedelta(minutes=m), [(1, 2400, 2400)])
        for i, m in enumerate((0, 9, 19, 28, 40))
    ]
    items = score_orders(base_orders() + burst, SINCE)
    assert ids(items) == {f"v{i}" for i in range(5)}
    assert all("1 of 5" in it["reason"] for it in items)


def test_new_mismatch_boost_only():
    normal = order("nm", "cfresh", recent(), [(1, 2400, 2400)], ship="US", bill="CA")
    assert score_orders(base_orders() + [normal], SINCE) == []

    high = [(9, 4900, 4900)]
    with_mm = order("hi", "cfresh2", recent(), high, ship="US", bill="CA")
    flagged = score_orders(base_orders() + [with_mm], SINCE)
    assert ids(flagged) == {"hi"}
    assert "first order, ships to US but billed in CA" in flagged[0]["reason"]
    assert flagged[0]["signals"]["boost"] == 1.5

    no_mm = order("hi", "cfresh2", recent(), high)
    plain = score_orders(base_orders() + [no_mm], SINCE)
    assert not plain or plain[0]["score"] < flagged[0]["score"]


def test_mismatch_on_returning_customer_no_boost():
    first = order("r1", "cret", recent() - timedelta(days=30), [(1, 2400, 2400)])
    later = order("r2", "cret", recent(), [(9, 4900, 4900)], ship="US", bill="CA")
    items = score_orders(base_orders() + [first, later], SINCE)
    assert all(it["signals"]["boost"] == 0 for it in items)


def test_coupon_not_flagged():
    o = order("cp", "c3", recent(), [(1, 1920, 2400)])
    assert score_orders(base_orders() + [o], SINCE) == []


def test_reason_human():
    extra = [
        order("bulk", "c1", recent(), [(25, 1500, 1500)]),
        order("glitch", "c2", recent(), [(1, 98, 4900)]),
    ]
    items = score_orders(base_orders() + extra, SINCE)
    assert len(items) == 2
    assert items[0]["score"] >= items[1]["score"]
    for it in items:
        assert {
            "order_id",
            "score",
            "reason",
            "threshold",
            "signals",
            "created_at",
            "customer_id",
            "total_cents",
        } <= it.keys()
        assert it["threshold"] == THRESHOLD
        assert "$" in it["reason"]
        assert it["score"] == round(it["score"], 1)
        assert all(v == round(v, 1) for v in it["signals"].values())


def test_too_few_orders():
    with pytest.raises(InsufficientData):
        score_orders(base_orders(10), SINCE)
    assert issubclass(InsufficientData, ValueError)


def test_bad_rows_skipped():
    bad = [
        order("nullp", "c4", recent(), [(1, 2400, 2400)]),
        order("zerop", "c5", recent(), [(1, 2400, 0)]),
        order("nant", "c6", recent(), [(1, 2400, 2400)]),
        order("negt", "c7", recent(), [(1, 2400, 2400)]),
    ]
    bad[0]["lines"][0]["unit_price_cents"] = None
    bad[2]["total_cents"] = float("nan")
    bad[3]["total_cents"] = -5
    assert score_orders(base_orders() + bad, SINCE) == []


def test_window():
    old = order("old", "c8", ANCHOR - timedelta(days=30), [(25, 1500, 1500)])
    items = score_orders(base_orders() + [old], SINCE)
    assert "old" not in ids(items)
    # baseline counts orders outside the window: 25 old + 5 new = 30, no InsufficientData
    mixed = base_orders(25)
    for o in mixed:
        o["created_at"] = "2026-06-01T10:00:00Z"
    mixed += [order(f"n{i}", f"cn{i}", recent(i * 120), [(1, 2400, 2400)]) for i in range(5)]
    assert score_orders(mixed, SINCE) == []


def test_seed_planted_found(ctx):
    from app.seed.generate import DECOY_ORDER_IDS, PLANTED_ANOMALY_ORDER_IDS

    got = ids(flag_anomalies(ctx))
    assert set(PLANTED_ANOMALY_ORDER_IDS) <= got
    assert got.isdisjoint(DECOY_ORDER_IDS)


def test_since_days_bounds(ctx):
    for bad in (0, 91):
        with pytest.raises(ValueError):
            flag_anomalies(ctx, since_days=bad)


def test_null_catalog_price_skipped_and_logged(caplog):
    o = order("gone", "c9", recent(), [(1, 2400, 2400)])
    o["lines"][0]["price_cents"] = None  # deleted product: LEFT JOIN gives NULL
    o["lines"].append({"qty": 1, "unit_price_cents": 98, "price_cents": None})
    with caplog.at_level("WARNING", logger="app.ml.anomaly"):
        items = score_orders(base_orders() + [o], SINCE)
    assert "gone" not in ids(items)
    assert "price signal skipped" in caplog.text


def test_velocity_window_edges_inclusive():
    t = recent(200)
    trio = [
        order(f"e{i}", "cedge", t + timedelta(minutes=60 * i), [(1, 2400, 2400)]) for i in range(3)
    ]
    items = {it["order_id"]: it for it in score_orders(base_orders() + trio, SINCE)}
    assert "e1" in items
    assert items["e1"]["signals"]["velocity"] == 3.5
    assert "1 of 3 orders" in items["e1"]["reason"]
    assert "e0" not in items and "e2" not in items  # each sees only 2 within an hour
