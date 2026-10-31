import pytest
from pydantic import ValidationError

from app.agent.models import DiffItem, Plan, Step, StepResult, Validation
from app.tools.registry import ToolResult


def test_plan_defaults():
    p = Plan(request="x", steps=[])
    assert p.status == "ready" and p.id == "" and p.blocked_inputs == [] and p.judge is None
    assert p.source == "live" and p.usage == {} and p.message == "" and p.prompt_version == ""


def test_plan_roundtrip():
    p = Plan(
        request="r",
        steps=[
            Step(
                id="s1",
                tool="mark_shipped",
                args={"order_ids": ["O0001"], "carrier": "usps"},
                rationale="why",
                evidence=["O0001"],
            )
        ],
    )
    assert Plan.model_validate_json(p.model_dump_json()) == p


def test_status_rejects_unknown():
    with pytest.raises(ValidationError):
        Plan(request="r", steps=[], status="done")


def test_source_rejects_unknown():
    with pytest.raises(ValidationError):
        Plan(request="r", steps=[], source="mock")


def test_mutable_defaults_not_shared():
    a, b = Plan(request="a", steps=[]), Plan(request="b", steps=[])
    a.usage["x"] = 1
    a.blocked_inputs.append({"source_id": "E002"})
    assert b.usage == {} and b.blocked_inputs == []


def test_step_result_extends_tool_result():
    r = StepResult(ok=True, summary="done", step_id="s1")
    assert isinstance(r, ToolResult)
    assert r.audit_id is None and r.replayed is False and r.undo_token is None


def test_diff_and_validation_defaults():
    assert DiffItem(step_id="", before={}, after={}).amount_cents is None
    v = Validation(step_id="s1", ok=True)
    assert v.reason is None
