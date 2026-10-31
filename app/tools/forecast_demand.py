"""forecast_demand tool (P3-ML-3). Read-only wrapper over app.ml.forecast; no math here."""

from __future__ import annotations

from app.agent.models import DiffItem
from app.ml import forecast
from app.tools.registry import Ctx, ToolResult, ToolSpec, register

MAX_HORIZON = 60

SPEC = ToolSpec(
    name="forecast_demand",
    description=(
        "Forecast daily demand and days until stockout with an 80% range. Use before any restock. "
        "Read-only. Quote `explanation`; never compute quantities yourself. "
        "product_id: one product_id, or null for every active product. horizon_days: 1-60. "
        "only_at_risk (with null product_id): keep only products that run out within horizon_days."
    ),
    destructive=False,
    moves_money=False,
    undoable=False,
    input_schema={
        "type": "object",
        "additionalProperties": False,
        "required": ["product_id", "horizon_days", "only_at_risk"],
        "properties": {
            "product_id": {"anyOf": [{"type": "string"}, {"type": "null"}]},
            "horizon_days": {"type": "integer"},
            "only_at_risk": {"type": "boolean"},
        },
    },
)


def _days_label(f: dict) -> str:
    d = f["days_to_stockout"]
    return f"{f['name']} ({d}d)" if d is not None else f"{f['name']} (no stockout)"


def _single(pid: str, h: int, ctx: Ctx) -> ToolResult:
    try:
        f = forecast.forecast_demand(pid, ctx, horizon_days=h)
    except ValueError as e:
        return ToolResult(ok=False, summary=f"Forecast failed: {e}", error=str(e))
    return ToolResult(
        ok=True, summary=f"{_days_label(f)}: {f['explanation']}", data={"forecast": f}
    )


def _all(h: int, only_at_risk: bool, ctx: Ctx) -> ToolResult:
    ids = [r[0] for r in ctx.db.execute("SELECT id FROM products WHERE active = 1 ORDER BY id")]
    items, skipped = [], []
    for pid in ids:
        try:  # one bad product must not sink the batch
            items.append(forecast.forecast_demand(pid, ctx, horizon_days=h))
        except ValueError as e:
            skipped.append({"product_id": pid, "error": str(e)})
    if only_at_risk:
        items = [
            f for f in items if f["days_to_stockout"] is not None and f["days_to_stockout"] <= h
        ]
    items.sort(key=lambda f: (f["days_to_stockout"] is None, f["days_to_stockout"] or 0))
    at_risk = [f for f in items if f["days_to_stockout"] is not None]
    if at_risk:
        summary = f"{len(at_risk)} products run out within {h} days: " + ", ".join(
            _days_label(f) for f in at_risk
        )
    else:
        summary = f"No products run out within {h} days."
    if not only_at_risk:
        summary += f" ({len(items)} products forecast.)"
    return ToolResult(
        ok=True,
        summary=summary,
        data={"items": items, "skipped": skipped, "llm_text": _llm_text(summary, items, skipped)},
    )


def _llm_text(summary: str, items: list[dict], skipped: list[dict]) -> str:
    """Compact per-product lines for the planner; full dicts in data stay for the UI."""
    lines = [summary] + [
        f"{f['product_id']} | {f['name']} | days_to_stockout={f['days_to_stockout']}"
        f" range={f['stockout_range']} | reorder_qty={f['reorder_qty']} | {f['explanation']}"
        for f in items
    ]
    lines += [f"skipped {s['product_id']}: {s['error']}" for s in skipped]
    return "\n".join(lines)


def run(args: dict, ctx: Ctx) -> ToolResult:
    pid, h, risk = args.get("product_id"), args.get("horizon_days"), args.get("only_at_risk", True)
    if (
        not isinstance(h, int)
        or isinstance(h, bool)
        or not 1 <= h <= MAX_HORIZON
        or not isinstance(risk, bool)
        or not (pid is None or isinstance(pid, str))
    ):
        return ToolResult(ok=False, summary="horizon_days must be 1-60", error="invalid")
    return _all(h, risk, ctx) if pid is None else _single(pid, h, ctx)


def preview(args: dict, ctx: Ctx) -> DiffItem:
    what = args.get("product_id") or "all active products"
    summary = f"Forecast demand for {what} over the next {args.get('horizon_days')} days."
    return DiffItem(step_id="", before={}, after={"read_only": True, "summary": summary})


register(SPEC, run, preview)
