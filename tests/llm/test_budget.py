import importlib

import pytest

import app.llm.budget as budget
from app.config import get_settings
from app.llm.budget import (
    BudgetExceeded,
    Busy,
    cost_usd,
    ensure_budget,
    record_spend,
    worst_case_usd,
)


def set_settings(monkeypatch, **kw):
    for k, v in kw.items():
        monkeypatch.setenv(k.upper(), str(v))
    get_settings.cache_clear()


def test_cost_sonnet_mixed():
    u = {
        "input_tokens": 1000,
        "cache_creation_input_tokens": 5000,
        "cache_read_input_tokens": 0,
        "output_tokens": 2000,
    }
    assert cost_usd("claude-sonnet-5-5", u) == pytest.approx(0.002 + 0.0125 + 0.02)


def test_cost_haiku_cache_read():
    assert cost_usd("claude-haiku-5-5", {"cache_read_input_tokens": 1_000_000}) == pytest.approx(
        0.01
    )


def test_cost_unknown_model():
    with pytest.raises(KeyError):
        cost_usd("gpt-x", {})


def test_worst_case():
    assert worst_case_usd("claude-sonnet-5-5", 10_000, 8_000) == pytest.approx(0.02 + 0.08)


def test_session_budget(tmp_data_dir, monkeypatch):
    set_settings(monkeypatch, llm_session_budget_usd=0.10, llm_daily_budget_usd=5)
    record_spend("sA", 0.08)
    ensure_budget("sA", 0.01)
    with pytest.raises(BudgetExceeded) as e:
        ensure_budget("sA", 0.05)
    assert e.value.scope == "session"
    ensure_budget("sB", 0.05)  # other session unaffected


def test_global_budget(tmp_data_dir, monkeypatch):
    set_settings(monkeypatch, llm_session_budget_usd=1, llm_daily_budget_usd=0.10)
    record_spend("sA", 0.06)
    record_spend("sB", 0.03)
    with pytest.raises(BudgetExceeded) as e:
        ensure_budget("sC", 0.02)
    assert e.value.scope == "global"
    assert budget.spend_today() == pytest.approx(0.09)


def test_ledger_survives_reimport(tmp_data_dir):
    record_spend("sA", 0.2)
    saved = dict(vars(budget))  # restore after, so other modules keep the same class objects
    try:
        importlib.reload(budget)
        assert budget.spend_today("sA") == pytest.approx(0.2)
    finally:
        vars(budget).update(saved)


def test_session_id_not_stored_raw(tmp_data_dir):
    record_spend("secret-session", 0.01)
    assert b"secret-session" not in (tmp_data_dir / "spend.db").read_bytes()


def test_slot_busy():
    slots = [budget.llm_slot(wait_s=0.01) for _ in range(4)]
    for s in slots:
        s.__enter__()
    try:
        with pytest.raises(Busy), budget.llm_slot(wait_s=0.01):
            pass
    finally:
        for s in slots:
            s.__exit__(None, None, None)
    with budget.llm_slot(wait_s=0.01):  # released slots are reusable
        pass


def test_rate_window_busy(monkeypatch):
    monkeypatch.setattr(
        budget, "_calls", budget.deque([budget.time.monotonic()] * budget.CALLS_PER_MIN)
    )
    with pytest.raises(Busy), budget.llm_slot(wait_s=0.01):
        pass
