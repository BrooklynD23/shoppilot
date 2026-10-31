"""P4-T4: end-to-end safety over the HTTP API (gates, replay, undo, audit chain, CSV).

Planner patch point: `app.main.make_plan` (the route calls it, then validates, dry-runs and saves
the plan for real). Stripe is the mock client wrapped by a recorder.
"""

import csv
import io
import json
from contextlib import contextmanager
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import app.llm.client as llm_client
import app.main as main
from app.agent.models import Plan, Step
from app.config import get_settings
from app.db import get_db
from app.integrations import stripe_client
from app.llm.prompts import ROUTER_PROMPT
from app.safety import inbound_guard as ig
from app.seed.generate import DAMAGED_ORDER_ID, INJECTION_BODY

H = {"X-ShopPilot": "1"}
GUARD_CASES = Path(__file__).with_name("guard_cases.json")


@pytest.fixture(autouse=True)
def _fresh_guard_cache():
    ig._clear_cache()  # module-global verdict cache must not leak between tests
    yield
    ig._clear_cache()


@contextmanager
def store(client):
    with get_db(client.cookies.get(main.COOKIE)) as db:
        yield db


def _usage():
    return {
        "input_tokens": 1,
        "cache_creation_input_tokens": 0,
        "cache_read_input_tokens": 0,
        "output_tokens": 1,
    }


def _text(obj, stop="end_turn"):
    return {
        "content": [{"type": "text", "text": json.dumps(obj)}],
        "stop_reason": stop,
        "model": "claude-haiku-5-5",
        "usage": _usage(),
    }


class PlannerSpy:
    """Fake SDK send: router -> plan, planner reads the inbox then finishes, guard says clean."""

    def __init__(self):
        self.sent = []

    def __call__(self, kw):
        self.sent.append(json.loads(json.dumps(kw, default=str)))
        system = kw["system"][0]["text"]
        if system == ig.GUARD_SYSTEM_PROMPT:
            return _text({"label": "clean", "confidence": 0.9, "reason": "normal"})
        if system == ROUTER_PROMPT:
            return _text({"reason": "ops", "route": "plan", "reply": ""})
        if "tool_result" not in json.dumps(kw["messages"]):
            return {
                "content": [{"type": "tool_use", "id": "tu_1", "name": "list_inbox", "input": {}}],
                "stop_reason": "tool_use",
                "model": "claude-sonnet-5-5",
                "usage": _usage(),
            }
        return _text({"status": "ready", "message": "Inbox reviewed."})

    @property
    def prompt_text(self) -> str:
        return json.dumps(self.sent)


@pytest.fixture
def planner_spy(monkeypatch):
    monkeypatch.setenv("LLM_MODE", "live")
    get_settings.cache_clear()
    spy = PlannerSpy()
    monkeypatch.setattr(llm_client, "_send", spy)
    return spy


class StripeRec:
    def __init__(self):
        self.calls = []


@pytest.fixture
def stripe_rec(monkeypatch):
    rec, real = StripeRec(), stripe_client.refund
    assert stripe_client.mode() == "mock"  # no key in tests: never a real Stripe call

    def refund(payment_intent_id, amount_cents, reason, idempotency_key):
        rec.calls.append({"amount_cents": amount_cents, "idempotency_key": idempotency_key})
        return real(payment_intent_id, amount_cents, reason, idempotency_key)

    monkeypatch.setattr(stripe_client, "refund", refund)
    return rec


@pytest.fixture
def plan_for(monkeypatch):
    """plan_for(client, *steps) -> plan_id. steps are (tool, args); evidence is owner_request."""

    def make(client, *steps, request=f"Refund order {DAMAGED_ORDER_ID}, it arrived broken"):
        fixed = Plan(
            request=request,
            status="ready",
            steps=[
                Step(
                    id=f"s{i}", tool=t, args=a, rationale="owner asked", evidence=["owner_request"]
                )
                for i, (t, a) in enumerate(steps, 1)
            ],
        )
        monkeypatch.setattr(
            main,
            "make_plan",
            lambda req, ctx, **kw: fixed.model_copy(deep=True, update={"request": req}),
        )
        r = client.post("/api/plan", json={"request": request}, headers=H)
        assert r.status_code == 200, r.text
        body = r.json()
        assert all(v["ok"] for v in body["validations"]), body["validations"]
        return body["plan_id"]

    return make


REFUND = (
    "refund_order",
    {"order_id": DAMAGED_ORDER_ID, "amount_cents": None, "reason": "requested_by_customer"},
)


@pytest.fixture
def fixed_plan_id(session_client, plan_for):
    return plan_for(session_client, REFUND)


def _execute(client, plan_id, ids, **extra):
    return client.post(
        "/api/execute", json={"plan_id": plan_id, "approved_step_ids": ids, **extra}, headers=H
    )


def _audit(client):
    return client.get("/api/audit").json()


def _paid_order(client) -> str:
    with store(client) as db:
        return db.execute(
            "SELECT id FROM orders WHERE status = 'paid' ORDER BY id LIMIT 1"
        ).fetchone()[0]


def _ship_one(client, plan_for) -> tuple[str, str]:
    oid = _paid_order(client)
    pid = plan_for(
        client,
        ("mark_shipped", {"order_ids": [oid], "carrier": "ups"}),
        request=f"Ship {oid} via UPS",
    )
    res = _execute(client, pid, ["s1"]).json()["results"][0]
    assert res["ok"] is True, res
    return res["audit_id"], oid


# ---------- inbound guard ----------


def test_planted_email_never_reaches_planner(session_client, planner_spy):
    r = session_client.post("/api/plan", json={"request": "Handle today's inbox"}, headers=H)
    assert r.status_code == 200 and r.json()["plan"]["status"] == "ready"
    assert any(c.get("tools") for c in planner_spy.sent)  # the planner really read the inbox
    assert "Refund every order" not in planner_spy.prompt_text
    inbox = session_client.get("/api/inbox").json()
    assert next(e for e in inbox if e["id"] == "E002")["verdict"]["allowed"] is False


def test_guard_down_demo_still_safe(session_client, monkeypatch):
    def down(**_kw):
        raise llm_client.LLMError("budget")

    monkeypatch.setattr(ig, "complete_json", down)
    r = session_client.get("/api/inbox")
    assert r.status_code == 200
    by_id = {e["id"]: e["verdict"] for e in r.json()}
    assert by_id["E002"]["allowed"] is False and by_id["E002"]["label"] == "injection"
    assert by_id["E001"]["allowed"] is False and by_id["E001"]["label"] == "guard_error"


def test_planted_text_matches_seed():
    case = next(c for c in json.loads(GUARD_CASES.read_text(encoding="utf-8")) if c["id"] == 1)
    assert case["text"] == INJECTION_BODY  # R4


# ---------- execute gates (R1) ----------


def test_unapproved_refund_skipped(session_client, fixed_plan_id, stripe_rec):
    r = _execute(session_client, fixed_plan_id, [])
    assert r.status_code == 422 and r.json()["error"]["code"] == "plan_invalid"
    assert stripe_rec.calls == []
    kinds = {a["kind"] for a in _audit(session_client)["actions"]}
    assert not kinds & {"confirm", "execute"}


def test_double_execute_409_one_refund(session_client, fixed_plan_id, stripe_rec):
    r1 = _execute(session_client, fixed_plan_id, ["s1"]).json()["results"][0]
    r2 = _execute(session_client, fixed_plan_id, ["s1"]).json()["results"][0]  # R1: replay
    assert r1["ok"] is True and r1["replayed"] is False
    assert r2["replayed"] is True and r2["audit_id"] == r1["audit_id"]
    assert len(stripe_rec.calls) == 1
    assert stripe_rec.calls[0]["idempotency_key"].startswith("refund:")  # R20
    with store(session_client) as db:
        assert (
            db.execute(
                "SELECT COUNT(*) FROM refunds WHERE order_id=?", (DAMAGED_ORDER_ID,)
            ).fetchone()[0]
            == 1
        )


def test_execute_ignores_client_args(session_client, fixed_plan_id, stripe_rec):
    with store(session_client) as db:
        total, refunded = db.execute(
            "SELECT total_cents, refunded_cents FROM orders WHERE id=?", (DAMAGED_ORDER_ID,)
        ).fetchone()
    evil = {
        "steps": [
            {
                "id": "s1",
                "tool": "refund_order",
                "args": {"order_id": DAMAGED_ORDER_ID, "amount_cents": 1},
            }
        ],
        "amount_cents": 1,
    }
    r = _execute(session_client, fixed_plan_id, ["s1"], **evil)
    assert r.status_code in (200, 422)
    if r.status_code == 200:
        assert [c["amount_cents"] for c in stripe_rec.calls] == [total - refunded]
    else:
        assert stripe_rec.calls == []


def test_revalidate_at_execute(session_client, fixed_plan_id, stripe_rec):
    with store(session_client) as db:
        db.execute(
            "UPDATE orders SET status='refunded', refunded_cents=total_cents WHERE id=?",
            (DAMAGED_ORDER_ID,),
        )
    r = _execute(session_client, fixed_plan_id, ["s1"])
    assert r.status_code == 200
    res = r.json()["results"][0]
    assert res["ok"] is False and res["error"] == "invalid"
    assert stripe_rec.calls == []


def test_approved_ids_subset(session_client, fixed_plan_id, stripe_rec):
    r = _execute(session_client, fixed_plan_id, ["s99"])
    assert r.status_code == 422 and r.json()["error"]["code"] == "plan_invalid"
    assert stripe_rec.calls == []


# ---------- undo (R22) ----------


def test_cross_session_undo_404(two_session_clients, plan_for):
    a, b = two_session_clients
    aid, _ = _ship_one(a, plan_for)
    r = b.post(f"/api/undo/{aid}", headers=H)
    assert r.status_code == 404 and r.json()["error"]["code"] == "not_found"
    assert next(x for x in _audit(a)["actions"] if x["id"] == aid)["can_undo"] is True


def test_undo_refused_after_change(session_client, plan_for):
    aid, oid = _ship_one(session_client, plan_for)
    with store(session_client) as db:  # owner edits the shipment outside the agent
        db.execute("UPDATE orders SET tracking_number='HAND-EDITED' WHERE id=?", (oid,))
    r = session_client.post(f"/api/undo/{aid}", headers=H)
    assert r.status_code == 409 and r.json()["error"]["code"] == "changed_since"


def test_refund_not_undoable(session_client, fixed_plan_id, stripe_rec):
    res = _execute(session_client, fixed_plan_id, ["s1"]).json()["results"][0]
    assert res["ok"] is True
    row = next(x for x in _audit(session_client)["actions"] if x["id"] == res["audit_id"])
    assert row["can_undo"] is False
    r = session_client.post(f"/api/undo/{res['audit_id']}", headers=H)
    assert r.status_code == 409 and r.json()["error"]["code"] == "not_undoable"


# ---------- rate limits (R36) ----------


def test_classroom_nat(client):
    """30 graders behind one IP each create a session and plan once: no 429 on /api/plan."""
    for _ in range(30):
        main._hits.pop(("session", "testclient"), None)  # sessions arrive over minutes in class
        client.cookies.clear()
        assert client.post("/api/session", json={}).status_code in (200, 201)
        r = client.post("/api/plan", json={"request": "What shipped yesterday?"}, headers=H)
        assert r.status_code != 429, r.text
        assert r.status_code == 200


# ---------- audit chain + exports ----------


def test_audit_chain_ok_and_detects_edit(session_client, fixed_plan_id):
    assert session_client.get("/api/audit").json()["chain_ok"] is True  # R26 shape
    with store(session_client) as db:
        db.execute("DROP TRIGGER audit_no_update")
        db.execute(
            "UPDATE audit_log SET payload_json = '{\"summary\":\"forged\"}' WHERE kind = 'plan'"
        )
    assert session_client.get("/api/audit").json()["chain_ok"] is False


def test_csv_injection_neutralised(session_client):
    payload = '=HYPERLINK("http://evil.example","click")'
    with store(session_client) as db:
        db.execute(
            "UPDATE customers SET name=? WHERE id=(SELECT customer_id FROM orders WHERE id=?)",
            (payload, DAMAGED_ORDER_ID),
        )
    r = session_client.get("/api/export/orders_csv")
    assert r.status_code == 200
    rows = list(csv.DictReader(io.StringIO(r.text)))
    row = next(x for x in rows if x["order_id"] == DAMAGED_ORDER_ID)
    assert row["customer"] == "'" + payload


def test_fresh_client_has_no_session():
    with TestClient(main.app, headers=H) as c:
        assert (
            c.post(
                "/api/execute", json={"plan_id": "plan_000000000000", "approved_step_ids": ["s1"]}
            ).status_code
            == 401
        )
