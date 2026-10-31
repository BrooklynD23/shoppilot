"""Dry-run (P2-T9): one DiffItem per plan step from tool previews. No writes."""
from __future__ import annotations

import logging

from app.agent.models import DiffItem, Plan, Step
from app.tools.registry import Ctx, get_tool

log = logging.getLogger(__name__)


def _preview(step: Step, ctx: Ctx) -> DiffItem:
    try:
        diff = get_tool(step.tool).preview(step.args, ctx)
        return diff.model_copy(update={"step_id": step.id})
    except Exception:
        log.exception("preview failed: step=%s tool=%s", step.id, step.tool)
        return DiffItem(step_id=step.id, before={}, after={"error": "Preview unavailable"})


def dry_run(plan: Plan, ctx: Ctx) -> list[DiffItem]:
    return [_preview(s, ctx) for s in plan.steps]
