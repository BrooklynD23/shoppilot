import json
import time

import anthropic
import httpx2
import pytest

import app.llm.client as client
from app.config import get_settings
from app.llm import budget
from app.llm.client import LLMError, Trace, complete, complete_json, recording_key, save_recording

SONNET = "claude-sonnet-5-5"
HAIKU = "claude-haiku-5-5"
M = [{"role": "user", "content": "hi"}]
TOOL = {"name": "list_orders", "description": "d", "input_schema": {"type": "object"},
        "strict": True}
FMT = {"type": "object", "properties": {"a": {"type": "string"}}, "required": ["a"],
       "additionalProperties": False}
USAGE = {"input_tokens": 1000, "cache_creation_input_tokens": 5000,
         "cache_read_input_tokens": 0, "output_tokens": 2000}
_REQ = httpx2.Request("POST", "https://api.anthropic.com/v1/messages")


def resp(text="ok", stop="end_turn", usage=None):
    return {"content": [{"type": "text", "text": text}], "stop_reason": stop,
            "model": SONNET, "usage": usage or USAGE}


def status_err(cls, code, *, headers=None, body=None, msg="err"):
    r = httpx2.Response(code, headers=headers or {}, request=_REQ)
    return cls(msg, response=r, body=body)


def T(request="ship it", deadline_s=90.0):
    return Trace(request=request, session_id="s1", deadline=time.monotonic() + deadline_s)


def call(trace=None, **kw):
    args = dict(stage="planner", model=SONNET, system="S", messages=M, trace=trace or T(),
                max_tokens=8000, effort="medium")
    return complete(**{**args, **kw})


def set_env(monkeypatch, **kw):
    for k, v in kw.items():
        monkeypatch.setenv(k.upper(), str(v))
    get_settings.cache_clear()


@pytest.fixture(autouse=True)
def live(monkeypatch):
    set_env(monkeypatch, llm_mode="live")


@pytest.fixture
def sleeps(monkeypatch):
    out = []
    monkeypatch.setattr(time, "sleep", out.append)
    return out


class Script:
    """Fake _send: pops results (dict -> response, Exception -> raised); records kwargs."""

    def __init__(self, *results):
        self.results, self.sent = list(results), []

    def __call__(self, kwargs):
        self.sent.append(kwargs)
        r = self.results.pop(0)
        if isinstance(r, Exception):
            raise r
        return r

    @property
    def kwargs(self):
        return self.sent[-1]


@pytest.fixture
def send(monkeypatch):
    def install(*results):
        s = Script(*results)
        monkeypatch.setattr(client, "_send", s)
        return s
    return install


@pytest.fixture
def tmp_recordings(tmp_path, monkeypatch):
    d = tmp_path / "recordings"
    d.mkdir()
    monkeypatch.setattr(client, "RECORDINGS_DIR", d)
    return d


def write_recording(d, request, calls, name=None):
    data = {"request": request, "prompt_version": "x", "recorded_at": "2026-10-30",
            "calls": [{"stage": "planner", "model": SONNET, "response": c} for c in calls]}
    (d / (name or f"{recording_key(request)}.json")).write_text(json.dumps(data))


def test_success_records_usage_and_cost(send):
    send(resp())
    t = T()
    r = call(trace=t)
    assert r.usage.cost_usd == pytest.approx(0.0345) and r.usage.retries == 0
    assert not r.usage.replayed and r.usage.cache_write_tokens == 5000
    assert t.calls == [r.usage]
    assert budget.spend_today("s1") == pytest.approx(0.0345)


def test_request_shape(send):
    s = send(resp())
    call(tools=[TOOL], output_format=FMT)
    k = s.kwargs
    assert k["system"][0]["cache_control"] == {"type": "ephemeral"}
    assert k["cache_control"] == {"type": "ephemeral"}
    assert k["tool_choice"] == {"type": "auto"} and k["tools"] == [TOOL]
    assert k["output_config"] == {"effort": "medium",
                                  "format": {"type": "json_schema", "schema": FMT}}
    assert k["fallbacks"] == "default" and k["betas"]
    assert not {"temperature", "top_p", "top_k", "thinking"} & k.keys()


def test_router_shape_has_no_planner_extras(send):
    s = send(resp())
    call(stage="router", model=HAIKU, max_tokens=512, effort="low", output_format=FMT)
    k = s.kwargs
    assert not {"tools", "tool_choice", "betas", "fallbacks"} & k.keys()
    assert "cache_control" not in k["system"][0]


def test_retry_after_honoured(send, sleeps):
    send(status_err(anthropic.RateLimitError, 429, headers={"retry-after": "3"}), resp())
    assert call().usage.retries == 1 and sleeps == [3.0]


def test_spend_limit_429_not_retried(send, sleeps):
    body = {"error": {"type": "rate_limit_error", "message": "x",
                      "details": {"error_code": "enforced_spend_limit_reached"}}}
    send(status_err(anthropic.RateLimitError, 429, body=body))
    with pytest.raises(LLMError) as e:
        call()
    assert e.value.kind == "budget" and sleeps == []


def test_user_cap_400_not_retried(send):
    msg = "You have reached your specified API usage limits. You will regain access on ..."
    s = send(status_err(anthropic.BadRequestError, 400,
                        body={"error": {"type": "invalid_request_error", "message": msg}}))
    with pytest.raises(LLMError) as e:
        call()
    assert e.value.kind == "budget" and len(s.sent) == 1


def test_overloaded_529_backoff_then_gives_up(send, sleeps):
    send(*[status_err(anthropic.OverloadedError, 529) for _ in range(3)])
    with pytest.raises(LLMError) as e:
        call()
    assert e.value.kind == "overloaded" and len(sleeps) == 2
    assert 1 <= sleeps[0] <= 1.5 and 2 <= sleeps[1] <= 2.5


def test_connection_error_two_attempts(send, sleeps):
    s = send(*[anthropic.APIConnectionError(request=_REQ) for _ in range(2)])
    with pytest.raises(LLMError) as e:
        call()
    assert e.value.kind == "unreachable" and len(s.sent) == 2 and len(sleeps) == 1


def test_long_retry_after_fails_fast(send, sleeps):
    send(status_err(anthropic.RateLimitError, 429, headers={"retry-after": "45"}))
    with pytest.raises(LLMError) as e:
        call()
    assert e.value.kind == "rate_limited" and e.value.retry_after == 45 and sleeps == []


def test_deadline_respected(send, sleeps):
    send(status_err(anthropic.InternalServerError, 500))
    with pytest.raises(LLMError):
        call(trace=T(deadline_s=1))
    assert sleeps == []


def test_auth_error_maps_not_configured(send):
    send(status_err(anthropic.AuthenticationError, 401))
    with pytest.raises(LLMError) as e:
        call()
    assert e.value.kind == "not_configured"


def test_bad_request_not_retried(send):
    s = send(status_err(anthropic.BadRequestError, 400,
                        body={"error": {"type": "invalid_request_error", "message": "bad"}}))
    with pytest.raises(LLMError) as e:
        call()
    assert e.value.kind == "bad_request" and len(s.sent) == 1


def test_max_tokens_retries_once_doubled(send):
    s = send(resp(stop="max_tokens"), resp())
    assert call().stop_reason == "end_turn"
    assert [k["max_tokens"] for k in s.sent] == [8000, 16000]


def test_max_tokens_twice_raises(send):
    send(resp(stop="max_tokens"), resp(stop="max_tokens"))
    with pytest.raises(LLMError) as e:
        call()
    assert "split" in e.value.user_message


def test_budget_exceeded_before_send(send, monkeypatch):
    set_env(monkeypatch, llm_mode="live", llm_session_budget_usd=0.01)
    s = send(resp())
    with pytest.raises(LLMError) as e:
        call()
    assert e.value.kind == "budget" and s.sent == []


def test_busy_maps_to_busy(send, monkeypatch):
    def full(*_a, **_k):
        raise budget.Busy("full")
    monkeypatch.setattr(client, "llm_slot", full)
    send(resp())
    with pytest.raises(LLMError) as e:
        call()
    assert e.value.kind == "busy"


def test_replay_returns_calls_in_order(tmp_recordings, monkeypatch, send):
    set_env(monkeypatch, llm_mode="replay")
    s = send()
    r1, r2 = resp("one"), resp("two")
    write_recording(tmp_recordings, "Ship it", [r1, r2])
    t = T(request="  ship   IT ")
    assert call(trace=t).content == r1["content"]
    r = call(trace=t)
    assert r.content == r2["content"] and t.calls[-1].replayed and r.usage.cost_usd == 0
    assert s.sent == []


def test_replay_miss(tmp_recordings, monkeypatch):
    set_env(monkeypatch, llm_mode="replay")
    with pytest.raises(LLMError) as e:
        call(trace=T(request="never recorded"))
    assert e.value.kind == "replay_miss"


def test_live_budget_falls_back_to_replay(tmp_recordings, monkeypatch, send):
    set_env(monkeypatch, llm_mode="live", llm_session_budget_usd=0.01)
    send()
    write_recording(tmp_recordings, "ship it", [resp("canned")])
    r = call()
    assert r.usage.replayed and r.content[0]["text"] == "canned"


def test_api_key_never_in_error_text(send, monkeypatch):
    set_env(monkeypatch, llm_mode="live", anthropic_api_key="sk-ant-secret123")
    send(status_err(anthropic.AuthenticationError, 401, msg="bad key sk-ant-secret123"))
    with pytest.raises(LLMError) as e:
        call()
    assert "sk-ant" not in str(e.value) and "sk-ant" not in e.value.user_message


def test_no_key_is_not_configured(monkeypatch):
    set_env(monkeypatch, llm_mode="live", anthropic_api_key="")
    monkeypatch.setattr(client, "_client", None)
    with pytest.raises(LLMError) as e:
        call()
    assert e.value.kind == "not_configured"


def test_record_mode_saves_recording(tmp_recordings, monkeypatch, send):
    set_env(monkeypatch, llm_mode="record")
    send(resp("live answer"))
    t = T(request="Ship It")
    call(trace=t)
    path = save_recording(t)
    data = json.loads(path.read_text())
    assert path.name == f"{recording_key('ship it')}.json"
    assert data["calls"][0]["response"]["content"][0]["text"] == "live answer"
    assert data["calls"][0]["stage"] == "planner" and data["prompt_version"]


def test_recording_key_normalizes():
    assert recording_key("  Ship\n IT ") == recording_key("ship it")
    assert len(recording_key("x")) == 16


# ---- complete_json (R25) ----

def cj(**kw):
    args = dict(model=HAIKU, system="S", user="U", schema=FMT, max_tokens=256,
                timeout_s=15.0, replay_key="abc123")
    return complete_json(**{**args, **kw})


def test_complete_json_returns_dict(send):
    s = send(resp('{"a": "b"}'))
    assert cj() == {"a": "b"}
    k = s.kwargs
    assert k["output_config"]["format"] == {"type": "json_schema", "schema": FMT}
    assert k["messages"] == [{"role": "user", "content": "U"}]
    assert budget.spend_today("guard") > 0


def test_complete_json_replay_by_key(tmp_recordings, monkeypatch, send):
    set_env(monkeypatch, llm_mode="replay")
    send()
    write_recording(tmp_recordings, "x", [resp('{"a": "z"}')], name="guard_abc123.json")
    assert cj() == {"a": "z"}


def test_complete_json_record_writes_guard_file(tmp_recordings, monkeypatch, send):
    set_env(monkeypatch, llm_mode="record")
    send(resp('{"a": "r"}'))
    cj(replay_key="k9")
    data = json.loads((tmp_recordings / "guard_k9.json").read_text())
    assert data["calls"][0]["stage"] == "guard"


@pytest.mark.parametrize("result", [
    resp("not json"),
    resp('{"a": 1}', stop="refusal"),
    status_err(anthropic.AuthenticationError, 401),
])
def test_complete_json_any_error_raises(send, result):
    send(result)
    with pytest.raises(LLMError):
        cj()


def test_complete_json_replay_miss_raises(tmp_recordings, monkeypatch):
    set_env(monkeypatch, llm_mode="replay")
    with pytest.raises(LLMError) as e:
        cj(replay_key="nope")
    assert e.value.kind == "replay_miss"
