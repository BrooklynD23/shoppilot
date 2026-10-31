"""Strict tool registry (P1-T4). Tools never log, commit or close (R23)."""
from __future__ import annotations

import copy
import importlib
import pkgutil
import re
import sqlite3
import sys
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime
from typing import TYPE_CHECKING, Any

from jsonschema import Draft202012Validator
from jsonschema.exceptions import SchemaError, best_match
from pydantic import BaseModel, ConfigDict

if TYPE_CHECKING:  # no runtime import from app.agent
    from app.agent.models import DiffItem  # noqa: F401

_NAME = re.compile(r"^[a-z][a-z0-9_]{0,63}$")


@dataclass(frozen=True)
class Ctx:
    session_id: str  # never logged or sent out; use db.session_hash
    db: sqlite3.Connection  # open transaction; tools never commit/close
    now: datetime  # wall clock, tz-aware UTC
    today: date  # store date = meta.anchor


class ToolSpec(BaseModel):
    model_config = ConfigDict(frozen=True)
    name: str
    description: str
    input_schema: dict
    destructive: bool
    moves_money: bool
    undoable: bool


class ToolResult(BaseModel):
    ok: bool
    summary: str
    data: dict = {}
    undo_token: str | None = None
    error: str | None = None


@dataclass(frozen=True)
class Registered:
    spec: ToolSpec
    run: Callable[..., ToolResult]
    preview: Callable[..., Any]
    undo: Callable[..., ToolResult] | None = None


_TOOLS: dict[str, Registered] = {}


def _check_strict(s: Any, path: str = "input_schema") -> None:
    """Every object subschema: additionalProperties false, all properties required."""
    if isinstance(s, list):
        for i, x in enumerate(s):
            _check_strict(x, f"{path}[{i}]")
        return
    if not isinstance(s, dict):
        return
    t = s.get("type")
    if t == "object" or (isinstance(t, list) and "object" in t):
        if s.get("additionalProperties") is not False:
            raise ValueError(f"{path}: additionalProperties must be false")
        if set(s.get("required", [])) != set(s.get("properties", {})):
            raise ValueError(f"{path}: every property must be required")
    for k, v in s.get("properties", {}).items():
        _check_strict(v, f"{path}.{k}")
    for k in ("items", "anyOf", "oneOf", "allOf"):
        if k in s:
            _check_strict(s[k], f"{path}.{k}")


def register(spec: ToolSpec, run, preview, undo=None) -> None:
    if spec.name in _TOOLS:
        raise ValueError(f"tool {spec.name!r} already registered")
    if not _NAME.match(spec.name):
        raise ValueError(f"bad tool name {spec.name!r}")
    try:
        Draft202012Validator.check_schema(spec.input_schema)
    except SchemaError as e:
        raise ValueError(f"invalid input_schema: {e.message}") from e
    if spec.input_schema.get("type") != "object":
        raise ValueError("input_schema must be type object")
    _check_strict(spec.input_schema)
    if spec.moves_money and not spec.destructive:
        raise ValueError("moves_money requires destructive")
    if spec.undoable != (undo is not None):
        raise ValueError("undoable must match presence of undo")
    _TOOLS[spec.name] = Registered(spec.model_copy(deep=True), run, preview, undo)


def get_tools() -> list[ToolSpec]:
    return [t.spec for t in _TOOLS.values()]


def get_tool(name: str) -> Registered:
    return _TOOLS[name]


def validate_args(name: str, args: dict) -> str | None:
    err = best_match(Draft202012Validator(
        get_tool(name).spec.input_schema,
        format_checker=Draft202012Validator.FORMAT_CHECKER).iter_errors(args))
    return err.message if err else None


def claude_tool_defs() -> list[dict]:
    return [{"name": t.name, "description": t.description,
             "input_schema": copy.deepcopy(t.input_schema), "strict": True} for t in get_tools()]


def load_tools() -> None:
    import app.tools as pkg

    for m in pkgutil.iter_modules(pkg.__path__):
        full = f"{pkg.__name__}.{m.name}"
        if m.name != "registry" and full not in sys.modules:
            importlib.import_module(full)


def _reset_for_tests() -> None:
    _TOOLS.clear()
