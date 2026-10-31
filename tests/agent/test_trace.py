"""Spec 09 §6: agent trace on the plan response. Scripted fake SDK, no network."""

import json
from types import SimpleNamespace

import pytest

import app.agent.planner as planner
import app.llm.client as client
from app.agent.planner import make_plan
from app.llm.client import recording_key
from app.safety import inbound_guard
from app.safety.inbound_guard import GuardVerdict
from app.seed.generate import DAMAGED_ORDER_ID, INJECTION_EMAIL_ID
from app.tools import registry
from tests.agent.test_planner import ANY, _paid_ids, final, judge_pass, router, tool_use

AGENTS = {"router", "planner", "guard", "forecaster", "validator", "judge", "executor"}
EVENTS = {"start", "read", "staged", "pass", "reject", "block", "warn", "ask", "done", "error"}
REFUND = {"order_id": DAMAGED_ORDER_ID, "amount_cents": 100, "reason": "requested_by_customer"}


@pytest.fixture(autouse=True)
def fake_guard(monkeypatch, llm_script):
    registry.load_tools()

    def _screen(text, source_id):  # reason quotes the email, as a real guard reason may
        bad = source_id == f"email:{INJECTION_EMAIL_ID}"
        label = "injection" if bad else "clean"
        return GuardVerdict(source_id=source_id, allowed=not bad, label=label, reason=text)

    monkeypatch.setattr(inbound_guard, "screen", _screen)


def _check(trace):
    """Spec 09 §2 contract, every event."""
    assert 1 <= len(trace) <= 60
    for e in trace:
        assert set(e) == {"agent", "event", "detail", "t_ms", "step_id"}
        assert e["agent"] in AGENTS and e["event"] in EVENTS
        assert isinstance(e["detail"], str) and 1 <= len(e["detail"]) <= 160
        assert isinstance(e["t_ms"], int) and e["t_ms"] >= 0
    t = [e["t_ms"] for e in trace]
    assert t == sorted(t)


def test_happy_plan_router_planner_judge_in_time_order(llm_script, ctx, monkeypatch):
    clock = iter(range(0, 10**6, 250))  # every monotonic() read moves 250 ms on
    monkeypatch.setattr(planner, "time", SimpleNamespace(monotonic=lambda: next(clock) / 1000))
    ids = _paid_ids(ctx)
    ship = {"order_ids": ids, "carrier": "usps", "rationale": "r", "evidence": ids}
    llm_script.push(
        router(),
        tool_use(("list_orders", {**ANY, "order_ids": ids})),
        tool_use(("mark_shipped", ship)),
        final("ready", "Ship 2."),
        judge_pass(),
    )
    p = make_plan("Ship yesterday's orders", ctx)
    _check(p.trace)
    assert [(e["agent"], e["event"], e["step_id"]) for e in p.trace] == [
        ("router", "start", None),
        ("router", "pass", None),
        ("planner", "start", None),
        ("planner", "read", None),
        ("planner", "start", None),
        ("planner", "staged", "s1"),
        ("validator", "pass", "s1"),
        ("planner", "start", None),
        ("planner", "done", None),
        ("judge", "start", None),
        ("judge", "pass", None),
    ]
    assert p.trace[-1]["t_ms"] > p.trace[0]["t_ms"]


def test_recorded_self_repair_reject_then_staged(llm_script, ctx, tmp_path, monkeypatch):
    monkeypatch.setattr(client, "RECORDINGS_DIR", tmp_path)
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
    calls = [
        ("router", router()),
        ("planner", tool_use(("list_orders", {**ANY, "order_ids": ids}))),
        ("planner", tool_use(email, ship)),  # email before ship: validator rejects it
        ("planner", tool_use(email)),  # repaired: ship is staged first now
        ("planner", final("ready", "Ship.")),
        ("judge", judge_pass()),
    ]
    req = "ship and notify"
    rec = {
        "request": req,
        "calls": [{"stage": s, "model": r["model"], "response": r} for s, r in calls],
    }
    (tmp_path / f"{recording_key(req)}.json").write_text(json.dumps(rec))
    p = make_plan(req, ctx, force_replay=True)
    assert p.source == "replay" and llm_script.sent == []
    _check(p.trace)
    seq = [(e["agent"], e["event"], e["step_id"]) for e in p.trace]
    i = seq.index(("validator", "reject", None))
    assert "tracking email before" in p.trace[i]["detail"]  # the validator's own reason
    j = seq.index(("planner", "staged", "s2"), i)
    assert "send_email" in p.trace[j]["detail"] and seq[j + 1] == ("validator", "pass", "s2")


def test_blocked_email_one_guard_block_id_and_label_only(llm_script, ctx):
    llm_script.push(
        router(),
        tool_use(("list_inbox", {})),
        tool_use(("list_inbox", {})),  # second read: same verdict, no second block
        final("needs_clarification", "?"),
    )
    p = make_plan("check inbox", ctx)
    _check(p.trace)
    guard = [(e["event"], e["detail"]) for e in p.trace if e["agent"] == "guard"]
    assert guard == [("block", f"{INJECTION_EMAIL_ID} blocked as injection.")]


def test_no_detail_quotes_the_inbox(llm_script, ctx):
    inbox = ctx.db.execute("SELECT from_addr, subject, body FROM inbox ORDER BY id").fetchall()
    _, subject, body = inbox[0]
    # A model that copies email text into a step; validator reasons quote args back.
    refund = {**REFUND, "rationale": body, "evidence": [subject]}
    ship = {"order_ids": [body], "carrier": "usps", "rationale": "r", "evidence": []}
    llm_script.push(
        router(),
        tool_use(("list_inbox", {})),
        tool_use(("refund_order", refund), ("mark_shipped", ship)),
        final("needs_clarification", "?"),
    )
    p = make_plan("handle the inbox", ctx)
    _check(p.trace)
    assert sum(e["event"] == "reject" for e in p.trace) == 2
    details = " | ".join(e["detail"] for e in p.trace)
    for row in inbox:
        for text in (*row[:2], row[2][:40]):
            assert text not in details


def test_details_clipped_and_events_capped(llm_script, ctx):
    ids = _paid_ids(ctx, 1)
    reads = [tool_use(*[("list_orders", {**ANY, "order_ids": ids})] * 15) for _ in range(4)]
    long_id = "O" + "1" * 300  # id-shaped, so the reason quoting it is kept, then clipped
    refund = {**REFUND, "rationale": "r", "evidence": [long_id]}
    llm_script.push(
        router(), *reads, tool_use(("refund_order", refund)), final("needs_clarification", "?")
    )
    p = make_plan("look hard", ctx)
    _check(p.trace)
    # 71 events: 11 non-read + 60 reads. Reads go first, so all 11 others stay.
    assert len(p.trace) == 60 and sum(e["event"] != "read" for e in p.trace) == 11
    assert max(len(e["detail"]) for e in p.trace) == 160
    assert (p.trace[0]["agent"], p.trace[-1]["event"]) == ("router", "ask")


def test_cap_without_enough_reads_keeps_head_and_end():
    events = [{"event": "staged", "t_ms": i} for i in range(80)]
    out = planner._capped(events)
    assert len(out) == 60 and out[:57] == events[:57] and out[-3:] == events[-3:]


def test_plan_route_returns_trace(session_client, llm_script):
    llm_script.push(router("reject", reply="Shop only, friend."))
    j = session_client.post("/api/plan", json={"request": "what's the weather?"}).json()
    assert [(e["agent"], e["event"]) for e in j["trace"]] == [
        ("router", "start"),
        ("router", "reject"),
    ]
    assert "Shop only" not in json.dumps(j["trace"])  # model reply never in a detail
    assert "trace" not in j["plan"]  # sent once, top level
