import csv
import io

import pytest

from app.integrations import export


@pytest.mark.parametrize(
    "v,out",
    [("=1+1", "'=1+1"), ("+x", "'+x"), ("-x", "'-x"), ("@x", "'@x"),
     ("\tx", "'\tx"), ("\rx", "'\rx"), ("ok", "ok"), (42, "42"), (None, "")],
)
def test_csv_injection_guard(v, out):
    assert export._safe_cell(v) == out


def test_export_kinds():
    assert export.EXPORT_KINDS == ("orders_csv", "refunds_csv", "report_pdf")


def test_orders_csv_header_and_rows(ctx):
    body, mt, fn = export.render("orders_csv", ctx)
    assert mt == "text/csv" and fn.endswith(".csv")
    assert body.splitlines()[0].startswith(b"order_id,")
    n = ctx.db.execute("SELECT COUNT(*) FROM orders").fetchone()[0]
    assert n > 0 and len(list(csv.reader(io.StringIO(body.decode())))) == n + 1


def test_orders_csv_escapes_hostile_name(ctx):
    cid = ctx.db.execute("SELECT customer_id FROM orders LIMIT 1").fetchone()[0]
    ctx.db.execute("UPDATE customers SET name = ? WHERE id = ?", ("=HYPERLINK(1)", cid))
    body, _, _ = export.render("orders_csv", ctx)
    assert b"'=HYPERLINK(1)" in body


def _add_refund(ctx):
    oid = ctx.db.execute("SELECT id FROM orders LIMIT 1").fetchone()[0]
    ctx.db.execute(
        "INSERT INTO refunds VALUES (?,?,?,?,?,?,?)",
        ("rf_1", oid, 500, "requested_by_customer", "re_test123", "mock",
         "2026-10-15T09:00:00+00:00"),
    )
    return oid


def test_refunds_csv(ctx):
    body, mt, fn = export.render("refunds_csv", ctx)
    n = ctx.db.execute("SELECT COUNT(*) FROM refunds").fetchone()[0]
    assert mt == "text/csv" and fn.endswith(".csv") and len(body.splitlines()) == n + 1
    assert body.splitlines()[0].startswith(b"refund_id,")
    _add_refund(ctx)
    body, _, _ = export.render("refunds_csv", ctx)
    lines = body.splitlines()
    assert len(lines) == n + 2 and b"re_test123,mock" in body


def test_report_pdf_is_pdf(ctx):
    _add_refund(ctx)
    body, mt, fn = export.render("report_pdf", ctx)
    assert body[:5] == b"%PDF-" and mt == "application/pdf" and fn.endswith(".pdf")


def test_pdf_survives_non_latin_name(ctx):
    cid = ctx.db.execute("SELECT customer_id FROM orders LIMIT 1").fetchone()[0]
    ctx.db.execute("UPDATE customers SET name = ? WHERE id = ?", ("Zoë 李 🚀", cid))
    body, _, _ = export.render("report_pdf", ctx)
    assert body[:5] == b"%PDF-"


def test_unknown_kind_raises(ctx):
    with pytest.raises(ValueError):
        export.render("audit_csv", ctx)
