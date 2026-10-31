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
    assert er.preview({"kind": kind}, ctx).after["url"] == f"/api/export/{kind}"


def test_unknown_kind_fails(ctx):
    r = er.run({"kind": "audit_csv"}, ctx)
    assert not r.ok and r.error == "invalid"


def test_spec_flags():
    assert er.SPEC.destructive is False
    assert er.SPEC.moves_money is False and er.SPEC.undoable is False
    assert er.SPEC.input_schema["properties"]["kind"]["enum"] == list(EXPORT_KINDS)
