"""mark_shipped tool (P5-I4). No commit, no log_action (R23); undo checks post state (R22)."""

from __future__ import annotations

import hashlib
import json

from app.agent.models import DiffItem
from app.db import session_hash
from app.tools.registry import Ctx, ToolResult, ToolSpec, register

MAX_IDS = 50  # ponytail: mirrors policy's 50-id cap; import from safety.policy once it exists
_COLS = ("status", "carrier", "tracking_number", "shipped_at")

SPEC = ToolSpec(
    name="mark_shipped",
    description="Mark paid orders as shipped with a carrier; sets a tracking number. Undoable.",
    destructive=False,
    moves_money=False,
    undoable=True,
    input_schema={
        "type": "object",
        "additionalProperties": False,
        "required": ["order_ids", "carrier"],
        "properties": {
            "order_ids": {"type": "array", "items": {"type": "string"}},
            "carrier": {"type": "string", "enum": ["usps", "ups", "fedex"]},
        },
    },
)


def tracking_number(carrier: str, sh: str, order_id: str) -> str:
    digest = hashlib.sha1((sh + order_id).encode(), usedforsecurity=False).hexdigest()
    return carrier.upper() + digest[:12].upper()


def _load(ctx: Ctx, ids: list[str]) -> dict[str, dict]:
    cur = ctx.db.execute(
        "SELECT id, status, carrier, tracking_number, shipped_at FROM orders"
        " WHERE id IN (SELECT value FROM json_each(?))",
        (json.dumps(ids),),
    )
    return {r[0]: dict(zip(_COLS, tuple(r)[1:], strict=True)) for r in cur}


def _check(args: dict, ctx: Ctx) -> tuple[list[str], dict[str, dict], ToolResult | None]:
    ids = list(dict.fromkeys(args["order_ids"]))
    if not ids:
        return ids, {}, ToolResult(ok=False, summary="No orders given.", error="no_orders")
    if len(ids) > MAX_IDS:
        return (
            ids,
            {},
            ToolResult(ok=False, summary=f"At most {MAX_IDS} orders per step.", error="too_many"),
        )
    found = _load(ctx, ids)
    missing = [i for i in ids if i not in found]
    if missing:
        return (
            ids,
            found,
            ToolResult(
                ok=False, summary=f"Unknown orders: {', '.join(missing)}", error="not_found"
            ),
        )
    bad = [i for i in ids if found[i]["status"] != "paid"]
    if bad:
        return (
            ids,
            found,
            ToolResult(
                ok=False, summary=f"Not in paid status: {', '.join(bad)}", error="invalid_status"
            ),
        )
    return ids, found, None


def _write(ctx: Ctx, oid: str, row: dict) -> None:
    ctx.db.execute(
        "UPDATE orders SET status=?, carrier=?, tracking_number=?, shipped_at=? WHERE id=?",
        (*(row[c] for c in _COLS), oid),
    )


def run(args: dict, ctx: Ctx) -> ToolResult:
    ids, found, err = _check(args, ctx)
    if err:
        return err
    sh, carrier, ts = session_hash(ctx.session_id), args["carrier"], ctx.now.isoformat()
    entries = []
    for oid in ids:
        post = {
            "status": "shipped",
            "carrier": carrier,
            "tracking_number": tracking_number(carrier, sh, oid),
            "shipped_at": ts,
        }
        _write(ctx, oid, post)
        entries.append({"id": oid, "prior": found[oid], "post": post})
    return ToolResult(
        ok=True,
        summary=f"Marked {len(ids)} order(s) shipped via {carrier.upper()}.",
        data={"orders": [{"id": e["id"], **e["post"]} for e in entries]},
        undo_token=json.dumps({"orders": entries}),
    )


def preview(args: dict, ctx: Ctx) -> DiffItem:
    ids = list(dict.fromkeys(args["order_ids"]))[:MAX_IDS]
    found = _load(ctx, ids) if ids else {}
    return DiffItem(
        step_id="",
        before={i: found[i]["status"] if i in found else "missing" for i in ids},
        after={i: f"shipped ({args['carrier']})" for i in ids},
    )


def undo(token: str, ctx: Ctx) -> ToolResult:
    entries = json.loads(token)["orders"]
    live = _load(ctx, [e["id"] for e in entries])
    changed = [e["id"] for e in entries if live.get(e["id"]) != e["post"]]
    if changed:
        return ToolResult(
            ok=False, summary=f"Orders changed since: {', '.join(changed)}", error="changed_since"
        )
    for e in entries:
        _write(ctx, e["id"], e["prior"])
    return ToolResult(
        ok=True,
        summary=f"Restored {len(entries)} order(s) to their prior state.",
        data={"order_ids": [e["id"] for e in entries]},
    )


register(SPEC, run, preview, undo)
