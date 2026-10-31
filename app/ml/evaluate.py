"""Spec 03 §6 evaluation on the real seed. `python -m app.ml.evaluate` prints the README table."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from itertools import accumulate
from unittest import mock

from app.ml import anomaly
from app.ml.forecast import _load_series, forecast_series
from app.seed.generate import DECOY_ORDER_IDS, PLANTED_ANOMALY_ORDER_IDS

MIN_BACKTEST_DAYS = 60


def _fold(units: list[float], first, cut: int, h: int) -> tuple[list[float], ...]:
    """Errors for model/snaive/mean28 plus daily and cumulative band hits on one fold."""
    train, test = units[:cut], units[cut : cut + h]
    # on_hand=0 makes stock = -cum ± spread, so the cumulative band reads straight off it
    r = forecast_series(train, first, 0, 0, 0, horizon_days=h)
    b, s = r["band"], r["stock"]
    snaive = [train[-7 + i % 7] for i in range(h)]
    m28 = sum(train[-28:]) / 28
    cum = list(accumulate(test))
    return (
        [abs(a - p) for a, p in zip(test, b["mean"], strict=True)],
        [abs(a - p) for a, p in zip(test, snaive, strict=True)],
        [abs(a - m28) for a in test],
        [float(lo <= a <= hi) for a, lo, hi in zip(test, b["lo"], b["hi"], strict=True)],
        [float(-hi <= c <= -lo) for c, lo, hi in zip(cum, s["lo"], s["hi"], strict=True)],
    )


def backtest(ctx, folds: int = 2, h: int = 14) -> dict:
    """Rolling origin, `folds` x `h` days, on every product with >= 60 days of history."""
    pools: list[list[float]] = [[], [], [], [], []]
    n = 0
    for (pid,) in ctx.db.execute("SELECT id FROM products ORDER BY id").fetchall():
        _, units, first, _ = _load_series(ctx, pid)
        if len(units) < MIN_BACKTEST_DAYS:
            continue
        n += 1
        for f in range(folds, 0, -1):
            for pool, xs in zip(pools, _fold(units, first, len(units) - f * h, h), strict=True):
                pool.extend(xs)
    if not n:
        raise ValueError(f"no product has {MIN_BACKTEST_DAYS} days of history")
    avg = [round(sum(p) / len(p), 3) for p in pools]
    return {
        "mae": {"model": avg[0], "snaive": avg[1], "mean28": avg[2]},
        "coverage": {"daily": avg[3], "cumulative": avg[4]},
        "n_products": n,
    }


def anomaly_eval(ctx) -> dict:
    """Recall/precision over the full history, plus the highest score any decoy reaches."""
    orders, _ = anomaly._load_orders(ctx)
    since = datetime.combine(ctx.today - timedelta(days=365), datetime.min.time(), UTC)
    # ponytail: patches the module threshold to read sub-threshold scores; eval/CLI only
    with mock.patch.object(anomaly, "THRESHOLD", float("-inf")):
        scored = {it["order_id"]: it["score"] for it in anomaly.score_orders(orders, since)}
    flagged = {oid for oid, s in scored.items() if s >= anomaly.THRESHOLD}
    planted = set(PLANTED_ANOMALY_ORDER_IDS)
    hits = len(flagged & planted)
    return {
        "recall": hits / len(planted),
        "precision": hits / len(flagged) if flagged else 0.0,
        "decoy_max_score": max(scored.get(d, 0.0) for d in DECOY_ORDER_IDS),
        "flagged": len(flagged),
    }


def markdown_table(bt: dict, an: dict) -> str:
    m, c = bt["mae"], bt["coverage"]
    rows = [
        (
            "Daily MAE (units/day)",
            f"model **{m['model']:.2f}**, seasonal-naive "
            f"{m['snaive']:.2f}, 28-day mean {m['mean28']:.2f} ({bt['n_products']} products)",
            "model ≤ seasonal-naive AND ≤ 1.05 × mean28",
        ),
        ("80% band coverage, daily", f"**{c['daily']:.2f}**", "0.70–0.95"),
        ("80% band coverage, cumulative", f"**{c['cumulative']:.2f}**", "0.70–0.95"),
        ("Anomaly recall on planted", f"**{an['recall']:.2f}**", "1.00"),
        ("Anomaly precision", f"**{an['precision']:.2f}** ({an['flagged']} flagged)", "≥ 0.8"),
        ("Decoy not flagged", f"max score **{an['decoy_max_score']:.1f}**", "< 3.5"),
    ]
    out = ["| Metric | Result | Gate |", "|---|---|---|"]
    return "\n".join(out + [f"| {a} | {b} | {g} |" for a, b, g in rows])


if __name__ == "__main__":
    import sqlite3

    from app.db import init_schema
    from app.seed.generate import CANON_ANCHOR, seed_store
    from app.tools.registry import Ctx

    conn = sqlite3.connect(":memory:")
    init_schema(conn)
    seed_store(conn, CANON_ANCHOR)
    c = Ctx("eval", conn, datetime.now(UTC), CANON_ANCHOR)
    print(markdown_table(backtest(c), anomaly_eval(c)))  # noqa: T201 - CLI output
