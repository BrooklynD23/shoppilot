"""Demand forecast: stdlib Croston-SBA / SES x day-of-week (spec 03 §2.1, §3.1)."""
from __future__ import annotations

import math
import statistics
from datetime import date, timedelta
from itertools import accumulate
from statistics import NormalDist

Z80 = NormalDist().inv_cdf(0.9)  # 1.2816
COVER_DAYS = 14
MIN_HISTORY_DAYS = 14
DEAD_AFTER_DAYS = 60
ALPHAS = (0.05, 0.1, 0.2, 0.3, 0.5)
ADI_CUT = 1.32
CROSTON_ALPHA = 0.1
RESID_DAYS = 56
HISTORY_OUT_DAYS = 28
_COLS = ("id", "sku", "name", "stock", "cost_cents", "lead_time_days")


def _sanitise(units: list) -> tuple[list[float], list[str]]:
    ok = [isinstance(u, (int, float)) and not math.isnan(u) and u >= 0 for u in units]
    bad = ok.count(False)
    clean = [float(u) if good else 0.0 for u, good in zip(units, ok, strict=True)]
    return clean, ([f"dropped {bad} rows with missing or negative qty"] if bad else [])


def _dow_index(units: list[float], first: date) -> list[float]:
    if len(units) < 28:
        return [1.0] * 7
    start = max(0, len(units) - RESID_DAYS)
    sums, counts = [0.0] * 7, [0] * 7
    for i in range(start, len(units)):
        wd = (first + timedelta(i)).weekday()
        sums[wd] += units[i]
        counts[wd] += 1
    means = [s / c if c else 0.0 for s, c in zip(sums, counts, strict=True)]
    overall = sum(means) / 7
    if overall <= 0:
        return [1.0] * 7
    return [m / overall for m in means]  # mean of the 7 ratios is 1 by construction


def _ses(units: list[float], idx: list[float], first: date,
         alpha: float) -> tuple[float, list[float], float]:
    wds = [(first + timedelta(i)).weekday() for i in range(len(units))]
    des = [u / idx[w] if idx[w] > 0 else 0.0 for u, w in zip(units, wds, strict=True)]
    level = sum(des[:7]) / len(des[:7])
    resid, sse = [], 0.0
    for d, u, w in zip(des, units, wds, strict=True):
        r = u - level * idx[w]
        resid.append(r)
        sse += r * r
        level += alpha * (d - level)
    return level, resid, sse


def _ses_dow(units: list[float], first: date, days: int) -> tuple[list[float], list[float], dict]:
    idx = _dow_index(units, first)
    level, resid, _ = min((_ses(units, idx, first, a) for a in ALPHAS), key=lambda t: t[2])
    start = first + timedelta(len(units))
    mean = [level * idx[(start + timedelta(h)).weekday()] for h in range(days)]
    weekend = (idx[5] + idx[6]) / 2 > 1.1 * sum(idx[:5]) / 5
    return mean, resid, {"weekend": weekend}


def _croston_sba(units: list[float], days: int) -> tuple[list[float], list[float], dict]:
    a = CROSTON_ALPHA
    nz = [i for i, u in enumerate(units) if u > 0]
    z, p = units[nz[0]], len(units) / len(nz)
    resid, last = [], nz[0]
    for i, u in enumerate(units):
        rate = (1 - a / 2) * z / p
        if i <= nz[0]:
            continue
        resid.append(u - rate)
        if u > 0:
            z += a * (u - z)
            p, last = p + a * ((i - last) - p), i
    rate = (1 - a / 2) * z / p
    return [rate] * days, resid, {"interval": p, "size": z}


def _band(hmean: list[float], hcum: list[float], sigma: float, as_of: date,
          on_hand: int) -> tuple[dict, dict]:
    """Daily demand band and projected stock, horizon long, rounded for the UI."""
    # ponytail: assumes independent daily errors; residual bootstrap if coverage < 0.70
    r2 = lambda xs: [round(x, 2) for x in xs]  # noqa: E731
    spread = [Z80 * sigma * math.sqrt(k) for k in range(1, len(hmean) + 1)]
    band = {"level": 0.8,
            "dates": [(as_of + timedelta(h)).isoformat() for h in range(1, len(hmean) + 1)],
            "mean": r2(hmean),
            "lo": r2([max(0.0, m - Z80 * sigma) for m in hmean]),
            "hi": r2([m + Z80 * sigma for m in hmean])}
    stock = {"mean": r2([on_hand - c for c in hcum]),
             "lo": r2([on_hand - c - s for c, s in zip(hcum, spread, strict=True)]),
             "hi": r2([on_hand - c + s for c, s in zip(hcum, spread, strict=True)])}
    return band, stock


def _first_hit(cum: list[float], sigma: float, on_hand: int, sign: int) -> int | None:
    for k, c in enumerate(cum, 1):
        if c + sign * Z80 * sigma * math.sqrt(k) >= on_hand:
            return k
    return None


def _stockout(cum: list[float], sigma: float, on_hand: int) -> tuple[int | None, list[int] | None]:
    if on_hand == 0:
        return 0, [0, 0]
    point = _first_hit(cum, sigma, on_hand, 0)
    if point is None:
        return None, None
    earliest = _first_hit(cum, sigma, on_hand, +1)
    # ponytail: latest capped at the horizon when the low band never runs out inside it
    latest = _first_hit(cum, sigma, on_hand, -1) or len(cum)
    return point, [earliest, latest]


def _reorder(cum_all: list[float], sigma: float, lead: int, on_hand: int, on_order: int) -> int:
    n = lead + COVER_DAYS
    need = cum_all[n - 1] + Z80 * sigma * math.sqrt(n)
    return max(0, math.ceil(need) - on_hand - on_order)


def _explain(method: str, avg: float, info: dict, r: dict, lead: int, n_days: int) -> str:
    if method == "no_demand":
        return f"No sales in the last {DEAD_AFTER_DAYS} days, so no restock suggested."
    if method == "insufficient_history":
        return f"Only {n_days} days of sales, too little to forecast. Tell me a quantity to order."
    if method == "croston_sba":
        head = (f"Sells rarely: about 1 sale every {info['interval']:.0f} days, "
                f"~{info['size']:.1f} units each (≈{avg:.1f}/day).")
    else:
        head = f"Sells about {avg:.1f}/day{', more on weekends' if info['weekend'] else ''}."
    d, rng, h = r["days_to_stockout"], r["stockout_range"], len(r["band"]["mean"])
    if d == 0:
        stock = "Already out of stock."
    elif d is None:
        stock = f"{r['on_hand']} in stock: runs out not within {h} days."
    else:
        stock = f"{r['on_hand']} in stock runs out in about {d} days (80% range {rng[0]}–{rng[1]})."
    qty = r["reorder_qty"]
    tail = (f" Lead time is {lead} days, so order now: {qty} units covers the lead time"
            f" plus {COVER_DAYS} days." if qty else " No reorder needed now.")
    if d is not None and d < lead:
        gap = lead - d
        tail += (f" Expect to be out of stock for about {gap} day{'s' * (gap != 1)}"
                 " before the PO arrives.")
    return f"{head} {stock}{tail}"


def _fit(units: list[float], first: date, days: int) -> tuple[str, list[float], list[float], dict]:
    """Guards then SBC classification: (method, daily mean over `days`, residuals, info)."""
    n = len(units)
    if sum(units[-DEAD_AFTER_DAYS:]) == 0:
        return "no_demand", [0.0] * days, [], {}
    if n < MIN_HISTORY_DAYS:
        return "insufficient_history", [sum(units) / n] * days, units, {}
    if n / sum(1 for u in units if u > 0) >= ADI_CUT:
        return "croston_sba", *_croston_sba(units, days)
    return "ses_dow", *_ses_dow(units, first, days)


def forecast_series(units: list[float], first_date: date, on_hand: int, on_order: int,
                    lead_time_days: int, horizon_days: int = 14) -> dict:
    """Pure core. units[i] = units sold on first_date + i; the last entry is yesterday."""
    if not 1 <= horizon_days <= 60:
        raise ValueError("horizon_days must be 1-60")
    if on_hand is None or on_hand < 0:
        raise ValueError("bad on_hand")
    units, warnings = _sanitise(units)
    n = len(units)
    as_of = first_date + timedelta(n - 1)
    days = max(horizon_days, lead_time_days + COVER_DAYS)
    method, mean, resid, info = _fit(units, first_date, days)
    tail = resid[-RESID_DAYS:]
    sigma = statistics.pstdev(tail) if len(tail) >= 2 and method != "no_demand" else 0.0
    cum = list(accumulate(mean))
    hmean, hcum = mean[:horizon_days], cum[:horizon_days]
    band, stock = _band(hmean, hcum, sigma, as_of, on_hand)
    dts, rng = _stockout(hcum, sigma, on_hand)
    reorder: int | None = _reorder(cum, sigma, lead_time_days, on_hand, on_order)
    if method == "no_demand":
        dts, rng, reorder = None, None, 0
    elif method == "insufficient_history":
        dts, rng, reorder = None, None, None
    hist = units[-HISTORY_OUT_DAYS:]
    hist_dates = [(as_of - timedelta(len(hist) - 1 - i)).isoformat() for i in range(len(hist))]
    result = {
        "method": method, "as_of": as_of.isoformat(), "history_days": n,
        "on_hand": on_hand, "on_order": on_order, "lead_time_days": lead_time_days,
        "avg_daily": round(sum(hmean) / horizon_days, 1),
        "days_to_stockout": dts, "stockout_range": rng, "band": band, "stock": stock,
        "history": {"dates": hist_dates, "units": hist},
        "reorder_qty": reorder,
        "warnings": warnings,
    }
    result["explanation"] = _explain(method, result["avg_daily"], info, result, lead_time_days, n)
    return result


def _load_series(ctx, product_id: str) -> tuple[dict, list[float], date, list[str]]:
    """Product row, daily units first_date..yesterday, first_date, warnings. The only SQL here."""
    row = ctx.db.execute(
        f"SELECT {', '.join(_COLS)} FROM products WHERE id = ?",  # noqa: S608 - constant columns
        (product_id,),
    ).fetchone()
    if row is None:
        raise ValueError("unknown product")
    product = dict(zip(_COLS, row, strict=True))
    product["on_order"] = ctx.db.execute(
        "SELECT COALESCE(SUM(qty), 0) FROM purchase_orders"
        " WHERE product_id = ? AND status = 'open'",
        (product_id,),
    ).fetchone()[0]
    start = ctx.today - timedelta(180)
    rows = ctx.db.execute(
        "SELECT substr(o.created_at, 1, 10) AS d,"
        " SUM(CASE WHEN i.qty > 0 THEN i.qty ELSE 0 END),"
        " SUM(CASE WHEN i.qty > 0 THEN 0 ELSE 1 END)"
        " FROM order_items i JOIN orders o ON o.id = i.order_id"
        " WHERE i.product_id = ? AND o.status != 'cancelled' AND d >= ? AND d < ?"
        " GROUP BY d",
        (product_id, start.isoformat(), ctx.today.isoformat()),
    ).fetchall()
    by_day = {date.fromisoformat(d): float(q) for d, q, _ in rows if q > 0}
    bad = sum(b for _, _, b in rows)
    warnings = [f"dropped {bad} rows with missing or negative qty"] if bad else []
    first = min(by_day) if by_day else ctx.today
    units = [by_day.get(first + timedelta(i), 0.0) for i in range((ctx.today - first).days)]
    return product, units, first, warnings


def forecast_demand(product_id: str, ctx, horizon_days: int = 14) -> dict:
    """Frozen name (spec §3.1). Raises ValueError for unknown product or bad horizon."""
    p, units, first, warnings = _load_series(ctx, product_id)
    r = forecast_series(units, first, p["stock"], p["on_order"], p["lead_time_days"], horizon_days)
    qty = r["reorder_qty"]
    return {
        "product_id": p["id"], "sku": p["sku"], "name": p["name"],
        **r,
        "unit_cost_cents": p["cost_cents"],
        "reorder_cost_cents": None if qty is None else qty * p["cost_cents"],
        "warnings": warnings + r["warnings"],
    }
