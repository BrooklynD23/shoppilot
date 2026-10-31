import sqlite3
from datetime import UTC, date, datetime

import pytest

from app.tools import send_email as se
from app.tools.registry import Ctx


@pytest.fixture
def ctx(mem_conn):
    mem_conn.row_factory = sqlite3.Row  # mirror get_db
    mem_conn.execute(
        "INSERT INTO customers VALUES ('C0001','Ann $x','ann@example.com','US','2026-01-01')"
    )
    mem_conn.execute(
        "INSERT INTO customers VALUES ('C0002','Bob','bob@example.com','US','2026-01-01')"
    )
    for oid, cid, status, tn in [
        ("O0001", "C0001", "shipped", "UPSABC123"),
        ("O0002", "C0002", "shipped", "UPSDEF456"),
        ("O0003", "C0001", "paid", None),
    ]:
        mem_conn.execute(
            "INSERT INTO orders (id, customer_id, created_at, status, total_cents, ship_country,"
            " carrier, tracking_number) VALUES (?, ?, '2026-10-14T10:00:00', ?, 4200, 'US', ?, ?)",
            (oid, cid, status, "ups" if tn else None, tn),
        )
    return Ctx("sid-test", mem_conn, datetime(2026, 10, 15, 9, 0, tzinfo=UTC), date(2026, 10, 15))


def outbox(ctx):
    return [dict(r) for r in ctx.db.execute("SELECT * FROM outbox ORDER BY rowid")]


def args(ids, template="tracking", body=None):
    return {"order_ids": ids, "template": template, "custom_body": body}


def test_tracking_two_orders_two_rows(ctx):
    r = se.run(args(["O0001", "O0002"]), ctx)
    assert r.ok and r.undo_token
    rows = outbox(ctx)
    assert len(rows) == 2
    assert "UPSABC123" in rows[0]["body"] and rows[0]["to_email"] == "ann@example.com"
    assert "UPSDEF456" in rows[1]["body"] and rows[1]["template"] == "tracking"
    assert "Ann $x" in rows[0]["body"]  # stray $ in a name does not crash


def test_custom_null_body_fails(ctx):
    r = se.run(args(["O0001"], "custom", None), ctx)
    assert not r.ok and r.error == "missing_body"
    assert outbox(ctx) == []


def test_custom_body_too_long(ctx):
    r = se.run(args(["O0001"], "custom", "x" * 2001), ctx)
    assert not r.ok and r.error == "too_long"
    assert outbox(ctx) == []


def test_custom_body_sent_verbatim(ctx):
    r = se.run(args(["O0001"], "custom", "Price is $5 ${oops}"), ctx)
    assert r.ok
    assert "Price is $5 ${oops}" in outbox(ctx)[0]["body"]


def test_undo_recalls_all_rows_deletes_none(ctx):
    token = se.run(args(["O0001", "O0002"]), ctx).undo_token
    r = se.undo(token, ctx)
    assert r.ok
    rows = outbox(ctx)
    assert len(rows) == 2 and all(row["recalled_at"] for row in rows)


def test_preview_creates_no_rows(ctx):
    d = se.preview(args(["O0001", "O0002"]), ctx)
    assert outbox(ctx) == []
    assert d.step_id == "" and d.before == {} and d.amount_cents is None
    assert d.after["O0001"]["to"] == "ann@example.com" and d.after["O0001"]["subject"]


def test_tracking_unshipped_fails(ctx):
    r = se.run(args(["O0001", "O0003"]), ctx)
    assert not r.ok and r.error == "no_tracking"
    assert outbox(ctx) == []


def test_unknown_order_and_too_many(ctx):
    assert se.run(args(["O9999"]), ctx).error == "not_found"
    assert se.run(args([f"O{i:04d}" for i in range(51)]), ctx).error == "too_many"
    assert se.run(args([]), ctx).error == "no_orders"


def test_refund_confirmation_needs_refund(ctx):
    assert se.run(args(["O0001"], "refund_confirmation"), ctx).error == "no_refund"
    ctx.db.execute(
        "INSERT INTO refunds VALUES ('r1','O0001',1500,'duplicate','re_123','test',"
        "'2026-10-15T08:00:00')"
    )
    r = se.run(args(["O0001"], "refund_confirmation"), ctx)
    assert r.ok and "re_123" in outbox(ctx)[0]["body"] and "$15.00" in outbox(ctx)[0]["body"]


def test_payment_request_needs_active_link(ctx):
    assert se.run(args(["O0001"], "payment_request"), ctx).error == "no_payment_link"
    ctx.db.execute(
        "INSERT INTO payment_links (id, order_id, amount_cents, stripe_link_id, url,"
        " mode, created_at) VALUES ('p1','O0001',900,'plink_1',"
        "'https://buy.stripe.com/test_x','test','2026-10-15T08:00:00')"
    )
    r = se.run(args(["O0001"], "payment_request"), ctx)
    assert r.ok and "https://buy.stripe.com/test_x" in outbox(ctx)[0]["body"]


def test_spec_flags():
    s = se.SPEC
    assert (s.name, s.destructive, s.moves_money, s.undoable) == ("send_email", False, False, True)


@pytest.mark.parametrize("template", ["tracking", "refund_confirmation", "payment_request"])
def test_preview_before_prior_step_runs_shows_placeholder(ctx, template):
    # plan [mark_shipped, send_email(tracking)] is previewed before mark_shipped runs
    d = se.preview(args(["O0003"], template), ctx)
    assert "error" not in d.after
    e = d.after["O0003"]
    assert e["to"] == "ann@example.com" and "O0003" in e["subject"]
    assert "(" in e["body"]  # placeholder, not a crash or blank
    assert se.run(args(["O0003"], template), ctx).ok is False  # run still enforces


def test_preview_keeps_hard_errors(ctx):
    assert se.preview(args(["NOPE"]), ctx).after == {"error": "Unknown orders: NOPE"}


def test_undo_changed_since_when_already_recalled(ctx):
    r = se.run(args(["O0001", "O0002"]), ctx)
    from app.integrations import outbox as ob

    ob.recall(ctx, r.data["outbox_ids"][1])
    u = se.undo(r.undo_token, ctx)
    assert not u.ok and u.error == "changed_since"
    assert outbox(ctx)[0]["recalled_at"] is None  # nothing touched


def test_preview_never_shows_stale_refund_or_link(ctx):
    # plan [refund_order, send_email(refund_confirmation)] on an order with an older refund
    ctx.db.execute(
        "INSERT INTO refunds VALUES ('r0','O0001',700,'duplicate','re_old','test',"
        "'2026-10-01T08:00:00')"
    )
    ctx.db.execute(
        "INSERT INTO payment_links (id, order_id, amount_cents, stripe_link_id, url,"
        " mode, created_at) VALUES ('p0','O0001',900,'plink_0',"
        "'https://buy.stripe.com/test_old','test','2026-10-01T08:00:00')"
    )
    refund = se.preview(args(["O0001"], "refund_confirmation"), ctx).after["O0001"]["body"]
    assert "re_old" not in refund and "$7.00" not in refund and "at send time" in refund
    link = se.preview(args(["O0001"], "payment_request"), ctx).after["O0001"]["body"]
    assert "test_old" not in link and "at send time" in link


def test_limits_come_from_policy():
    from app.safety import policy

    assert se.MAX_IDS is policy.MAX_EMAIL_ORDER_IDS
    assert se.EMAIL_BODY_MAX_CHARS is policy.EMAIL_BODY_MAX_CHARS
    assert all(isinstance(t, se.Template) for t in se.TEMPLATES.values())


def test_tracking_refunded_order_with_tracking_fails(ctx):
    ctx.db.execute("UPDATE orders SET status='refunded' WHERE id='O0001'")
    r = se.run(args(["O0001"]), ctx)
    assert not r.ok and r.error == "no_tracking"
    assert outbox(ctx) == []
