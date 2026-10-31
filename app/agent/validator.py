"""Deterministic plan validator (P2-T7; spec 02 §5, R18, R46, R50).

SELECT-only reads through ctx.db, never the LLM. Caps live in app.safety.policy (R18).
"""

from __future__ import annotations

import logging
import re
from collections.abc import Callable
from dataclasses import dataclass, field

from app.agent.models import Plan, Step, Validation
from app.safety import policy  # hard import (R18): a missing guard must fail loudly
from app.tools.registry import Ctx, get_tool, validate_args

MAX_STEPS = 20
MAX_ORDER_IDS = 50
READ_TOOLS = frozenset({"list_orders", "list_inbox", "forecast_demand", "flag_anomalies"})
OWNER = "owner_request"
_EMAIL_ID = re.compile(r"^E\d+$")
log = logging.getLogger(__name__)


@dataclass
class PlanContext:
    request: str
    seen_ids: set[str] | None = None  # None: evidence must exist in the DB (validate_plan)
    blocked_ids: set[str] = field(default_factory=set)
    email_customers: dict[str, str] = field(default_factory=dict)


def _blocked(ev: str, pc: PlanContext) -> bool:
    """The guard keys verdicts as 'email:<inbox id>'; evidence cites the bare id."""
    return ev in pc.blocked_ids or f"email:{ev}" in pc.blocked_ids


def _order(ctx: Ctx, oid: str) -> tuple | None:
    return ctx.db.execute(
        "SELECT status, customer_id, refunded_cents, total_cents FROM orders WHERE id = ?", (oid,)
    ).fetchone()


def _email_customer(ctx: Ctx, pc: PlanContext, eid: str) -> str | None:
    if eid in pc.email_customers:
        return pc.email_customers[eid]
    row = ctx.db.execute(  # the sender's customer only, never the linked order's (#66)
        "SELECT c.id FROM inbox i "
        "LEFT JOIN customers c ON lower(c.email) = lower(i.from_addr) WHERE i.id = ?",
        (eid,),
    ).fetchone()
    return row[0] if row else None


def _exists_in_db(ctx: Ctx, ident: str) -> bool:
    return any(
        ctx.db.execute(f"SELECT 1 FROM {t} WHERE id = ?", (ident,)).fetchone()  # noqa: S608
        for t in ("orders", "inbox", "products", "customers")
    )


def _step_order_ids(step: Step) -> list[str]:
    a = step.args
    ids = a.get("order_ids") if isinstance(a.get("order_ids"), list) else []
    return ids + ([a["order_id"]] if isinstance(a.get("order_id"), str) else [])


def _check_evidence(step: Step, ctx: Ctx, pc: PlanContext) -> str | None:
    for ev in step.evidence:
        if ev == OWNER:
            continue
        if _blocked(ev, pc):
            return f"evidence {ev} is a blocked email"
        known = ev in pc.seen_ids if pc.seen_ids is not None else _exists_in_db(ctx, ev)
        if not known:
            return f"evidence {ev} was not in any tool result"
        if _EMAIL_ID.match(ev):  # R50: email evidence binds the step to that customer
            cust = _email_customer(ctx, pc, ev)
            owners = {r[1] for o in _step_order_ids(step) if (r := _order(ctx, o))}
            if step.args.get("customer_id"):
                owners.add(step.args["customer_id"])
            if not owners:  # R50 covers every write tool (#77)
                return "email evidence needs an order or customer; cite owner_request"
            if owners != {cust}:
                return "evidence does not match order"
    return None


def _prior_has(prior: list[Step], tool: str, oid: str) -> bool:
    return any(s.tool == tool and oid in _step_order_ids(s) for s in prior)


def _check_mark_shipped(step: Step, prior: list[Step], ctx: Ctx, pc: PlanContext) -> str | None:
    ids = step.args["order_ids"]
    if len(ids) > MAX_ORDER_IDS:
        return f"at most {MAX_ORDER_IDS} orders per step"
    for oid in ids:
        row = _order(ctx, oid)
        if row is None:
            return f"order {oid} not found in this store"
        if row[0] != "paid":
            return f"{oid} is {row[0]}, not paid"
        if _prior_has(prior, "mark_shipped", oid):
            return f"{oid} is already shipped earlier in this plan"
    return None


def _email_order_ok(template: str, oid: str, row: tuple, prior: list[Step], ctx: Ctx) -> str | None:
    if (
        template == "tracking"
        and row[0] != "shipped"
        and not _prior_has(prior, "mark_shipped", oid)
    ):
        return f"tracking email before {oid} is shipped"
    if (
        template == "refund_confirmation"
        and row[2] <= 0
        and not _prior_has(prior, "refund_order", oid)
    ):
        return f"refund confirmation before {oid} is refunded"
    if (
        template == "payment_request"
        and not _prior_has(prior, "create_payment_link", oid)
        and not ctx.db.execute(
            "SELECT 1 FROM payment_links WHERE order_id = ? AND active = 1", (oid,)
        ).fetchone()
    ):
        return f"payment request before a payment link exists for {oid}"
    return None


def _check_send_email(step: Step, prior: list[Step], ctx: Ctx, pc: PlanContext) -> str | None:
    ids, template = step.args["order_ids"], step.args["template"]
    body = step.args.get("custom_body")
    if not ids or len(ids) > MAX_ORDER_IDS:
        return f"email 1 to {MAX_ORDER_IDS} orders per step"
    if template == "custom" and not (isinstance(body, str) and body.strip()):
        return "custom email needs custom_body"
    for oid in ids:
        row = _order(ctx, oid)
        if row is None:
            return f"order {oid} not found in this store"
        err = _email_order_ok(template, oid, row, prior, ctx)
        if err:
            return err
    return None


def _refund_evidence_ok(step: Step, cust: str, ctx: Ctx, pc: PlanContext) -> bool:
    oid = step.args["order_id"]
    for ev in step.evidence:
        if ev == OWNER and re.search(rf"\b{re.escape(oid)}\b", pc.request, re.IGNORECASE):
            return True
        if _EMAIL_ID.match(ev) and not _blocked(ev, pc) and _email_customer(ctx, pc, ev) == cust:
            return True
    return False


def _check_refund_order(step: Step, prior: list[Step], ctx: Ctx, pc: PlanContext) -> str | None:
    oid, amt = step.args["order_id"], step.args.get("amount_cents")
    row = _order(ctx, oid)
    if row is None:
        return f"order {oid} not found in this store"
    status, cust, refunded, total = row
    if status not in policy.REFUNDABLE_STATUSES:
        return f"order {oid} is {status}, not refundable"
    if amt is not None and not 0 < amt <= total - refunded:
        return f"refund exceeds refundable amount (${(total - refunded) / 100:,.2f})"
    if not _refund_evidence_ok(step, cust, ctx, pc):
        return "refund needs evidence from the owner or this order's customer"
    return None


def _check_payment_link(step: Step, prior: list[Step], ctx: Ctx, pc: PlanContext) -> str | None:
    if (step.args.get("order_id") is None) == (step.args.get("customer_id") is None):
        return "payment link needs exactly one of order_id or customer_id"
    return None


def _check_restock(step: Step, prior: list[Step], ctx: Ctx, pc: PlanContext) -> str | None:
    pid = step.args["product_id"]
    if any(s.tool == "create_restock_po" and s.args.get("product_id") == pid for s in prior):
        return f"one restock PO per product per plan ({pid} already staged)"
    return None


_CHECKS: dict[str, Callable[[Step, list[Step], Ctx, PlanContext], str | None]] = {
    "mark_shipped": _check_mark_shipped,
    "send_email": _check_send_email,
    "refund_order": _check_refund_order,
    "create_payment_link": _check_payment_link,
    "create_restock_po": _check_restock,
}


def _common(step: Step, prior: list[Step]) -> str | None:
    if step.tool in READ_TOOLS:
        return "read tools are not plan steps"
    try:
        get_tool(step.tool)
    except KeyError:
        return "unknown tool"
    err = validate_args(step.tool, step.args)
    if err:
        return err
    if len(prior) >= MAX_STEPS:
        return f"too many steps (max {MAX_STEPS})"
    if any(p.tool == step.tool and p.args == step.args for p in prior):
        return "duplicate step"
    return None


def _reason(step: Step, prior: list[Step], ctx: Ctx, pc: PlanContext) -> str | None:
    err = _common(step, prior) or _check_evidence(step, ctx, pc)
    check = _CHECKS.get(step.tool)
    err = err or (check(step, prior, ctx, pc) if check else None)
    if err:
        return err
    return policy.check_plan(Plan(request=pc.request, steps=[step]), ctx)[0].reason


def validate_step(step: Step, prior: list[Step], ctx: Ctx, pc: PlanContext) -> Validation:
    try:
        reason = _reason(step, prior, ctx, pc)
    except Exception:  # noqa: BLE001 - fail closed, never raise from validation
        log.exception("validate_step crashed for step %s (%s)", step.id, step.tool)
        reason = "validation failed"
    return Validation(step_id=step.id, ok=reason is None, reason=reason)


def _plan_context(plan: Plan, ctx: Ctx) -> PlanContext:
    blocked = {str(b.get("source_id")) for b in plan.blocked_inputs if not b.get("allowed")}
    allowed = {
        r[0]
        for r in ctx.db.execute("SELECT source_id FROM guard_verdicts WHERE allowed = 1").fetchall()
    }
    pc = PlanContext(request=plan.request, seen_ids=None, blocked_ids=blocked)
    for (eid,) in ctx.db.execute("SELECT id FROM inbox").fetchall():
        if f"email:{eid}" not in allowed:  # unscreened or blocked: fail closed (#56)
            blocked.add(f"email:{eid}")
        cust = _email_customer(ctx, pc, eid)
        if cust:
            pc.email_customers[eid] = cust
    return pc


def validate_plan(plan: Plan, ctx: Ctx) -> list[Validation]:
    """One Validation per step, plan order; plan-level policy caps fill the remaining slots."""
    pc = _plan_context(plan, ctx)
    caps = policy.check_plan(plan, ctx)  # first, so a capped step unlocks nothing (#55)
    out: list[Validation] = []
    accepted: list[Step] = []  # rejected steps never run, so they satisfy no dependency
    for s, pv in zip(plan.steps, caps, strict=True):
        v = validate_step(s, accepted, ctx, pc)
        if v.ok and not pv.ok:
            v = pv
        out.append(v)
        if v.ok:
            accepted.append(s)
    return out
