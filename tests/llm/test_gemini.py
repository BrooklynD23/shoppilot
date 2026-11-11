"""Gemini adapter: Anthropic-shaped kwargs <-> google-genai types, error mapping. No network."""

import os
import time
from pathlib import Path

import httpx2
import pytest
from google.auth.exceptions import DefaultCredentialsError
from google.genai import errors, types

from app.llm import client, gemini

TOOLS = [
    {
        "name": "list_orders",
        "description": "List orders.",
        "input_schema": {
            "type": "object",
            "properties": {"status": {"type": "string"}},
            "required": ["status"],
            "additionalProperties": False,
        },
        "strict": True,
    }
]
FORMAT = {"type": "object", "properties": {"status": {"type": "string"}}}
SIG = b"\x01sig"


def _kw(**over):
    kw = client._build(
        "planner", "gemini-3.1-flash-lite", "SYS", [], 800, "medium", TOOLS, FORMAT, 12.0
    )
    return {**kw, **over}


def test_request_mapping():
    messages = [
        {"role": "user", "content": "ship today"},
        {
            "role": "assistant",
            "content": [
                {"type": "text", "text": "Looking."},
                {
                    "type": "tool_use",
                    "id": "gm_abc",
                    "name": "list_orders",
                    "input": {"status": "paid"},
                    "thought_signature": "AXNpZw==",
                },
            ],
        },
        {
            "role": "user",
            "content": [
                {"type": "tool_result", "tool_use_id": "gm_abc", "content": "[]", "is_error": True}
            ],
        },
    ]
    contents = gemini.to_contents(messages)
    assert [c.role for c in contents] == ["user", "model", "user"]
    call = contents[1].parts[1]
    assert call.function_call.name == "list_orders" and call.function_call.args == {
        "status": "paid"
    }
    assert call.function_call.id is None and call.thought_signature == SIG  # local id not sent
    resp = contents[2].parts[0].function_response
    assert resp.name == "list_orders" and resp.response == {"error": "[]"}

    cfg = gemini.to_config(_kw(tool_choice={"type": "any"}))
    assert cfg.system_instruction == "SYS" and cfg.max_output_tokens == 800
    assert cfg.http_options.timeout == 12000
    # forced tool turn: Vertex rejects mode ANY + JSON mime, so no format on this turn
    assert cfg.response_mime_type is None and cfg.response_json_schema is None
    auto = gemini.to_config(_kw(tool_choice={"type": "auto"}))
    assert auto.response_mime_type == "application/json" and auto.response_json_schema == FORMAT
    assert auto.automatic_function_calling.disable
    assert cfg.thinking_config is None  # effort not mapped
    decl = cfg.tools[0].function_declarations[0]
    assert decl.name == "list_orders" and decl.parameters_json_schema == TOOLS[0]["input_schema"]
    assert cfg.tool_config.function_calling_config.mode == "ANY"


def _resp(parts, finish="STOP", **usage):
    return types.GenerateContentResponse(
        candidates=[
            types.Candidate(content=types.Content(role="model", parts=parts), finish_reason=finish)
        ],
        usage_metadata=types.GenerateContentResponseUsageMetadata(**usage),
    )


def test_response_mapping():
    fc = types.Part(
        function_call=types.FunctionCall(name="list_orders", args={"status": "paid"}),
        thought_signature=SIG,
    )
    r = gemini.to_anthropic(
        _resp(
            [types.Part(text="hmm", thought=True), types.Part(text="ok"), fc],
            prompt_token_count=100,
            cached_content_token_count=40,
            candidates_token_count=7,
            thoughts_token_count=3,
        ),
        "gemini-3.1-flash-lite",
    )
    assert r["stop_reason"] == "tool_use"
    text, use = r["content"]
    assert text == {"type": "text", "text": "ok"}
    assert use["id"].startswith("gm_") and use["input"] == {"status": "paid"}
    assert use["thought_signature"] == "AXNpZw=="
    assert r["usage"] == {
        "input_tokens": 60,
        "cache_read_input_tokens": 40,
        "cache_creation_input_tokens": 0,
        "output_tokens": 10,
    }
    # round trip: the echoed assistant turn carries the signature back
    back = gemini.to_contents([{"role": "assistant", "content": r["content"]}])[0].parts[1]
    assert back.thought_signature == SIG

    stop = lambda f: gemini.to_anthropic(_resp([types.Part(text="x")], f), "m")["stop_reason"]  # noqa: E731
    assert stop("MAX_TOKENS") == "max_tokens"
    assert stop("SAFETY") == "refusal"
    assert stop("STOP") == "end_turn"


@pytest.mark.parametrize(
    ("exc", "kind", "attempts"),
    [
        (errors.ClientError(429, {"error": {"message": "quota"}}), "rate_limited", 3),
        (errors.ServerError(503, {"error": {"message": "busy"}}), "overloaded", 3),
        (errors.ClientError(403, {"error": {"message": "denied"}}), "not_configured", 1),
        (
            errors.ClientError(
                400, {"error": {"message": "x", "details": [{"reason": "API_KEY_INVALID"}]}}
            ),
            "not_configured",
            1,
        ),
        (errors.ClientError(400, {"error": {"message": "bad schema"}}), "bad_request", 1),
        (httpx2.ConnectError("down"), "unreachable", 2),
        (DefaultCredentialsError("no adc"), "not_configured", 1),
    ],
)
def test_error_classification(exc, kind, attempts):
    assert client._classify(exc)[:2] == (kind, attempts)


def test_live_loop_retries_gemini_errors(llm_script, monkeypatch):
    monkeypatch.setattr(client.time, "sleep", lambda _s: None)
    ok = {"content": [{"type": "text", "text": "{}"}], "stop_reason": "end_turn", "usage": {}}
    llm_script.push(errors.ServerError(503, {"error": {"message": "busy"}}), ok)
    trace = client.Trace("r", "s", time.monotonic() + 60)
    r = client.complete(
        stage="judge",
        model="claude-haiku-5-5",
        system="S",
        messages=[{"role": "user", "content": "hi"}],
        trace=trace,
        max_tokens=64,
        effort="low",
    )
    assert r.usage.retries == 1 and len(llm_script.sent) == 2


def test_service_account_json_written_for_adc(monkeypatch, tmp_path):
    monkeypatch.setattr(gemini.tempfile, "tempdir", str(tmp_path))
    monkeypatch.delenv("GOOGLE_APPLICATION_CREDENTIALS", raising=False)
    path = gemini._write_adc('{"type": "service_account"}')
    assert os.environ["GOOGLE_APPLICATION_CREDENTIALS"] == path
    assert Path(path).read_text(encoding="utf-8") == '{"type": "service_account"}'
    assert os.stat(path).st_mode & 0o077 == 0  # owner-only


def test_express_mode_client_is_vertex():
    c = gemini.make_client(project="p", location="us-central1", api_key="k", sa_json=None)
    assert c.vertexai


def test_not_configured_without_vertex_auth(monkeypatch):
    for k in ("GOOGLE_CLOUD_PROJECT", "GOOGLE_API_KEY", "GOOGLE_APPLICATION_CREDENTIALS_JSON"):
        monkeypatch.delenv(k, raising=False)
    monkeypatch.setenv("LLM_PROVIDER", "gemini")
    monkeypatch.setattr(client, "_gclient", None)
    client.get_settings.cache_clear()
    with pytest.raises(client.LLMError) as e:
        client._sdk_send(_kw())
    assert e.value.kind == "not_configured"


@pytest.mark.live
def test_gemini_live_smoke(monkeypatch):
    # Vertex auth from env: GOOGLE_API_KEY (express) or project + ADC / service-account JSON
    key, project = os.environ.get("GOOGLE_API_KEY"), os.environ.get("GOOGLE_CLOUD_PROJECT")
    sa = os.environ.get("GOOGLE_APPLICATION_CREDENTIALS_JSON")
    if not (key or (project and (sa or os.environ.get("GOOGLE_APPLICATION_CREDENTIALS")))):
        pytest.skip("no Vertex credentials (GOOGLE_API_KEY or project + service account)")
    loc = os.environ.get("GOOGLE_CLOUD_LOCATION") or "global"
    gm = gemini.make_client(project=project, location=loc, api_key=key, sa_json=sa)
    kw = _kw(
        messages=[{"role": "user", "content": "List paid orders, then answer."}],
        tool_choice={"type": "any"},
    )
    r = gemini.send(gm, kw)
    assert r["stop_reason"] == "tool_use", r
    use = next(b for b in r["content"] if b["type"] == "tool_use")
    kw2 = {
        **kw,
        "tool_choice": {"type": "auto"},
        "messages": [
            *kw["messages"],
            {"role": "assistant", "content": r["content"]},
            {
                "role": "user",
                "content": [{"type": "tool_result", "tool_use_id": use["id"], "content": "[]"}],
            },
        ],
    }
    r2 = gemini.send(gm, kw2)
    assert r2["stop_reason"] == "end_turn" and r2["usage"]["output_tokens"] > 0, r2
