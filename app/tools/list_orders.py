"""list_orders read tool (P2-T6, spec 02 §4.8). Never returns orders.note (R24)."""

from __future__ import annotations

from app.agent.models import DiffItem
from app.tools.registry import Ctx, ToolResult, ToolSpec, register

MAX_ROWS = 50
STATUSES = ("any", "paid", "shipped", "refunded")
_DATE = {"anyOf": [{"type": "string", "format": "date"}, {"type": "null"}]}

SPEC = ToolSpec(
    name="list_orders",
    description=(
        "Read orders: filter by status, inclusive created date range, or exact ids. "
        "At most 50, newest first. Read-only."
    ),
    destructive=False,
    moves_money=False,
    undoable=False,
    input_schema={
        "type": "object",
        "additionalProperties": False,
        "required": ["status", "created_from", "created_to", "order_ids"],
        "properties": {
            "status": {"type": "string", "enum": list(STATUSES)},
            "created_from": _DATE,
            "created_to": _DATE,
            "order_ids": {
                "anyOf": [{"type": "array", "items": {"type": "string"}}, {"type": "null"}]
            },
        },
    },
)

_COLS = (
    "SELECT o.id, o.created_at, o.status, o.customer_id, c.name, c.email, o.total_cents,"
    " o.refunded_cents, o.carrier, o.tracking_number FROM orders o"
    " JOIN customers c ON c.id = o.customer_id"
)
_KEYS = (
    "id",
    "created_at",
    "status",
    "customer_id",
    "customer_name",
    "customer_email",
    "total_cents",
    "refunded_cents",
    "carrier",
    "tracking_number",
)


def _bad(args: dict) -> bool:
    ids = args.get("order_ids")
    dates = (args.get("created_from"), args.get("created_to"))
    return (
        args.get("status") not in STATUSES
        or not all(d is None or isinstance(d, str) for d in dates)
        or not (ids is None or (isinstance(ids, list) and all(isinstance(i, str) for i in ids)))
    )


def _where(args: dict) -> tuple[str, list]:
    clauses, params = [], []
    if args["status"] != "any":
        clauses.append("o.status = ?")
        params.append(args["status"])
    if args.get("created_from"):
        clauses.append("substr(o.created_at, 1, 10) >= ?")
        params.append(args["created_from"])
    if args.get("created_to"):
        clauses.append("substr(o.created_at, 1, 10) <= ?")
        params.append(args["created_to"])
    ids = args.get("order_ids")
    if ids is not None:
        clauses.append(f"o.id IN ({','.join('?' * len(ids))})" if ids else "0")
        params.extend(ids)
    return (" WHERE " + " AND ".join(clauses)) if clauses else "", params


def _items(ctx: Ctx, oid: str) -> list[dict]:
    rows = ctx.db.execute(
        "SELECT i.product_id, p.name, i.qty, i.unit_price_cents FROM order_items i"
        " JOIN products p ON p.id = i.product_id WHERE i.order_id = ? ORDER BY i.product_id",
        (oid,),
    )
    return [
        dict(zip(("product_id", "name", "qty", "unit_price_cents"), r, strict=True)) for r in rows
    ]


def run(args: dict, ctx: Ctx) -> ToolResult:
    if not isinstance(args, dict) or _bad(args):
        return ToolResult(ok=False, summary="Invalid list_orders arguments.", error="invalid")
    where, params = _where(args)
    rows = ctx.db.execute(
        f"{_COLS}{where} ORDER BY o.created_at DESC, o.id DESC LIMIT ?", (*params, MAX_ROWS + 1)
    ).fetchall()
    orders = [
        {**dict(zip(_KEYS, r, strict=True)), "items": _items(ctx, r[0])} for r in rows[:MAX_ROWS]
    ]
    return ToolResult(
        ok=True,
        summary=f"{len(orders)} orders",
        data={"orders": orders, "truncated": len(rows) > MAX_ROWS},
    )


def preview(args: dict, ctx: Ctx) -> DiffItem:
    return DiffItem(step_id="", before={}, after={})


register(SPEC, run, preview)
