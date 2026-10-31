"""HTTP surface (P1-T6): sessions, store, audit, undo, rate limits, error envelope, CSP."""

import logging
import math
import os
import secrets
import sqlite3
import threading
import time
from collections import deque
from collections.abc import Iterator
from contextlib import asynccontextmanager, contextmanager
from datetime import UTC, date, datetime
from http import HTTPStatus
from pathlib import Path
from typing import Annotated

from fastapi import APIRouter, Depends, FastAPI, Request, Response
from fastapi import Path as PathParam
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field, StringConstraints
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.agent.audit import UndoError, list_actions, log_action, undo_action, verify_chain
from app.agent.dryrun import dry_run
from app.agent.executor import PlanError, claim_plan, execute
from app.agent.planner import make_plan, save_plan
from app.agent.validator import validate_plan
from app.config import get_settings, session_hash
from app.db import SESSION_ID_RE, create_store, get_db, store_exists, sweep_sessions, touch_store
from app.integrations.export import EXPORT_KINDS, render
from app.integrations.outbox import list_outbox
from app.llm.client import LLMError
from app.safety import web
from app.safety.inbound_guard import screen_inbox
from app.seed.generate import STORE_NAME
from app.tools.registry import Ctx, get_tools, load_tools

log = logging.getLogger("shoppilot")
COOKIE = "sp_session"
CSP = (
    "default-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'; "
    "connect-src 'self'; frame-ancestors 'none'"
)
SECURITY_HEADERS = {
    "Content-Security-Policy": CSP,
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "same-origin",
}
# R36 limits: (bucket, limit, window_s)
SESSION_LIMIT, API_LIMIT, PLAN_IP_LIMIT, PLAN_SESSION_LIMIT = 10, 120, 60, 10
UNDO_STATUS = {"not_found": 404, "undo_failed": 422}  # rest -> 409
PLAN_ERROR = {
    "not_found": (404, "plan_not_found"),
    "expired": (410, "plan_expired"),
    "invalid": (422, "plan_invalid"),
}
STATUS_CODE = {
    401: "no_session",
    404: "not_found",
    413: "too_large",
    415: "bad_content_type",
    422: "bad_request",
    429: "rate_limited",
}


class ApiError(Exception):
    def __init__(
        self, status: int, code: str, message: str | None = None, retry_after_s: int | None = None
    ):
        super().__init__(code)
        self.status, self.code, self.retry_after_s = status, code, retry_after_s
        self.message = message or HTTPStatus(status).phrase


def _envelope(status: int, code: str, message: str, retry_after_s: int | None = None):
    err = {"code": code, "message": message}
    if retry_after_s is not None:
        err["retry_after_s"] = retry_after_s
    return JSONResponse({"error": err}, status_code=status)


# ---------- rate limiting ----------
# ponytail: in-process limiter, fine at --workers 1; move to a shared store if we scale out
_hits: dict[tuple, deque[float]] = {}
_hits_lock = threading.Lock()


def _reset_rate_limits() -> None:
    with _hits_lock:
        _hits.clear()


def _hit(key: tuple, limit: int, window_s: float = 60.0) -> None:
    now = time.monotonic()
    with _hits_lock:
        q = _hits.setdefault(key, deque())
        while q and q[0] <= now - window_s:
            q.popleft()
        if len(q) >= limit:
            wait = max(1, math.ceil(window_s - (now - q[0])))
            raise ApiError(429, "rate_limited", "Too many requests. Try again shortly.", wait)
        q.append(now)


def client_ip(request: Request) -> str:
    """R45: rightmost X-Forwarded-For entry (appended by Render's edge), else the peer."""
    xff = ",".join(request.headers.getlist("x-forwarded-for"))  # every header line, not the 1st
    last = xff.rsplit(",", 1)[-1].strip()
    return last or (request.client.host if request.client else "unknown")


def rate_limit(bucket: str, per_minute: int):
    def dep(request: Request) -> None:
        _hit((bucket, client_ip(request)), per_minute)

    return dep


# ---------- sessions ----------
# ponytail: one global lock serializes store create/reseed (fine at --workers 1);
# per-sid locks if create throughput ever matters
_store_lock = threading.Lock()


def _valid_sid(request: Request) -> str | None:
    sid = request.cookies.get(COOKIE, "")
    return sid if SESSION_ID_RE.fullmatch(sid) else None


def current_session(request: Request) -> str:
    sid = _valid_sid(request)
    if sid is None:  # regex first: a bad cookie never touches disk
        raise ApiError(401, "no_session", "No session. POST /api/session first.")
    request.state.store_reset = False
    if not store_exists(sid):
        with _store_lock:  # re-check: parallel requests after a restart reseed once
            if not store_exists(sid):  # restart wiped disk: reseed; one session-bucket hit
                _hit(("session", client_ip(request)), SESSION_LIMIT)
                sweep_sessions()
                create_store(sid, datetime.now(UTC).date())
                request.state.store_reset = True
    if not request.state.store_reset:
        touch_store(sid)
    return sid


@contextmanager
def _open_ctx(sid: str) -> Iterator[Ctx]:
    with get_db(sid) as db:
        anchor = db.execute("SELECT value FROM meta WHERE key = 'anchor'").fetchone()[0]
        yield Ctx(sid, db, datetime.now(UTC), date.fromisoformat(anchor))


def session_ctx(sid: str = Depends(current_session)) -> Iterator[Ctx]:
    with _open_ctx(sid) as ctx:
        yield ctx


SessionCtx = Annotated[Ctx, Depends(session_ctx, scope="function")]  # commit before response


def _modes() -> dict:
    s = get_settings()  # stripe mode mirrors stripe_client.resolve_mode without booting the SDK
    stripe = "test" if s.stripe_secret_key and s.stripe_mode == "auto" else "mock"
    return {"store_name": STORE_NAME, "llm_mode": s.llm_mode, "stripe_mode": stripe}


# ---------- app ----------
@asynccontextmanager
async def lifespan(_app: FastAPI):
    s = get_settings()
    s.data_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    sweep_sessions()
    load_tools()
    yield


app = FastAPI(title="ShopPilot+", lifespan=lifespan)
api = APIRouter(prefix="/api", dependencies=[Depends(rate_limit("api", API_LIMIT))])


@app.middleware("http")
async def guard(request: Request, call_next):
    try:
        response = await call_next(request)
    except Exception:
        sid = _valid_sid(request)
        log.exception(
            "unhandled error path=%s session=%s",
            request.url.path,
            session_hash(sid) if sid else "-",
        )
        response = _envelope(500, "internal", "Something went wrong.")
    response.headers.update(SECURITY_HEADERS)
    return response


@app.exception_handler(ApiError)
async def _api_error(_r: Request, e: ApiError):
    return _envelope(e.status, e.code, e.message, e.retry_after_s)


@app.exception_handler(StarletteHTTPException)
async def _http_error(_r: Request, e: StarletteHTTPException):
    code = STATUS_CODE.get(e.status_code, "http_error")
    return _envelope(e.status_code, code, HTTPStatus(e.status_code).phrase)


@app.exception_handler(RequestValidationError)
async def _validation_error(_r: Request, _e: RequestValidationError):
    return _envelope(422, "bad_request", "Invalid request.")  # never echo input


@app.exception_handler(UndoError)
async def _undo_error(_r: Request, e: UndoError):
    return _envelope(UNDO_STATUS.get(e.code, 409), e.code, e.message)


@app.exception_handler(sqlite3.OperationalError)
async def _db_error(_r: Request, e: sqlite3.OperationalError):
    if "locked" not in str(e):
        raise e  # guard middleware logs it and returns the 500 envelope
    return _envelope(503, "busy", "Store is busy. Try again shortly.", 2)  # R1: retry replays


@app.get("/healthz")
def healthz() -> dict:
    return {"ok": True, "version": os.environ.get("RENDER_GIT_COMMIT", "dev")[:7]}


class SessionRequest(BaseModel):
    reset: bool = False


@api.post("/session", dependencies=[Depends(rate_limit("session", SESSION_LIMIT))])
def post_session(request: Request, response: Response, body: SessionRequest | None = None):
    s = get_settings()
    sid = _valid_sid(request)
    with _store_lock:  # sweep + create serialized so MAX_SESSIONS holds
        store_reset = sid is not None and not store_exists(sid)  # R48: valid cookie, file gone
        created = sid is None or body is not None and body.reset or store_reset
        if created:
            sid = sid or secrets.token_urlsafe(32)
            sweep_sessions()
            create_store(sid, datetime.now(UTC).date())
    if not created:
        touch_store(sid)
    with _open_ctx(sid) as ctx:
        if created:
            log_action(ctx, "session", {"summary": "Store created"})
        anchor = ctx.today.isoformat()
    response.set_cookie(
        COOKIE,
        sid,
        max_age=s.session_ttl_hours * 3600,
        httponly=True,
        samesite="lax",
        secure=s.app_env == "prod",
        path="/",
    )
    return {"created": created, "store_reset": store_reset, "anchor": anchor, **_modes()}


_ORDER_COLS = (
    "id, customer_id, created_at, status, total_cents, refunded_cents, currency,"
    " ship_country, carrier, tracking_number, shipped_at"
)  # no note (R24)


def store_snapshot(ctx: Ctx) -> dict:
    db = ctx.db
    q = f"SELECT {_ORDER_COLS} FROM orders ORDER BY created_at DESC, id DESC LIMIT 100"  # noqa: S608
    orders = [dict(r) for r in db.execute(q)]
    by_id = {o["id"]: {**o, "items": []} for o in orders}
    marks = ",".join("?" * len(by_id))
    q = f"SELECT order_id, product_id, qty, unit_price_cents FROM order_items WHERE order_id IN ({marks})"  # noqa: S608, E501
    for it in db.execute(q, list(by_id)):
        by_id[it["order_id"]]["items"].append(dict(it))
    return {
        "products": [dict(r) for r in db.execute("SELECT * FROM products ORDER BY id")],
        "orders": list(by_id.values()),
        "orders_total": db.execute("SELECT count(*) FROM orders").fetchone()[0],
        "customers": [
            dict(r)
            for r in db.execute(
                "SELECT id, name, email, country, created_at FROM customers ORDER BY id"
            )
        ],
    }


@api.get("/store")
def get_store(request: Request, ctx: SessionCtx):
    return {
        "anchor": ctx.today.isoformat(),
        "store_reset": request.state.store_reset,
        **_modes(),
        **store_snapshot(ctx),
    }


@api.get("/audit")
def get_audit(ctx: SessionCtx):
    return {"chain_ok": verify_chain(ctx), "actions": list_actions(ctx)}


@api.post("/undo/{audit_id}")
def post_undo(audit_id: Annotated[str, PathParam(pattern=r"^aud_[0-9a-f]{12}$")], ctx: SessionCtx):
    return undo_action(ctx, audit_id).model_dump(exclude={"undo_token"})


# ---------- W2 routes ----------
@api.get("/inbox")
def get_inbox(ctx: SessionCtx):
    return screen_inbox(ctx)


class PlanRequest(BaseModel):
    request: Annotated[str, StringConstraints(min_length=1, max_length=2000)]
    replay: bool = False


def plan_limits(request: Request, sid: str = Depends(current_session)) -> None:
    sh = session_hash(sid)
    _hit(("plan_ip", client_ip(request)), PLAN_IP_LIMIT)
    _hit(("plan", sh), PLAN_SESSION_LIMIT)
    _hit(("plan_hour", sh), get_settings().llm_max_plans_per_session_hour, 3600.0)


@api.post("/plan", dependencies=[Depends(plan_limits)])
def post_plan(body: PlanRequest, ctx: SessionCtx):
    try:  # R32: route orchestrates; make_plan does not save
        plan = make_plan(body.request, ctx, force_replay=body.replay)
    except LLMError as e:
        if getattr(e, "kind", None) == "replay_miss":
            raise ApiError(404, "replay_miss", "No recorded plan for this request.") from e
        raise
    validations = validate_plan(plan, ctx)
    diff = dry_run(plan, ctx)
    plan_id = save_plan(ctx, plan, validations, diff)
    clarify = (
        {"question": plan.message, "options": []} if plan.status == "needs_clarification" else None
    )  # R44
    return {
        "plan_id": plan_id,
        "source": plan.source,
        "plan": plan.model_dump(),
        "validations": [v.model_dump() for v in validations],
        "diff": [d.model_dump() for d in diff],
        "tools": {
            t.name: {
                "destructive": t.destructive,
                "moves_money": t.moves_money,
                "undoable": t.undoable,
            }
            for t in get_tools()
        },
        "clarify": clarify,
        "usage": plan.usage,
    }


class ExecuteRequest(BaseModel):
    plan_id: Annotated[str, StringConstraints(pattern=r"^plan_[0-9a-f]{12}$")]
    approved_step_ids: list[Annotated[str, StringConstraints(max_length=32)]] = Field(max_length=20)


@api.post("/execute")
def post_execute(body: ExecuteRequest, ctx: SessionCtx):
    try:  # R1: per-step execute on a stored plan
        plan = claim_plan(ctx, body.plan_id)
        results = execute(plan, set(body.approved_step_ids), ctx)
    except PlanError as e:
        status, code = PLAN_ERROR.get(e.code, (422, "plan_invalid"))
        raise ApiError(status, code) from e
    return {
        "plan_id": body.plan_id,
        "results": [r.model_dump(exclude={"undo_token"}) for r in results],
    }


@api.get("/outbox")
def get_outbox(ctx: SessionCtx):
    return list_outbox(ctx)


@api.get("/export/{kind}")
def get_export(kind: str, ctx: SessionCtx):
    if kind not in EXPORT_KINDS:
        raise ApiError(404, "not_found", "Unknown export.")
    body, media_type, filename = render(kind, ctx)
    return Response(
        body,
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@api.api_route("/{_rest:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE"])
def api_not_found(_rest: str):
    raise ApiError(404, "not_found", "Unknown API route.")  # never fall through to static HTML


web.install(app)  # R10: added after guard, so it runs outermost
app.include_router(api)
# mounted last so API routes win
app.mount("/", StaticFiles(directory=Path(__file__).parent / "static", html=True), name="static")
