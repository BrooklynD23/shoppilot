"""One door to Claude: retries, spend guard, slot, record/replay (spec 02 §3, §6, §7)."""

import hashlib
import json
import logging
import random
import sqlite3
import time
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Literal

import anthropic
from pydantic import BaseModel

from app.config import get_settings, session_hash
from app.llm.budget import (
    BudgetExceeded,
    Busy,
    cost_usd,
    ensure_budget,
    llm_slot,
    record_spend,
    worst_case_usd,
)

log = logging.getLogger(__name__)

RECORDINGS_DIR = Path(__file__).with_name("recordings")
PLANNER_BETAS = ["server-side-fallback-2026-07-01"]
MAX_RETRY_WAIT_S = 20.0
_SPEND_CAP_MSG = "You have reached your specified API usage limits"

_MSG = {
    "busy": "The AI is busy. Try again in a few seconds.",
    "overloaded": "The AI service is overloaded. Try again in a minute.",
    "unreachable": "Could not reach the AI service.",
    "budget": "Live AI is paused (budget reached). Try a demo request.",
    "not_configured": "Live AI is not configured.",
    "bad_request": "Internal error building the AI request.",
    "replay_miss": "No recording for this request. Run: python -m tests.eval.record",
}

Kind = Literal[
    "busy",
    "rate_limited",
    "overloaded",
    "unreachable",
    "budget",
    "not_configured",
    "bad_request",
    "replay_miss",
]


class LLMError(Exception):
    def __init__(
        self, kind: Kind, user_message: str | None = None, retry_after: float | None = None
    ):
        self.kind = kind
        self.user_message = user_message or _MSG.get(kind, "The AI request failed.")
        self.retry_after = retry_after
        super().__init__(self.user_message)


class CallUsage(BaseModel):
    stage: str
    model: str
    ms: int
    input_tokens: int
    cache_read_tokens: int
    cache_write_tokens: int
    output_tokens: int
    cost_usd: float
    retries: int
    replayed: bool


class LLMResponse(BaseModel):
    content: list[dict]
    stop_reason: str
    model: str
    usage: CallUsage
    stop_details: dict | None = None


@dataclass
class Trace:
    request: str
    session_id: str
    deadline: float  # time.monotonic() seconds
    calls: list[CallUsage] = field(default_factory=list)
    recorded: list[dict] = field(default_factory=list)
    n: int = 0  # logical complete() calls; replay index (calls[] also holds max_tokens retries)


# Test seam: when set, called with the kwargs dict instead of the SDK.
_send: Callable[[dict], Any] | None = None
_client: anthropic.Anthropic | None = None


def recording_key(request: str) -> str:
    return hashlib.sha256(" ".join(request.lower().split()).encode()).hexdigest()[:16]


def guard_version(system: str, schema: dict) -> str:
    return hashlib.sha256((system + json.dumps(schema, sort_keys=True)).encode()).hexdigest()[:8]


# ---------- SDK ----------


def _sdk() -> anthropic.Anthropic:
    global _client
    if _client is None:
        key = get_settings().anthropic_api_key
        if key is None:
            raise LLMError("not_configured")
        _client = anthropic.Anthropic(
            api_key=key.get_secret_value(),
            max_retries=0,
            timeout=anthropic.Timeout(60.0, connect=5.0),
        )
    return _client


def _sdk_send(kwargs: dict) -> Any:
    kw = dict(kwargs)
    sdk = _sdk().with_options(timeout=kw.pop("timeout"))
    api = sdk.beta.messages if "betas" in kw else sdk.messages
    r = api.create(**kw)
    log.info("llm ok request_id=%s model=%s", getattr(r, "_request_id", None), r.model)
    return r


def _to_dict(r: Any) -> dict:
    return r if isinstance(r, dict) else r.model_dump(mode="json")


# ---------- request + classification ----------


def _build(
    stage: str,
    model: str,
    system: str,
    messages: list[dict],
    max_tokens: int,
    effort: str,
    tools: list[dict] | None,
    output_format: dict | None,
    timeout_s: float,
) -> dict:
    sys_block: dict = {"type": "text", "text": system}
    out_cfg: dict = {"effort": effort}
    if output_format:
        out_cfg["format"] = {"type": "json_schema", "schema": output_format}
    kw: dict = dict(
        model=model,
        max_tokens=max_tokens,
        system=[sys_block],
        messages=messages,
        cache_control={"type": "ephemeral"},
        output_config=out_cfg,
        timeout=timeout_s,
    )
    if stage == "planner":
        sys_block["cache_control"] = {"type": "ephemeral"}
        kw.update(betas=PLANNER_BETAS, fallbacks="default")
        if tools:
            kw.update(tools=tools, tool_choice={"type": "auto"})
    return kw


def _error_body(exc: anthropic.APIStatusError) -> dict:
    body = exc.body if isinstance(exc.body, dict) else {}
    err = body.get("error")
    return err if isinstance(err, dict) else {}


def _retry_after(exc: anthropic.APIStatusError) -> float | None:
    try:
        return float(exc.response.headers["retry-after"])
    except (KeyError, ValueError):
        return None


def _classify(exc: Exception) -> tuple[Kind, int, float | None]:
    """-> (kind, max_attempts, retry_after). max_attempts 1 = never retried."""
    if isinstance(exc, anthropic.APIConnectionError):  # includes APITimeoutError
        return "unreachable", 2, None
    if not isinstance(exc, anthropic.APIStatusError):
        return "bad_request", 1, None
    err = _error_body(exc)
    code = exc.status_code
    log.warning("llm error status=%s type=%s request_id=%s", code, err.get("type"), exc.request_id)
    if isinstance(exc, anthropic.RateLimitError):
        details = err.get("details") if isinstance(err.get("details"), dict) else {}
        if details.get("error_code") == "enforced_spend_limit_reached":
            return "budget", 1, None
        return "rate_limited", 3, _retry_after(exc)
    if code in (401, 402, 403):
        return "not_configured", 1, None
    if code == 400 and str(err.get("message", "")).startswith(_SPEND_CAP_MSG):
        return "budget", 1, None
    if code >= 500:
        return "overloaded", 3, _retry_after(exc)
    return "bad_request", 1, None


def _usage(stage: str, model: str, raw: dict, ms: int, retries: int, replayed: bool) -> CallUsage:
    u = raw.get("usage") or {}
    return CallUsage(
        stage=stage,
        model=model,
        ms=ms,
        retries=retries,
        replayed=replayed,
        input_tokens=u.get("input_tokens") or 0,
        cache_read_tokens=u.get("cache_read_input_tokens") or 0,
        cache_write_tokens=u.get("cache_creation_input_tokens") or 0,
        output_tokens=u.get("output_tokens") or 0,
        cost_usd=0.0 if replayed else cost_usd(model, u),
    )


def _response(raw: dict, usage: CallUsage) -> LLMResponse:
    return LLMResponse(
        content=raw.get("content") or [],
        stop_reason=raw.get("stop_reason") or "",
        model=raw.get("model") or usage.model,
        usage=usage,
        stop_details=raw.get("stop_details"),
    )


# ---------- live call with retries ----------


def _attempt(kw: dict, trace: Trace) -> dict:
    est_in = len(json.dumps([kw["system"], kw["messages"], kw.get("tools")])) // 3
    try:
        with llm_slot():
            ensure_budget(trace.session_id, worst_case_usd(kw["model"], est_in, kw["max_tokens"]))
            return _to_dict((_send or _sdk_send)(kw))
    except Busy:
        raise LLMError("busy") from None
    except BudgetExceeded as e:
        log.warning("llm budget reached scope=%s", e.scope)
        raise LLMError("budget") from None
    except sqlite3.Error:
        log.exception("llm spend ledger unavailable")
        raise LLMError("busy") from None


def _wait_or_raise(exc: Exception, attempt: int, trace: Trace) -> None:
    kind, max_attempts, retry_after = _classify(exc)
    if kind == "rate_limited":
        msg = f"The AI is busy. Try again in {int(retry_after or 5)} s."
    else:
        msg = None
    wait = retry_after if retry_after is not None else 2**attempt + random.uniform(0, 0.5)  # noqa: S311
    if (
        attempt + 1 >= max_attempts
        or wait > MAX_RETRY_WAIT_S
        or time.monotonic() + wait > trace.deadline
    ):
        raise LLMError(kind, msg, retry_after) from None
    time.sleep(wait)


def _live(stage: str, kw: dict, trace: Trace) -> LLMResponse:
    attempt, doubled, t0 = 0, False, time.monotonic()
    while True:
        try:
            raw = _attempt(kw, trace)
        except anthropic.AnthropicError as exc:
            _wait_or_raise(exc, attempt, trace)
            attempt += 1
            continue
        usage = _usage(stage, kw["model"], raw, int((time.monotonic() - t0) * 1000), attempt, False)
        record_spend(trace.session_id, usage.cost_usd)
        trace.calls.append(usage)
        if raw.get("stop_reason") == "max_tokens":
            if doubled:
                raise LLMError("bad_request", "Request too big; split it.")
            doubled, kw = True, {**kw, "max_tokens": kw["max_tokens"] * 2}
            continue
        if get_settings().llm_mode == "record":
            trace.recorded.append({"stage": stage, "model": kw["model"], "response": raw})
        log.info(
            "llm stage=%s model=%s ms=%s retries=%s session=%s",
            stage,
            kw["model"],
            usage.ms,
            attempt,
            session_hash(trace.session_id),
        )
        return _response(raw, usage)


# ---------- replay ----------


def _replay(
    stage: str, model: str, trace: Trace, path: Path, idx: int, version: str | None
) -> LLMResponse:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if version is not None and data.get("guard_version") != version:
            raise KeyError("guard_version")  # stale guard prompt/schema: fail closed
        rec = data["calls"][idx]
    except (OSError, ValueError, KeyError, IndexError, TypeError):
        raise LLMError("replay_miss") from None
    raw = rec["response"]
    usage = _usage(stage, rec.get("model") or model, raw, 0, 0, True)
    trace.calls.append(usage)
    return _response(raw, usage)


def _call(
    stage: str, kw: dict, trace: Trace, rec_path: Path, version: str | None = None
) -> LLMResponse:
    idx, trace.n = trace.n, trace.n + 1
    if get_settings().llm_mode == "replay":
        return _replay(stage, kw["model"], trace, rec_path, idx, version)
    try:
        return _live(stage, kw, trace)
    except LLMError as e:
        if e.kind not in ("budget", "not_configured"):
            raise
        try:
            return _replay(stage, kw["model"], trace, rec_path, idx, version)
        except LLMError:
            raise e from None


def complete(
    *,
    stage: Literal["router", "planner", "judge"],
    model: str,
    system: str,
    messages: list[dict],
    trace: Trace,
    max_tokens: int,
    effort: str,
    tools: list[dict] | None = None,
    output_format: dict | None = None,
    timeout_s: float = 60.0,
) -> LLMResponse:
    kw = _build(stage, model, system, messages, max_tokens, effort, tools, output_format, timeout_s)
    return _call(stage, kw, trace, RECORDINGS_DIR / f"{recording_key(trace.request)}.json")


def _write_recording(path: Path, request: str, calls: list[dict], **stamp: str) -> Path:
    if not stamp:
        from app.llm.prompts import PROMPT_VERSION  # lazy: prompts are optional for the guard

        stamp = {"prompt_version": PROMPT_VERSION}
    path.parent.mkdir(parents=True, exist_ok=True)
    data = {
        "request": request,
        **stamp,
        "recorded_at": datetime.now(UTC).isoformat(timespec="seconds"),
        "calls": calls,
    }
    path.write_text(json.dumps(data, indent=1, sort_keys=True), encoding="utf-8")
    return path


def save_recording(trace: Trace) -> Path:
    path = RECORDINGS_DIR / f"{recording_key(trace.request)}.json"
    return _write_recording(path, trace.request, trace.recorded)


def complete_json(
    *,
    model: str,
    system: str,
    user: str,
    schema: dict,
    max_tokens: int,
    timeout_s: float,
    replay_key: str,
) -> dict:
    """Guard stage (R25): one structured call, parsed JSON. Any failure -> LLMError."""
    trace = Trace(request=replay_key, session_id="guard", deadline=time.monotonic() + timeout_s)
    kw = _build(
        "guard",
        model,
        system,
        [{"role": "user", "content": user}],
        max_tokens,
        "low",
        None,
        schema,
        timeout_s,
    )
    path = RECORDINGS_DIR / f"guard_{replay_key}.json"
    version = guard_version(system, schema)
    try:
        r = _call("guard", kw, trace, path, version)
    except LLMError:
        raise
    except Exception:
        log.exception("guard call failed")
        raise LLMError("bad_request") from None
    if r.stop_reason != "end_turn":
        raise LLMError("bad_request", f"Guard call ended with {r.stop_reason}.")
    try:
        text = next(b["text"] for b in r.content if b.get("type") == "text")
        out = json.loads(text)
    except (StopIteration, KeyError, ValueError):
        raise LLMError("bad_request", "Guard returned invalid JSON.") from None
    if not isinstance(out, dict):
        raise LLMError("bad_request", "Guard returned invalid JSON.")
    if trace.recorded:
        try:
            _write_recording(path, f"guard:{replay_key}", trace.recorded, guard_version=version)
        except Exception:
            log.exception("guard recording write failed")
            raise LLMError("bad_request") from None
    return out
