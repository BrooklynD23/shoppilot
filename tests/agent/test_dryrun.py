import pytest

from app.agent.dryrun import dry_run
from app.agent.models import DiffItem, Plan, Step
from app.tools import registry
from app.tools.registry import Registered, ToolResult, ToolSpec


def _spec(name: str, money: bool = False) -> ToolSpec:
    return ToolSpec(
        name=name,
        description=name,
        input_schema={"type": "object"},
        destructive=money,
        moves_money=money,
        undoable=False,
    )


def _run(args, ctx):
    return ToolResult(ok=True, summary="ran")


def _echo_preview(args, ctx):
    return DiffItem(step_id="", before={"x": 0}, after={"x": args.get("x", 1)})


def _refund_preview(args, ctx):
    return DiffItem(
        step_id="",
        before={"refunded": 0},
        after={"refunded": args["amount_cents"]},
        amount_cents=args["amount_cents"],
    )


def _crash_preview(args, ctx):
    raise RuntimeError("boom")


def _mutating_preview(args, ctx):
    args["x"] = 99
    args.setdefault("nested", {})["y"] = 1
    return DiffItem(step_id="", before={}, after={})


def _write_then_crash_preview(args, ctx):
    ctx.db.execute("INSERT INTO meta (key, value) VALUES ('leak', 'x')")
    raise RuntimeError("boom")


@pytest.fixture
def ctx(mem_conn, fixed_now, anchor):
    # schema-only DB: dry-run needs no seed data (fake tools only)
    return registry.Ctx("sid", mem_conn, fixed_now, anchor)


@pytest.fixture
def fake_tools(monkeypatch):
    for name, prev, money in (
        ("fake_echo", _echo_preview, False),
        ("fake_refund", _refund_preview, True),
        ("fake_crash", _crash_preview, False),
        ("fake_mutate", _mutating_preview, False),
        ("fake_write", _write_then_crash_preview, False),
    ):
        monkeypatch.setitem(registry._TOOLS, name, Registered(_spec(name, money), _run, prev))


def _plan(*tools_args) -> Plan:
    steps = [
        Step(id=f"s{i}", tool=t, args=a, rationale="r") for i, (t, a) in enumerate(tools_args, 1)
    ]
    return Plan(request="req", steps=steps)


plan3 = _plan(("fake_echo", {"x": 1}), ("fake_echo", {"x": 2}), ("fake_echo", {"x": 3}))
refund_plan = _plan(("fake_refund", {"amount_cents": 4200}))
plan_with_crashing_preview = _plan(("fake_echo", {}), ("fake_crash", {}), ("fake_echo", {"x": 5}))


def test_one_diff_per_step_in_order(ctx, fake_tools):
    assert [d.step_id for d in dry_run(plan3, ctx)] == ["s1", "s2", "s3"]


def test_amount_passed_through(ctx, fake_tools):
    assert dry_run(refund_plan, ctx)[0].amount_cents == 4200


def test_preview_crash_isolated(ctx, fake_tools):
    d = dry_run(plan_with_crashing_preview, ctx)
    assert d[1].step_id == "s2" and d[1].before == {}
    assert d[1].after == {"error": "Preview unavailable"} and d[2].after == {"x": 5}


def test_unknown_tool_isolated(ctx, fake_tools):
    d = dry_run(_plan(("no_such_tool", {})), ctx)
    assert d[0].after == {"error": "Preview unavailable"}


def test_no_writes(ctx, fake_tools):
    before = ctx.db.total_changes
    dry_run(plan3, ctx)
    assert ctx.db.total_changes == before


def test_mutating_preview_leaves_plan_args(ctx, fake_tools):
    p = _plan(("fake_mutate", {"x": 1, "nested": {}}))
    dry_run(p, ctx)
    assert p.steps[0].args == {"x": 1, "nested": {}}


def test_preview_writes_rolled_back(ctx, fake_tools):
    d = dry_run(_plan(("fake_write", {}), ("fake_echo", {"x": 2})), ctx)
    ctx.db.commit()  # save_plan's later commit must not persist preview writes
    assert ctx.db.execute("SELECT COUNT(*) FROM meta WHERE key='leak'").fetchone()[0] == 0
    assert d[0].after == {"error": "Preview unavailable"} and d[1].after == {"x": 2}
