"""P4-T3: CSRF header, body limit, global plan cap, extra headers (app/safety/web.py)."""

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from app.config import load_settings
from app.safety import web

H = {"X-ShopPilot": "1"}
J = {**H, "content-type": "application/json"}


@pytest.fixture
def c():
    web._reset_for_tests()
    app = FastAPI()

    @app.post("/api/plan")
    async def plan(_r: Request):
        return {"ok": True}

    @app.post("/api/echo")
    async def echo(r: Request):
        return {"n": len(await r.body())}

    @app.get("/api/x")
    async def x():
        return {"ok": True}

    web.install(app)
    yield TestClient(app)
    web._reset_for_tests()


def test_csrf_header_required(c):
    r = c.post("/api/echo", json={})
    assert r.status_code == 403 and r.json()["error"]["code"] == "csrf"
    assert c.post("/api/echo", json={}, headers=H).status_code == 200


def test_csrf_bad_origin(c):
    r = c.post("/api/echo", json={}, headers={**H, "Origin": "https://evil.example"})
    assert r.status_code == 403 and r.json()["error"]["code"] == "csrf"


def test_csrf_same_origin_ok(c):
    r = c.post("/api/echo", json={}, headers={**H, "Origin": "http://testserver"})
    assert r.status_code == 200


def test_csrf_same_host_behind_tls_proxy_ok(c):
    # R45: no --proxy-headers, so request scheme is http while the browser Origin is https.
    r = c.post("/api/echo", json={}, headers={**H, "Origin": "https://testserver"})
    assert r.status_code == 200


def test_form_content_type_415(c):
    r = c.post("/api/echo", data={"a": "b"}, headers=H)
    assert r.status_code == 415 and r.json()["error"]["code"] == "bad_content_type"


def test_json_with_charset_ok(c):
    hdr = {**H, "content-type": "application/json; charset=utf-8"}
    assert c.post("/api/echo", content=b"{}", headers=hdr).status_code == 200


def test_get_needs_no_header(c):
    assert c.get("/api/x").status_code == 200


def test_body_too_large_413(c):
    r = c.post("/api/echo", content=b"{" + b" " * 16_400 + b"}", headers=J)
    assert r.status_code == 413 and r.json()["error"]["code"] == "too_large"


def test_streamed_body_too_large_413(c):
    def gen():
        for _ in range(20):
            yield b" " * 1_000

    r = c.post("/api/echo", content=gen(), headers={**H, "content-type": "application/json"})
    assert r.status_code == 413 and r.json()["error"]["code"] == "too_large"


def test_streamed_body_small_reaches_route(c):
    def gen():
        yield b"{"
        yield b"}"

    r = c.post("/api/echo", content=gen(), headers={**H, "content-type": "application/json"})
    assert r.status_code == 200 and r.json() == {"n": 2}


def test_global_plan_cap(c, monkeypatch):
    monkeypatch.setattr(web, "PLAN_DAILY_CAP", 2)
    codes = [c.post("/api/plan", json={"request": "x"}, headers=H).status_code for _ in range(3)]
    assert codes == [200, 200, 503]
    err = c.post("/api/plan", json={"request": "x"}, headers=H).json()["error"]
    assert err["code"] == "demo_budget_reached" and err["retry_after_s"] > 0


def test_plan_cap_resets_next_utc_day(c, monkeypatch):
    monkeypatch.setattr(web, "PLAN_DAILY_CAP", 1)
    assert c.post("/api/plan", json={}, headers=H).status_code == 200
    assert c.post("/api/plan", json={}, headers=H).status_code == 503
    monkeypatch.setattr(web, "_today", lambda: "2099-01-01")
    assert c.post("/api/plan", json={}, headers=H).status_code == 200


def test_csrf_rejects_do_not_burn_plan_budget(c, monkeypatch):
    monkeypatch.setattr(web, "PLAN_DAILY_CAP", 1)
    assert c.post("/api/plan", json={}).status_code == 403
    assert c.post("/api/plan", json={}, headers=H).status_code == 200


def _plan_app(status: int) -> TestClient:
    app = FastAPI()

    @app.post("/api/plan")
    async def plan():
        from fastapi.responses import JSONResponse

        return JSONResponse({"error": {"code": "x", "message": "x"}}, status_code=status)

    web.install(app)
    return TestClient(app)


@pytest.mark.parametrize("status", [401, 404, 422, 429, 503])
def test_rejected_plans_do_not_burn_budget(c, monkeypatch, status):
    monkeypatch.setattr(web, "PLAN_DAILY_CAP", 1)
    bad = _plan_app(status)
    assert [bad.post("/api/plan", json={}, headers=H).status_code for _ in range(3)] == [status] * 3
    assert web._plans[1] == 0
    assert c.post("/api/plan", json={}, headers=H).status_code == 200
    assert web._plans[1] == 1
    assert c.post("/api/plan", json={}, headers=H).status_code == 503


def test_post_llm_failure_keeps_slot(monkeypatch):  # #61: a crash after a paid turn counts
    monkeypatch.setattr(web, "PLAN_DAILY_CAP", 1)
    assert _plan_app(500).post("/api/plan", json={}, headers=H).status_code == 500
    assert web._plans[1] == 1
    assert _plan_app(500).post("/api/plan", json={}, headers=H).status_code == 503


def test_route_exception_keeps_slot(c, monkeypatch):
    monkeypatch.setattr(web, "PLAN_DAILY_CAP", 1)
    app = FastAPI()

    @app.post("/api/plan")
    async def plan():
        raise RuntimeError("boom")

    web.install(app)
    with pytest.raises(RuntimeError):
        TestClient(app).post("/api/plan", json={}, headers=H)
    assert web._plans[1] == 1


def test_release_after_day_rollover_is_noop(monkeypatch):
    web._reset_for_tests()
    day = web._take_plan_slot()
    monkeypatch.setattr(web, "_today", lambda: "2099-01-01")
    assert web._take_plan_slot() == "2099-01-01"
    web._release_plan_slot(day)
    assert web._plans == ("2099-01-01", 1)
    web._reset_for_tests()


def test_nat_classroom_not_blocked(c):  # Review Focus 5
    assert all(
        c.post(
            "/api/plan", json={"request": "x"}, headers=H, cookies={"sp_session": f"{i:043d}"}
        ).status_code
        == 200
        for i in range(30)
    )


def test_headers(c):
    h = c.get("/api/x").headers
    csp = h["content-security-policy"]
    assert "object-src 'none'" in csp and "base-uri 'none'" in csp and "form-action 'self'" in csp
    assert "default-src 'self'" in csp
    assert h["cache-control"] == "no-store" and "camera=()" in h["permissions-policy"]


def test_headers_on_error_responses(c):
    h = c.post("/api/echo", json={}).headers
    assert "object-src 'none'" in h["content-security-policy"] and h["cache-control"] == "no-store"


def test_existing_csp_is_appended_once(c):
    app = FastAPI()

    @app.get("/api/x")
    async def x():
        from fastapi.responses import JSONResponse

        return JSONResponse({}, headers={"Content-Security-Policy": "default-src 'none'"})

    web.install(app)
    csp = TestClient(app).get("/api/x").headers["content-security-policy"]
    assert csp.startswith("default-src 'none'; ") and csp.count("object-src") == 1


@pytest.mark.parametrize("env,present", [("prod", True), ("dev", False)])
def test_hsts_only_in_prod(c, monkeypatch, env, present):
    vals = {"APP_ENV": env, "GOOGLE_CLOUD_PROJECT": "p", "GOOGLE_API_KEY": "x" * 10}
    monkeypatch.setattr(web, "get_settings", lambda: load_settings(vals))
    h = c.get("/api/x").headers
    assert ("strict-transport-security" in h) is present
