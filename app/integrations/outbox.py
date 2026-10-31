"""Fake email outbox: every email lands in the session's `outbox` table, nothing is sent."""

from uuid import uuid4

_KEYS = ("id", "to_email", "subject", "body", "template", "order_id", "created_at", "recalled_at")


def send(ctx, to_email: str, subject: str, body: str, template: str, order_id: str | None) -> str:
    outbox_id = uuid4().hex
    ctx.db.execute(
        "INSERT INTO outbox (id, to_email, subject, body, template, order_id, created_at)"
        " VALUES (?, ?, ?, ?, ?, ?, ?)",
        (outbox_id, to_email, subject, body, template, order_id, ctx.now.isoformat()),
    )
    return outbox_id


def recall(ctx, outbox_id: str) -> None:
    """Set recalled_at (first recall wins); the row is never deleted."""
    cur = ctx.db.execute(
        "UPDATE outbox SET recalled_at = COALESCE(recalled_at, ?) WHERE id = ?",
        (ctx.now.isoformat(), outbox_id),
    )
    if cur.rowcount == 0:
        raise KeyError(outbox_id)


def list_outbox(ctx) -> list[dict]:
    rows = ctx.db.execute(
        "SELECT id, to_email, subject, body, template, order_id, created_at, recalled_at"
        " FROM outbox ORDER BY created_at DESC, rowid DESC"
    ).fetchall()
    return [dict(zip(_KEYS, tuple(r), strict=True)) for r in rows]
