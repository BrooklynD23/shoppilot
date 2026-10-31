"""send_email tool (P5-I5): templates into the fake outbox. No commit, no log_action (R23)."""

from __future__ import annotations

import json
from string import Template

from app.agent.models import DiffItem
from app.integrations import outbox
from app.safety.policy import EMAIL_BODY_MAX_CHARS
from app.safety.policy import MAX_EMAIL_ORDER_IDS as MAX_IDS
from app.tools.registry import Ctx, ToolResult, ToolSpec, register

PREVIEW_BODIES = 3
STORE = "Fern & Kiln"

SPEC = ToolSpec(
    name="send_email",
    description=(
        "Email the customers of the given orders using a template (fake outbox, never "
        "sent). custom_body is required only for template=custom. Undoable (recall)."
    ),
    destructive=False,
    moves_money=False,
    undoable=True,
    input_schema={
        "type": "object",
        "additionalProperties": False,
        "required": ["order_ids", "template", "custom_body"],
        "properties": {
            "order_ids": {"type": "array", "items": {"type": "string"}},
            "template": {
                "type": "string",
                "enum": ["tracking", "refund_confirmation", "payment_request", "custom"],
            },
            "custom_body": {"anyOf": [{"type": "string"}, {"type": "null"}]},
        },
    },
)

# bodies; values are substituted, never re-parsed, so LLM text cannot inject $vars
TEMPLATES: dict[str, Template] = {
    "tracking": Template(
        "Hi $name,\n\nYour order $order_id shipped via $carrier. "
        "Tracking number: $tracking_number.\n\n$store"
    ),
    "refund_confirmation": Template(
        "Hi $name,\n\nWe refunded $amount on order $order_id (ref $refund_id).\n\n$store"
    ),
    "payment_request": Template(
        "Hi $name,\n\nPlease complete payment for order $order_id here: $url\n\n$store"
    ),
    "custom": Template("Hi $name,\n\n$custom_body\n\n$store"),
}
_SUBJECTS: dict[str, Template] = {
    "tracking": Template("Your order $order_id has shipped"),
    "refund_confirmation": Template("Refund for order $order_id"),
    "payment_request": Template("Payment request for order $order_id"),
    "custom": Template("About your order $order_id"),
}

_ORDER_SQL = (
    "SELECT o.id, c.name, c.email, o.carrier, o.tracking_number, o.status,"
    " (SELECT amount_cents FROM refunds r WHERE r.order_id = o.id"
    "  ORDER BY created_at DESC, rowid DESC LIMIT 1),"
    " (SELECT stripe_refund_id FROM refunds r WHERE r.order_id = o.id"
    "  ORDER BY created_at DESC, rowid DESC LIMIT 1),"
    " (SELECT url FROM payment_links p WHERE p.order_id = o.id AND p.active = 1"
    "  ORDER BY created_at DESC, rowid DESC LIMIT 1)"
    " FROM orders o JOIN customers c ON c.id = o.customer_id"
    " WHERE o.id IN (SELECT value FROM json_each(?))"
)
_COLS = (
    "name",
    "email",
    "carrier",
    "tracking_number",
    "status",
    "refund_cents",
    "refund_id",
    "url",
)

# template -> (required column, error code)
_NEEDS = {
    "tracking": ("tracking_number", "no_tracking"),
    "refund_confirmation": ("refund_id", "no_refund"),
    "payment_request": ("url", "no_payment_link"),
}
# preview runs before earlier plan steps (mark_shipped, refund, payment link) have executed.
# run() sends the LATEST refund / active link, which an earlier step may create, so preview
# never shows an existing one (it could be stale); tracking only when still unassigned.
_SEND_TIME = {
    "refund_id": "(latest refund at send time)",
    "refund_cents": None,
    "url": "(latest active payment link at send time)",
}


def _fail(summary: str, error: str) -> ToolResult:
    return ToolResult(ok=False, summary=summary, error=error)


def _load(ctx: Ctx, ids: list[str]) -> dict[str, dict]:
    cur = ctx.db.execute(_ORDER_SQL, (json.dumps(ids),))
    return {r[0]: dict(zip(_COLS, tuple(r)[1:], strict=True)) for r in cur}


def _check_args(args: dict, ids: list[str]) -> ToolResult | None:
    body = args.get("custom_body")
    if args["template"] == "custom" and not (body or "").strip():
        return _fail("custom template needs a custom_body.", "missing_body")
    if body is not None and len(body) > EMAIL_BODY_MAX_CHARS:
        return _fail(f"custom_body is over {EMAIL_BODY_MAX_CHARS} characters.", "too_long")
    if not ids:
        return _fail("No orders given.", "no_orders")
    if len(ids) > MAX_IDS:
        return _fail(f"At most {MAX_IDS} orders per step.", "too_many")
    return None


def _render(oid: str, row: dict, args: dict, preview: bool) -> dict:
    t = args["template"]
    if preview:
        row = {
            **row,
            **_SEND_TIME,
            "tracking_number": row["tracking_number"] or "(assigned when shipped)",
        }
    amount = row["refund_cents"]
    values = {
        **row,
        "order_id": oid,
        "store": STORE,
        "custom_body": args.get("custom_body") or "",
        "carrier": (row["carrier"] or "").upper(),
        "amount": f"${amount / 100:,.2f}" if amount is not None else "(refund amount)",
        "refund_id": row["refund_id"] or "",
        "url": row["url"] or "",
    }
    return {
        "order_id": oid,
        "to": row["email"],
        "subject": _SUBJECTS[t].safe_substitute(values),
        "body": TEMPLATES[t].safe_substitute(values),
    }


def _build(args: dict, ctx: Ctx, strict: bool = True) -> tuple[list[dict], ToolResult | None]:
    """Validate and render every email; writes nothing. strict=False = preview (no _NEEDS)."""
    ids = list(dict.fromkeys(args["order_ids"]))
    err = _check_args(args, ids)
    if err:
        return [], err
    found = _load(ctx, ids)
    missing = [i for i in ids if i not in found]
    if missing:
        return [], _fail(f"Unknown orders: {', '.join(missing)}", "not_found")
    need = _NEEDS.get(args["template"]) if strict else None
    if need:
        # tracking also needs status 'shipped': refunded orders keep their tracking number
        bad = [
            i
            for i in ids
            if not found[i][need[0]]
            or (need[0] == "tracking_number" and found[i]["status"] != "shipped")
        ]
        if bad:
            return [], _fail(f"{need[1].replace('_', ' ')}: {', '.join(bad)}", need[1])
    return [_render(i, found[i], args, preview=not strict) for i in ids], None


def run(args: dict, ctx: Ctx) -> ToolResult:
    emails, err = _build(args, ctx)
    if err:
        return err
    ids = [
        outbox.send(ctx, e["to"], e["subject"], e["body"], args["template"], e["order_id"])
        for e in emails
    ]
    return ToolResult(
        ok=True,
        summary=f"Queued {len(ids)} {args['template']} email(s) in the fake outbox.",
        data={"outbox_ids": ids, "order_ids": [e["order_id"] for e in emails]},
        undo_token=json.dumps({"outbox_ids": ids}),
    )


def preview(args: dict, ctx: Ctx) -> DiffItem:
    emails, err = _build(args, ctx, strict=False)
    if err:
        return DiffItem(step_id="", before={}, after={"error": err.summary})
    after = {
        e["order_id"]: {
            "to": e["to"],
            "subject": e["subject"],
            **({"body": e["body"]} if n < PREVIEW_BODIES else {}),
        }
        for n, e in enumerate(emails)
    }
    return DiffItem(step_id="", before={}, after=after)


def undo(token: str, ctx: Ctx) -> ToolResult:
    ids = json.loads(token)["outbox_ids"]
    # R22 post state: every row still un-recalled
    live = dict(
        tuple(r)
        for r in ctx.db.execute(
            "SELECT id, recalled_at FROM outbox WHERE id IN (SELECT value FROM json_each(?))",
            (json.dumps(ids),),
        )
    )
    missing = [i for i in ids if i not in live]
    if missing:
        return _fail(f"Outbox email {missing[0]} not found.", "not_found")
    if any(live[i] is not None for i in ids):
        return _fail("Some of these emails were already recalled.", "changed_since")
    for oid in ids:
        outbox.recall(ctx, oid)
    return ToolResult(
        ok=True, summary=f"Recalled {len(ids)} email(s) (fake outbox).", data={"outbox_ids": ids}
    )


register(SPEC, run, preview, undo)
