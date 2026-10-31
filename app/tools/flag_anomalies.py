"""flag_anomalies tool (P3-ML-5). Read-only wrapper over app.ml.anomaly; never does math itself."""

from __future__ import annotations

from app.agent.models import DiffItem
from app.ml import anomaly
from app.tools.registry import Ctx, ToolResult, ToolSpec, register

MAX_LIMIT = 50

SPEC = ToolSpec(
    name="flag_anomalies",
    description=(
        "Find suspicious orders (price glitches, bulk orders, order bursts, country mismatch) "
        "placed in the last since_days days (1-90; 7 = this week), top `limit` (1-50) by score. "
        "Read-only. Quote each `reason` verbatim; never compute scores yourself."
    ),
    destructive=False,
    moves_money=False,
    undoable=False,
    input_schema={
        "type": "object",
        "additionalProperties": False,
        "required": ["since_days", "limit"],
        "properties": {"since_days": {"type": "integer"}, "limit": {"type": "integer"}},
    },
)


def _int_in(v, lo: int, hi: int) -> bool:
    return isinstance(v, int) and not isinstance(v, bool) and lo <= v <= hi


def _window(days: int) -> str:
    return "this week" if days == 7 else f"in the last {days} days"


def run(args: dict, ctx: Ctx) -> ToolResult:
    days, limit = args.get("since_days"), args.get("limit")
    if not _int_in(days, 1, anomaly.MAX_SINCE_DAYS) or not _int_in(limit, 1, MAX_LIMIT):
        return ToolResult(
            ok=False, summary="since_days must be 1-90 and limit 1-50", error="invalid"
        )
    empty = {"items": [], "total_flagged": 0, "threshold": anomaly.THRESHOLD}
    try:
        items = anomaly.flag_anomalies(ctx, since_days=days)
    except anomaly.InsufficientData:
        return ToolResult(ok=True, summary="too few orders to judge", data=empty)
    except ValueError as e:
        return ToolResult(ok=False, summary=f"Anomaly scan failed: {e}", error="invalid")
    if not items:
        return ToolResult(ok=True, summary=f"No suspicious orders {_window(days)}.", data=empty)
    top = items[0]
    summary = (
        f"{len(items)} suspicious orders {_window(days)}; top: {top['order_id']} — {top['reason']}"
    )
    return ToolResult(
        ok=True,
        summary=summary,
        data={**empty, "items": items[:limit], "total_flagged": len(items)},
    )


def preview(args: dict, ctx: Ctx) -> DiffItem:
    summary = (
        f"Scan orders from the last {args.get('since_days')} days for anomalies "
        f"(show top {args.get('limit')})."
    )
    return DiffItem(step_id="", before={}, after={"read_only": True, "summary": summary})


register(SPEC, run, preview)
