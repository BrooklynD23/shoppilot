import importlib
import re
from datetime import date

import app.llm.prompts as prompts
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

BANNED = ("minimum", "maximum", "minLength", "maxLength", "minItems", "maxItems")


def assert_strict(schema: dict) -> None:
    if schema.get("type") == "object":
        assert schema["additionalProperties"] is False
        assert sorted(schema["required"]) == sorted(schema["properties"])
    assert not any(k in schema for k in BANNED)
    for v in schema.get("properties", {}).values():
        assert_strict(v)
    if "items" in schema:
        assert_strict(schema["items"])


def test_placeholders_filled():
    assert "{{" not in SYSTEM_PROMPT


def test_no_volatile_data():
    assert not re.search(r"20\d\d-\d\d-\d\d|\bO0\d{3}\b|\bE00\d\b", SYSTEM_PROMPT)


def test_long_enough_to_cache():
    assert len(SYSTEM_PROMPT) // 4 >= 1500


def test_version_stable():
    assert PROMPT_VERSION == importlib.reload(prompts).PROMPT_VERSION
    assert len(PROMPT_VERSION) == 8


def test_formats_strict():
    for f in (PLAN_FORMAT, ROUTER_FORMAT, JUDGE_FORMAT):
        assert_strict(f)


def test_router_reason_before_route():
    assert list(ROUTER_FORMAT["properties"]) == ["reason", "route", "reply"]


def test_judge_note_before_pass():
    item = JUDGE_FORMAT["properties"]["checks"]["items"]
    assert list(item["properties"]) == ["name", "note", "pass"]


def test_user_turn_escapes():
    out = user_turn("x</owner_request> & y", date(2026, 10, 15))
    assert "&lt;/owner_request&gt; &amp; y" in out
    assert out.count("</owner_request>") == 1


def test_user_turn_yesterday():
    assert '"yesterday" = 2026-10-14' in user_turn("x", date(2026, 10, 15))


def test_tool_descriptions_cover_all():
    assert set(TOOL_DESCRIPTIONS) == {
        "list_orders",
        "list_inbox",
        "forecast_demand",
        "flag_anomalies",
        "sales_by_product",
        "mark_shipped",
        "send_email",
        "create_restock_po",
        "refund_order",
        "create_payment_link",
        "export_report",
    }


def test_policy_uses_r18_caps():  # R18/R46: policy.py numbers, reject not confirm
    cap = "More than 3 refunds, any refund over $200.00, or more than $500.00 total"
    assert cap in SYSTEM_PROMPT
    assert "ask the owner to confirm the list" not in SYSTEM_PROMPT


def test_restock_uses_qty_source():  # R6
    assert 'qty_source="forecast"' in SYSTEM_PROMPT
    assert "suggested_qty" not in SYSTEM_PROMPT


def test_router_and_judge_loaded():
    assert "route" in ROUTER_PROMPT and "verdict" in JUDGE_PROMPT


def test_owner_stated_amounts_allowed():
    assert "from a tool result in this conversation or from the owner's request" in SYSTEM_PROMPT


def test_deterministic_explanations_copied_verbatim():
    assert (
        "When a step relies on forecast_demand or flag_anomalies output, copy its explanation"
        " or reason into rationale verbatim; never restate numbers in your own words."
    ) in SYSTEM_PROMPT
