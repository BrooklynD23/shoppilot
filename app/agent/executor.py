"""Per-step, approval-gated executor (P2-T10, contract R1).

Each /api/execute call: claim_plan (write lock, then checks), then for every requested step in
plan order: replay a stored step_runs row, or re-validate against the live DB and run it.
Only successes are stored, so a failed step can be retried. Tools never log or commit (R23).
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, datetime, timedelta

from app.agent.audit import log_action
from app.agent.models import Plan, Step, StepResult
from app.agent.validator import PlanContext, _plan_context, validate_step
from app.config import get_settings
from app.safety import policy
from app.tools.registry import Ctx, ToolResult, get_tool

log = logging.getLogger(__name__)
_TS = "%Y-%m-%dT%H:%M:%SZ"


class PlanError(Exception):
    """code: not_found (404) | expired (410) | invalid (422)."""

    def __init__(self, code: str, message: str | None = None):
        super().__init__(message or code)
        self.code = code


def _parse_ts(ts: str) -> datetime:
    dt = datetime.fromisoformat(ts)
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def claim_plan(ctx: Ctx, plan_id: str) -> Plan:
    """R1 lock-then-check. Re-callable; an executed plan stays claimable so replays work."""
    if not ctx.db.in_transaction:
        ctx.db.execute("BEGIN IMMEDIATE")  # session write lock before any check
    cur = ctx.db.execute(
        "UPDATE plans SET status = CASE status WHEN 'proposed' THEN 'executing' ELSE status END"
        " WHERE id = ? AND status IN ('proposed', 'executing', 'executed')",
        (plan_id,),
    )
    if cur.rowcount == 0:
        raise PlanError("not_found")
    plan_json, created_at = ctx.db.execute(
        "SELECT plan_json, created_at FROM plans WHERE id = ?", (plan_id,)
    ).fetchone()
    ttl = timedelta(minutes=get_settings().plan_ttl_minutes)
    if ctx.now - _parse_ts(created_at) > ttl:
        raise PlanError("expired")
    plan = Plan.model_validate_json(plan_json).model_copy(update={"id": plan_id})
    if plan.status != "ready":
        raise PlanError("invalid")
    return plan


def _stored_validations(ctx: Ctx, plan_id: str) -> dict[str, dict]:
    row = ctx.db.execute("SELECT validations_json FROM plans WHERE id = ?", (plan_id,)).fetchone()
    if row is None:
        raise PlanError("not_found")
    return {v["step_id"]: v for v in json.loads(row[0])}


def _stored_run(ctx: Ctx, plan_id: str, step_id: str) -> StepResult | None:
    row = ctx.db.execute(
        "SELECT result_json FROM step_runs WHERE plan_id = ? AND step_id = ?", (plan_id, step_id)
    ).fetchone()
    if row is None:
        return None
    return StepResult.model_validate_json(row[0]).model_copy(update={"replayed": True})


def _stored_diffs(ctx: Ctx, plan_id: str) -> dict[str, dict]:
    row = ctx.db.execute("SELECT diff_json FROM plans WHERE id = ?", (plan_id,)).fetchone()
    return {d["step_id"]: d for d in json.loads(row[0] or "[]")} if row else {}


def _exceeds_preview(res: ToolResult, diff: dict | None) -> bool:
    """#60: the run ordered or charged more than the owner saw in the preview."""
    if not diff:
        return False
    approved = dict(diff.get("after") or {})
    if diff.get("amount_cents") is not None:
        approved["amount_cents"] = diff["amount_cents"]
    for key in ("qty", "amount_cents"):
        want, got = approved.get(key), res.data.get(key)
        if isinstance(want, int) and isinstance(got, int) and got > want:
            return True
    return False


def _why_invalid(step: Step, stored: dict | None, ctx: Ctx, pc: PlanContext) -> str | None:
    if not stored or not stored.get("ok"):
        return (stored or {}).get("reason") or "no valid plan-time check"
    live = validate_step(step, [], ctx, pc)
    if not live.ok:
        return live.reason
    return policy.check_plan(Plan(request=pc.request, steps=[step]), ctx)[0].reason


def _run_tool(step: Step, ctx: Ctx, diff: dict | None = None) -> ToolResult:
    """Run inside a savepoint so a crash, a failed run or a run past the preview leaves no
    partial writes."""
    ctx.db.execute("SAVEPOINT step_run")
    try:
        res = get_tool(step.tool).run(step.args, ctx)
    except Exception:  # noqa: BLE001 - contain tool crashes; details go to the server log
        log.exception("tool %s crashed on step %s", step.tool, step.id)
        res = ToolResult(
            ok=False, summary="This step failed; nothing else ran.", error="tool_crashed"
        )
    if res.ok and _exceeds_preview(res, diff):
        res = ToolResult(
            ok=False,
            error="changed_since_preview",
            summary="Not run: the amount changed since you approved it. Ask for a fresh plan.",
        )
    if res.ok:
        ctx.db.execute("RELEASE step_run")
    else:
        ctx.db.execute("ROLLBACK TO step_run")
        ctx.db.execute("RELEASE step_run")
    return res


def _run_step(
    plan: Plan, step: Step, stored: dict | None, ctx: Ctx, pc: PlanContext, diff: dict | None = None
) -> StepResult:
    ids = {"plan_id": plan.id, "step_id": step.id, "tool": step.tool}
    reason = _why_invalid(step, stored, ctx, pc)
    if reason:
        summary = "Not run: " + reason
        aid = log_action(ctx, "validate", {"summary": summary, "reason": reason}, **ids)
        return StepResult(step_id=step.id, ok=False, summary=summary, error="invalid", audit_id=aid)
    log_action(ctx, "confirm", {"summary": f"Owner approved {step.tool}"}, **ids)
    res = _run_tool(step, ctx, diff)
    aid = log_action(
        ctx,
        "execute" if res.ok else "error",
        {"summary": res.summary, "args": step.args},
        undo_token=res.undo_token if res.ok else None,
        **ids,
    )
    out = StepResult(**res.model_dump(), step_id=step.id, audit_id=aid)
    if res.ok:
        ctx.db.execute(
            "INSERT INTO step_runs (plan_id, step_id, audit_id, result_json, created_at)"
            " VALUES (?,?,?,?,?)",
            (
                plan.id,
                step.id,
                aid,
                out.model_dump_json(exclude={"undo_token"}),
                ctx.now.strftime(_TS),
            ),
        )
    return out


def execute(plan: Plan, approved_step_ids: set[str], ctx: Ctx) -> list[StepResult]:
    """One StepResult per requested id, plan order. Stops at the first failure in this call."""
    if not approved_step_ids or not approved_step_ids <= {s.id for s in plan.steps}:
        raise PlanError("invalid")
    stored = _stored_validations(ctx, plan.id)
    diffs = _stored_diffs(ctx, plan.id)
    pc = _plan_context(plan, ctx)
    out: list[StepResult] = []
    failed = False
    for step in (s for s in plan.steps if s.id in approved_step_ids):
        r = _stored_run(ctx, plan.id, step.id)
        if r is None and failed:
            r = StepResult(
                step_id=step.id,
                ok=False,
                summary="Not run (an earlier step failed)",
                error="not_run",
            )
        elif r is None:
            r = _run_step(plan, step, stored.get(step.id), ctx, pc, diffs.get(step.id))
            failed = not r.ok
        out.append(r)
    done = ctx.db.execute(
        "SELECT COUNT(*) FROM step_runs WHERE plan_id = ?", (plan.id,)
    ).fetchone()[0]
    if done == len(plan.steps):
        ctx.db.execute("UPDATE plans SET status = 'executed' WHERE id = ?", (plan.id,))
    return out
