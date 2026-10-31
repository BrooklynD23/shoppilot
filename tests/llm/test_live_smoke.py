"""Live smoke spike (P2-T4). Real Anthropic calls; cost < $0.02.

Run: RUN_LIVE=1 ANTHROPIC_API_KEY=... uv run pytest tests/llm/test_live_smoke.py -m live -v
Skipped unless RUN_LIVE=1 (conftest) and a key is in env or .env.
"""

import json
import os
import time
from pathlib import Path

import pytest

from app.config import get_settings
from app.llm import client
from app.llm.client import Trace, complete

pytestmark = pytest.mark.live

ENV_FILE = Path(__file__).resolve().parents[2] / ".env"

LOOKUP_TOOL = {
    "name": "lookup_order",
    "description": "Look up one order by id. Returns its status.",
    "input_schema": {"type": "object", "properties": {"order_id": {"type": "string"}},
                     "required": ["order_id"], "additionalProperties": False},
    "strict": True,
}
PLAN_FMT = {"type": "object", "properties": {"answer": {"type": "string"}},
            "required": ["answer"], "additionalProperties": False}
ROUTER_FMT = {"type": "object",
              "properties": {"reason": {"type": "string"},
                             "route": {"type": "string", "enum": ["plan", "reject"]},
                             "reply": {"type": "string"}},
              "required": ["reason", "route", "reply"], "additionalProperties": False}
# ~2,000+ tokens: above the prompt-cache minimum for 5.5 models.
LONG_SYSTEM = "You help run a small online candle shop called Fern & Kiln. " + " ".join(
    f"Rule {i}: keep answers short, name order ids exactly, never invent data."
    for i in range(160))


def _key_from_env_file() -> str | None:
    try:
        lines = ENV_FILE.read_text(encoding="utf-8").splitlines()
    except OSError:
        return None
    for line in lines:
        name, _, value = line.partition("=")
        if name.strip() == "ANTHROPIC_API_KEY" and value.strip():
            return value.strip().strip("\"'")
    return None


@pytest.fixture(autouse=True)
def live_settings(monkeypatch):
    key = os.environ.get("ANTHROPIC_API_KEY") or _key_from_env_file()
    if not key:
        pytest.skip("no ANTHROPIC_API_KEY in env or .env")
    monkeypatch.setenv("ANTHROPIC_API_KEY", key)
    monkeypatch.setenv("LLM_MODE", "live")
    monkeypatch.setattr(client, "_client", None)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def _trace(request: str) -> Trace:
    return Trace(request=request, session_id="live-smoke", deadline=time.monotonic() + 90)


def test_strict_tool_plus_format_plus_fallback():
    s = get_settings()
    r = complete(stage="planner", model=s.planner_model, system="You look up orders.",
                 messages=[{"role": "user", "content": "Look up order O1 then answer"}],
                 trace=_trace("smoke tool"), max_tokens=1024, effort="low",
                 tools=[LOOKUP_TOOL], output_format=PLAN_FMT)
    assert r.stop_reason in ("tool_use", "end_turn")


def test_prefix_cache_hits():
    s, t = get_settings(), _trace("smoke cache")
    for q in ("Say hi.", "Say bye."):
        last = complete(stage="planner", model=s.planner_model, system=LONG_SYSTEM,
                        messages=[{"role": "user", "content": q}], trace=t,
                        max_tokens=256, effort="low")
    assert last.usage.cache_read_tokens >= 1000


def test_haiku_structured():
    s = get_settings()
    r = complete(stage="router", model=s.judge_model,
                 system="Route shop requests. route plan for shop work, reject otherwise.",
                 messages=[{"role": "user", "content": "What's the weather in Pomona?"}],
                 trace=_trace("smoke router"), max_tokens=512, effort="low",
                 output_format=ROUTER_FMT)
    text = next(b["text"] for b in r.content if b.get("type") == "text")
    assert json.loads(text)["route"] in ("plan", "reject")
