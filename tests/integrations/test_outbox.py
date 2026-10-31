import sqlite3
from contextlib import contextmanager
from dataclasses import replace
from datetime import timedelta
from secrets import token_urlsafe

import pytest

from app.integrations import outbox


@contextmanager
def _store_ctx(now, today):
    """Schema-only store opened through the real get_db (no seed dependency)."""
    from app.config import get_settings
    from app.db import get_db, init_schema, store_path
    from app.tools.registry import Ctx

    sid = token_urlsafe(32)
    conn = sqlite3.connect(store_path(sid, get_settings()))
    init_schema(conn)
    conn.commit()
    conn.close()
    with get_db(sid) as db:
        yield Ctx(sid, db, now, today)


@pytest.fixture
def octx(fixed_now, anchor):
    with _store_ctx(fixed_now, anchor) as c:
        yield c


def _send(ctx, subject="Your order shipped"):
    return outbox.send(ctx, "ana@example.com", subject, "Tracking: 1Z999", "tracking", None)


def test_send_then_list_returns_one_unrecalled_row(octx):
    oid = _send(octx)
    rows = outbox.list_outbox(octx)
    assert len(rows) == 1
    row = rows[0]
    assert row["id"] == oid
    assert row["to_email"] == "ana@example.com"
    assert row["template"] == "tracking"
    assert row["order_id"] is None
    assert row["created_at"] == octx.now.isoformat()
    assert row["recalled_at"] is None


def test_recall_sets_recalled_at_and_keeps_row(octx):
    oid = _send(octx)
    outbox.recall(octx, oid)
    rows = outbox.list_outbox(octx)
    assert len(rows) == 1
    assert rows[0]["recalled_at"] == octx.now.isoformat()


def test_recall_unknown_id_raises_keyerror(octx):
    with pytest.raises(KeyError):
        outbox.recall(octx, "nope")


def test_list_outbox_newest_first(octx):
    first = _send(octx, "first")
    later = replace(octx, now=octx.now + timedelta(minutes=1))
    second = _send(later, "second")
    third = _send(later, "third")  # same timestamp: insertion order breaks the tie
    assert [r["id"] for r in outbox.list_outbox(octx)] == [third, second, first]


def test_sessions_are_isolated(octx, fixed_now, anchor):
    _send(octx)
    with _store_ctx(fixed_now, anchor) as other:
        assert outbox.list_outbox(other) == []
