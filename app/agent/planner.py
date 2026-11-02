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
from app.agent.validator import OWNER, READ_TOOLS, PlanContext, validate_step
from app.config import get_settings
from app.llm.client import LLMError, LLMResponse, Trace, recording_key, save_recording
from app.llm.prompts import (
    JUDGE_CHECKS,
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
# Turn 1 must call a tool: Haiku otherwise answers from guesses. Haiku 5.5 accepts forced
# tool_choice (Sonnet/Opus 5.5 return 400); that turn skips thinking, later turns are "auto".
FIRST_TURN = {"type": "any"}
PLAN_DEADLINE_S = 90
MAX_REQUEST_CHARS = 2000
RESULT_MAX_CHARS = 24_000  # fits list_orders' 50-row max (seed: 22.4K); 8K hid 2 of 20 orders
TRUNC = "…[truncated, narrow the query]"
TOO_BIG = "Request too big; split it into smaller requests."
REFUSED = "I can't help with that request."
_ID = re.compile(r"\b[OEPC]\d+\b")
_STAGE = {"router": (512, 15.0), "planner": (8000, 60.0), "judge": (1024, 15.0)}
MAX_TRACE, MAX_DETAIL = 60, 160  # spec 09 §2
_END = {  # plan status -> planner trace event (spec 09 §3)
    "ready": ("done", "Plan ready: {n} for your approval."),
    "needs_clarification": ("ask", "One question for you before it plans further."),
    "refused": ("reject", "Declined this request."),
    "error": ("error", "Stopped before the plan was ready."),
}
log = logging.getLogger(__name__)


@dataclass
class PlanTrace(Trace):
    """LLM trace plus the spec 09 agent trace: display data, never sent to a model."""

    t0: float = 0.0  # time.monotonic() when make_plan started
    events: list[dict] = field(default_factory=list)


@dataclass
class _Loop:
    request: str
    ctx: Ctx
    trace: PlanTrace
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
    tool_choice: dict | None = None,
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
        tool_choice=tool_choice,
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


# ---------- agent trace (spec 09): templates, ids and counts only ----------
def _emit(
    trace: PlanTrace, agent: str, event: str, detail: str, step_id: str | None = None
) -> None:
    """detail never holds email text or model free text (spec 09 §4)."""
    last = trace.events[-1]["t_ms"] if trace.events else 0
    t_ms = max(last, int((time.monotonic() - trace.t0) * 1000))  # non-decreasing
    detail = " ".join(detail.split())[:MAX_DETAIL]
    trace.events.append(
        {"agent": agent, "event": event, "detail": detail, "t_ms": t_ms, "step_id": step_id}
    )


def _capped(events: list[dict]) -> list[dict]:
    """At most MAX_TRACE: drop the latest reads first; failing that, keep head and end."""
    extra = len(events) - MAX_TRACE
    if extra <= 0:
        return events
    drop = set([i for i, e in enumerate(events) if e["event"] == "read"][-extra:])
    kept = [e for i, e in enumerate(events) if i not in drop]
    return kept[: MAX_TRACE - 3] + kept[-3:] if len(kept) > MAX_TRACE else kept


def _strings(x) -> list[str]:
    """Every string in model-written tool input, dict keys included."""
    if isinstance(x, dict):
        return [s for k, v in x.items() for s in (*_strings(k), *_strings(v))]
    if isinstance(x, list):
        return [s for v in x for s in _strings(v)]
    return [x] if isinstance(x, str) else []


def _why(reason: str | None, step: Step) -> str:
    """The validator's reason, unless it quotes model-written text (ids, schema words are ok)."""
    ours = json.dumps(get_tool(step.tool).spec.input_schema)
    for s in _strings([step.args, step.evidence]):
        if not s or _ID.fullmatch(s) or s == OWNER or json.dumps(s) in ours:
            continue
        if reason and (s in reason or repr(s)[1:-1] in reason):  # f-string or jsonschema repr
            return f"{step.tool} failed a check"
    return reason or "validation failed"


def _n(k: float, noun: str) -> str:
    return f"{k} {noun}{'' if k == 1 else 's'}"


def _read_detail(name: str, args: dict, data: dict) -> tuple[str, str]:
    """(agent, detail) for a read tool: counts and ids, never row text."""
    if name == "list_inbox":
        verdicts = data.get("verdicts") or []
        bad = sum(not v.get("allowed") for v in verdicts)
        return "planner", f"list_inbox: {_n(len(verdicts) - bad, 'email')} allowed, {bad} blocked."
    if name == "flag_anomalies":
        return "forecaster", f"flag_anomalies: {_n(data.get('total_flagged', 0), 'flagged order')}."
    if name == "forecast_demand":
        items = [data["forecast"]] if "forecast" in data else data.get("items") or []
        risk = [f for f in items if f.get("days_to_stockout") is not None]
        if not risk:
            return (
                "forecaster",
                f"forecast_demand: no stockout ahead for {_n(len(items), 'product')}.",
            )
        f = min(risk, key=lambda f: f["days_to_stockout"])
        days = f["days_to_stockout"]
        when = "today" if days <= 0 else f"in about {_n(days, 'day')}"
        return "forecaster", (
            f"forecast_demand: {len(risk)} at risk. {f['product_id']} runs out first, {when}."
        )
    if name == "list_orders":  # status passed the tool's enum check
        status = "" if args.get("status") == "any" else f"{args.get('status')} "
        return "planner", f"list_orders: {_n(len(data.get('orders') or []), status + 'order')}."
    return "planner", f"{name}: done."


def _judge_event(j: dict) -> tuple[str, str]:
    if j.get("note") == "judge unavailable":
        return "warn", "Review unavailable. Check the plan yourself."
    if j.get("verdict") == "pass":
        return "pass", "Pass. The plan matches your request."
    checks = [c for c in j.get("checks") or [] if isinstance(c, dict)]
    failed = [c["name"] for c in checks if c.get("pass") is False and c.get("name") in JUDGE_CHECKS]
    names = ", ".join(failed) or "none named"
    return "warn", f"{str(j.get('verdict')).capitalize()}. Failed checks: {names}."


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
        _emit(lp.trace, "planner", "read", f"{name}: rejected its arguments.")
        return f"REJECTED: {res.error or res.summary}", True
    text = _result_text(res)
    lp.pc.seen_ids |= set(_ID.findall(text))
    for v in res.data.get("verdicts") or []:
        if not v.get("allowed") and v not in lp.blocked:
            lp.blocked.append(v)
            lp.pc.blocked_ids.add(str(v.get("source_id")))
            eid = _ID.search(str(v.get("source_id")))  # id and label only, never the reason
            who = eid.group() if eid else "An email"
            _emit(lp.trace, "guard", "block", f"{who} blocked as {v.get('label')}.")
    lp.pc.email_customers.update(res.data.get("email_customers") or {})
    agent, detail = _read_detail(name, args, res.data)
    _emit(lp.trace, agent, "read", detail)
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
    sid = step.id if v.ok else None  # a rejected write never gets an id
    ids = ", ".join(s for s in _strings(args) if _ID.fullmatch(s))
    what = f"{name} for {ids}" if ids else name
    _emit(
        lp.trace, "planner", "staged", f"Staged {sid}: {what}." if sid else f"Proposed {what}.", sid
    )
    if not v.ok:  # always re-validate: new evidence or newly staged steps can fix it
        key = (name, json.dumps([args, step.evidence], sort_keys=True))
        again = key in lp.rejected
        why = _why(v.reason, step)
        _emit(lp.trace, "validator", "reject", f"Rejected{' again' if again else ''}: {why}.")
        if again:
            return "REJECTED again; drop this step or ask the owner.", True
        lp.rejected.add(key)
        return f"REJECTED: {v.reason}", True
    lp.steps.append(step)
    _emit(lp.trace, "validator", "pass", f"{step.id} passes.", step.id)
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
    for n in range(1, MAX_TURNS + 1):
        if time.monotonic() > lp.trace.deadline:
            break
        _emit(lp.trace, "planner", "start", f"Turn {n}: {_n(len(lp.steps), 'step')} staged so far.")
        r = _complete(
            "planner",
            trace=lp.trace,
            force_replay=lp.force_replay,
            system=SYSTEM_PROMPT,
            messages=messages,
            output_format=PLAN_FORMAT,
            tools=tools,
            tool_choice=FIRST_TURN if n == 1 else None,
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


def _plan(request: str, ctx: Ctx, trace: PlanTrace, force_replay: bool) -> Plan:
    _emit(trace, "router", "start", "Reading your request.")
    r = route(request, trace, force_replay=force_replay)
    if r.get("route") == "reject":  # the reply is model text: never in the trace
        _emit(trace, "router", "reject", "Not shop work. Declined before planning.")
        return Plan(request=request, steps=[], status="refused", message=str(r.get("reply", "")))
    if r.get("reason") == "router unavailable":
        _emit(trace, "router", "warn", "Router unavailable. Sent to the planner.")
    else:
        _emit(trace, "router", "pass", "Shop work. Routed to the planner.")
    lp = _Loop(request, ctx, trace, force_replay, PlanContext(request=request, seen_ids=set()))
    try:
        status, message = _loop(lp)
    except LLMError as e:
        if force_replay and e.kind == "replay_miss":
            raise
        status, message = "error", e.user_message
    steps = lp.steps if status == "ready" else []  # clarify/refuse/error: nothing approvable
    event, detail = _END[status]
    _emit(trace, "planner", event, detail.format(n=_n(len(steps), "step")))
    plan = Plan(
        request=request, steps=steps, blocked_inputs=lp.blocked, status=status, message=message
    )
    if status == "ready" and steps:
        _emit(trace, "judge", "start", "Reviewing the plan against your request.")
        plan.judge = judge(plan, trace, force_replay=force_replay)
        _emit(trace, "judge", *_judge_event(plan.judge))
    return plan


def _fully_recorded(trace: Trace, plan: Plan) -> bool:
    """Replay is positional: a stage that fell open unrecorded would misalign every call."""
    stages = [c["stage"] for c in trace.recorded]
    return bool(stages) and stages[0] == "router" and (plan.judge is None or stages[-1] == "judge")


def make_plan(request: str, ctx: Ctx, *, force_replay: bool = False) -> Plan:
    if not request.strip() or len(request) > MAX_REQUEST_CHARS:
        raise ValueError(f"request must be 1 to {MAX_REQUEST_CHARS} characters")
    t0 = time.monotonic()
    trace = PlanTrace(
        request=request, session_id=ctx.session_id, deadline=t0 + PLAN_DEADLINE_S, t0=t0
    )
    plan = _plan(request, ctx, trace, force_replay)
    plan.trace = _capped(trace.events)
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
