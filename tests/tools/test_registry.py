import dataclasses
import sqlite3
from datetime import UTC, date, datetime

import pytest
from pydantic import ValidationError

from app.tools import registry as r
from app.tools.registry import (
    Ctx,
    ToolResult,
    ToolSpec,
    claude_tool_defs,
    get_tool,
    get_tools,
    load_tools,
    register,
    validate_args,
)

SCHEMA = {
    "type": "object",
    "properties": {"order_id": {"type": "string"}},
    "required": ["order_id"],
    "additionalProperties": False,
}


@pytest.fixture(autouse=True)
def _reset():
    saved = dict(r._TOOLS)
    r._TOOLS.clear()
    yield
    r._TOOLS.clear()
    r._TOOLS.update(saved)


def spec(name="mark_shipped", schema=SCHEMA, **kw):
    return ToolSpec(
        name=name,
        description="d",
        input_schema=schema,
        destructive=kw.get("destructive", False),
        moves_money=kw.get("moves_money", False),
        undoable=kw.get("undoable", False),
    )


def run(args, ctx):
    return ToolResult(ok=True, summary="ok")


def preview(args, ctx):
    return None


def undo(token, ctx):
    return ToolResult(ok=True, summary="u")


def test_register_and_list():
    register(spec(undoable=True), run, preview, undo)
    assert [t.name for t in get_tools()] == ["mark_shipped"]
    assert get_tool("mark_shipped").undo is undo


def test_duplicate_rejected():
    register(spec(), run, preview)
    with pytest.raises(ValueError, match="already registered"):
        register(spec(), run, preview)


def test_bad_name_rejected():
    with pytest.raises(ValueError):
        register(spec(name="Bad-Name"), run, preview)


def test_non_strict_schema_rejected():
    bad = {"type": "object", "properties": {}}
    with pytest.raises(ValueError):
        register(spec(schema=bad), run, preview)


def test_invalid_schema_rejected():
    bad = {"type": "nonsense", "additionalProperties": False}
    with pytest.raises(ValueError):
        register(spec(schema=bad), run, preview)


def test_money_must_be_destructive():
    with pytest.raises(ValueError):
        register(spec(moves_money=True, destructive=False), run, preview)


def test_undoable_needs_undo_fn():
    with pytest.raises(ValueError):
        register(spec(undoable=True), run, preview)
    with pytest.raises(ValueError):
        register(spec(undoable=False), run, preview, undo)


def test_validate_args():
    register(spec(), run, preview)
    assert validate_args("mark_shipped", {"order_id": "O0001"}) is None
    assert "order_id" in validate_args("mark_shipped", {})
    assert validate_args("mark_shipped", {"order_id": "O1", "x": 1}) is not None


def test_unknown_tool():
    with pytest.raises(KeyError):
        get_tool("nope")


def test_claude_defs_strict():
    register(spec(), run, preview)
    d = claude_tool_defs()[0]
    assert d["strict"] is True and d["name"] == "mark_shipped"
    assert set(d) == {"name", "description", "input_schema", "strict"}


def test_ctx_frozen():
    c = Ctx("s", sqlite3.connect(":memory:"), datetime.now(UTC), date(2026, 10, 15))
    with pytest.raises(dataclasses.FrozenInstanceError):
        c.today = date(2026, 1, 1)


def test_load_tools_idempotent():
    load_tools()
    before = get_tools()
    load_tools()
    assert get_tools() == before


def test_undo_token_must_be_str():
    with pytest.raises(ValidationError):
        ToolResult(ok=True, summary="s", undo_token={"a": 1})


def test_flags_required():
    with pytest.raises(ValidationError):
        ToolSpec(name="x", description="d", input_schema={})


def test_root_property_missing_from_required():
    bad = {
        "type": "object",
        "properties": {"a": {"type": "string"}},
        "required": [],
        "additionalProperties": False,
    }
    with pytest.raises(ValueError):
        register(spec(schema=bad), run, preview)


def test_nested_object_must_be_strict():
    bad = {
        "type": "object",
        "required": ["o"],
        "additionalProperties": False,
        "properties": {"o": {"type": "object", "properties": {}}},
    }
    with pytest.raises(ValueError):
        register(spec(schema=bad), run, preview)


def test_date_format_checked():
    s = {
        "type": "object",
        "required": ["d"],
        "additionalProperties": False,
        "properties": {"d": {"type": "string", "format": "date"}},
    }
    register(spec(schema=s), run, preview)
    assert validate_args("mark_shipped", {"d": "yesterday"}) is not None
    assert validate_args("mark_shipped", {"d": "2026-10-15"}) is None


def test_defs_are_copies():
    register(spec(), run, preview)
    claude_tool_defs()[0]["input_schema"]["properties"]["rationale"] = {"type": "string"}
    assert validate_args("mark_shipped", {"order_id": "O1"}) is None


def test_ref_defs_rejected():
    s = {
        "type": "object",
        "properties": {"o": {"$ref": "#/$defs/O"}},
        "required": ["o"],
        "additionalProperties": False,
        "$defs": {"O": {"type": "object", "properties": {}}},
    }
    with pytest.raises(ValueError):
        register(spec(schema=s), run, preview)


def test_untyped_object_node_must_be_strict():
    s = {
        "type": "object",
        "properties": {"o": {"properties": {"a": {"type": "string"}}}},
        "required": ["o"],
        "additionalProperties": False,
    }
    with pytest.raises(ValueError):
        register(spec(schema=s), run, preview)


def test_get_tools_returns_copies():
    register(spec(), run, preview)
    get_tools()[0].input_schema["required"] = []
    assert validate_args("mark_shipped", {}) is not None
    assert claude_tool_defs()[0]["input_schema"]["required"] == ["order_id"]


def test_name_trailing_newline_rejected():
    with pytest.raises(ValueError):
        register(spec(name="mark_shipped\n"), run, preview)
