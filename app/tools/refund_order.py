"""refund_order tool (P5-I6). destructive+moves_money, irreversible: no undo (R6, R38).

No commit, no log_action (R23). Stripe metadata/keys use session_hash, never the raw id (R20/R21).
"""
from __future__ import annotations

import secrets
import sqlite3
from datetime import timedelta

from app.agent.models import DiffItem
from app.config import get_settings
from app.db import session_hash
from app.integrations import stripe_client
from app.safety.policy import REFUND_CAP_PER_ORDER_CENTS, REFUND_WINDOW_DAYS, REFUNDABLE_STATUSES
from app.tools.create_payment_link import _writes_used
from app.tools.registry import Ctx, ToolResult, ToolSpec, register

IRREVERSIBLE_REASON = "card refunds cannot be reversed via API"

SPEC = ToolSpec(
    name="refund_order",
    description=("Refund one order through Stripe test mode. amount_cents null means the full "
                 "refundable amount. Irreversible."),
    destructive=True, moves_money=True, undoable=False,
    input_schema={
        "type": "object", "additionalProperties": False,
        "required": ["order_id", "amount_cents", "reason"],
        "properties": {
            "order_id": {"type": "string"},
            "amount_cents": {"anyOf": [{"type": "integer"}, {"type": "null"}]},
            "reason": {"type": "string",
                       "enum": ["duplicate", "fraudulent", "requested_by_customer"]},
        },
    },
)


def _fail(error: str, summary: str) -> ToolResult:
    return ToolResult(ok=False, summary=summary, error=error)


def _load(ctx: Ctx, oid: str) -> dict | None:
    row = ctx.db.execute(
        "SELECT status, total_cents, refunded_cents, created_at, stripe_payment_intent_id"
        " FROM orders WHERE id=?", (oid,)).fetchone()
    keys = ("status", "total", "refunded", "created_at", "pi")
    return dict(zip(keys, tuple(row), strict=True)) if row else None


def _checks(args: dict, o: dict | None, ctx: Ctx) -> tuple[int, ToolResult | None]:
    """Returns (amount, failure). Mirrors policy._check_refund with machine-readable codes."""
    oid = args["order_id"]
    if o is None:
        return 0, _fail("not_found", f"Unknown order {oid}.")
    remaining = o["total"] - o["refunded"]
    if o["status"] == "refunded" or remaining <= 0:
        return 0, _fail("already_refunded", "Order already fully refunded.")
    if o["status"] not in REFUNDABLE_STATUSES:
        return 0, _fail("not_refundable", f"Order {oid} is {o['status']}, not refundable.")
    if str(o["created_at"])[:10] < (ctx.today - timedelta(days=REFUND_WINDOW_DAYS)).isoformat():
        return 0, _fail("outside_window",
                        f"Order {oid} is older than {REFUND_WINDOW_DAYS} days: refund manually.")
    amount = remaining if args["amount_cents"] is None else args["amount_cents"]
    if amount <= 0:
        return 0, _fail("bad_amount", "Refund amount must be positive.")
    if amount > remaining:
        return 0, _fail("amount_exceeds_refundable",
                        "Refund larger than what is left on the charge.")
    if amount > REFUND_CAP_PER_ORDER_CENTS:
        return 0, _fail("over_cap", f"Refunds over ${REFUND_CAP_PER_ORDER_CENTS // 100} "
                                    "per order are blocked: refund manually in Stripe.")
    cap = get_settings().stripe_max_writes_per_session
    if _writes_used(ctx) + 1 + (o["pi"] is None) > cap:
        return 0, _fail("stripe_cap_reached",
                        f"Demo limit: {cap} Stripe actions per session. "
                        "Reset the store to continue.")
    return amount, None


def _record(ctx: Ctx, oid: str, o: dict, amount: int, reason: str, re: dict, mode: str) -> bool:
    """Insert refund row then update order. Returns False if re_ id was already recorded."""
    try:
        ctx.db.execute(
            "INSERT INTO refunds (id, order_id, amount_cents, reason, stripe_refund_id, mode,"
            " created_at) VALUES (?,?,?,?,?,?,?)",
            ("rf_" + secrets.token_hex(6), oid, amount, reason, re["id"], mode,
             ctx.now.isoformat()))
    except sqlite3.IntegrityError:
        return False  # statement-level atomic: nothing written
    new_refunded = o["refunded"] + amount
    status = "refunded" if new_refunded >= o["total"] else o["status"]
    ctx.db.execute("UPDATE orders SET refunded_cents=?, status=? WHERE id=?",
                   (new_refunded, status, oid))
    return True


def run(args: dict, ctx: Ctx) -> ToolResult:
    oid, reason = args["order_id"], args["reason"]
    o = _load(ctx, oid)
    amount, err = _checks(args, o, ctx)
    if err:
        return err
    sh = session_hash(ctx.session_id)
    n_prior = ctx.db.execute("SELECT COUNT(*) FROM refunds WHERE order_id=?", (oid,)).fetchone()[0]
    try:
        pi = o["pi"] or stripe_client.ensure_payment_intent(sh, oid, o["total"])
        re = stripe_client.refund(pi, amount, reason, f"refund:{sh}:{oid}:{n_prior}:{amount}")
    except stripe_client.StripeFailure as e:
        return _fail(e.code, e.user_message)
    if o["pi"] is None:
        ctx.db.execute("UPDATE orders SET stripe_payment_intent_id=? WHERE id=?", (pi, oid))
    mode = stripe_client.mode()
    fresh = _record(ctx, oid, o, amount, reason, re, mode)
    label = "[MOCK] Refunded" if mode == "mock" else "Refunded"
    return ToolResult(
        ok=True,
        summary=f"{label} ${amount / 100:.2f} on order {oid} (Stripe {mode.upper()} {re['id']})"
                + ("" if fresh else " - already recorded"),
        data={"stripe_refund_id": re["id"], "payment_intent_id": pi, "amount_cents": amount,
              "mode": mode, "undoable": False, "irreversible_reason": IRREVERSIBLE_REASON,
              "duplicate": not fresh})


def preview(args: dict, ctx: Ctx) -> DiffItem:
    o = _load(ctx, args["order_id"]) or {"status": None, "total": 0, "refunded": 0}
    amount = args["amount_cents"]
    amount = o["total"] - o["refunded"] if amount is None else amount
    after_refunded = o["refunded"] + amount
    return DiffItem(
        step_id="",
        before={"order_id": args["order_id"], "refunded_cents": o["refunded"],
                "status": o["status"]},
        after={"refunded_cents": after_refunded,
               "status": "refunded" if o["total"] and after_refunded >= o["total"] else o["status"],
               "irreversible": True, "stripe_mode": stripe_client.mode()},
        amount_cents=amount)


register(SPEC, run, preview, None)
