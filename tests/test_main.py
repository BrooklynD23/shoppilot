import socket
import sqlite3

import pytest


def test_healthz(client):
    r = client.get("/healthz")
    assert r.status_code == 200
    assert r.json()["ok"] is True
    assert r.json()["version"] == "dev"


def test_healthz_version_truncated(client, monkeypatch):
    monkeypatch.setenv("RENDER_GIT_COMMIT", "abcdef1234567")
    assert client.get("/healthz").json()["version"] == "abcdef1"


def test_index_served(client):
    r = client.get("/")
    assert r.status_code == 200 and "ShopPilot" in r.text


def test_network_blocked():
    with pytest.raises(RuntimeError, match="network disabled"):
        socket.create_connection(("example.com", 80))


def test_connect_ex_blocked():
    with pytest.raises(RuntimeError, match="network disabled"):
        socket.socket().connect_ex(("example.com", 80))


def test_security_headers(client):
    h = client.get("/healthz").headers
    assert "default-src 'self'" in h["content-security-policy"]
    assert "frame-ancestors 'none'" in h["content-security-policy"]
    assert h["x-content-type-options"] == "nosniff" and h["referrer-policy"] == "same-origin"
    assert "content-security-policy" in client.get("/").headers  # static too


def test_plan_route_live(session_client, llm_script):
    # INT-1: W2 landed, /api/plan is live (was 501 not_built)
    llm_script.push(llm_script.text({"reason": "r", "route": "reject", "reply": "Shop only."}))
    r = session_client.post("/api/plan", json={"request": "what's the weather?"})
    assert r.status_code == 200 and r.json()["plan"]["status"] == "refused"
    assert r.json()["plan_id"].startswith("plan_")


@pytest.mark.parametrize("path", ["/api/inbox", "/api/outbox", "/api/export/orders_csv"])
def test_w2_get_routes_live(session_client, path):
    assert session_client.get(path).status_code == 200


def test_web_hardening_installed(client):
    # INT-1 / R10: safety.web.install(app) runs on the real app
    h = client.get("/healthz").headers
    assert "object-src 'none'" in h["content-security-policy"]
    assert "camera=()" in h["permissions-policy"]
    r = client.post("/api/session", json={}, headers={"X-ShopPilot": "0"})
    assert r.status_code == 403 and r.json()["error"]["code"] == "csrf"


def test_plan_body_validated(session_client):
    assert session_client.post("/api/plan", json={"request": ""}).status_code == 422
    r = session_client.post("/api/plan", json={"request": "x" * 2001})
    assert r.status_code == 422 and r.json()["error"]["code"] == "bad_request"
    assert "xxxx" not in r.text  # no input echo


def test_execute_plan_id_validated(session_client):
    r = session_client.post("/api/execute", json={"plan_id": "../x", "approved_step_ids": []})
    assert r.status_code == 422
    r = session_client.post(
        "/api/execute", json={"plan_id": "plan_000000000000", "approved_step_ids": ["s"] * 21}
    )
    assert r.status_code == 422


def test_unknown_export_404(session_client):
    r = session_client.get("/api/export/passwd")
    assert r.status_code == 404 and r.json()["error"]["code"] == "not_found"


def test_undo_unknown_404(session_client):
    r = session_client.post("/api/undo/aud_000000000000")
    assert r.status_code == 404 and r.json()["error"]["code"] == "not_found"


@pytest.mark.parametrize("bad", ["../../x", "..%2F..%2Fx", "aud_XYZ"])
def test_undo_bad_id_never_500(session_client, bad):
    r = session_client.post(f"/api/undo/{bad}")
    assert r.status_code in (404, 405, 422)
    assert "error" in r.json()


def test_audit_lists_session_row(session_client):
    j = session_client.get("/api/audit").json()
    assert j["chain_ok"] is True and j["actions"][0]["kind"] == "session"


def test_500_hides_details(session_client, monkeypatch):
    import app.main as main

    def boom(*_a, **_k):
        raise RuntimeError("secret-traceback-text")

    monkeypatch.setattr(main, "store_snapshot", boom)
    r = session_client.get("/api/store")
    assert r.status_code == 500
    assert r.json()["error"]["code"] == "internal"
    assert "secret-traceback-text" not in r.text and "Traceback" not in r.text


def _raise_store(monkeypatch, exc):
    import app.main as main

    def boom(*_a, **_k):
        raise exc

    monkeypatch.setattr(main, "store_snapshot", boom)


def test_db_locked_is_503_busy(session_client, monkeypatch):
    # #69: a writer holding BEGIN IMMEDIATE during a slow Stripe call -> retryable, not 500
    _raise_store(monkeypatch, sqlite3.OperationalError("database is locked"))
    r = session_client.get("/api/store")
    assert r.status_code == 503
    assert r.json()["error"]["code"] == "busy" and r.json()["error"]["retry_after_s"] == 2


def test_other_operational_error_is_500(session_client, monkeypatch):
    _raise_store(monkeypatch, sqlite3.OperationalError("no such table: secret_tbl"))
    r = session_client.get("/api/store")
    assert r.status_code == 500 and r.json()["error"]["code"] == "internal"
    assert "secret_tbl" not in r.text
