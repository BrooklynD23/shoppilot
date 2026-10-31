import json
import sqlite3
from datetime import UTC, date, datetime

import pytest

from app.tools import mark_shipped as ms
from app.tools.registry import Ctx


@pytest.fixture
def ctx(mem_conn):
    mem_conn.row_factory = sqlite3.Row  # mirror get_db
    mem_conn.execute(
        "INSERT INTO customers VALUES ('C0001','Ann','ann@example.com','US','2026-01-01')"
    )
    for oid, status in [("O0001", "paid"), ("O0002", "paid"), ("O0003", "shipped")]:
        mem_conn.execute(
            "INSERT INTO orders (id, customer_id, created_at, status, total_cents, ship_country)"
            " VALUES (?, 'C0001', '2026-10-14T10:00:00', ?, 1000, 'US')",
            (oid, status),
        )
    return Ctx("sid-test", mem_conn, datetime(2026, 10, 15, 9, 0, tzinfo=UTC), date(2026, 10, 15))


def rows(ctx):
    return [
        tuple(r)
        for r in ctx.db.execute(
            "SELECT id, status, carrier, tracking_number, shipped_at FROM orders ORDER BY id"
        )
    ]


def test_paid_order_becomes_shipped(ctx):
    r = ms.run({"order_ids": ["O0001"], "carrier": "ups"}, ctx)
    assert r.ok and r.undo_token
    oid, status, carrier, tracking, shipped_at = rows(ctx)[0]
    assert (status, carrier) == ("shipped", "ups")
    assert tracking.startswith("UPS") and len(tracking) == 15
    assert shipped_at
    assert (
        ms.run({"order_ids": ["O0002"], "carrier": "ups"}, ctx).data["orders"][0]["tracking_number"]
        != tracking
    )


def test_tracking_is_deterministic(ctx):
    assert ms.tracking_number("ups", "abc", "O0001") == ms.tracking_number("ups", "abc", "O0001")


def test_non_paid_order_fails_and_db_unchanged(ctx):
    before = rows(ctx)
    r = ms.run({"order_ids": ["O0001", "O0003"], "carrier": "usps"}, ctx)
    assert not r.ok and r.error == "invalid_status"
    assert rows(ctx) == before


def test_missing_order_fails(ctx):
    r = ms.run({"order_ids": ["O9999"], "carrier": "usps"}, ctx)
    assert not r.ok and r.error == "not_found"


def test_too_many_ids(ctx):
    r = ms.run({"order_ids": [f"O{i:04d}" for i in range(51)], "carrier": "usps"}, ctx)
    assert not r.ok and r.error == "too_many"


def test_undo_restores_prior_fields(ctx):
    before = rows(ctx)
    token = ms.run({"order_ids": ["O0001", "O0002"], "carrier": "fedex"}, ctx).undo_token
    r = ms.undo(token, ctx)
    assert r.ok
    assert rows(ctx) == before


def test_undo_after_manual_edit_is_changed_since(ctx):
    token = ms.run({"order_ids": ["O0001", "O0002"], "carrier": "fedex"}, ctx).undo_token
    ctx.db.execute("UPDATE orders SET carrier='usps' WHERE id='O0002'")
    snapshot = rows(ctx)
    r = ms.undo(token, ctx)
    assert not r.ok and r.error == "changed_since"
    assert rows(ctx) == snapshot


def test_token_has_prior_and_post(ctx):
    token = json.loads(ms.run({"order_ids": ["O0001"], "carrier": "ups"}, ctx).undo_token)
    assert token["orders"][0]["prior"]["status"] == "paid"
    assert token["orders"][0]["post"]["status"] == "shipped"


def test_preview_no_writes(ctx):
    before = rows(ctx)
    d = ms.preview({"order_ids": ["O0001"], "carrier": "ups"}, ctx)
    assert d.step_id == ""
    assert d.before == {"O0001": "paid"} and d.after == {"O0001": "shipped (ups)"}
    assert d.amount_cents is None
    assert rows(ctx) == before


def test_spec_flags():
    s = ms.SPEC
    assert (s.name, s.destructive, s.moves_money, s.undoable) == (
        "mark_shipped",
        False,
        False,
        True,
    )
