"""CSV and PDF exports (spec 05 §10). Built in memory, never cached, no disk writes."""

import csv
import io

from reportlab.lib import colors
from reportlab.lib.pagesizes import letter
from reportlab.lib.styles import getSampleStyleSheet
from reportlab.platypus import Paragraph, SimpleDocTemplate, Spacer, Table, TableStyle

EXPORT_KINDS = ("orders_csv", "refunds_csv", "report_pdf")

_FORMULA_PREFIXES = ("=", "+", "-", "@", "\t", "\r")

_ORDERS_SQL = """
SELECT o.id, c.name, c.email, o.created_at, o.status, o.total_cents, o.refunded_cents,
       o.currency, o.carrier, o.tracking_number, o.shipped_at
FROM orders o JOIN customers c ON c.id = o.customer_id ORDER BY o.created_at, o.id"""
_ORDERS_HEADER = ("order_id", "customer", "email", "created_at", "status", "total_cents",
                  "refunded_cents", "currency", "carrier", "tracking_number", "shipped_at")

_REFUNDS_SQL = """
SELECT id, order_id, amount_cents, reason, stripe_refund_id, mode, created_at
FROM refunds ORDER BY created_at, id"""
_REFUNDS_HEADER = ("refund_id", "order_id", "amount_cents", "reason", "stripe_refund_id",
                   "mode", "created_at")


def _safe_cell(v: object) -> str:
    """Neutralise spreadsheet formulas: names can come from attacker-controlled email."""
    s = "" if v is None else str(v)
    return "'" + s if s.startswith(_FORMULA_PREFIXES) else s


def _csv(header: tuple[str, ...], rows: list) -> bytes:
    buf = io.StringIO()
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(header)
    w.writerows([_safe_cell(v) for v in row] for row in rows)
    return buf.getvalue().encode("utf-8")


def _latin1(v: object) -> str:
    # ponytail: latin-1 only; embed DejaVuSans TTF if non-Latin names appear
    return ("" if v is None else str(v)).encode("latin-1", "replace").decode("latin-1")


def _money(cents: int) -> str:
    return f"${cents / 100:,.2f}"


def _table(header: list[str], rows: list[list[str]]) -> Table:
    t = Table([header, *rows], repeatRows=1)
    t.setStyle(TableStyle([
        ("FONTNAME", (0, 0), (-1, 0), "Helvetica-Bold"),
        ("FONTSIZE", (0, 0), (-1, -1), 8),
        ("GRID", (0, 0), (-1, -1), 0.25, colors.grey),
        ("BACKGROUND", (0, 0), (-1, 0), colors.lightgrey),
    ]))
    return t


def _pdf(ctx) -> bytes:
    orders = ctx.db.execute(_ORDERS_SQL).fetchall()
    refunds = ctx.db.execute(_REFUNDS_SQL).fetchall()
    styles = getSampleStyleSheet()
    total = sum(r[5] for r in orders)
    refunded = sum(r[2] for r in refunds)
    story = [
        Paragraph("ShopPilot+ store report", styles["Title"]),
        Paragraph(f"Store date: {ctx.today.isoformat()}", styles["Normal"]),
        Paragraph(f"Orders: {len(orders)} | Sales: {_money(total)} | "
                  f"Refunds: {len(refunds)} ({_money(refunded)})", styles["Normal"]),
        Spacer(1, 12),
        Paragraph("Orders", styles["Heading2"]),
        _table(["Order", "Customer", "Status", "Total", "Refunded"],
               [[_latin1(r[0]), _latin1(r[1]), _latin1(r[4]), _money(r[5]), _money(r[6])]
                for r in orders]),
        Spacer(1, 12),
        Paragraph("Refunds", styles["Heading2"]),
        _table(["Order", "Stripe refund", "Amount", "Reason", "Mode"],
               [[_latin1(r[1]), _latin1(r[4]), _money(r[2]), _latin1(r[3]), _latin1(r[5])]
                for r in refunds]),
    ]
    buf = io.BytesIO()
    SimpleDocTemplate(buf, pagesize=letter, title="ShopPilot+ report").build(story)
    return buf.getvalue()


def render(kind: str, ctx) -> tuple[bytes, str, str]:
    """Return (body, media_type, filename) for one of EXPORT_KINDS; ValueError otherwise."""
    if kind not in EXPORT_KINDS:
        raise ValueError(f"unknown export kind: {kind!r}")
    stamp = ctx.today.isoformat()
    if kind == "orders_csv":
        body = _csv(_ORDERS_HEADER, ctx.db.execute(_ORDERS_SQL).fetchall())
        return body, "text/csv", f"orders-{stamp}.csv"
    if kind == "refunds_csv":
        body = _csv(_REFUNDS_HEADER, ctx.db.execute(_REFUNDS_SQL).fetchall())
        return body, "text/csv", f"refunds-{stamp}.csv"
    return _pdf(ctx), "application/pdf", f"report-{stamp}.pdf"
