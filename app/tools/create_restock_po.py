"""create_restock_po tool (P3-ML-4). Destructive, not money, undoable (R6); no commit/log (R23)."""

from __future__ import annotations

import json
import secrets
from datetime import timedelta

from app.agent.models import DiffItem
from app.ml import forecast
from app.safety.policy import RESTOCK_QTY_MAX, RESTOCK_QTY_MIN
from app.tools.registry import Ctx, ToolResult, ToolSpec, register

SPEC = ToolSpec(
    name="create_restock_po",
    description=(
        "Create a purchase order. Use qty_source='forecast' unless the user stated an exact "
        "number. qty must be null for 'forecast' (the app uses the forecast's reorder quantity) "
        f"and {RESTOCK_QTY_MIN}-{RESTOCK_QTY_MAX} for 'user'. Undo cancels an open PO."
    ),
    destructive=True,
    moves_money=False,
    undoable=True,
    input_schema={
        "type": "object",
        "additionalProperties": False,
        "required": ["product_id", "qty_source", "qty"],
        "properties": {
            "product_id": {"type": "string"},
            "qty_source": {"type": "string", "enum": ["forecast", "user"]},
            "qty": {"anyOf": [{"type": "integer"}, {"type": "null"}]},
        },
    },
)


def _resolve_qty(args: dict, ctx: Ctx) -> tuple[int, dict]:
    """(qty, forecast). Shared by preview and run so they cannot disagree. Raises ValueError."""
    src, qty, pid = args.get("qty_source"), args.get("qty"), args.get("product_id")
    if not isinstance(pid, str):
        raise ValueError("product_id must be a string")
    if src not in ("forecast", "user"):
        raise ValueError("qty_source must be 'forecast' or 'user'")
    if src == "forecast" and qty is not None:
        raise ValueError("qty must be null when qty_source is forecast")
    if src == "user" and (
        not isinstance(qty, int)
        or isinstance(qty, bool)
        or not RESTOCK_QTY_MIN <= qty <= RESTOCK_QTY_MAX
    ):
        raise ValueError(f"restock qty must be {RESTOCK_QTY_MIN} to {RESTOCK_QTY_MAX}")
    f = forecast.forecast_demand(pid, ctx)  # ValueError("unknown product")
    if src == "user":
        return qty, f
    rq = f["reorder_qty"]
    if rq is None:
        raise ValueError(f["explanation"])  # insufficient history: asks for a quantity
    if rq == 0:
        prefix = "already covered by open PO: " if f["on_order"] > 0 else ""
        raise ValueError(prefix + f["explanation"])
    if rq > RESTOCK_QTY_MAX:  # spec 03 §3.3: PO qty == reorder_qty, never a silent clamp
        raise ValueError(
            f"forecast suggests {rq} units, over the {RESTOCK_QTY_MAX} cap; give a quantity"
        )
    return rq, f


def _arrives_on(f: dict, ctx: Ctx) -> str:
    return (ctx.today + timedelta(days=f["lead_time_days"])).isoformat()


def _fail(error: str) -> ToolResult:
    return ToolResult(ok=False, summary=f"Restock not created: {error}", error=error)


def run(args: dict, ctx: Ctx) -> ToolResult:
    try:
        qty, f = _resolve_qty(args, ctx)
    except ValueError as e:
        return _fail(str(e))
    po_id = "po_" + secrets.token_hex(6)
    cost = f["unit_cost_cents"]
    ctx.db.execute(
        "INSERT INTO purchase_orders (id, product_id, qty, unit_cost_cents, status,"
        " forecast_json, created_at, expected_at) VALUES (?,?,?,?, 'open', ?,?,?)",
        (
            po_id,
            f["product_id"],
            qty,
            cost,
            json.dumps(f),
            ctx.now.isoformat(),
            _arrives_on(f, ctx),
        ),
    )
    amount = qty * cost
    return ToolResult(
        ok=True,
        summary=(
            f"Created PO {po_id}: {qty} x {f['name']} (${amount / 100:,.2f}),"
            f" arrives {_arrives_on(f, ctx)}."
        ),
        data={
            "po_id": po_id,
            "product_id": f["product_id"],
            "qty": qty,
            "unit_cost_cents": cost,
            "amount_cents": amount,
        },
        undo_token=json.dumps({"po_id": po_id, "status": "open"}),
    )


def preview(args: dict, ctx: Ctx) -> DiffItem:
    try:
        qty, f = _resolve_qty(args, ctx)
    except ValueError as e:
        return DiffItem(step_id="", before={}, after={"error": str(e)})
    cost = f["unit_cost_cents"]
    return DiffItem(
        step_id="",
        before={
            "product": f["name"],
            "on_hand": f["on_hand"],
            "on_order": f["on_order"],
            "days_to_stockout": f["days_to_stockout"],
            "forecast": f,
        },
        after={
            "po": "new",
            "qty": qty,
            "unit_cost_cents": cost,
            "arrives_on": _arrives_on(f, ctx),
            "status": "open",
        },
        amount_cents=qty * cost,
    )


def undo(token: str, ctx: Ctx) -> ToolResult:
    try:
        tok = json.loads(token)
        po_id, post = tok["po_id"], tok["status"]
    except (TypeError, ValueError, KeyError):
        return _fail("bad undo token")
    row = ctx.db.execute("SELECT status FROM purchase_orders WHERE id=?", (po_id,)).fetchone()
    if row is None or row[0] != post:  # R22: live row no longer equals post state
        return ToolResult(
            ok=False,
            error="changed_since",
            summary=f"PO {po_id} is no longer open, so it cannot be cancelled.",
        )
    ctx.db.execute("UPDATE purchase_orders SET status='cancelled' WHERE id=?", (po_id,))
    return ToolResult(ok=True, summary=f"Cancelled PO {po_id}.", data={"po_id": po_id})


register(SPEC, run, preview, undo)
