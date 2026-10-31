"""export_report tool (P5-I8). Pure: returns the download URL; the /api/export route renders."""

from __future__ import annotations

from app.agent.models import DiffItem
from app.integrations.export import EXPORT_FILES, EXPORT_KINDS
from app.tools.registry import Ctx, ToolResult, ToolSpec, register

SPEC = ToolSpec(
    name="export_report",
    description="Prepare a download link for an export: orders CSV, refunds CSV, or a PDF report.",
    destructive=False,
    moves_money=False,
    undoable=False,
    input_schema={
        "type": "object",
        "additionalProperties": False,
        "required": ["kind"],
        "properties": {"kind": {"type": "string", "enum": list(EXPORT_KINDS)}},
    },
)


def run(args: dict, ctx: Ctx) -> ToolResult:
    kind = args.get("kind")
    if kind not in EXPORT_KINDS:
        return ToolResult(ok=False, summary=f"Unknown export kind: {kind!r}", error="invalid")
    url = f"/api/export/{kind}"
    return ToolResult(ok=True, summary=f"Export ready: {url}", data={"kind": kind, "url": url})


def preview(args: dict, ctx: Ctx) -> DiffItem:
    kind = args.get("kind")
    if kind not in EXPORT_KINDS:
        return DiffItem(step_id="", before={}, after={"error": f"Unknown export kind: {kind!r}"})
    stem, ext = EXPORT_FILES[kind]
    return DiffItem(step_id="", before={}, after={"file": f"{stem}-{ctx.today.isoformat()}.{ext}"})


register(SPEC, run, preview)
