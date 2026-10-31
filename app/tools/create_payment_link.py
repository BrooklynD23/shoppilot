"""create_payment_link tool (P5-I7). destructive+moves_money+undoable (R6); no commit/log (R23)."""
from __future__ import annotations

import json
import secrets

from app.agent.models import DiffItem
from app.config import get_settings
from app.db import session_hash
from app.integrations import stripe_client
from app.tools.registry import Ctx, ToolResult, ToolSpec, register

MIN_CENTS, MAX_CENTS = 50, 100_000
MAX_DESC = 200
_NULL_STR = {"anyOf": [{"type": "string"}, {"type": "null"}]}

SPEC = ToolSpec(
    name="create_payment_link",
    description=("Create a Stripe test-mode payment link for exactly one order or customer "
                 "($0.50-$1,000). Undo deactivates the link."),
    destructive=True, moves_money=True, undoable=True,
    input_schema={
        "type": "object", "additionalProperties": False,
        "required": ["order_id", "customer_id", "amount_cents", "description"],
        "properties": {
            "order_id": _NULL_STR, "customer_id": _NULL_STR,
            "amount_cents": {"type": "integer"}, "description": {"type": "string"},
        },
    },
)


def _fail(error: str, summary: str) -> ToolResult:
    return ToolResult(ok=False, summary=summary, error=error)


def _writes_used(ctx: Ctx) -> int:
    """Stripe writes this session: refunds (not seeded) + links + PaymentIntents (spec §11)."""
    return ctx.db.execute(
        "SELECT (SELECT COUNT(*) FROM refunds WHERE stripe_refund_id NOT LIKE 're_seed_%')"
        " + (SELECT COUNT(*) FROM payment_links)"
        " + (SELECT COUNT(*) FROM orders WHERE stripe_payment_intent_id IS NOT NULL)"
    ).fetchone()[0]


def _check(args: dict, ctx: Ctx) -> ToolResult | None:
    oid, cid = args["order_id"], args["customer_id"]
    if (oid is None) == (cid is None):
        return _fail("bad_target", "Give exactly one of order_id or customer_id.")
    if not MIN_CENTS <= args["amount_cents"] <= MAX_CENTS:
        return _fail("bad_amount", "Payment link amount must be between $0.50 and $1,000.")
    if not 0 < len(args["description"].strip()) <= MAX_DESC:
        return _fail("bad_description", f"Description must be 1-{MAX_DESC} characters.")
    table, tid = ("orders", oid) if oid else ("customers", cid)
    if not ctx.db.execute(f"SELECT 1 FROM {table} WHERE id=?", (tid,)).fetchone():  # noqa: S608
        return _fail("not_found", f"Unknown {table[:-1]} {tid}.")
    cap = get_settings().stripe_max_writes_per_session
    if _writes_used(ctx) >= cap:
        return _fail("stripe_cap_reached",
                     f"Demo limit: {cap} Stripe actions per session. Reset the store to continue.")
    return None


def run(args: dict, ctx: Ctx) -> ToolResult:
    err = _check(args, ctx)
    if err:
        return err
    oid, cid, amount = args["order_id"], args["customer_id"], args["amount_cents"]
    col, target = ("order_id", oid) if oid else ("customer_id", cid)
    n_prior = ctx.db.execute(
        f"SELECT COUNT(*) FROM payment_links WHERE {col}=?", (target,)).fetchone()[0]  # noqa: S608
    sh = session_hash(ctx.session_id)
    try:
        link = stripe_client.create_payment_link(
            args["description"].strip(), amount, {"session_hash": sh, col: target},
            f"plink:{sh}:{target}:{amount}:{n_prior}")
    except stripe_client.StripeFailure as e:
        return _fail(e.code, e.user_message)
    mode = stripe_client.mode()
    ctx.db.execute(
        "INSERT INTO payment_links (id, order_id, customer_id, amount_cents, stripe_link_id, url,"
        " active, mode, created_at) VALUES (?,?,?,?,?,?,1,?,?)",
        ("pl_" + secrets.token_hex(6), oid, cid, amount, link["id"], link["url"], mode,
         ctx.now.isoformat()))
    label = "[MOCK] Created" if mode == "mock" else "Created"
    return ToolResult(
        ok=True,
        summary=f"{label} ${amount / 100:.2f} payment link for {target}"
                f" (Stripe {mode.upper()} {link['id']}): {link['url']}",
        data={"link_id": link["id"], "url": link["url"], "amount_cents": amount, "mode": mode},
        undo_token=json.dumps({"link_id": link["id"]}))


def preview(args: dict, ctx: Ctx) -> DiffItem:
    return DiffItem(
        step_id="", before={},
        after={"amount": f"${args['amount_cents'] / 100:.2f}",
               "description": args["description"], "stripe_mode": stripe_client.mode()},
        amount_cents=args["amount_cents"])


def undo(token: str, ctx: Ctx) -> ToolResult:
    link_id = json.loads(token)["link_id"]
    row = ctx.db.execute(
        "SELECT active FROM payment_links WHERE stripe_link_id=?", (link_id,)).fetchone()
    if not row or row[0] != 1:
        return _fail("changed_since", f"Payment link {link_id} is no longer active.")
    try:
        stripe_client.deactivate_payment_link(link_id)
    except stripe_client.StripeFailure as e:
        return _fail(e.code, e.user_message)
    ctx.db.execute("UPDATE payment_links SET active=0 WHERE stripe_link_id=?", (link_id,))
    return ToolResult(ok=True, summary=f"Deactivated payment link {link_id}.",
                      data={"link_id": link_id})


register(SPEC, run, preview, undo)
