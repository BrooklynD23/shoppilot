"""Planner: Haiku router -> Sonnet staged tool loop -> Haiku judge (P2-T8; spec 02 §2, R8, R32).

make_plan never saves; the /api/plan route runs make_plan -> validate_plan -> dry_run ->
save_plan. Nothing here raises for LLM trouble: it becomes Plan(status="error"). The one
exception (R8): force_replay with no recording raises LLMError("replay_miss") -> route 404.
"""

from __future__ import annotations

import copy
import html
import json
import logging
import re
import secrets
import time
from dataclasses import dataclass, field

import app.llm.client as llm
from app.agent.audit import log_action
from app.agent.models import DiffItem, Plan, Step, Validation
from app.agent.validator import READ_TOOLS, PlanContext, validate_step
from app.config import get_settings
from app.llm.client import LLMError, LLMResponse, Trace, recording_key, save_recording
from app.llm.prompts import (
    JUDGE_FORMAT,
    JUDGE_PROMPT,
    PLAN_FORMAT,
    PROMPT_VERSION,
    ROUTER_FORMAT,
    ROUTER_PROMPT,
    SYSTEM_PROMPT,
    TOOL_DESCRIPTIONS,
    user_turn,
)
from app.tools.registry import Ctx, claude_tool_defs, get_tool

MAX_TURNS = 6
PLAN_DEADLINE_S = 90
MAX_REQUEST_CHARS = 2000
RESULT_MAX_CHARS = 8000
TRUNC = "…[truncated, narrow the query]"
TOO_BIG = "Request too big; split it into smaller requests."
REFUSED = "I can't help with that request."
_ID = re.compile(r"\b[OEPC]\d+\b")
_STAGE = {"router": (512, 15.0), "planner": (8000, 60.0), "judge": (1024, 15.0)}
log = logging.getLogger(__name__)


@dataclass
class _Loop:
    request: str
    ctx: Ctx
    trace: Trace
    force_replay: bool
    pc: PlanContext
    steps: list[Step] = field(default_factory=list)
    blocked: list[dict] = field(default_factory=list)
    rejected: set[tuple[str, str]] = field(default_factory=set)


def tool_defs() -> list[dict]:
    """Registry defs sorted by name; prompt descriptions; staged tools get rationale+evidence."""
    out = []
    for d in sorted(claude_tool_defs(), key=lambda t: t["name"]):
        d = copy.deepcopy(d)
        d["description"] = TOOL_DESCRIPTIONS.get(d["name"], d["description"])
        if d["name"] not in READ_TOOLS:
            s = d["input_schema"]
            s["properties"] = {
                **s["properties"],
                "rationale": {"type": "string"},
                "evidence": {"type": "array", "items": {"type": "string"}},
            }
            s["required"] = [*s.get("required", []), "rationale", "evidence"]
        out.append(d)
    return out


def _complete(
    stage: str,
    *,
    trace: Trace,
    force_replay: bool,
    system: str,
    messages: list[dict],
    output_format: dict,
    tools: list[dict] | None = None,
) -> LLMResponse:
    s = get_settings()
    model = s.planner_model if stage == "planner" else s.judge_model
    if force_replay:  # R8: client has no per-call mode switch, so read the recording directly
        path = llm.RECORDINGS_DIR / f"{recording_key(trace.request)}.json"
        idx, trace.n = trace.n, trace.n + 1
        return llm._replay(stage, model, trace, path, idx, None)
    max_tokens, stage_timeout = _STAGE[stage]
    remaining = trace.deadline - time.monotonic()
    if remaining <= 0:  # PLAN_DEADLINE_S bounds the whole plan, not just retry waits
        raise LLMError("busy", TOO_BIG)
    timeout_s = max(1.0, min(stage_timeout, remaining))
    effort = s.planner_effort if stage == "planner" else "low"
    return llm.complete(
        stage=stage,
        model=model,
        system=system,
        messages=messages,
        trace=trace,
        max_tokens=max_tokens,
        effort=effort,
        tools=tools,
        output_format=output_format,
        timeout_s=timeout_s,
    )


def _refusal_text(r: LLMResponse) -> str:
    return str((r.stop_details or {}).get("explanation") or REFUSED)


def _final_json(r: LLMResponse) -> dict:
    """Last text block parsed as JSON; raises ValueError when absent or not an object."""
    texts = [b.get("text", "") for b in r.content if b.get("type") == "text"]
    out = json.loads(texts[-1]) if texts else None
    if not isinstance(out, dict):
        raise ValueError("no JSON object")
    return out


def route(request: str, trace: Trace, *, force_replay: bool = False) -> dict:
    msg = [
        {
            "role": "user",
            "content": f"<owner_request>{html.escape(request, quote=False)}</owner_request>",
        }
    ]
    try:
        r = _complete(
            "router",
            trace=trace,
            force_replay=force_replay,
            system=ROUTER_PROMPT,
            messages=msg,
            output_format=ROUTER_FORMAT,
        )
        if r.stop_reason == "refusal":  # spec 02 §6.1: never fall through to the planner
            return {"reason": "refusal", "route": "reject", "reply": _refusal_text(r)}
        out = _final_json(r)
    except LLMError as e:
        if force_replay and e.kind == "replay_miss":
            raise
        return {"reason": "router unavailable", "route": "plan", "reply": ""}
    except ValueError:
        return {"reason": "router unavailable", "route": "plan", "reply": ""}
    return out if out.get("route") in ("plan", "reject") else {**out, "route": "plan"}


def judge(plan: Plan, trace: Trace, *, force_replay: bool = False) -> dict:
    steps = [s.model_dump(include={"tool", "args", "rationale", "evidence"}) for s in plan.steps]
    body = (
        f"<owner_request>{html.escape(plan.request, quote=False)}</owner_request>\n"
        f"<plan_message>{html.escape(plan.message, quote=False)}</plan_message>\n"
        f"<steps>{html.escape(json.dumps(steps, sort_keys=True), quote=False)}</steps>\n"
        f"<blocked_inputs>{json.dumps(plan.blocked_inputs, sort_keys=True)}"
        "</blocked_inputs>"
    )
    try:
        r = _complete(
            "judge",
            trace=trace,
            force_replay=force_replay,
            system=JUDGE_PROMPT,
            messages=[{"role": "user", "content": body}],
            output_format=JUDGE_FORMAT,
        )
        out = _final_json(r)
        if out.get("verdict") not in ("pass", "warn", "fail"):
            raise ValueError("bad verdict")
        return out
    except (LLMError, ValueError):
        return {"verdict": "warn", "checks": [], "note": "judge unavailable"}


def _result_text(res) -> str:
    text = res.data.get("llm_text") if isinstance(res.data.get("llm_text"), str) else None
    text = text or json.dumps(res.data, sort_keys=True, default=str)
    return text if len(text) <= RESULT_MAX_CHARS else text[:RESULT_MAX_CHARS] + TRUNC


def _run_read(name: str, args: dict, lp: _Loop) -> tuple[str, bool]:
    res = get_tool(name).run(args, lp.ctx)
    if not res.ok:
        return f"REJECTED: {res.error or res.summary}", True
    text = _result_text(res)
    lp.pc.seen_ids |= set(_ID.findall(text))
    for v in res.data.get("verdicts") or []:
        if not v.get("allowed") and v not in lp.blocked:
            lp.blocked.append(v)
            lp.pc.blocked_ids.add(str(v.get("source_id")))
    lp.pc.email_customers.update(res.data.get("email_customers") or {})
    return text, False


def _stage(name: str, args: dict, lp: _Loop) -> tuple[str, bool]:
    args = dict(args)
    rationale, evidence = args.pop("rationale", ""), args.pop("evidence", [])
    step = Step(
        id=f"s{len(lp.steps) + 1}",
        tool=name,
        args=args,
        rationale=str(rationale),
        evidence=[str(e) for e in evidence] if isinstance(evidence, list) else [],
    )
    v = validate_step(step, lp.steps, lp.ctx, lp.pc)
    if not v.ok:  # always re-validate: new evidence or newly staged steps can fix it
        key = (name, json.dumps([args, step.evidence], sort_keys=True))
        if key in lp.rejected:
            return "REJECTED again; drop this step or ask the owner.", True
        lp.rejected.add(key)
        return f"REJECTED: {v.reason}", True
    lp.steps.append(step)
    return f"STAGED {step.id}: {name} — awaiting owner approval, not executed.", False


def _handle_tool_use(block: dict, lp: _Loop) -> dict:
    name, args = block.get("name", ""), block.get("input")
    try:
        get_tool(name)
        ok_args = isinstance(args, dict)
    except KeyError:
        ok_args = False
    if not ok_args:
        text, err = "REJECTED: unknown tool", True
    elif name in READ_TOOLS:
        text, err = _run_read(name, args, lp)
    else:
        text, err = _stage(name, args, lp)
    out = {"type": "tool_result", "tool_use_id": block.get("id"), "content": text}
    return {**out, "is_error": True} if err else out


def _loop(lp: _Loop) -> tuple[str, str]:
    """Run the tool loop. -> (status, message); staged steps accumulate in lp.steps."""
    messages = [{"role": "user", "content": user_turn(lp.request, lp.ctx.today)}]
    tools = tool_defs()
    for _ in range(MAX_TURNS):
        if time.monotonic() > lp.trace.deadline:
            break
        r = _complete(
            "planner",
            trace=lp.trace,
            force_replay=lp.force_replay,
            system=SYSTEM_PROMPT,
            messages=messages,
            output_format=PLAN_FORMAT,
            tools=tools,
        )
        if r.stop_reason == "refusal":
            return "refused", _refusal_text(r)
        uses = [b for b in r.content if b.get("type") == "tool_use"]
        if not uses:
            try:
                out = _final_json(r)
            except ValueError:
                return "error", "The AI returned an unreadable plan. Try again."
            status = out.get("status")
            if status not in ("ready", "needs_clarification", "refused"):
                return "error", "The AI returned an unreadable plan. Try again."
            return status, str(out.get("message", ""))
        messages = [
            *messages,
            {"role": "assistant", "content": r.content},
            {"role": "user", "content": [_handle_tool_use(b, lp) for b in uses]},
        ]
    return "error", TOO_BIG


def _usage_summary(trace: Trace) -> dict:
    calls = [c.model_dump() for c in trace.calls]
    read = sum(c.cache_read_tokens for c in trace.calls)
    total = sum(c.input_tokens + c.cache_read_tokens + c.cache_write_tokens for c in trace.calls)
    sums = {
        k: sum(getattr(c, k) for c in trace.calls)
        for k in ("input_tokens", "cache_read_tokens", "cache_write_tokens", "output_tokens", "ms")
    }
    return {
        "calls": calls,
        **sums,
        "total_cost_usd": round(sum(c.cost_usd for c in trace.calls), 6),
        "cache_hit_pct": round(100 * read / total, 1) if total else 0.0,
        "prompt_version": PROMPT_VERSION,
    }


def _plan(request: str, ctx: Ctx, trace: Trace, force_replay: bool) -> Plan:
    r = route(request, trace, force_replay=force_replay)
    if r.get("route") == "reject":
        return Plan(request=request, steps=[], status="refused", message=str(r.get("reply", "")))
    lp = _Loop(request, ctx, trace, force_replay, PlanContext(request=request, seen_ids=set()))
    try:
        status, message = _loop(lp)
    except LLMError as e:
        if force_replay and e.kind == "replay_miss":
            raise
        return Plan(
            request=request,
            steps=[],
            blocked_inputs=lp.blocked,
            status="error",
            message=e.user_message,
        )
    steps = lp.steps if status == "ready" else []  # clarify/refuse/error: nothing approvable
    plan = Plan(
        request=request, steps=steps, blocked_inputs=lp.blocked, status=status, message=message
    )
    if status == "ready" and steps:
        plan.judge = judge(plan, trace, force_replay=force_replay)
    return plan


def _fully_recorded(trace: Trace, plan: Plan) -> bool:
    """Replay is positional: a stage that fell open unrecorded would misalign every call."""
    stages = [c["stage"] for c in trace.recorded]
    return bool(stages) and stages[0] == "router" and (plan.judge is None or stages[-1] == "judge")


def make_plan(request: str, ctx: Ctx, *, force_replay: bool = False) -> Plan:
    if not request.strip() or len(request) > MAX_REQUEST_CHARS:
        raise ValueError(f"request must be 1 to {MAX_REQUEST_CHARS} characters")
    trace = Trace(
        request=request, session_id=ctx.session_id, deadline=time.monotonic() + PLAN_DEADLINE_S
    )
    plan = _plan(request, ctx, trace, force_replay)
    plan.usage = _usage_summary(trace)
    plan.prompt_version = PROMPT_VERSION
    plan.source = "replay" if any(c.replayed for c in trace.calls) else "live"
    if (
        get_settings().llm_mode == "record"
        and plan.status != "error"
        and _fully_recorded(trace, plan)
    ):
        save_recording(trace)
    return plan


def save_plan(ctx: Ctx, plan: Plan, validations: list[Validation], diff: list[DiffItem]) -> str:
    """Insert plans row (status 'proposed'), set plan.id, log 'plan'. Caller commits (R32)."""
    pid = "plan_" + secrets.token_hex(6)
    plan.id = pid
    ctx.db.execute(
        "INSERT INTO plans (id, request, plan_json, validations_json, diff_json, status,"
        " created_at) VALUES (?,?,?,?,?,'proposed',?)",
        (
            pid,
            plan.request,
            plan.model_dump_json(),
            json.dumps([v.model_dump() for v in validations]),
            json.dumps([d.model_dump() for d in diff]),
            ctx.now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        ),
    )
    log_action(
        ctx,
        "plan",
        {
            "summary": f"Plan: {len(plan.steps)} steps ({plan.status})",
            "status": plan.status,
            "steps": len(plan.steps),
            "prompt_version": plan.prompt_version,
            "source": plan.source,
        },
        plan_id=pid,
    )
    return pid
