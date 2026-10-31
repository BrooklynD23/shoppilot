"""P5-I10: Layer-4 end-to-end flow over HTTP, mock Stripe, stubbed planner (R1, R26, R38)."""

import app.main as main
from app.agent.models import Plan, Step
from app.seed.generate import DAMAGED_ORDER_ID

OWNER = ["owner_request"]


def _stub_plan(monkeypatch, plan):
    monkeypatch.setattr(main, "make_plan", lambda request, ctx, force_replay=False: plan)


def _run_step(client, plan_id, step_id):
    r = client.post("/api/execute", json={"plan_id": plan_id, "approved_step_ids": [step_id]})
    assert r.status_code == 200, r.text
    (res,) = [x for x in r.json()["results"] if x["step_id"] == step_id]
    assert res["ok"], res
    return res


def _refund_actions(client):
    actions = client.get("/api/audit").json()["actions"]
    return [a for a in actions if a["tool"] == "refund_order" and a["kind"] == "execute"]


def test_layer4_flow(session_client, monkeypatch):
    c = session_client
    store = c.get("/api/store").json()
    assert store["stripe_mode"] == "mock"  # R26: top-level, UI never hardcodes it
    paid = [o for o in store["orders"] if o["status"] == "paid" and o["id"] != DAMAGED_ORDER_ID]
    ship = [o["id"] for o in paid[:2]]
    damaged = next(o for o in store["orders"] if o["id"] == DAMAGED_ORDER_ID)
    request = (
        f"Ship {ship[0]} and {ship[1]} by UPS, email tracking, refund {DAMAGED_ORDER_ID}"
        f" and send {damaged['customer_id']} a $12.00 payment link"
    )
    plan = Plan(
        request=request,
        steps=[
            Step(
                id="s1",
                tool="mark_shipped",
                args={"order_ids": ship, "carrier": "ups"},
                rationale="ship",
                evidence=OWNER,
            ),
            Step(
                id="s2",
                tool="send_email",
                args={"order_ids": ship, "template": "tracking", "custom_body": None},
                rationale="tracking",
                evidence=OWNER,
            ),
            Step(
                id="s3",
                tool="refund_order",
                args={
                    "order_id": DAMAGED_ORDER_ID,
                    "amount_cents": None,
                    "reason": "requested_by_customer",
                },
                rationale="damaged",
                evidence=OWNER,
            ),
            Step(
                id="s4",
                tool="create_payment_link",
                args={
                    "order_id": None,
                    "customer_id": damaged["customer_id"],
                    "amount_cents": 1200,
                    "description": "Replacement mug",
                },
                rationale="recover",
                evidence=OWNER,
            ),
        ],
    )
    _stub_plan(monkeypatch, plan)

    r = c.post("/api/plan", json={"request": request})
    assert r.status_code == 200, r.text
    body = r.json()
    assert all(v["ok"] for v in body["validations"]), body["validations"]
    diff = {d["step_id"]: d for d in body["diff"]}
    assert diff["s3"]["amount_cents"] == damaged["total_cents"] - damaged["refunded_cents"]
    assert diff["s4"]["amount_cents"] == 1200
    assert diff["s3"]["after"]["irreversible"] is True
    pid = body["plan_id"]

    # everything except the refund, one step per call (R1)
    shipped = _run_step(c, pid, "s1")
    for sid in ("s2", "s4"):
        _run_step(c, pid, sid)
    assert _refund_actions(c) == []
    orders = {o["id"]: o for o in c.get("/api/store").json()["orders"]}
    assert orders[DAMAGED_ORDER_ID]["refunded_cents"] == damaged["refunded_cents"]
    assert all(orders[o]["status"] == "shipped" for o in ship)

    refund = _run_step(c, pid, "s3")
    audit = c.get("/api/audit").json()
    assert audit["chain_ok"]
    (entry,) = _refund_actions(c)
    assert entry["can_undo"] is False  # audit field name for "undoable" (R26 /api/audit)
    assert refund["data"]["stripe_refund_id"].startswith("re_mock_")
    assert len(c.get("/api/outbox").json()) == 2

    r = c.post(f"/api/undo/{entry['id']}")  # R38
    assert r.status_code == 409 and r.json()["error"]["code"] == "not_undoable"
    r = c.post(f"/api/undo/{shipped['audit_id']}")
    assert r.status_code == 200, r.text
    orders = {o["id"]: o for o in c.get("/api/store").json()["orders"]}
    assert all(orders[o]["status"] == "paid" for o in ship)

    pdf = c.get("/api/export/report_pdf")
    assert pdf.status_code == 200 and pdf.content.startswith(b"%PDF-")
    assert c.get("/api/store").json()["stripe_mode"] == "mock"
