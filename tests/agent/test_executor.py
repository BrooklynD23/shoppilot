"""P2-T10: per-step executor with lock-then-check claim (R1)."""
import json
from datetime import timedelta

import pytest

from app.agent.executor import PlanError, claim_plan, execute
from app.agent.models import Plan, Step, Validation
from app.seed.generate import DAMAGED_ORDER_ID
from app.tools import registry
from app.tools.registry import Registered, ToolResult, ToolSpec

_SCHEMA = {"type": "object", "additionalProperties": False, "required": ["tag"],
           "properties": {"tag": {"type": "string"}}}


@pytest.fixture
def runs():
    return []


@pytest.fixture(autouse=True)
def tools(monkeypatch, runs):
    registry.load_tools()
    flaky = {"n": 0}

    def ok(args, ctx):
        runs.append(args["tag"])
        return ToolResult(ok=True, summary=f"did {args['tag']}", undo_token=f"tok_{args['tag']}")

    def fail(args, ctx):
        runs.append(args["tag"])
        return ToolResult(ok=False, summary="nope", error="fail_reason")

    def boom(args, ctx):
        runs.append(args["tag"])
        raise RuntimeError("secret internals")

    def flaky_run(args, ctx):
        runs.append(args["tag"])
        flaky["n"] += 1
        return ToolResult(ok=flaky["n"] > 1, summary="flaky", error=None if flaky["n"] > 1 else "x")

    for name, fn in (("ok_tool", ok), ("fail_tool", fail), ("boom_tool", boom),
                     ("flaky_tool", flaky_run)):
        spec = ToolSpec(name=name, description=name, input_schema=_SCHEMA,
                        destructive=True, moves_money=False, undoable=False)
        monkeypatch.setitem(registry._TOOLS, name, Registered(spec, fn, lambda a, c: None))
    for name in ("mark_shipped", "send_email", "refund_order"):  # count real-tool runs too
        reg = registry._TOOLS[name]

        def counted(args, ctx, _run=reg.run, _name=name):
            runs.append(_name)
            return _run(args, ctx)
        monkeypatch.setitem(registry._TOOLS, name, Registered(reg.spec, counted, reg.preview,
                                                              reg.undo))


def _plan(*steps, status="ready", request="req"):
    return Plan(request=request, status=status, steps=[
        Step(id=f"s{i}", tool=t, args=a, rationale="r", evidence=list(ev))
        for i, (t, a, ev) in enumerate(steps, 1)])


def fake(tool, tag):
    return (tool, {"tag": tag}, ())


def _save(ctx, plan, validations=None, created_at=None, pid="plan_000000000001"):
    vals = validations or [Validation(step_id=s.id, ok=True) for s in plan.steps]
    ts = (created_at or ctx.now).strftime("%Y-%m-%dT%H:%M:%SZ")
    ctx.db.execute(
        "INSERT INTO plans (id, request, plan_json, validations_json, diff_json, status,"
        " created_at) VALUES (?,?,?,?,?,'proposed',?)",
        (pid, plan.request, plan.model_dump_json(),
         json.dumps([v.model_dump() for v in vals]), "[]", ts))
    return pid


def _run(ctx, plan, ids, **kw):
    pid = _save(ctx, plan, **kw)
    return execute(claim_plan(ctx, pid), ids, ctx)


def _status(ctx, pid="plan_000000000001"):
    return ctx.db.execute("SELECT status FROM plans WHERE id = ?", (pid,)).fetchone()[0]


@pytest.fixture
def yesterday_ids(ctx):
    day = (ctx.today - timedelta(days=1)).isoformat()
    return [r[0] for r in ctx.db.execute(
        "SELECT id FROM orders WHERE status = 'paid' AND substr(created_at,1,10) = ?"
        " ORDER BY id", (day,)).fetchall()]


def test_only_approved_run(ctx, runs):
    r = _run(ctx, _plan(fake("ok_tool", "a"), fake("ok_tool", "b")), {"s1"})
    assert runs == ["a"] and [x.step_id for x in r] == ["s1"] and r[0].ok
    assert _status(ctx) == "executing"


def test_stop_after_failure(ctx, runs):
    r = _run(ctx, _plan(fake("ok_tool", "a"), fake("fail_tool", "b"), fake("ok_tool", "c")),
             {"s1", "s2", "s3"})
    assert [x.error for x in r] == [None, "fail_reason", "not_run"] and runs == ["a", "b"]


def test_exception_contained(ctx):
    r = _run(ctx, _plan(fake("boom_tool", "a")), {"s1"})
    assert r[0].error == "tool_crashed" and not r[0].ok
    assert "Traceback" not in r[0].summary and "secret" not in r[0].summary


def test_double_execute_returns_stored(ctx, runs):
    pid = _save(ctx, _plan(fake("ok_tool", "a")))
    r1 = execute(claim_plan(ctx, pid), {"s1"}, ctx)
    r2 = execute(claim_plan(ctx, pid), {"s1"}, ctx)
    assert runs == ["a"] and r2[0].replayed and not r1[0].replayed
    assert r2[0].audit_id == r1[0].audit_id and r2[0].ok and r2[0].summary == "did a"
    assert _status(ctx, pid) == "executed"


def test_failed_step_retryable(ctx, runs):
    pid = _save(ctx, _plan(fake("flaky_tool", "f")))
    assert not execute(claim_plan(ctx, pid), {"s1"}, ctx)[0].ok
    assert execute(claim_plan(ctx, pid), {"s1"}, ctx)[0].ok and runs == ["f", "f"]


def test_expired(ctx):
    pid = _save(ctx, _plan(fake("ok_tool", "a")), created_at=ctx.now - timedelta(minutes=16))
    with pytest.raises(PlanError) as e:
        claim_plan(ctx, pid)
    assert e.value.code == "expired"


def test_not_found(ctx):
    with pytest.raises(PlanError) as e:
        claim_plan(ctx, "plan_ffffffffffff")
    assert e.value.code == "not_found"


def test_unknown_step_id(ctx):
    pid = _save(ctx, _plan(fake("ok_tool", "a")))
    with pytest.raises(PlanError) as e:
        execute(claim_plan(ctx, pid), {"s9"}, ctx)
    assert e.value.code == "invalid"


def test_unticked_prerequisite_rejects_all(ctx, runs, yesterday_ids):
    plan = _plan(("mark_shipped", {"order_ids": yesterday_ids, "carrier": "usps"}, yesterday_ids),
                 ("send_email", {"order_ids": yesterday_ids, "template": "tracking",
                                 "custom_body": None}, yesterday_ids))
    r = _run(ctx, plan, {"s2"})
    assert len(r) == 1 and not r[0].ok and r[0].error == "invalid"
    assert "before" in r[0].summary and runs == []


def test_prerequisite_run_earlier_then_ok(ctx, runs, yesterday_ids):
    plan = _plan(("mark_shipped", {"order_ids": yesterday_ids, "carrier": "usps"}, yesterday_ids),
                 ("send_email", {"order_ids": yesterday_ids, "template": "tracking",
                                 "custom_body": None}, yesterday_ids))
    pid = _save(ctx, plan)
    assert execute(claim_plan(ctx, pid), {"s1"}, ctx)[0].ok
    r = execute(claim_plan(ctx, pid), {"s2"}, ctx)
    assert r[0].ok, r[0].summary
    assert runs == ["mark_shipped", "send_email"] and _status(ctx, pid) == "executed"


def test_stale_state_rejected(ctx, runs):
    plan = _plan(("refund_order", {"order_id": DAMAGED_ORDER_ID, "amount_cents": None,
                                   "reason": "requested_by_customer"}, ["owner_request"]),
                 request=f"refund {DAMAGED_ORDER_ID}")
    ctx.db.execute("UPDATE orders SET status = 'refunded', refunded_cents = total_cents"
                   " WHERE id = ?", (DAMAGED_ORDER_ID,))
    r = _run(ctx, plan, {"s1"})
    assert not r[0].ok and r[0].error == "invalid" and runs == []


def test_stored_validation_not_ok(ctx, runs):
    plan = _plan(fake("ok_tool", "a"))
    r = _run(ctx, plan, {"s1"}, validations=[Validation(step_id="s1", ok=False, reason="bad")])
    assert r[0].error == "invalid" and "bad" in r[0].summary and runs == []


def test_audit_rows(ctx):
    _run(ctx, _plan(fake("ok_tool", "a"), fake("fail_tool", "b")), {"s1", "s2"})
    rows = [tuple(r) for r in ctx.db.execute(
        "SELECT kind, plan_id, step_id, tool, undo_token FROM audit_log"
        " WHERE plan_id IS NOT NULL ORDER BY rowid")]
    pid = "plan_000000000001"
    assert rows == [("confirm", pid, "s1", "ok_tool", None),
                    ("execute", pid, "s1", "ok_tool", "tok_a"),
                    ("confirm", pid, "s2", "fail_tool", None),
                    ("error", pid, "s2", "fail_tool", None)]
    sr = ctx.db.execute("SELECT step_id, result_json FROM step_runs").fetchall()
    assert [r[0] for r in sr] == ["s1"] and "tok_a" not in sr[0][1]


def test_invalid_step_logs_validate(ctx):
    _run(ctx, _plan(fake("ok_tool", "a")), {"s1"},
         validations=[Validation(step_id="s1", ok=False, reason="bad")])
    kinds = [r[0] for r in ctx.db.execute("SELECT kind FROM audit_log WHERE plan_id IS NOT NULL")]
    assert kinds == ["validate"]


def test_plan_status_final(ctx):
    pid = _save(ctx, _plan(fake("ok_tool", "a"), fake("fail_tool", "b")))
    execute(claim_plan(ctx, pid), {"s1", "s2"}, ctx)
    assert _status(ctx, pid) == "executing"  # s2 failed: not every step has a step_runs row


def test_non_ready_plan_not_claimable(ctx):
    pid = _save(ctx, _plan(fake("ok_tool", "a"), status="needs_clarification"))
    with pytest.raises(PlanError) as e:
        claim_plan(ctx, pid)
    assert e.value.code == "invalid"
