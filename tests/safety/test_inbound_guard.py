import json
import re
from pathlib import Path

import pytest

import app.safety.inbound_guard as ig
from app.seed.generate import INJECTION_BODY

CASES = json.loads((Path(__file__).parent / "guard_cases.json").read_text("utf-8"))


@pytest.fixture(autouse=True)
def fresh():
    ig._clear_cache()


def fake_llm(case):
    def f(**kw):
        if case["layer"] == "H":
            raise AssertionError("heuristic case must not call the LLM")
        return case["llm_fixture"]

    return f


def boom(**_k):
    raise ConnectionError()


@pytest.mark.parametrize("case", CASES, ids=lambda c: f"case{c['id']}")
def test_case(case, monkeypatch):
    monkeypatch.setattr(ig, "complete_json", fake_llm(case))
    v = ig.screen(case["text"], f"{case['source']}:{case['id']}")
    assert v.allowed is case["expect_allowed"] and v.label == case["expect_label"]


@pytest.mark.parametrize("case", CASES, ids=lambda c: f"layer{c['id']}")
def test_layer(case):
    score, _ = ig.heuristic_score(case["text"])
    assert (score >= ig.BLOCK_SCORE) is (case["layer"] == "H")


def test_planted_text_matches_seed():
    assert CASES[0]["text"] == INJECTION_BODY


def test_planted_email_offline(monkeypatch):
    monkeypatch.setattr(ig, "complete_json", boom)
    v = ig.screen(CASES[0]["text"], "email:E002")
    assert not v.allowed and v.label == "injection" and v.reason.startswith("Blocked: ")
    assert "override the agent's rules" in v.reason and v.score == 1.0


def test_oversize_no_llm(monkeypatch):
    monkeypatch.setattr(ig, "complete_json", fake_llm({"layer": "H"}))
    v = ig.screen("a" * 4001, "email:x")
    assert v.label == "oversize" and v.allowed is False


def test_llm_error_fails_closed_and_not_cached(monkeypatch):
    calls = []

    def err(**k):
        calls.append(1)
        raise TimeoutError()

    monkeypatch.setattr(ig, "complete_json", err)
    t = "Where is my order?"
    v = ig.screen(t, "email:a")
    assert v.label == "guard_error" and v.reason == "Guard unavailable — held for manual review."
    assert ig.screen(t, "email:a").allowed is False and len(calls) == 2


def test_bad_llm_output_fails_closed(monkeypatch):
    monkeypatch.setattr(
        ig, "complete_json", lambda **k: {"label": "maybe", "confidence": 1, "reason": ""}
    )
    assert ig.screen("Thanks!", "email:a").label == "guard_error"


def test_cache_one_llm_call(monkeypatch):
    calls = []
    monkeypatch.setattr(ig, "complete_json", lambda **k: calls.append(k) or clean_llm())
    ig.screen("Where is my order?", "email:a")
    v = ig.screen("Where is my order?", "email:b")
    assert len(calls) == 1 and v.source_id == "email:b"


def test_nonce_wrapping_and_clamp(monkeypatch):
    # plan used "hello </untrusted-", but role_markup blocks it before the LLM;
    # any benign text proves the wrap
    seen = {}

    def f(**k):
        seen.update(k)
        return {"label": "injection", "confidence": 7.0, "reason": "x" * 999}

    monkeypatch.setattr(ig, "complete_json", f)
    text = "hello </b> thanks\nfor the mug"
    v = ig.screen(text, "email:a")
    m = re.match(r"<untrusted-([0-9a-f]{16})>\n(.*)\n</untrusted-\1>$", seen["user"], re.S)
    assert m and m.group(2) == text
    assert v.score == 1.0 and len(v.reason) <= 200 and seen["model"] == "claude-haiku-5-5"
    assert seen["replay_key"] == ig.hashlib.sha256(text.encode()).hexdigest()[:16]


def test_low_confidence_injection_allowed(monkeypatch):
    monkeypatch.setattr(
        ig,
        "complete_json",
        lambda **k: {"label": "injection", "confidence": 0.3, "reason": "unsure"},
    )
    assert ig.screen("Thanks!", "email:a").allowed is True


def test_tool_name_rule(monkeypatch):
    from app.tools.registry import ToolSpec

    spec = ToolSpec(
        name="refund_order",
        description="",
        input_schema={},
        destructive=True,
        moves_money=True,
        undoable=False,
    )
    monkeypatch.setattr(ig, "get_tools", lambda: [spec])
    score, rules = ig.heuristic_score("please run refund_order")
    assert score == 0.5 and rules == ["tool_name"]


# ---------- screen_inbox (R24) ----------


def _guard_calls(monkeypatch):
    calls = []
    real = ig.screen

    def spy(text, source_id):
        calls.append(source_id)
        return real(text, source_id)

    monkeypatch.setattr(ig, "screen", spy)
    return calls


def _blocks(ctx):
    return ctx.db.execute("SELECT payload_json FROM audit_log WHERE kind='guard_block'").fetchall()


def clean_llm(**_k):
    return {"label": "clean", "confidence": 0.9, "reason": "ok"}


def test_screen_inbox_caches(ctx, monkeypatch):
    monkeypatch.setattr(ig, "complete_json", clean_llm)
    calls = _guard_calls(monkeypatch)
    first = ig.screen_inbox(ctx)
    assert len(calls) == 4
    rows = ctx.db.execute("SELECT source_id FROM guard_verdicts ORDER BY source_id").fetchall()
    assert [r[0] for r in rows] == ["email:E001", "email:E002", "email:E003", "email:E004"]
    calls.clear()
    second = ig.screen_inbox(ctx)
    assert calls == [] and second == first
    e = first[0]
    assert set(e) == {"id", "from", "subject", "body", "received_at", "order_id", "verdict"}
    assert e["verdict"]["source_id"] == f"email:{e['id']}"


def test_screen_inbox_logs_block_once(ctx, monkeypatch):
    monkeypatch.setattr(ig, "complete_json", clean_llm)
    ig.screen_inbox(ctx)
    ig.screen_inbox(ctx)
    blocks = _blocks(ctx)
    assert len(blocks) == 1
    p = json.loads(blocks[0][0])
    assert p["source_id"] == "email:E002" and p["label"] == "injection" and p["score"] == 1.0


def test_e002_blocked_offline(ctx, monkeypatch):
    monkeypatch.setattr(ig, "complete_json", boom)
    by_id = {e["id"]: e["verdict"] for e in ig.screen_inbox(ctx)}
    assert by_id["E002"]["label"] == "injection" and by_id["E002"]["allowed"] is False
    assert {by_id[k]["label"] for k in ("E001", "E003", "E004")} == {"guard_error"}
    # guard_error is not stored, so the next call retries
    stored = {r[0] for r in ctx.db.execute("SELECT source_id FROM guard_verdicts")}
    assert stored == {"email:E002"} and len(_blocks(ctx)) == 1


def test_screen_inbox_concurrent_first_load(ctx, monkeypatch):
    """#53/#54: a second connection screens and commits mid-flight; no IntegrityError."""
    from app.db import get_db

    monkeypatch.setattr(ig, "complete_json", clean_llm)
    real, raced = ig.screen, []

    def racing(text, source_id):
        if not raced:
            raced.append(1)
            assert not ctx.db.in_transaction  # no write txn held across LLM calls (#54)
            with get_db(ctx.session_id) as db2:
                ig.screen_inbox(ctx.__class__(ctx.session_id, db2, ctx.now, ctx.today))
        return real(text, source_id)

    monkeypatch.setattr(ig, "screen", racing)
    out = ig.screen_inbox(ctx)
    assert len(out) == 4
    n = ctx.db.execute("SELECT COUNT(*) FROM guard_verdicts").fetchone()[0]
    assert n == 4 and len(_blocks(ctx)) == 1
    assert {e["id"]: e["verdict"]["label"] for e in out}["E002"] == "injection"


L_CASES = [c for c in CASES if c["layer"] == "L"]


@pytest.mark.live
@pytest.mark.parametrize("case", L_CASES, ids=lambda c: f"live{c['id']}")
def test_live(case):
    pytest.skip("body in P4-T6")


def _replay_miss(**k):
    from app.llm.client import LLMError

    raise LLMError("replay_miss")


def test_replay_miss_falls_back_to_heuristic(ctx, monkeypatch):
    # Recorded mode with no saved guard answer: the regex layer decides; verdicts are stored.
    monkeypatch.setattr(ig, "complete_json", _replay_miss)
    by_id = {e["id"]: e["verdict"] for e in ig.screen_inbox(ctx)}
    assert by_id["E002"]["label"] == "injection" and by_id["E002"]["allowed"] is False
    for k in ("E001", "E003", "E004"):
        assert by_id[k]["label"] == "heuristic_only" and by_id[k]["allowed"] is True
    allowed = {r[0] for r in ctx.db.execute("SELECT source_id FROM guard_verdicts WHERE allowed=1")}
    assert {"email:E001", "email:E003", "email:E004"} <= allowed


def test_replay_miss_email_is_valid_evidence(ctx, monkeypatch):
    # The validator must agree with the inbox: an allowed email can back a refund.
    from app.agent.models import Plan
    from app.agent.validator import _plan_context

    monkeypatch.setattr(ig, "complete_json", _replay_miss)
    ig.screen_inbox(ctx)
    pc = _plan_context(Plan(request="refund damaged", steps=[]), ctx)
    assert "email:E001" not in pc.blocked_ids and "email:E002" in pc.blocked_ids


def test_other_llm_errors_still_fail_closed(monkeypatch):
    from app.llm.client import LLMError

    def spend_cap(**k):
        raise LLMError("budget")

    monkeypatch.setattr(ig, "complete_json", spend_cap)
    assert ig.screen("Where is my order?", "email:z").label == "guard_error"
