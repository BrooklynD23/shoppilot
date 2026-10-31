"""Agent plan models (P2-T1, contract R2). Data only, no logic."""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel

from app.tools.registry import ToolResult


class Step(BaseModel):
    id: str
    tool: str
    args: dict
    rationale: str
    evidence: list[str] = []


class Plan(BaseModel):
    request: str
    steps: list[Step]
    blocked_inputs: list[dict] = []  # GuardVerdict.model_dump() dicts
    id: str = ""  # "plan_" + 12 hex, set by save_plan
    status: Literal["ready", "needs_clarification", "refused", "error"] = "ready"
    message: str = ""
    usage: dict = {}
    judge: dict | None = None
    prompt_version: str = ""
    source: Literal["live", "replay"] = "live"
    trace: list[dict] = []  # spec 09: display-only agent events, never fed back to a model


class DiffItem(BaseModel):
    step_id: str
    before: dict
    after: dict
    amount_cents: int | None = None


class Validation(BaseModel):
    step_id: str
    ok: bool
    reason: str | None = None


class StepResult(ToolResult):
    step_id: str
    audit_id: str | None = None
    replayed: bool = False
