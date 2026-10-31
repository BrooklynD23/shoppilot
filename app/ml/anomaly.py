"""Order anomaly scoring: modified z (Iglewicz-Hoaglin) plus business rules (spec 03 §2.2)."""

import logging
import math
from bisect import bisect_left, bisect_right
from collections import defaultdict
from datetime import UTC, datetime, time, timedelta
from statistics import mean, median

log = logging.getLogger(__name__)

THRESHOLD = 3.5
MIN_ORDERS = 30
BOOST = 1.5
VELOCITY_WINDOW_S = 3600
MAX_SINCE_DAYS = 90


class InsufficientData(ValueError):
    """Fewer than MIN_ORDERS usable orders to build a baseline."""


def modified_z(xs: list[float]) -> list[float]:
    """M = 0.6745(x-med)/MAD; MeanAD fallback when MAD == 0; all-equal -> zeros."""
    if not xs:
        return []
    med = median(xs)
    dev = [abs(x - med) for x in xs]
    mad = median(dev)
    if mad:
        return [0.6745 * (x - med) / mad for x in xs]
    mean_ad = mean(dev)
    if mean_ad:
        return [(x - med) / (1.253314 * mean_ad) for x in xs]
    return [0.0] * len(xs)


def _ts(s: str) -> datetime:
    t = datetime.fromisoformat(s)
    return t if t.tzinfo else t.replace(tzinfo=UTC)


def _money(cents: float) -> str:
    return f"${cents / 100:,.2f}"


def _num(x: float) -> str:
    return f"{x:g}"


def _valid(o: dict) -> bool:
    t = o.get("total_cents")
    return isinstance(t, int | float) and not math.isnan(t) and t >= 0


def _units(o: dict) -> int:
    return sum(ln["qty"] for ln in o["lines"] if isinstance(ln.get("qty"), int) and ln["qty"] > 0)


def _price(o: dict) -> tuple[float, str, int]:
    """(score, text, skipped_lines) from the lowest paid/catalog ratio across usable lines."""
    best, skipped = None, 0
    for ln in o["lines"]:
        paid, listed = ln.get("unit_price_cents"), ln.get("price_cents")
        if paid is None or not listed or paid < 0:
            skipped += 1
            continue
        if best is None or paid / listed < best[0]:
            best = (paid / listed, paid, listed)
    if best is None or best[0] >= 0.5:
        return 0.0, "", skipped
    ratio, paid, listed = best
    text = f"Paid {_money(paid)} for an item listed at {_money(listed)} ({ratio:.0%} of price)"
    return 10 * (1 - ratio), text, skipped


def _velocity(orders: list[dict]) -> dict[str, int]:
    """Orders by the same customer within ±60 min of each order (itself included); sort + bisect."""
    times: dict[str, list[float]] = defaultdict(list)
    for o in sorted(orders, key=lambda o: (o["customer_id"], o["_t"])):
        times[o["customer_id"]].append(o["_t"])
    out = {}
    for o in orders:
        ts, t = times[o["customer_id"]], o["_t"]
        out[o["id"]] = bisect_right(ts, t + VELOCITY_WINDOW_S) - bisect_left(
            ts, t - VELOCITY_WINDOW_S
        )
    return out


def _first_orders(orders: list[dict]) -> set[str]:
    first: dict[str, dict] = {}
    for o in orders:
        cur = first.get(o["customer_id"])
        if cur is None or o["_t"] < cur["_t"]:
            first[o["customer_id"]] = o
    return {o["id"] for o in first.values()}


def _prepare(orders: list[dict]) -> list[dict]:
    good = [{**o, "_t": _ts(o["created_at"]).timestamp()} for o in orders if _valid(o)]
    if len(good) < len(orders):
        log.warning(
            "anomaly: skipped %d orders with NaN/negative/missing totals", len(orders) - len(good)
        )
    if len(good) < MIN_ORDERS:
        raise InsufficientData(f"need at least {MIN_ORDERS} orders, have {len(good)}")
    return good


def _item(o: dict, sig: dict[str, float], texts: dict[str, str], boost_text: str) -> dict:
    ranked = sorted((k for k in texts if sig[k] > 0), key=lambda k: -sig[k])
    parts = [texts[k] for i, k in enumerate(ranked[:2]) if i == 0 or sig[k] >= THRESHOLD]
    if sig["boost"]:
        parts.append(boost_text)
    score = max(sig[k] for k in texts) + sig["boost"]
    return {
        "order_id": o["id"],
        "score": round(score, 1),
        "threshold": THRESHOLD,
        "reason": "; ".join(parts) + ".",
        "signals": {k: round(v, 1) for k, v in sig.items()},
        "created_at": o["created_at"],
        "customer_id": o["customer_id"],
        "total_cents": o["total_cents"],
        "_raw": score,
    }


def score_orders(orders: list[dict], report_since: datetime) -> list[dict]:
    """Score every order against the full baseline; return flagged ones since report_since."""
    good = _prepare(orders)
    since = (report_since if report_since.tzinfo else report_since.replace(tzinfo=UTC)).timestamp()
    units = [_units(o) for o in good]
    z_total = modified_z([math.log1p(o["total_cents"]) for o in good])
    z_units = modified_z(units)
    med_total, med_units = median(o["total_cents"] for o in good), median(units)
    velocity, firsts = _velocity(good), _first_orders(good)
    skipped, out = 0, []
    for o, zt, zu, n_units in zip(good, z_total, z_units, units, strict=True):
        price, price_text, bad = _price(o)
        skipped += bad
        if o["_t"] < since:
            continue
        n = velocity[o["id"]]
        mismatch = o["id"] in firsts and o.get("ship_country") != o.get("bill_country")
        sig = {
            "total": abs(zt),
            "units": max(0.0, zu),
            "price": price,
            "velocity": 3.5 + (n - 3) if n >= 3 else 0.0,
            "boost": BOOST if mismatch else 0.0,
        }
        texts = {
            "total": f"Order total {_money(o['total_cents'])} is "
            f"{o['total_cents'] / med_total:.2g}× the typical {_money(med_total)}"
            if med_total
            else "",
            "units": f"{n_units} units in one order ({_money(o['total_cents'])}); "
            f"typical is {_num(med_units)}",
            "price": price_text,
            "velocity": f"1 of {n} orders from this customer within an hour",
        }
        it = _item(
            o,
            sig,
            texts,
            f"first order, ships to {o.get('ship_country')} but billed in {o.get('bill_country')}",
        )
        if it.pop("_raw") >= THRESHOLD:
            out.append(it)
    if skipped:
        log.warning("anomaly: price signal skipped on %d lines (NULL or zero price)", skipped)
    return sorted(out, key=lambda it: -it["score"])


def _load_orders(ctx) -> tuple[list[dict], list[str]]:
    """All orders with bill country (customers.country) and lines joined to catalog price."""
    rows = ctx.db.execute(
        "SELECT o.id, o.customer_id, o.created_at, o.total_cents, o.ship_country, c.country"
        " FROM orders o LEFT JOIN customers c ON c.id = o.customer_id"
    ).fetchall()
    lines: dict[str, list[dict]] = defaultdict(list)
    for oid, qty, paid, listed in ctx.db.execute(
        "SELECT i.order_id, i.qty, i.unit_price_cents, p.price_cents"
        " FROM order_items i LEFT JOIN products p ON p.id = i.product_id"
    ):
        lines[oid].append({"qty": qty, "unit_price_cents": paid, "price_cents": listed})
    orders = [
        {
            "id": r[0],
            "customer_id": r[1],
            "created_at": r[2],
            "total_cents": r[3],
            "ship_country": r[4],
            "bill_country": r[5],
            "lines": lines.get(r[0], []),
        }
        for r in rows
    ]
    orphans = sum(1 for o in orders if o["bill_country"] is None)
    return orders, [f"{orphans} orders without a customer"] if orphans else []


def flag_anomalies(ctx, since_days: int = 7) -> list[dict]:
    """Frozen name. Report window = last `since_days` days before ctx.today (R37)."""
    if not isinstance(since_days, int) or not 1 <= since_days <= MAX_SINCE_DAYS:
        raise ValueError(f"since_days must be 1-{MAX_SINCE_DAYS}")
    orders, warnings = _load_orders(ctx)
    for w in warnings:
        log.warning("anomaly: %s", w)
    since = datetime.combine(ctx.today - timedelta(days=since_days), time(), UTC)
    return score_orders(orders, since)
