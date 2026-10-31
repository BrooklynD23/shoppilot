"""P2-T8: planner (router, staged tool loop, judge, save_plan). Scripted fake SDK, no network."""

import json
from types import SimpleNamespace

import pytest

import app.agent.planner as planner
import app.llm.client as client
from app.agent.models import DiffItem, Plan, Validation
from app.agent.planner import MAX_TURNS, make_plan, save_plan, tool_defs
from app.config import get_settings
from app.llm.client import LLMError, recording_key
from app.llm.prompts import PROMPT_VERSION
from app.safety import inbound_guard
from app.safety.inbound_guard import GuardVerdict
from app.seed.generate import DAMAGED_EMAIL_ID, DAMAGED_ORDER_ID, INJECTION_EMAIL_ID
from app.tools import registry

HAIKU, SONNET = "claude-haiku-5-5", "claude-sonnet-5-5"
USAGE = {
    "input_tokens": 100,
    "cache_creation_input_tokens": 0,
    "cache_read_input_tokens": 300,
    "output_tokens": 50,
}
ANY = {"status": "any", "created_from": None, "created_to": None, "order_ids": None}


def _resp(content, stop="end_turn", model=SONNET):
    return {"content": content, "stop_reason": stop, "model": model, "usage": USAGE}


def _text(obj, model):
    return _resp([{"type": "text", "text": json.dumps(obj)}], model=model)


def router(route="plan", reply=""):
    return _text({"reason": "r", "route": route, "reply": reply}, HAIKU)


def final(status="ready", message="ok"):
    return _text({"status": status, "message": message}, SONNET)


def judge_pass():
    return _text({"checks": [], "verdict": "pass"}, HAIKU)


_ids = iter(range(10**6))


def tool_use(*calls):
    """tool_use(("name", args), ...) -> one assistant turn with parallel calls."""
    blocks = [
        {"type": "tool_use", "id": f"tu_{next(_ids)}", "name": n, "input": a} for n, a in calls
    ]
    return _resp(blocks, stop="tool_use")


class Script:
    def __init__(self):
        self.results, self.sent = [], []

    def push(self, *rs):
        self.results.extend(rs)

    def __call__(self, kwargs):
        self.sent.append(json.loads(json.dumps(kwargs, default=str)))
        r = self.results.pop(0)
        if isinstance(r, Exception):
            raise r
        return r

    @property
    def models(self):
        return [k["model"] for k in self.sent]

    def last_tool_results(self):
        return [
            b
            for b in self.sent[-1]["messages"][-1]["content"]
            if isinstance(b, dict) and b.get("type") == "tool_result"
        ]

    def tool_results_after(self, i):
        return [
            b
            for b in self.sent[i]["messages"][-1]["content"]
            if isinstance(b, dict) and b.get("type") == "tool_result"
        ]


@pytest.fixture(autouse=True)
def setup(monkeypatch):
    monkeypatch.setenv("LLM_MODE", "live")
    get_settings.cache_clear()
    registry.load_tools()

    def _screen(text, source_id):
        bad = source_id == f"email:{INJECTION_EMAIL_ID}"
        return GuardVerdict(
            source_id=source_id,
            allowed=not bad,
            label="injection" if bad else "clean",
            reason="r",
            score=0.0,
        )

    monkeypatch.setattr(inbound_guard, "screen", _screen)


@pytest.fixture
def script(monkeypatch):
    s = Script()
    monkeypatch.setattr(client, "_send", s)
    return s


def _paid_ids(ctx, n=2):
    return [
        r[0]
        for r in ctx.db.execute(
            "SELECT id FROM orders WHERE status='paid' ORDER BY id LIMIT ?", (n,)
        )
    ]


def test_router_reject_skips_sonnet(script, ctx):
    script.push(router("reject", reply="I help with shop operations."))
    p = make_plan("what's the weather?", ctx)
    assert p.status == "refused" and p.steps == [] and script.models == [HAIKU]
    assert p.message == "I help with shop operations."


def test_read_then_stage_then_final(script, ctx):
    ids = _paid_ids(ctx)
    script.push(
        router(),
        tool_use(("list_orders", {**ANY, "order_ids": ids})),
        tool_use(
            (
                "mark_shipped",
                {"order_ids": ids, "carrier": "usps", "rationale": "r", "evidence": ids},
            )
        ),
        final("ready", "Ship 2."),
        judge_pass(),
    )
    p = make_plan("Ship yesterday's orders", ctx)
    assert p.status == "ready" and [s.tool for s in p.steps] == ["mark_shipped"]
    s = p.steps[0]
    assert "rationale" not in s.args and "evidence" not in s.args
    assert s.evidence == ids and s.rationale == "r" and s.id == "s1"
    assert "STAGED s1" in script.tool_results_after(3)[0]["content"]
    assert p.judge["verdict"] == "pass" and p.id == ""  # make_plan does not save (R32)
    assert script.models == [HAIKU, SONNET, SONNET, SONNET, HAIKU]


def test_rejected_step_fed_back_and_dropped(script, ctx):
    big = {
        "order_id": DAMAGED_ORDER_ID,
        "amount_cents": 10**7,
        "reason": "requested_by_customer",
        "rationale": "r",
        "evidence": ["owner_request"],
    }
    script.push(
        router(),
        tool_use(("refund_order", big)),
        tool_use(("refund_order", big)),
        final("needs_clarification", "How much?"),
    )
    p = make_plan(f"refund {DAMAGED_ORDER_ID}", ctx)
    first, again = script.tool_results_after(2)[0], script.tool_results_after(3)[0]
    assert first["is_error"] and first["content"].startswith("REJECTED:")
    assert again["is_error"] and "REJECTED again" in again["content"]
    assert p.status == "needs_clarification" and p.steps == [] and p.judge is None


def test_clarification_discards_steps(script, ctx):
    ids = _paid_ids(ctx, 1)
    script.push(
        router(),
        tool_use(("list_orders", {**ANY, "order_ids": ids})),
        tool_use(
            (
                "mark_shipped",
                {"order_ids": ids, "carrier": "ups", "rationale": "r", "evidence": ids},
            )
        ),
        final("needs_clarification", "Which carrier?"),
    )
    p = make_plan("ship stuff", ctx)
    assert p.status == "needs_clarification" and p.steps == [] and p.message == "Which carrier?"


def test_refusal_stop_reason(script, ctx):
    script.push(router(), _resp([], stop="refusal"))
    p = make_plan("do something bad", ctx)
    assert p.status == "refused" and p.steps == []


def test_refusal_uses_stop_details(script, ctx):
    r = {**_resp([], stop="refusal"), "stop_details": {"explanation": "Not allowed."}}
    script.push(router(), r)
    p = make_plan("do something bad", ctx)
    assert p.status == "refused" and p.message == "Not allowed."


def test_router_refusal_skips_sonnet(script, ctx):
    r = {**_resp([], stop="refusal", model=HAIKU), "stop_details": {"explanation": "No."}}
    script.push(r)
    p = make_plan("do something bad", ctx)
    assert script.models == [HAIKU] and p.status == "refused" and p.message == "No."


def test_router_refusal_default_message(script, ctx):
    script.push(_resp([], stop="refusal", model=HAIKU))
    p = make_plan("do something bad", ctx)
    assert script.models == [HAIKU] and p.status == "refused" and p.message


def test_record_skips_save_when_router_fell_open(script, ctx, monkeypatch):
    monkeypatch.setenv("LLM_MODE", "record")
    get_settings.cache_clear()
    saved = []
    monkeypatch.setattr(planner, "save_recording", saved.append)
    script.push(LLMError("overloaded"), final("needs_clarification", "?"))
    p = make_plan("hm", ctx)
    assert p.status == "needs_clarification" and saved == []


def test_record_skips_save_when_judge_fell_open(script, ctx, monkeypatch):
    monkeypatch.setenv("LLM_MODE", "record")
    get_settings.cache_clear()
    saved = []
    monkeypatch.setattr(planner, "save_recording", saved.append)
    ids = _paid_ids(ctx, 1)
    script.push(
        router(),
        tool_use(("list_orders", {**ANY, "order_ids": ids})),
        tool_use(
            (
                "mark_shipped",
                {"order_ids": ids, "carrier": "usps", "rationale": "r", "evidence": ids},
            )
        ),
        final(),
        LLMError("overloaded"),
    )
    p = make_plan("ship it", ctx)
    assert p.status == "ready" and p.judge["verdict"] == "warn" and saved == []


def test_record_saves_complete_trace(script, ctx, monkeypatch):
    monkeypatch.setenv("LLM_MODE", "record")
    get_settings.cache_clear()
    saved = []
    monkeypatch.setattr(planner, "save_recording", saved.append)
    script.push(router(), final("needs_clarification", "?"))
    make_plan("hm", ctx)
    assert len(saved) == 1


def test_max_turns(script, ctx):
    script.push(router(), *[tool_use(("list_inbox", {})) for _ in range(MAX_TURNS)])
    p = make_plan("loop forever", ctx)
    assert p.status == "error" and "split" in p.message and p.steps == []
    assert script.models.count(SONNET) == MAX_TURNS


def test_llm_error_becomes_error_plan(script, ctx):
    err = LLMError("overloaded")
    script.push(router(), err)  # _send raising LLMError propagates out of complete()
    p = make_plan("ship", ctx)
    assert p.status == "error" and p.message == err.user_message and p.steps == []


def test_judge_failure_is_warn(script, ctx, monkeypatch):
    ids = _paid_ids(ctx, 1)
    script.push(
        router(),
        tool_use(("list_orders", {**ANY, "order_ids": ids})),
        tool_use(
            (
                "mark_shipped",
                {"order_ids": ids, "carrier": "usps", "rationale": "r", "evidence": ids},
            )
        ),
        final(),
        _resp([{"type": "text", "text": "not json"}], model=HAIKU),
    )
    p = make_plan("ship it", ctx)
    assert p.status == "ready" and p.judge["verdict"] == "warn"


def test_tool_defs_augmented():
    d = {t["name"]: t for t in tool_defs()}
    assert {"rationale", "evidence"} <= set(d["refund_order"]["input_schema"]["required"])
    assert "rationale" not in d["list_orders"]["input_schema"]["properties"]
    assert [t["name"] for t in tool_defs()] == sorted(d)
    from app.llm.prompts import TOOL_DESCRIPTIONS

    assert d["refund_order"]["description"] == TOOL_DESCRIPTIONS["refund_order"]


def test_registry_schema_not_mutated():
    before = registry.claude_tool_defs()
    tool_defs()
    assert registry.claude_tool_defs() == before


def test_every_tool_classified():
    from app.agent.validator import READ_TOOLS

    names = {t.name for t in registry.get_tools()}
    assert names >= READ_TOOLS


def test_all_tool_results_in_one_message(script, ctx):
    script.push(
        router(),
        tool_use(
            ("list_orders", ANY), ("list_inbox", {}), ("list_orders", {**ANY, "status": "paid"})
        ),
        final("needs_clarification", "What next?"),
    )
    make_plan("look around", ctx)
    assert len(script.tool_results_after(2)) == 3


def test_inbox_blocked_inputs_collected(script, ctx):
    script.push(router(), tool_use(("list_inbox", {})), final("needs_clarification", "?"))
    p = make_plan("check inbox", ctx)
    assert any(
        b["source_id"].endswith(INJECTION_EMAIL_ID) and not b["allowed"] for b in p.blocked_inputs
    )


def test_usage_summed(script, ctx):
    script.push(router(), final("needs_clarification", "?"))
    p = make_plan("hm", ctx)
    calls = p.usage["calls"]
    assert len(calls) == 2 and p.prompt_version == PROMPT_VERSION
    assert p.usage["total_cost_usd"] == pytest.approx(sum(c["cost_usd"] for c in calls))
    assert p.usage["prompt_version"] == PROMPT_VERSION
    assert p.usage["cache_hit_pct"] == pytest.approx(75.0)
    for k in ("input_tokens", "cache_read_tokens", "cache_write_tokens", "output_tokens", "ms"):
        assert p.usage[k] == sum(c[k] for c in calls)
    assert (p.usage["input_tokens"], p.usage["cache_read_tokens"], p.usage["output_tokens"]) == (
        200,
        600,
        100,
    )


def test_plan_saved_and_logged(ctx):
    p = Plan(request="r", steps=[])
    pid = save_plan(
        ctx, p, [Validation(step_id="s1", ok=True)], [DiffItem(step_id="s1", before={}, after={})]
    )
    assert pid.startswith("plan_") and len(pid) == 17 and p.id == pid
    row = ctx.db.execute(
        "SELECT status, request, plan_json, validations_json FROM plans WHERE id=?", (pid,)
    ).fetchone()
    assert row[0] == "proposed" and row[1] == "r" and json.loads(row[2])["id"] == pid
    assert json.loads(row[3])[0]["step_id"] == "s1"
    assert (
        ctx.db.execute("SELECT kind FROM audit_log WHERE plan_id=?", (pid,)).fetchone()[0] == "plan"
    )


def test_force_replay_sets_source(script, ctx, tmp_path, monkeypatch):
    monkeypatch.setattr(client, "RECORDINGS_DIR", tmp_path)
    req = "replay me"
    rec = {
        "request": req,
        "calls": [
            {"stage": "router", "model": HAIKU, "response": router()},
            {"stage": "planner", "model": SONNET, "response": final("needs_clarification", "?")},
        ],
    }
    (tmp_path / f"{recording_key(req)}.json").write_text(json.dumps(rec))
    p = make_plan(req, ctx, force_replay=True)
    assert p.source == "replay" and script.sent == [] and p.status == "needs_clarification"
    assert all(c["replayed"] for c in p.usage["calls"])


def test_force_replay_miss_raises(script, ctx, tmp_path, monkeypatch):
    # R8: route maps LLMError(kind="replay_miss") to 404; must not become a saved error plan
    monkeypatch.setattr(client, "RECORDINGS_DIR", tmp_path)
    with pytest.raises(LLMError) as ei:
        make_plan("nothing recorded", ctx, force_replay=True)
    assert ei.value.kind == "replay_miss" and script.sent == []


def test_force_replay_planner_miss_raises(script, ctx, tmp_path, monkeypatch):
    monkeypatch.setattr(client, "RECORDINGS_DIR", tmp_path)
    req = "router only"
    rec = {"request": req, "calls": [{"stage": "router", "model": HAIKU, "response": router()}]}
    (tmp_path / f"{recording_key(req)}.json").write_text(json.dumps(rec))
    with pytest.raises(LLMError) as ei:
        make_plan(req, ctx, force_replay=True)
    assert ei.value.kind == "replay_miss"


def _fake_clock(monkeypatch, script, jumps):
    """planner sees clock[0]; after the n-th sent call, clock jumps to jumps[n]."""
    clock = [0.0]
    monkeypatch.setattr(planner, "time", SimpleNamespace(monotonic=lambda: clock[0]))

    def send(kwargs):
        try:
            return script(kwargs)
        finally:
            clock[0] = jumps.get(len(script.sent), clock[0])

    monkeypatch.setattr(client, "_send", send)


def test_planner_timeout_clamped_to_deadline(script, ctx, monkeypatch):
    _fake_clock(monkeypatch, script, {1: planner.PLAN_DEADLINE_S - 5})
    script.push(router(), final("needs_clarification", "?"))
    make_plan("hm", ctx)
    assert [k["timeout"] for k in script.sent] == [15.0, 5.0]


def test_no_call_after_deadline(script, ctx, monkeypatch):
    ids = _paid_ids(ctx, 1)
    _fake_clock(monkeypatch, script, {4: planner.PLAN_DEADLINE_S + 1})
    script.push(
        router(),
        tool_use(("list_orders", {**ANY, "order_ids": ids})),
        tool_use(
            (
                "mark_shipped",
                {"order_ids": ids, "carrier": "usps", "rationale": "r", "evidence": ids},
            )
        ),
        final(),
    )
    p = make_plan("ship it", ctx)
    assert script.models == [HAIKU, SONNET, SONNET, SONNET]  # judge never sent
    assert p.status == "ready" and p.judge["verdict"] == "warn"


def test_rejected_refund_fixed_with_new_evidence(script, ctx):
    args = {
        "order_id": DAMAGED_ORDER_ID,
        "amount_cents": 100,
        "reason": "requested_by_customer",
        "rationale": "r",
    }
    script.push(
        router(),
        tool_use(("refund_order", {**args, "evidence": ["owner_request"]})),
        tool_use(("list_inbox", {})),
        tool_use(("refund_order", {**args, "evidence": [DAMAGED_EMAIL_ID]})),
        final("ready", "Refund."),
        judge_pass(),
    )
    p = make_plan("refund the damaged mug", ctx)
    assert script.tool_results_after(2)[0]["content"].startswith("REJECTED:")
    assert "STAGED" in script.tool_results_after(4)[0]["content"]
    assert p.status == "ready" and [s.tool for s in p.steps] == ["refund_order"]


def test_email_rejected_before_ship_then_staged(script, ctx):
    ids = _paid_ids(ctx, 1)
    email = (
        "send_email",
        {
            "order_ids": ids,
            "template": "tracking",
            "custom_body": None,
            "rationale": "r",
            "evidence": ids,
        },
    )
    ship = (
        "mark_shipped",
        {"order_ids": ids, "carrier": "usps", "rationale": "r", "evidence": ids},
    )
    script.push(
        router(),
        tool_use(("list_orders", {**ANY, "order_ids": ids})),
        tool_use(email, ship),
        tool_use(email),
        final("ready", "Ship."),
        judge_pass(),
    )
    p = make_plan("ship and notify", ctx)
    first = script.tool_results_after(3)
    assert first[0]["is_error"] and "STAGED" in first[1]["content"]
    assert "STAGED" in script.tool_results_after(4)[0]["content"]
    assert [s.tool for s in p.steps] == ["mark_shipped", "send_email"]


@pytest.mark.parametrize("bad", ["  ", "x" * 2001])
def test_bad_request_raises(ctx, bad):
    with pytest.raises(ValueError):
        make_plan(bad, ctx)
