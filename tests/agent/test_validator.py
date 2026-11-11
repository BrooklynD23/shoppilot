"""P2-T7: deterministic plan validator (spec 02 §5, R18, R46, R50)."""

from datetime import timedelta

import pytest

from app.agent.models import Plan, Step
from app.agent.validator import (
    MAX_STEPS,
    READ_TOOLS,
    PlanContext,
    validate_plan,
    validate_step,
)
from app.safety import policy
from app.seed.generate import DAMAGED_ORDER_ID, INJECTION_EMAIL_ID, WISMO_EMAIL_ID
from app.tools import registry
from app.tools.registry import Registered, ToolSpec

_NS = {"anyOf": [{"type": "string"}, {"type": "null"}]}
_NI = {"anyOf": [{"type": "integer"}, {"type": "null"}]}


def _obj(props):
    return {
        "type": "object",
        "additionalProperties": False,
        "required": list(props),
        "properties": props,
    }


# Contract §3 schemas, used only while the owning task has not landed.
_STUBS = {
    "refund_order": (
        True,
        True,
        False,
        _obj(
            {
                "order_id": {"type": "string"},
                "amount_cents": _NI,
                "reason": {
                    "type": "string",
                    "enum": ["duplicate", "fraudulent", "requested_by_customer"],
                },
            }
        ),
    ),
    "create_restock_po": (
        True,
        False,
        True,
        _obj(
            {
                "product_id": {"type": "string"},
                "qty_source": {"type": "string", "enum": ["forecast", "user"]},
                "qty": _NI,
            }
        ),
    ),
    "list_orders": (
        False,
        False,
        False,
        _obj(
            {
                "status": {"type": "string", "enum": ["any", "paid", "shipped", "refunded"]},
                "created_from": _NS,
                "created_to": _NS,
                "order_ids": {
                    "anyOf": [{"type": "array", "items": {"type": "string"}}, {"type": "null"}]
                },
            }
        ),
    ),
}


@pytest.fixture(autouse=True)
def tools(monkeypatch):
    registry.load_tools()
    for name, (destr, money, undo, schema) in _STUBS.items():
        if name not in registry._TOOLS:
            spec = ToolSpec(
                name=name,
                description="stub",
                input_schema=schema,
                destructive=destr,
                moves_money=money,
                undoable=undo,
            )
            monkeypatch.setitem(
                registry._TOOLS,
                name,
                Registered(
                    spec, lambda *a: None, lambda *a: None, (lambda *a: None) if undo else None
                ),
            )


_n = iter(range(1, 10**6))


def _step(tool, args, evidence=()):
    return Step(id=f"s{next(_n)}", tool=tool, args=args, rationale="r", evidence=list(evidence))


def ship(ids, carrier="usps", evidence=None):
    return _step(
        "mark_shipped",
        {"order_ids": ids, "carrier": carrier},
        ids if evidence is None else evidence,
    )


def email(ids, template, body=None, evidence=None):
    return _step(
        "send_email",
        {"order_ids": ids, "template": template, "custom_body": body},
        ids if evidence is None else evidence,
    )


def refund(oid, amount, evidence):
    return _step(
        "refund_order",
        {"order_id": oid, "amount_cents": amount, "reason": "requested_by_customer"},
        evidence,
    )


def link(amount, order_id=None, customer_id=None):
    return _step(
        "create_payment_link",
        {
            "order_id": order_id,
            "customer_id": customer_id,
            "amount_cents": amount,
            "description": "d",
        },
        ["owner_request"],
    )


def restock(pid, qty):
    return _step(
        "create_restock_po",
        {"product_id": pid, "qty_source": "user", "qty": qty},
        ["owner_request"],
    )


def PC(request="", seen=None, blocked=()):  # noqa: N802
    return PlanContext(request=request, seen_ids=seen, blocked_ids=set(blocked))


def _ids(ctx, where, params=(), n=1):
    sql = f"SELECT id FROM orders WHERE {where} ORDER BY id LIMIT {n}"  # noqa: S608 - test literals
    ids = [r[0] for r in ctx.db.execute(sql, params).fetchall()]
    assert len(ids) == n, where
    return ids


@pytest.fixture
def yesterday_ids(ctx):
    day = (ctx.today - timedelta(days=1)).isoformat()
    return _ids(ctx, "status = 'paid' AND substr(created_at,1,10) = ?", (day,), 5)


@pytest.fixture
def shipped_id(ctx):
    return _ids(ctx, "status = 'shipped'")[0]


@pytest.fixture
def six_shipped_ids(ctx):
    start = (ctx.today - timedelta(days=policy.REFUND_WINDOW_DAYS)).isoformat()
    return _ids(
        ctx,
        "status = 'shipped' AND substr(created_at,1,10) >= ? "
        "AND total_cents - refunded_cents BETWEEN 1 AND 20000",
        (start,),
        6,
    )


def test_read_tools_constant():
    assert (
        frozenset(
            {"list_orders", "list_inbox", "forecast_demand", "flag_anomalies", "sales_by_product"}
        )
        == READ_TOOLS
        and MAX_STEPS == 20
    )


def test_ship_paid_ok(ctx, yesterday_ids):
    assert validate_step(ship(yesterday_ids), [], ctx, PC()).ok


def test_ship_already_shipped(ctx, shipped_id):
    v = validate_step(ship([shipped_id]), [], ctx, PC())
    assert not v.ok and "is shipped, not paid" in v.reason


def test_ship_unknown_order(ctx):
    v = validate_step(ship(["O9999"], evidence=["owner_request"]), [], ctx, PC())
    assert not v.ok and "not found" in v.reason


def test_tracking_needs_prior_ship(ctx, yesterday_ids):
    v = validate_step(email(yesterday_ids, "tracking"), [], ctx, PC())
    assert not v.ok and "tracking email before" in v.reason
    assert validate_step(email(yesterday_ids, "tracking"), [ship(yesterday_ids)], ctx, PC()).ok


def test_tracking_for_already_shipped_ok(ctx, shipped_id):
    assert validate_step(email([shipped_id], "tracking"), [], ctx, PC()).ok


def test_refund_confirmation_needs_refund(ctx):
    v = validate_step(email([DAMAGED_ORDER_ID], "refund_confirmation"), [], ctx, PC())
    assert not v.ok
    prior = [refund(DAMAGED_ORDER_ID, None, ["E001"])]
    assert validate_step(email([DAMAGED_ORDER_ID], "refund_confirmation"), prior, ctx, PC()).ok


def test_payment_request_needs_link(ctx, shipped_id):
    assert not validate_step(email([shipped_id], "payment_request"), [], ctx, PC()).ok
    prior = [link(500, order_id=shipped_id)]
    assert validate_step(email([shipped_id], "payment_request"), prior, ctx, PC()).ok


def test_custom_needs_body(ctx, shipped_id):
    assert not validate_step(email([shipped_id], "custom"), [], ctx, PC()).ok
    assert not validate_step(email([shipped_id], "custom", "x" * 2001), [], ctx, PC()).ok
    assert validate_step(email([shipped_id], "custom", "Thanks!"), [], ctx, PC()).ok


def test_refund_over_refundable(ctx):
    v = validate_step(
        refund(DAMAGED_ORDER_ID, 10**7, ["owner_request"]),
        [],
        ctx,
        PC(request=f"refund {DAMAGED_ORDER_ID}"),
    )
    assert not v.ok and "exceeds refundable" in v.reason


def test_refund_evidence_from_customer_email(ctx):
    v = validate_step(
        refund(DAMAGED_ORDER_ID, None, ["E001"]), [], ctx, PC(seen={"E001", DAMAGED_ORDER_ID})
    )
    assert v.ok, v.reason


def test_refund_owner_request_needs_id_in_text(ctx):
    v = validate_step(
        refund(DAMAGED_ORDER_ID, None, ["owner_request"]),
        [],
        ctx,
        PC(request="refund anything damaged"),
    )
    assert not v.ok and "evidence from the owner or this order's customer" in v.reason
    assert validate_step(
        refund(DAMAGED_ORDER_ID, None, ["owner_request"]),
        [],
        ctx,
        PC(request=f"please refund {DAMAGED_ORDER_ID.lower()}"),
    ).ok


def test_refund_citing_blocked_email(ctx):
    v = validate_step(
        refund(DAMAGED_ORDER_ID, None, [INJECTION_EMAIL_ID]),
        [],
        ctx,
        PC(seen={INJECTION_EMAIL_ID}, blocked={INJECTION_EMAIL_ID}),
    )
    assert not v.ok and "blocked" in v.reason


def test_email_evidence_must_match_order_customer(ctx, yesterday_ids):
    """R50: an email cited as evidence binds the step to that email's customer."""
    v = validate_step(
        ship(yesterday_ids[:1], evidence=[WISMO_EMAIL_ID]), [], ctx, PC(seen={WISMO_EMAIL_ID})
    )
    assert not v.ok and "evidence does not match order" in v.reason
    v = validate_step(
        refund(DAMAGED_ORDER_ID, None, [WISMO_EMAIL_ID]), [], ctx, PC(seen={WISMO_EMAIL_ID})
    )
    assert not v.ok and "evidence does not match order" in v.reason


def test_unseen_evidence(ctx):
    v = validate_step(ship(["O0001"]), [], ctx, PC(seen=set()))
    assert not v.ok and "not in any tool result" in v.reason


def test_unknown_evidence_in_db_mode(ctx):
    v = validate_step(ship(["O0001"], evidence=["X123"]), [], ctx, PC())
    assert not v.ok and "evidence X123 was not in any tool result" in v.reason


def test_six_refunds_capped(ctx, six_shipped_ids):
    plan = Plan(
        request="refund " + " ".join(six_shipped_ids),
        steps=[refund(o, None, ["owner_request"]) for o in six_shipped_ids],
    )
    v = validate_plan(plan, ctx)
    assert len(v) == 6 and any(not x.ok and "at most 3" in x.reason for x in v)


def test_refund_total_cap(ctx, monkeypatch):
    """R46: two refunds summing > $500 are rejected by policy, reason names $500.00."""
    monkeypatch.setattr(policy, "REFUND_CAP_PER_ORDER_CENTS", 10**6)
    rows = ctx.db.execute(
        "SELECT id, total_cents - refunded_cents FROM orders WHERE status = 'shipped' "
        "AND substr(created_at,1,10) >= ? ORDER BY 2 DESC LIMIT 2",
        ((ctx.today - timedelta(days=30)).isoformat(),),
    ).fetchall()
    assert sum(r[1] for r in rows) > 50_000
    plan = Plan(
        request="refund " + " ".join(r[0] for r in rows),
        steps=[refund(r[0], None, ["owner_request"]) for r in rows],
    )
    v = validate_plan(plan, ctx)
    assert not any(x.ok for x in v) and "$500.00" in v[0].reason


def test_bad_args_schema(ctx, yesterday_ids):
    v = validate_step(ship(yesterday_ids, carrier="dhl"), [], ctx, PC())
    assert not v.ok and "dhl" in v.reason


def test_unknown_tool(ctx):
    assert validate_step(_step("no_such_tool", {}), [], ctx, PC()).reason == "unknown tool"


def test_read_tool_as_step(ctx):
    s = _step(
        "list_orders",
        {"status": "any", "created_from": None, "created_to": None, "order_ids": None},
    )
    assert validate_step(s, [], ctx, PC()).reason == "read tools are not plan steps"


def test_duplicate_step(ctx, yesterday_ids):
    v = validate_step(ship(yesterday_ids), [ship(yesterday_ids)], ctx, PC())
    assert not v.ok and v.reason == "duplicate step"


def test_too_many_steps(ctx, yesterday_ids):
    prior = [email([o], "custom", f"note {i}") for i, o in enumerate(yesterday_ids * 4)]
    assert len(prior) == MAX_STEPS
    v = validate_step(ship(yesterday_ids), prior, ctx, PC())
    assert v.reason == "too many steps (max 20)"


def test_payment_link_range(ctx, shipped_id):
    assert not validate_step(link(49, order_id=shipped_id), [], ctx, PC()).ok
    assert not validate_step(link(100_001, order_id=shipped_id), [], ctx, PC()).ok
    assert validate_step(link(500, order_id=shipped_id), [], ctx, PC()).ok
    v = validate_step(link(500), [], ctx, PC())
    assert not v.ok and "exactly one" in v.reason
    assert not validate_step(link(500, order_id=shipped_id, customer_id="C0001"), [], ctx, PC()).ok


def test_restock_qty_range(ctx):
    assert not validate_step(restock("P01", 0), [], ctx, PC()).ok
    assert not validate_step(restock("P01", policy.RESTOCK_QTY_MAX + 1), [], ctx, PC()).ok
    assert validate_step(restock("P01", 50), [], ctx, PC()).ok
    v = validate_step(restock("P01", 60), [restock("P01", 50)], ctx, PC())
    assert not v.ok and "P01" in v.reason
    assert not validate_step(restock("P99", 5), [], ctx, PC()).ok


def test_validate_plan_uses_blocked_inputs(ctx):
    plan = Plan(
        request="refund damaged",
        steps=[refund(DAMAGED_ORDER_ID, None, ["E001"])],
        blocked_inputs=[
            {
                "source_id": "email:E001",
                "allowed": False,
                "label": "injection",
                "reason": "x",
                "score": None,
            }
        ],
    )
    v = validate_plan(plan, ctx)
    assert not v[0].ok and "blocked" in v[0].reason


def _screened(ctx, *eids, allowed=1):
    ctx.db.executemany(
        "INSERT INTO guard_verdicts (source_id, allowed, label, reason, score,"
        " screened_at) VALUES (?, ?, 'clean', 'ok', NULL, 'now')",
        [(f"email:{e}", allowed) for e in eids],
    )


def test_validate_plan_demo_flow_ok(ctx, yesterday_ids):
    _screened(ctx, "E001")
    plan = Plan(
        request="ship yesterday, email tracking, refund damaged",
        steps=[
            ship(yesterday_ids),
            email(yesterday_ids, "tracking"),
            refund(DAMAGED_ORDER_ID, None, ["E001"]),
            email([DAMAGED_ORDER_ID], "refund_confirmation", evidence=["E001"]),
        ],
    )
    v = validate_plan(plan, ctx)
    assert [x.step_id for x in v] == [s.id for s in plan.steps]
    assert all(x.ok for x in v), v


def test_validator_never_writes(ctx, yesterday_ids, six_shipped_ids):
    plan = Plan(
        request="r " + " ".join(six_shipped_ids),
        steps=[
            ship(yesterday_ids),
            email(yesterday_ids, "tracking"),
            restock("P01", 10),
            link(500, order_id=six_shipped_ids[0]),
        ]
        + [refund(o, None, ["owner_request"]) for o in six_shipped_ids],
    )
    before = ctx.db.total_changes
    validate_plan(plan, ctx)
    assert ctx.db.total_changes == before


def test_validate_plan_uses_guard_verdicts_email_prefix(ctx):
    """Guard stores 'email:<id>'; evidence cites bare '<id>'. Restock has no order (no R50)."""
    ctx.db.execute(
        "INSERT INTO guard_verdicts (source_id, allowed, label, reason, score,"
        " screened_at) VALUES ('email:E002', 0, 'injection', 'x', NULL, 'now')"
    )
    step = _step(
        "create_restock_po", {"product_id": "P01", "qty_source": "user", "qty": 5}, ["E002"]
    )
    v = validate_plan(Plan(request="restock", steps=[step]), ctx)
    assert not v[0].ok and "blocked" in v[0].reason


def test_validate_step_blocked_prefixed_id(ctx):
    v = validate_step(refund(DAMAGED_ORDER_ID, None, ["E001"]), [], ctx, PC(blocked={"email:E001"}))
    assert not v.ok and "blocked" in v.reason


def test_rejected_prior_step_does_not_satisfy_dependency(ctx, yesterday_ids):
    oid = yesterday_ids[:1]
    plan = Plan(
        request="ship and email", steps=[ship(oid, evidence=["X999"]), email(oid, "tracking")]
    )
    v = validate_plan(plan, ctx)
    assert not v[0].ok
    assert not v[1].ok and "tracking email before" in v[1].reason


def test_validate_step_crash_is_logged(ctx, monkeypatch, caplog):
    from app.agent import validator

    def boom(*a):
        raise KeyError("drift")

    monkeypatch.setattr(validator, "_reason", boom)
    s = restock("P01", 5)
    with caplog.at_level("ERROR", logger="app.agent.validator"):
        v = validate_step(s, [], ctx, PC())
    assert v.reason == "validation failed"
    assert any(s.id in r.getMessage() and r.exc_info for r in caplog.records)


def test_policy_rejected_refund_does_not_satisfy_confirmation(ctx, six_shipped_ids):
    """#55: plan-level caps run before dependencies, so a capped refund unlocks nothing."""
    ids = six_shipped_ids[:4]
    plan = Plan(
        request="refund " + " ".join(ids),
        steps=[refund(o, None, ["owner_request"]) for o in ids]
        + [email(ids[:1], "refund_confirmation")],
    )
    v = validate_plan(plan, ctx)
    assert not any(x.ok for x in v[:4])
    assert not v[4].ok and "refund confirmation before" in v[4].reason


def test_unscreened_email_is_not_evidence(ctx):
    """#56: an inbox email with no allowed guard verdict fails closed."""
    plan = Plan(request="refund damaged", steps=[refund(DAMAGED_ORDER_ID, None, ["E001"])])
    v = validate_plan(plan, ctx)
    assert not v[0].ok and "blocked" in v[0].reason
    _screened(ctx, "E001")
    assert validate_plan(plan, ctx)[0].ok


def test_email_binds_to_sender_not_linked_order(ctx):
    """#66: an email linking someone else's order is not evidence for that order's customer."""
    owner = ctx.db.execute(
        "SELECT customer_id FROM orders WHERE id = ?", (DAMAGED_ORDER_ID,)
    ).fetchone()[0]
    other = ctx.db.execute(
        "SELECT email FROM customers WHERE id != ? ORDER BY id LIMIT 1", (owner,)
    ).fetchone()[0]
    ctx.db.execute(
        "INSERT INTO inbox VALUES ('E900', ?, 's', 'b', '2026-10-14T00:00:00Z', ?)",
        (other, DAMAGED_ORDER_ID),
    )
    _screened(ctx, "E900")
    plan = Plan(request="refund", steps=[refund(DAMAGED_ORDER_ID, None, ["E900"])])
    v = validate_plan(plan, ctx)
    assert not v[0].ok and "evidence does not match order" in v[0].reason


def test_restock_rejects_email_evidence(ctx):
    """#77 (R50): a write step with no order or customer owner cannot cite an email."""
    _screened(ctx, "E001")
    step = _step(
        "create_restock_po", {"product_id": "P01", "qty_source": "user", "qty": 5}, ["E001"]
    )
    v = validate_plan(Plan(request="restock", steps=[step]), ctx)
    assert not v[0].ok and "email evidence" in v[0].reason
