"""Gemini on Vertex AI: Anthropic-shaped request kwargs in, Anthropic-shaped response out.

The rest of the app (planner, guard, recordings, tests) only ever sees the Anthropic shape.
Dropped on purpose: cache_control (Gemini caches implicitly), betas, fallbacks and effort
(thinking_level values differ per Gemini model; the model default is used).
"""

import base64
import json
import logging
import os
import tempfile
import uuid
from typing import Any

import httpx2
from google import genai
from google.auth import exceptions as auth_errors
from google.genai import errors, types

# Exceptions the retry loop in client._live must catch for this provider. google-genai uses
# httpx2; httpx (v1) is only present in dev, so it is optional here.
ERRORS: tuple[type[Exception], ...] = (
    errors.APIError,
    auth_errors.GoogleAuthError,  # no ADC found, bad service-account key
    httpx2.TransportError,
)
try:
    import httpx

    ERRORS = (*ERRORS, httpx.TransportError)
except ImportError:  # pragma: no cover - prod image has no httpx v1
    pass

# The SDK warns on every tool-call turn that has a JSON schema set ("non-text parts in the
# response"); the adapter reads parts itself, so the warning is noise.
logging.getLogger("google_genai.types").setLevel(logging.ERROR)

_LOCAL_ID = "gm_"  # prefix for tool_use ids we invent when Gemini returns none
_REFUSAL = {"SAFETY", "PROHIBITED_CONTENT", "BLOCKLIST", "SPII", "RECITATION"}
_TOOL_MODE = {"auto": "AUTO", "any": "ANY", "tool": "ANY", "none": "NONE"}


def _sig(block: dict) -> bytes | None:
    s = block.get("thought_signature")
    return base64.b64decode(s) if s else None


def _tool_names(messages: list[dict]) -> dict[str, str]:
    """tool_use id -> function name (Gemini function responses need the name)."""
    return {
        b["id"]: b["name"]
        for m in messages
        if isinstance(m.get("content"), list)
        for b in m["content"]
        if b.get("type") == "tool_use"
    }


def _result_text(content: Any) -> str:
    if isinstance(content, str):
        return content
    return "".join(b.get("text", "") for b in content or [] if b.get("type") == "text")


def _part(block: dict, names: dict[str, str]) -> types.Part | None:
    kind = block.get("type")
    if kind == "text":
        return types.Part(text=block["text"], thought_signature=_sig(block))
    if kind == "tool_use":
        bid = block["id"]
        call = types.FunctionCall(
            name=block["name"],
            args=block.get("input") or {},
            id=None if bid.startswith(_LOCAL_ID) else bid,
        )
        return types.Part(function_call=call, thought_signature=_sig(block))
    if kind == "tool_result":
        tid = block["tool_use_id"]
        key = "error" if block.get("is_error") else "output"
        resp = types.FunctionResponse(
            name=names.get(tid, "unknown"),
            response={key: _result_text(block.get("content"))},
            id=None if tid.startswith(_LOCAL_ID) else tid,
        )
        return types.Part(function_response=resp)
    return None


def to_contents(messages: list[dict]) -> list[types.Content]:
    names = _tool_names(messages)
    out = []
    for m in messages:
        role = "model" if m["role"] == "assistant" else "user"
        c = m["content"]
        blocks = [{"type": "text", "text": c}] if isinstance(c, str) else c
        parts = [p for b in blocks if (p := _part(b, names)) is not None]
        out.append(types.Content(role=role, parts=parts))
    return out


def to_config(kw: dict) -> types.GenerateContentConfig:
    cfg: dict[str, Any] = {
        "system_instruction": "\n\n".join(b["text"] for b in kw["system"]),
        "max_output_tokens": kw["max_tokens"],
        "http_options": types.HttpOptions(timeout=int(kw["timeout"] * 1000)),
    }
    out_cfg = kw.get("output_config") or {}
    choice = kw.get("tool_choice") or {"type": "auto"}
    forced = bool(kw.get("tools")) and choice["type"] in ("any", "tool")
    # Vertex 400s on forced function calling (mode ANY) with a JSON mime type. A forced turn
    # must call a tool, so it never emits the final JSON; drop the format for that turn only.
    if (fmt := out_cfg.get("format")) and not forced:
        cfg["response_mime_type"] = "application/json"
        cfg["response_json_schema"] = fmt["schema"]
    if tools := kw.get("tools"):
        decls = [
            types.FunctionDeclaration(
                name=t["name"],
                description=t.get("description", ""),
                parameters_json_schema=t["input_schema"],
            )
            for t in tools
        ]
        cfg["tools"] = [types.Tool(function_declarations=decls)]
        fcc = types.FunctionCallingConfig(
            mode=_TOOL_MODE[choice["type"]],
            allowed_function_names=[choice["name"]] if choice["type"] == "tool" else None,
        )
        cfg["tool_config"] = types.ToolConfig(function_calling_config=fcc)
    # the app runs its own tool loop; never let the SDK call functions itself
    cfg["automatic_function_calling"] = types.AutomaticFunctionCallingConfig(disable=True)
    return types.GenerateContentConfig(**cfg)


def _block(p: types.Part) -> dict | None:
    if p.thought:
        return None
    if p.function_call:
        fc = p.function_call
        b = {
            "type": "tool_use",
            "id": fc.id or f"{_LOCAL_ID}{uuid.uuid4().hex[:12]}",
            "name": fc.name,
            "input": dict(fc.args or {}),
        }
    elif p.text:
        b = {"type": "text", "text": p.text}
    else:
        return None
    if p.thought_signature:  # Gemini 3 rejects a function-call turn sent back without it
        b["thought_signature"] = base64.b64encode(p.thought_signature).decode()
    return b


def to_anthropic(r: types.GenerateContentResponse, model: str) -> dict:
    cand = (r.candidates or [None])[0]
    parts = (cand.content.parts if cand and cand.content else None) or []
    content = [b for p in parts if (b := _block(p)) is not None]
    finish = cand.finish_reason.name if cand and cand.finish_reason else ""
    blocked = r.prompt_feedback is not None and r.prompt_feedback.block_reason is not None
    if blocked or finish in _REFUSAL:
        stop = "refusal"
    elif any(b["type"] == "tool_use" for b in content):
        stop = "tool_use"
    elif finish == "MAX_TOKENS":
        stop = "max_tokens"
    else:
        stop = "end_turn"
    u = r.usage_metadata or types.GenerateContentResponseUsageMetadata()
    cached = u.cached_content_token_count or 0
    return {
        "content": content,
        "stop_reason": stop,
        "model": model,
        "usage": {
            "input_tokens": (u.prompt_token_count or 0) - cached,
            "cache_read_input_tokens": cached,
            "cache_creation_input_tokens": 0,
            # thinking tokens are billed as output
            "output_tokens": (u.candidates_token_count or 0) + (u.thoughts_token_count or 0),
        },
    }


def _write_adc(sa_json: str) -> str:
    """Service-account JSON from env -> 0600 temp file, picked up by ADC."""
    fd, path = tempfile.mkstemp(prefix="gcp-sa-", suffix=".json")  # mode 0600
    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write(sa_json)
    os.environ["GOOGLE_APPLICATION_CREDENTIALS"] = path
    return path


def make_client(
    *, project: str | None, location: str, api_key: str | None, sa_json: str | None
) -> genai.Client:
    """Vertex AI client. SDK default: no retries; client._live retries."""
    if api_key:  # express mode: the key alone picks the project; global endpoint
        return genai.Client(vertexai=True, api_key=api_key)
    if sa_json:
        _write_adc(sa_json)
    return genai.Client(vertexai=True, project=project, location=location)


def send(client: genai.Client, kw: dict) -> dict:
    r = client.models.generate_content(
        model=kw["model"], contents=to_contents(kw["messages"]), config=to_config(kw)
    )
    return to_anthropic(r, kw["model"])


def _retry_after(exc: errors.APIError) -> float | None:
    try:
        return float(exc.response.headers["retry-after"])  # type: ignore[union-attr]
    except (AttributeError, KeyError, TypeError, ValueError):
        return None


def classify(exc: Exception) -> tuple[str, int, float | None]:
    """-> (kind, max_attempts, retry_after); same contract as client._classify."""
    if isinstance(exc, auth_errors.GoogleAuthError):
        return "not_configured", 1, None
    if not isinstance(exc, errors.APIError):
        return "unreachable", 2, None  # httpx transport error or timeout
    code, msg = exc.code or 0, json.dumps(exc.details) if exc.details else str(exc)
    if code == 429:
        return "rate_limited", 3, _retry_after(exc)
    if code in (401, 403) or (code == 400 and "API_KEY_INVALID" in msg):
        return "not_configured", 1, None
    if code >= 500:
        return "overloaded", 3, _retry_after(exc)
    return "bad_request", 1, None
