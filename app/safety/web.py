"""Web hardening (P4-T3, spec 04 §7): CSRF header, body limit, global plan cap, extra headers.

main.py calls install(app) once after its own middleware (INT-1, R10), so this runs outermost.
"""

import threading
from datetime import UTC, datetime, timedelta
from urllib.parse import urlsplit

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.config import get_settings

MAX_BODY_BYTES = 16_384
# Spec 10: Stripe webhooks. Exact paths only (no prefix, no trailing slash): Stripe sends no CSRF
# header or cookie, so these routes verify the Stripe-Signature header instead.
WEBHOOK_PATHS = frozenset({"/api/connect/webhooks/thin", "/api/connect/webhooks/billing"})
WEBHOOK_MAX_BODY_BYTES = 65_536  # snapshot events can pass 16 KiB; Stripe retries a 413, then quits
PLAN_DAILY_CAP = 300  # R7: count backstop; $ budgets (P2-T2) bind first
CSRF_HEADER = "X-ShopPilot"
UNSAFE_METHODS = {"POST", "PUT", "PATCH", "DELETE"}
CSP_EXTRA = "object-src 'none'; base-uri 'none'; form-action 'self'"
PERMISSIONS_POLICY = "camera=(), microphone=(), geolocation=()"
HSTS = "max-age=31536000"
# Pre-LLM rejections give the slot back; 500s and raised errors keep it (a paid turn may have
# run, #61). 404 = replay_miss, 503 = budget/busy.
RELEASE_STATUSES = frozenset({401, 404, 422, 429, 503})

# ponytail: in-process counter, resets on restart (R48); Console spend limit is the hard backstop.
_plans: tuple[str, int] = ("", 0)
_plans_lock = threading.Lock()


def _reset_for_tests() -> None:
    global _plans
    with _plans_lock:
        _plans = ("", 0)


def _today() -> str:
    return datetime.now(UTC).date().isoformat()


def _seconds_to_utc_midnight() -> int:
    now = datetime.now(UTC)
    midnight = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
    return max(1, int((midnight - now).total_seconds()))


def _take_plan_slot() -> str | None:
    """Return the day the slot was counted against, or None when the cap is reached."""
    global _plans
    day = _today()
    with _plans_lock:
        count = _plans[1] if _plans[0] == day else 0
        if count >= PLAN_DAILY_CAP:
            return None
        _plans = (day, count + 1)
        return day


def _release_plan_slot(day: str) -> None:
    """Give back a slot the route rejected before any LLM call (RELEASE_STATUSES)."""
    global _plans
    with _plans_lock:
        if _plans[0] == day and _plans[1] > 0:
            _plans = (day, _plans[1] - 1)


def _error(status: int, code: str, message: str, retry_after_s: int | None = None) -> JSONResponse:
    err: dict = {"code": code, "message": message}
    if retry_after_s is not None:
        err["retry_after_s"] = retry_after_s
    return JSONResponse({"error": err}, status_code=status)


async def _body_too_large(request: Request) -> bool:
    """Content-Length check; chunked bodies are read with a cap and cached for the route."""
    cap = WEBHOOK_MAX_BODY_BYTES if request.url.path in WEBHOOK_PATHS else MAX_BODY_BYTES
    length = request.headers.get("content-length")
    if length is not None:
        return not length.isdigit() or int(length) > cap
    if request.method not in UNSAFE_METHODS:
        return False
    chunks, size = [], 0
    async for chunk in request.stream():
        size += len(chunk)
        if size > cap:
            return True
        chunks.append(chunk)
    request._body = b"".join(chunks)  # BaseHTTPMiddleware replays a cached _body downstream
    return False


def _csrf_error(request: Request) -> JSONResponse | None:
    if request.method not in UNSAFE_METHODS or not request.url.path.startswith("/api/"):
        return None
    if request.url.path in WEBHOOK_PATHS:  # spec 10: the route checks Stripe-Signature instead
        return None
    if request.headers.get(CSRF_HEADER) != "1":
        return _error(403, "csrf", "Missing request header.")
    origin = request.headers.get("origin")
    # Host only, not scheme: uvicorn runs without --proxy-headers (R45), so the app sees http
    # while the browser sends https. The custom header already forces a CORS preflight.
    if origin is not None and urlsplit(origin).netloc != request.headers.get("host"):
        return _error(403, "csrf", "Cross-origin request blocked.")
    hdrs = request.headers
    has_body = hdrs.get("content-length", "0") != "0" or "transfer-encoding" in hdrs
    ctype = request.headers.get("content-type", "").split(";", 1)[0].strip().lower()
    if has_body and ctype != "application/json":
        return _error(415, "bad_content_type", "Send JSON.")
    return None


def _add_headers(request: Request, response) -> None:
    h = response.headers
    csp = h.get("content-security-policy")
    if csp is None:
        from app.main import SECURITY_HEADERS  # lazy: main imports this module (INT-1)

        for k, v in SECURITY_HEADERS.items():
            h.setdefault(k, v)
        csp = h["content-security-policy"]
    if "object-src" not in csp:
        h["Content-Security-Policy"] = f"{csp}; {CSP_EXTRA}"
    h["Permissions-Policy"] = PERMISSIONS_POLICY
    if request.url.path.startswith("/api/"):
        h["Cache-Control"] = "no-store"
    if get_settings().app_env == "prod":
        h["Strict-Transport-Security"] = HSTS


async def _guard(request: Request, call_next):
    if await _body_too_large(request):
        response = _error(413, "too_large", "Request body too large.")
    else:
        response = _csrf_error(request)
    slot_day = None
    if response is None and request.method == "POST" and request.url.path == "/api/plan":
        slot_day = _take_plan_slot()
        if slot_day is None:
            response = _error(
                503,
                "demo_budget_reached",
                "Daily demo budget reached. Try again tomorrow.",
                _seconds_to_utc_midnight(),
            )
    if response is None:
        response = await call_next(request)
        if slot_day is not None and response.status_code in RELEASE_STATUSES:
            _release_plan_slot(slot_day)
    _add_headers(request, response)
    return response


def install(app: FastAPI) -> None:
    """Add the hardening middleware. Call once, after main.py's own middleware."""
    app.middleware("http")(_guard)
