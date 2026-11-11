"""sales_by_product read tool: units, revenue and order count per product from one GROUP BY."""

from __future__ import annotations

import re

from app.agent.models import DiffItem
from app.tools.registry import Ctx, ToolResult, ToolSpec, register

MAX_LIMIT = 50
DEFAULT_LIMIT = 10
SORTS = {"units": "units DESC", "revenue": "revenue_cents DESC"}
# Sold = paid or shipped. Refunded, cancelled and on-hold orders are not sales.
# shortcut: partial refunds on a paid/shipped order still count in full; split per line if needed.
SOLD = ("paid", "shipped")
_DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")
_DATE = {"anyOf": [{"type": "string", "format": "date"}, {"type": "null"}]}

SPEC = ToolSpec(
    name="sales_by_product",
    description=(
        "Sales per product (paid and shipped orders) in an inclusive created date range: "
        "units, revenue_cents and order count, sorted by units or revenue, top `limit` (1-50). "
        "Read-only."
    ),
    destructive=False,
    moves_money=False,
    undoable=False,
    input_schema={
        "type": "object",
        "additionalProperties": False,
        "required": ["created_from", "created_to", "sort_by", "limit"],
        "properties": {
            "created_from": _DATE,
            "created_to": _DATE,
            "sort_by": {"type": "string", "enum": list(SORTS)},
            "limit": {"anyOf": [{"type": "integer"}, {"type": "null"}]},
        },
    },
)

_FROM = (
    " FROM order_items i JOIN orders o ON o.id = i.order_id"
    " JOIN products p ON p.id = i.product_id"
    f" WHERE o.status IN ({','.join('?' * len(SOLD))})"
)


def _bad(args: dict) -> bool:
    dates = (args.get("created_from"), args.get("created_to"))
    limit = args.get("limit")
    return (
        args.get("sort_by") not in SORTS
        or not all(d is None or (isinstance(d, str) and _DATE_RE.fullmatch(d)) for d in dates)
        or not (
            limit is None
            or (isinstance(limit, int) and not isinstance(limit, bool) and 1 <= limit <= MAX_LIMIT)
        )
    )


def _where(args: dict) -> tuple[str, list]:
    sql, params = _FROM, list(SOLD)
    if args.get("created_from"):
        sql += " AND substr(o.created_at, 1, 10) >= ?"
        params.append(args["created_from"])
    if args.get("created_to"):
        sql += " AND substr(o.created_at, 1, 10) <= ?"
        params.append(args["created_to"])
    return sql, params


def run(args: dict, ctx: Ctx) -> ToolResult:
    if not isinstance(args, dict) or _bad(args):
        return ToolResult(ok=False, summary="Invalid sales_by_product arguments.", error="invalid")
    where, params = _where(args)
    limit = args.get("limit") or DEFAULT_LIMIT
    rows = ctx.db.execute(
        "SELECT p.id, p.sku, p.name, SUM(i.qty) AS units,"
        " SUM(i.qty * i.unit_price_cents) AS revenue_cents, COUNT(DISTINCT o.id)"
        f"{where} GROUP BY p.id ORDER BY {SORTS[args['sort_by']]}, p.id LIMIT ?",
        (*params, limit),
    ).fetchall()
    first, last, n_orders = ctx.db.execute(
        f"SELECT MIN(substr(o.created_at, 1, 10)), MAX(substr(o.created_at, 1, 10)),"
        f" COUNT(DISTINCT o.id){where}",
        params,
    ).fetchone()
    keys = ("product_id", "sku", "name", "units", "revenue_cents", "orders")
    products = [dict(zip(keys, r, strict=True)) for r in rows]
    return ToolResult(
        ok=True,
        summary=f"{len(products)} products",
        data={
            "products": products,
            "range": {
                "from": args.get("created_from") or first,
                "to": args.get("created_to") or last,
            },
            "orders_counted": n_orders,
            "sort_by": args["sort_by"],
        },
    )


def preview(args: dict, ctx: Ctx) -> DiffItem:
    return DiffItem(step_id="", before={}, after={})


register(SPEC, run, preview)
