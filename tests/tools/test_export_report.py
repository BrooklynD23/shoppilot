from datetime import UTC, date, datetime

import pytest

from app.integrations.export import EXPORT_KINDS
from app.tools import export_report as er
from app.tools.registry import Ctx


@pytest.fixture
def ctx(mem_conn):
    return Ctx("sid-test", mem_conn, datetime(2026, 10, 15, 9, 0, tzinfo=UTC), date(2026, 10, 15))


@pytest.mark.parametrize("kind", EXPORT_KINDS)
def test_each_kind_returns_route_url(kind, ctx):
    r = er.run({"kind": kind}, ctx)
    assert r.ok and r.data["url"] == f"/api/export/{kind}"
    assert r.undo_token is None
    stem, ext = {
        "orders_csv": ("orders", "csv"),
        "refunds_csv": ("refunds", "csv"),
        "report_pdf": ("report", "pdf"),
    }[kind]
    assert er.preview({"kind": kind}, ctx).after == {"file": f"{stem}-2026-10-15.{ext}"}


@pytest.mark.parametrize("kind", EXPORT_KINDS)
def test_preview_file_matches_render(kind, ctx, monkeypatch):
    from app.integrations import export

    want = export.render(kind, ctx)[2]
    monkeypatch.setattr(export, "render", lambda *a: (_ for _ in ()).throw(AssertionError))
    assert er.preview({"kind": kind}, ctx).after["file"] == want


def test_unknown_kind_fails(ctx):
    r = er.run({"kind": "audit_csv"}, ctx)
    assert not r.ok and r.error == "invalid"


def test_spec_flags():
    assert er.SPEC.destructive is False
    assert er.SPEC.moves_money is False and er.SPEC.undoable is False
    assert er.SPEC.input_schema["properties"]["kind"]["enum"] == list(EXPORT_KINDS)
