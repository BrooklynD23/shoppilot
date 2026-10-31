"""Dry-run (P2-T9): one DiffItem per plan step from tool previews. No writes."""

from __future__ import annotations

import copy
import logging

from app.agent.models import DiffItem, Plan, Step
from app.tools.registry import Ctx, get_tool

log = logging.getLogger(__name__)


def _preview(step: Step, ctx: Ctx) -> DiffItem:
    ctx.db.execute("SAVEPOINT dry_run")
    try:  # deepcopy: a mutating preview must not change the validated plan (R32)
        diff = get_tool(step.tool).preview(copy.deepcopy(step.args), ctx)
        return diff.model_copy(update={"step_id": step.id})
    except Exception:
        log.exception("preview failed: step=%s tool=%s", step.id, step.tool)
        return DiffItem(step_id=step.id, before={}, after={"error": "Preview unavailable"})
    finally:  # previews must not write: always discard whatever they did
        ctx.db.execute("ROLLBACK TO dry_run")
        ctx.db.execute("RELEASE dry_run")


def dry_run(plan: Plan, ctx: Ctx) -> list[DiffItem]:
    return [_preview(s, ctx) for s in plan.steps]
