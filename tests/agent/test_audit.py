import sqlite3
import threading
import time

import pytest

from app.agent.audit import (
    UndoError,
    list_actions,
    log_action,
    undo_action,
    verify_chain,
)
from app.tools import registry as r
from app.tools.registry import Ctx, ToolResult, ToolSpec, register

SCHEMA = {"type": "object", "properties": {}, "required": [], "additionalProperties": False}
calls = {"undo": 0}
undo_hook = {"fn": None}


@pytest.fixture
def actx(mem_conn, fixed_now, anchor):
    """Schema-only store: audit needs no seed data (P1-T3 runs in parallel)."""
    return Ctx("x" * 43, mem_conn, fixed_now, anchor)


@pytest.fixture(autouse=True)
def bump_tool():
    saved = dict(r._TOOLS)
    r._TOOLS.clear()
    calls["undo"] = 0
    undo_hook["fn"] = None

    def undo(token, ctx):
        if token == "stale":
            return ToolResult(ok=False, summary="changed", error="changed_since")
        if token == "bad":
            return ToolResult(ok=False, summary="nope", error="boom")
        if undo_hook["fn"]:
            undo_hook["fn"]()
        calls["undo"] += 1
        return ToolResult(ok=True, summary=f"undid {token}")

    def spec(name, undoable):
        return ToolSpec(
            name=name,
            description="d",
            input_schema=SCHEMA,
            destructive=False,
            moves_money=False,
            undoable=undoable,
        )

    register(spec("bump", True), lambda a, c: None, lambda a, c: None, undo)
    register(spec("export_report", False), lambda a, c: None, lambda a, c: None)
    register(spec("refund_order", False), lambda a, c: None, lambda a, c: None)
    yield
    r._TOOLS.clear()
    r._TOOLS.update(saved)


def test_log_returns_id_and_persists(actx):
    aid = log_action(actx, "plan", {"request": "ship", "summary": "Planned"})
    assert aid.startswith("aud_") and len(aid) == 16
    row = list_actions(actx)[0]
    assert row["id"] == aid and row["summary"] == "Planned"
    assert row["ts"] == "2026-10-15T09:00:00Z"


def test_newest_first(actx):
    a = log_action(actx, "plan", {})
    b = log_action(actx, "validate", {})
    assert [x["id"] for x in list_actions(actx)] == [b, a]


def test_unknown_kind(actx):
    pytest.raises(ValueError, log_action, actx, "hack", {})


def test_unserialisable_payload(actx):
    pytest.raises(TypeError, log_action, actx, "plan", {"x": object()})


def test_token_not_exposed(actx):
    log_action(actx, "execute", {}, tool="bump", undo_token="secret-t")
    row = list_actions(actx)[0]
    assert "undo_token" not in row and "secret-t" not in str(row)
    assert set(row) == {
        "id",
        "ts",
        "kind",
        "plan_id",
        "step_id",
        "tool",
        "summary",
        "can_undo",
        "undone",
        "undone_at",
    }
    assert row["can_undo"] is True and row["undone"] is False


def test_undo_once(actx):
    aid = log_action(actx, "execute", {}, tool="bump", undo_token="t1")
    assert undo_action(actx, aid).ok
    with pytest.raises(UndoError) as e:
        undo_action(actx, aid)
    assert e.value.code == "already_undone"
    assert calls["undo"] == 1
    row = next(x for x in list_actions(actx) if x["id"] == aid)
    assert row["undone"] is True and row["can_undo"] is False
    assert row["undone_at"] == "2026-10-15T09:00:00Z"


def test_undo_not_undoable(actx):
    aid = log_action(actx, "plan", {})
    with pytest.raises(UndoError) as e:
        undo_action(actx, aid)
    assert e.value.code == "not_undoable"
    aid2 = log_action(actx, "execute", {}, tool="export_report")
    with pytest.raises(UndoError) as e:
        undo_action(actx, aid2)
    assert e.value.code == "not_undoable"


def test_undo_missing(actx):
    with pytest.raises(UndoError) as e:
        undo_action(actx, "aud_nope")
    assert e.value.code == "not_found"


@pytest.mark.parametrize(("token", "code"), [("stale", "changed_since"), ("bad", "undo_failed")])
def test_undo_tool_failure(actx, token, code):
    aid = log_action(actx, "execute", {}, tool="bump", undo_token=token)
    with pytest.raises(UndoError) as e:
        undo_action(actx, aid)
    assert e.value.code == code
    row = list_actions(actx)[0]
    assert row["id"] == aid and row["undone"] is False  # undo row rolled back
    assert verify_chain(actx)


def test_audit_chain_ok(actx):
    assert verify_chain(actx)
    for k in ("plan", "execute", "validate"):
        log_action(actx, k, {"k": k})
    assert verify_chain(actx)


def test_audit_chain_detects_edit(actx):
    log_action(actx, "plan", {"request": "ship"})
    log_action(actx, "plan", {"request": "refund"})
    assert verify_chain(actx)
    with pytest.raises(sqlite3.DatabaseError):
        actx.db.execute("UPDATE audit_log SET payload_json='{}'")
    actx.db.execute("DROP TRIGGER audit_no_update")
    actx.db.execute(
        'UPDATE audit_log SET payload_json=\'{"request":"x"}\' '
        "WHERE rowid=(SELECT min(rowid) FROM audit_log)"
    )
    assert not verify_chain(actx)


R38 = "Refunds are irreversible. Ask the agent for a payment link to recover money."


def test_undo_refund_r38_message(actx):
    aid = log_action(actx, "execute", {}, tool="refund_order", undo_token="t")
    n = actx.db.execute("SELECT count(*) FROM audit_log").fetchone()[0]
    with pytest.raises(UndoError) as e:
        undo_action(actx, aid)
    assert e.value.code == "not_undoable" and e.value.message == R38
    assert actx.db.execute("SELECT count(*) FROM audit_log").fetchone()[0] == n


@pytest.fixture
def file_db(tmp_path):
    from app.db import init_schema

    path = tmp_path / "store.db"
    with sqlite3.connect(path) as c:
        init_schema(c)
    c.close()
    return path


def _open(path):
    """Mirror get_db: own connection per request, Row factory, FKs on, commit/rollback."""
    conn = sqlite3.connect(path, check_same_thread=False, timeout=5)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def _request(path, fixed_now, anchor, fn, out, key):
    conn = _open(path)
    try:
        out[key] = fn(Ctx("x" * 43, conn, fixed_now, anchor))
        conn.commit()
    except BaseException as e:  # noqa: BLE001 - recorded for the assertion
        conn.rollback()
        out[key] = e
    finally:
        conn.close()


def test_double_click_undo_two_connections(file_db, fixed_now, anchor):
    c = _open(file_db)
    aid = log_action(
        Ctx("x" * 43, c, fixed_now, anchor), "execute", {}, tool="bump", undo_token="t1"
    )
    c.commit()
    c.close()
    entered = threading.Event()
    undo_hook["fn"] = lambda: (entered.set(), time.sleep(0.3))
    out = {}
    t1 = threading.Thread(
        target=_request, args=(file_db, fixed_now, anchor, lambda x: undo_action(x, aid), out, 1)
    )
    t2 = threading.Thread(
        target=_request, args=(file_db, fixed_now, anchor, lambda x: undo_action(x, aid), out, 2)
    )
    t1.start()
    assert entered.wait(5)
    t2.start()
    t1.join(10)
    t2.join(10)
    assert isinstance(out[1], ToolResult) and out[1].ok
    assert isinstance(out[2], UndoError) and out[2].code == "already_undone"
    assert calls["undo"] == 1
    c = _open(file_db)
    try:
        assert verify_chain(Ctx("x" * 43, c, fixed_now, anchor))
    finally:
        c.close()


class _PauseAfterHead:
    """Connection proxy: pauses right after log_action reads the chain head."""

    def __init__(self, conn, read, resume):
        self._c, self._read, self._resume = conn, read, resume

    def __getattr__(self, name):
        return getattr(self._c, name)

    def execute(self, sql, *a):
        cur = self._c.execute(sql, *a)
        if sql.startswith("SELECT row_hash FROM audit_log"):
            self._read.set()
            self._resume.wait(0.5)  # with the lock, A cannot finish, so this times out
        return cur


def test_concurrent_appends_keep_chain(file_db, fixed_now, anchor):
    read, a_done, out = threading.Event(), threading.Event(), {}

    def b(x):
        x = Ctx(x.session_id, _PauseAfterHead(x.db, read, a_done), x.now, x.today)
        return log_action(x, "plan", {"who": "B"})

    def a(x):
        try:
            return log_action(x, "plan", {"who": "A"})
        finally:
            a_done.set()

    tb = threading.Thread(target=_request, args=(file_db, fixed_now, anchor, b, out, "b"))
    tb.start()
    assert read.wait(5)
    ta = threading.Thread(target=_request, args=(file_db, fixed_now, anchor, a, out, "a"))
    ta.start()
    tb.join(10)
    ta.join(10)
    assert isinstance(out["a"], str) and isinstance(out["b"], str)
    c = _open(file_db)
    try:
        assert c.execute("SELECT count(*) FROM audit_log").fetchone()[0] == 2
        assert verify_chain(Ctx("x" * 43, c, fixed_now, anchor))
    finally:
        c.close()
