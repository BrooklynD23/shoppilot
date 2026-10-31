"""Hard business policy enforced outside the LLM (P4-T2; spec 04 §5, R18/R19/R37/R46).

Single source of every cap (R18). Called at validate time and again at execute time.
Never raises on bad args: every problem becomes a Validation reason.
"""
from __future__ import annotations

import json
from collections.abc import Callable
from datetime import timedelta

from app.agent.models import Plan, Step, Validation
from app.tools.registry import Ctx, ToolSpec, get_tool, get_tools, validate_args

MAX_STEPS_PER_PLAN = 20
MAX_REFUNDS_PER_PLAN = 3
REFUND_CAP_PER_ORDER_CENTS = 20_000
REFUND_CAP_PER_PLAN_CENTS = 50_000
REFUND_WINDOW_DAYS = 30
REFUNDS_PER_SESSION_HOUR = 5
REFUND_CENTS_PER_SESSION_HOUR = 100_000
DESTRUCTIVE_STEPS_PER_SESSION_HOUR = 30
MAX_EMAILS_PER_PLAN = 20
MAX_EMAIL_ORDER_IDS = 50
EMAIL_BODY_MAX_CHARS = 2_000
PAYMENT_LINK_MIN_CENTS = 50
PAYMENT_LINK_MAX_CENTS = 100_000
RESTOCK_QTY_MIN = 1
RESTOCK_QTY_MAX = 500

REFUNDABLE_STATUSES = ("paid", "shipped")
_ID_TABLES = {"order_id": ("orders", "order"), "order_ids": ("orders", "order"),
              "customer_id": ("customers", "customer"), "product_id": ("products", "product")}


def _usd(cents: int) -> str:
    return f"${cents / 100:,.2f}"


def needs_confirmation(spec: ToolSpec) -> bool:
    return spec.destructive or spec.moves_money


def refundable_cents(ctx: Ctx, order_id: str) -> int:
    row = ctx.db.execute("SELECT total_cents - refunded_cents FROM orders WHERE id = ?",
                         (order_id,)).fetchone()
    return int(row[0]) if row else 0


def _is_int(x: object) -> bool:
    return isinstance(x, int) and not isinstance(x, bool)


def _missing_ids(args: dict, ctx: Ctx) -> str | None:
    for key, (table, label) in _ID_TABLES.items():
        val = args.get(key)
        ids = val if isinstance(val, list) else [] if val is None else [val]
        for i in ids:
            if not isinstance(i, str) or not ctx.db.execute(
                    f"SELECT 1 FROM {table} WHERE id = ?", (i,)).fetchone():  # noqa: S608
                return f"{label} {i} not found in this store"
    return None


def _refund_amount(step: Step, ctx: Ctx) -> int:
    amt = step.args.get("amount_cents")
    return amt if _is_int(amt) else refundable_cents(ctx, step.args["order_id"])


def _check_refund(step: Step, ctx: Ctx) -> str | None:
    oid = step.args["order_id"]
    status, created = ctx.db.execute(
        "SELECT status, created_at FROM orders WHERE id = ?", (oid,)).fetchone()
    if status not in REFUNDABLE_STATUSES:
        return f"order {oid} is {status}, not refundable"
    if str(created)[:10] < (ctx.today - timedelta(days=REFUND_WINDOW_DAYS)).isoformat():
        return f"order {oid} is older than {REFUND_WINDOW_DAYS} days: refund manually in Stripe"
    remaining = refundable_cents(ctx, oid)
    if remaining <= 0:
        return f"order {oid} is already fully refunded"
    amt = _refund_amount(step, ctx)
    if not 1 <= amt <= remaining:
        return f"refund amount must be 1 to {remaining} cents for order {oid}"
    if amt > REFUND_CAP_PER_ORDER_CENTS:
        return f"over {_usd(REFUND_CAP_PER_ORDER_CENTS)[:-3]}: refund manually in Stripe"
    return None


def _check_email(step: Step, ctx: Ctx) -> str | None:
    if len(step.args["order_ids"]) > MAX_EMAIL_ORDER_IDS:
        return f"email at most {MAX_EMAIL_ORDER_IDS} orders per step"
    body = step.args.get("custom_body")
    if isinstance(body, str) and len(body) > EMAIL_BODY_MAX_CHARS:
        return f"custom_body over {EMAIL_BODY_MAX_CHARS:,} characters"
    return None


def _check_mark_shipped(step: Step, ctx: Ctx) -> str | None:
    for oid in step.args["order_ids"]:
        (status,) = ctx.db.execute("SELECT status FROM orders WHERE id = ?", (oid,)).fetchone()
        if status != "paid":
            return f"order {oid} is {status}, only paid orders can be shipped"
    return None


def _check_restock(step: Step, ctx: Ctx) -> str | None:
    src, qty = step.args.get("qty_source"), step.args.get("qty")
    if src == "forecast":
        return None if qty is None else "qty must be null when qty_source is forecast"
    if not _is_int(qty) or not RESTOCK_QTY_MIN <= qty <= RESTOCK_QTY_MAX:
        return f"restock qty must be {RESTOCK_QTY_MIN} to {RESTOCK_QTY_MAX}"
    return None


def _check_payment_link(step: Step, ctx: Ctx) -> str | None:
    amt = step.args.get("amount_cents")
    if not _is_int(amt) or not PAYMENT_LINK_MIN_CENTS <= amt <= PAYMENT_LINK_MAX_CENTS:
        return (f"payment link must be {_usd(PAYMENT_LINK_MIN_CENTS)} to "
                f"{_usd(PAYMENT_LINK_MAX_CENTS)}")
    return None


_CHECKERS: dict[str, Callable[[Step, Ctx], str | None]] = {
    "refund_order": _check_refund, "send_email": _check_email,
    "mark_shipped": _check_mark_shipped, "create_restock_po": _check_restock,
    "create_payment_link": _check_payment_link,
}


def _check_step(step: Step, ctx: Ctx) -> str | None:
    try:
        get_tool(step.tool)
    except KeyError:
        return "unknown tool"
    try:
        err = validate_args(step.tool, step.args)
        if err:
            return f"invalid arguments: {err}"
        checker = _CHECKERS.get(step.tool)
        return _missing_ids(step.args, ctx) or (checker(step, ctx) if checker else None)
    except Exception:  # noqa: BLE001 - fail closed, never raise from policy
        return "policy check failed"


def _recent_executes(ctx: Ctx) -> list[tuple[str | None, dict]]:
    since = (ctx.now - timedelta(seconds=3600)).strftime("%Y-%m-%dT%H:%M:%SZ")
    out = []
    for tool, body in ctx.db.execute(
            "SELECT tool, payload_json FROM audit_log WHERE kind = 'execute' AND ts >= ?",
            (since,)).fetchall():
        try:
            payload = json.loads(body)
        except (TypeError, ValueError):
            payload = {}
        payload = payload if isinstance(payload, dict) else {}
        if payload.get("ok") is not False:
            out.append((tool, payload))
    return out


def _session_hour(plan: Plan, ctx: Ctx, reasons: list[str | None]) -> None:
    recent = _recent_executes(ctx)
    destructive = {s.name for s in get_tools() if s.destructive}
    n_destr = sum(1 for t, _ in recent if t in destructive)
    refunds = [p for t, p in recent if t == "refund_order"]
    n_ref = len(refunds)
    cents = sum(p["amount_cents"] for p in refunds if _is_int(p.get("amount_cents")))
    for i, s in enumerate(plan.steps):
        if reasons[i] is None and s.tool == "refund_order":
            amt = _refund_amount(s, ctx)
            if n_ref + 1 > REFUNDS_PER_SESSION_HOUR or cents + amt > REFUND_CENTS_PER_SESSION_HOUR:
                reasons[i] = (f"session limit: at most {REFUNDS_PER_SESSION_HOUR} refunds and "
                              f"{_usd(REFUND_CENTS_PER_SESSION_HOUR)} per hour")
                continue
            n_ref, cents = n_ref + 1, cents + amt
        if reasons[i] is None and s.tool in destructive:
            if n_destr + 1 > DESTRUCTIVE_STEPS_PER_SESSION_HOUR:
                reasons[i] = (f"session limit: at most {DESTRUCTIVE_STEPS_PER_SESSION_HOUR} "
                              "destructive steps per hour")
            else:
                n_destr += 1


def _override(plan: Plan, reasons: list[str | None], tool: str | None, reason: str) -> None:
    for i, s in enumerate(plan.steps):
        if tool is None or s.tool == tool:
            reasons[i] = reason


def _plan_caps(plan: Plan, ctx: Ctx, reasons: list[str | None]) -> None:
    seen: set[str] = set()
    for i, s in enumerate(plan.steps):  # duplicate refunds: first one stands
        if s.tool == "refund_order" and reasons[i] is None:
            oid = s.args["order_id"]
            if oid in seen:
                reasons[i] = f"order {oid} is already refunded earlier in this plan"
            seen.add(oid)
    refund_idx = [i for i, s in enumerate(plan.steps) if s.tool == "refund_order"]
    total = sum(_refund_amount(plan.steps[i], ctx) for i in refund_idx if reasons[i] is None)
    if len(plan.steps) > MAX_STEPS_PER_PLAN:
        _override(plan, reasons, None, f"plan has more than {MAX_STEPS_PER_PLAN} steps")
    elif len(refund_idx) > MAX_REFUNDS_PER_PLAN:
        _override(plan, reasons, "refund_order",
                  f"bulk refund blocked; refund at most {MAX_REFUNDS_PER_PLAN} orders per plan")
    elif total > REFUND_CAP_PER_PLAN_CENTS:
        _override(plan, reasons, "refund_order",
                  f"refunds total over {_usd(REFUND_CAP_PER_PLAN_CENTS)} in one plan: blocked")
    if sum(1 for s in plan.steps if s.tool == "send_email") > MAX_EMAILS_PER_PLAN:
        _override(plan, reasons, "send_email",
                  f"at most {MAX_EMAILS_PER_PLAN} email steps per plan")


def check_plan(plan: Plan, ctx: Ctx) -> list[Validation]:
    """One Validation per step, same order. Plan-level caps override per-step reasons."""
    reasons = [_check_step(s, ctx) for s in plan.steps]
    try:
        _plan_caps(plan, ctx, reasons)
        _session_hour(plan, ctx, reasons)
    except Exception:  # noqa: BLE001 - fail closed
        reasons = ["policy check failed"] * len(plan.steps)
    return [Validation(step_id=s.id, ok=r is None, reason=r)
            for s, r in zip(plan.steps, reasons, strict=True)]
