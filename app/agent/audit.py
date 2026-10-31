"""Append-only, hash-chained audit log with single-shot undo (P1-T5, R22/R38)."""
from __future__ import annotations

import hashlib
import json
import secrets
import sqlite3

from app.tools.registry import Ctx, ToolResult, get_tool

AUDIT_KINDS = frozenset(
    {"session", "plan", "guard_block", "validate", "confirm", "execute", "undo", "error"})
GENESIS = "0" * 64


class UndoError(Exception):
    """code: not_found | not_undoable | already_undone | changed_since | undo_failed."""

    def __init__(self, code: str, message: str | None = None):
        super().__init__(message or code)
        self.code = code
        self.message = message or code


def _canonical(payload: dict) -> str:
    # default=None: json raises TypeError on anything it cannot encode
    return json.dumps(payload, sort_keys=True, separators=(",", ":"),
                      ensure_ascii=False, allow_nan=False, default=None)


def _row_hash(prev: str, aid: str, ts: str, kind: str, payload_json: str) -> str:
    return hashlib.sha256(f"{prev}\n{aid}\n{ts}\n{kind}\n{payload_json}".encode()).hexdigest()


def _ts(ctx: Ctx) -> str:
    return ctx.now.strftime("%Y-%m-%dT%H:%M:%SZ")


def _lock(ctx: Ctx) -> None:
    """Take the write lock up front. A deferred txn that reads the chain head and then
    writes either forks the chain (autocommit read) or hits SQLITE_BUSY on the upgrade
    (no retry). BEGIN IMMEDIATE waits on the busy timeout instead. The caller (get_db)
    commits."""
    if not ctx.db.in_transaction:
        ctx.db.execute("BEGIN IMMEDIATE")


def log_action(ctx: Ctx, kind: str, payload: dict, *, plan_id: str | None = None,
               step_id: str | None = None, tool: str | None = None,
               undo_token: str | None = None, ref_id: str | None = None) -> str:
    if kind not in AUDIT_KINDS:
        raise ValueError(f"unknown audit kind {kind!r}")
    if not isinstance(payload, dict):
        raise TypeError("payload must be a dict")
    body = _canonical(payload)
    aid, ts = "aud_" + secrets.token_hex(6), _ts(ctx)
    _lock(ctx)  # head read and insert must be one write txn, else concurrent appends fork
    last = ctx.db.execute(
        "SELECT row_hash FROM audit_log ORDER BY rowid DESC LIMIT 1").fetchone()
    prev = last[0] if last else GENESIS
    ctx.db.execute(
        "INSERT INTO audit_log (id, ts, kind, plan_id, step_id, tool, payload_json, undo_token,"
        " ref_id, prev_hash, row_hash) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
        (aid, ts, kind, plan_id, step_id, tool, body, undo_token, ref_id, prev,
         _row_hash(prev, aid, ts, kind, body)))
    return aid


def list_actions(ctx: Ctx, limit: int = 200) -> list[dict]:
    """Newest first. Never returns undo_token."""
    rows = ctx.db.execute(
        "SELECT a.id, a.ts, a.kind, a.plan_id, a.step_id, a.tool, a.payload_json,"
        " a.undo_token IS NOT NULL, u.ts FROM audit_log a"
        " LEFT JOIN audit_log u ON u.kind = 'undo' AND u.ref_id = a.id"
        " ORDER BY a.rowid DESC LIMIT ?", (max(0, int(limit)),)).fetchall()
    out = []
    for aid, ts, kind, plan_id, step_id, tool, body, has_token, undone_at in rows:
        summary = json.loads(body).get("summary")
        out.append({
            "id": aid, "ts": ts, "kind": kind, "plan_id": plan_id, "step_id": step_id,
            "tool": tool, "summary": summary if isinstance(summary, str) else kind,
            "can_undo": kind == "execute" and bool(has_token) and undone_at is None,
            "undone": undone_at is not None, "undone_at": undone_at,
        })
    return out


def verify_chain(ctx: Ctx) -> bool:
    prev = GENESIS
    for aid, ts, kind, body, p, h in ctx.db.execute(
            "SELECT id, ts, kind, payload_json, prev_hash, row_hash FROM audit_log"
            " ORDER BY rowid"):
        if p != prev or h != _row_hash(prev, aid, ts, kind, body):
            return False
        prev = h
    return True


def undo_action(ctx: Ctx, audit_id: str) -> ToolResult:
    """Insert the undo row first (unique index stops a racing second undo), then run the
    tool's undo. Any raise lets get_db roll the undo row back."""
    _lock(ctx)  # serialises a double-click: the 2nd waits, then hits the unique index
    row = ctx.db.execute(
        "SELECT kind, tool, undo_token FROM audit_log WHERE id = ?", (audit_id,)).fetchone()
    if row is None:
        raise UndoError("not_found", "No such action.")
    kind, tool, token = row
    try:
        undo = get_tool(tool).undo if kind == "execute" and token and tool else None
    except KeyError:
        undo = None
    if undo is None:
        msg = ("Refunds are irreversible. Ask the agent for a payment link to recover money."
               if tool == "refund_order" else "This action cannot be undone.")
        raise UndoError("not_undoable", msg)
    # savepoint: a failed undo leaves no undo row even if the caller catches and commits
    ctx.db.execute("SAVEPOINT undo_action")
    try:
        try:
            log_action(ctx, "undo", {"summary": f"Undo {tool}"}, tool=tool, ref_id=audit_id)
        except sqlite3.IntegrityError as e:
            raise UndoError("already_undone", "This action was already undone.") from e
        res = undo(token, ctx)
        if not res.ok:
            if res.error == "changed_since":
                raise UndoError("changed_since", "This changed since; undo would overwrite it.")
            raise UndoError("undo_failed", res.summary or "Undo failed.")
    except BaseException:
        ctx.db.execute("ROLLBACK TO undo_action")
        ctx.db.execute("RELEASE undo_action")
        raise
    ctx.db.execute("RELEASE undo_action")
    return res
