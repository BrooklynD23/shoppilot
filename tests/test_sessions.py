import time
from concurrent.futures import ThreadPoolExecutor
from unittest.mock import ANY

import pytest
from fastapi.testclient import TestClient

from app.config import get_settings
from app.db import get_db, store_path
from tests.conftest import HEADERS


def test_session_cookie_flags(client):
    r = client.post("/api/session", json={})
    c = r.headers["set-cookie"]
    assert "sp_session=" in c and "httponly" in c.lower() and "samesite=lax" in c.lower()
    assert "max-age=86400" in c.lower()
    j = r.json()
    assert j["created"] is True
    assert j["store_name"] == "Fern & Kiln" and j["anchor"]
    assert j["llm_mode"] in ("live", "replay", "record") and j["stripe_mode"] in ("test", "mock")
    assert client.cookies["sp_session"] not in r.text  # R21: id only in Set-Cookie


def test_existing_session_not_recreated(session_client):
    sid = session_client.cookies["sp_session"]
    r = session_client.post("/api/session", json={})
    assert r.json()["created"] is False and session_client.cookies["sp_session"] == sid


def test_no_cookie_401(client):
    r = client.get("/api/store")
    assert r.status_code == 401
    assert r.json() == {"error": {"code": "no_session", "message": ANY}}


@pytest.mark.parametrize("bad", ["../../etc/passwd", "a" * 2000, ""])
def test_tampered_cookie_401(client, bad, tmp_data_dir):
    client.cookies.set("sp_session", bad)
    assert client.get("/api/store").status_code == 401
    assert list(tmp_data_dir.iterdir()) == []


def test_store_snapshot(session_client):
    j = session_client.get("/api/store").json()
    assert len(j["products"]) == 20 and len(j["orders"]) == 100
    assert j["orders_total"] > 2000 and j["store_reset"] is False
    assert len(j["customers"]) > 100 and j["store_name"] == "Fern & Kiln"
    o = j["orders"][0]
    assert o["items"] and "note" not in o
    dates = [x["created_at"] for x in j["orders"]]
    assert dates == sorted(dates, reverse=True)


def test_isolation(two_session_clients):
    a, b = two_session_clients
    sid_a = a.cookies["sp_session"]
    with get_db(sid_a) as db:
        db.execute("update products set stock=0")
    assert all(p["stock"] == 0 for p in a.get("/api/store").json()["products"])
    assert any(p["stock"] > 0 for p in b.get("/api/store").json()["products"])


def test_missing_file_reseeds(session_client):
    store_path(session_client.cookies["sp_session"], get_settings()).unlink()
    assert session_client.get("/api/store").json()["store_reset"] is True
    assert session_client.get("/api/store").json()["store_reset"] is False


def test_reset_reseeds(session_client):
    sid = session_client.cookies["sp_session"]
    with get_db(sid) as db:
        db.execute("update products set stock=0")
    r = session_client.post("/api/session", json={"reset": True})
    assert r.json()["created"] is True and session_client.cookies["sp_session"] == sid
    assert any(p["stock"] > 0 for p in session_client.get("/api/store").json()["products"])


def test_session_rate_limit(client):
    for _ in range(10):
        client.cookies.clear()
        assert client.post("/api/session", json={}).status_code == 200
    r = client.post("/api/session", json={})
    assert r.status_code == 429
    assert r.json()["error"]["code"] == "rate_limited" and r.json()["error"]["retry_after_s"] >= 1


def test_forged_xff_does_not_change_key(client):
    # R45: only the rightmost X-Forwarded-For entry (the proxy's) is the client ip
    for i in range(10):
        client.post("/api/session", json={}, headers={"X-Forwarded-For": f"6.6.6.{i}, 9.9.9.9"})
    r = client.post("/api/session", json={}, headers={"X-Forwarded-For": "7.7.7.7, 9.9.9.9"})
    assert r.status_code == 429
    r = client.post("/api/session", json={}, headers={"X-Forwarded-For": "9.9.9.9, 8.8.8.8"})
    assert r.status_code == 200


def test_session_cap(client, monkeypatch, tmp_data_dir):
    monkeypatch.setenv("MAX_SESSIONS", "3")
    get_settings.cache_clear()
    for _ in range(5):
        client.cookies.clear()
        assert client.post("/api/session", json={}).status_code == 200
    assert len(list(tmp_data_dir.glob("*.db"))) <= 3


def test_plan_limit_is_per_session(two_session_clients):
    a, b = two_session_clients
    for _ in range(10):
        assert a.post("/api/plan", json={"request": "ship"}).status_code != 429
    assert a.post("/api/plan", json={"request": "ship"}).status_code == 429
    assert b.post("/api/plan", json={"request": "ship"}).status_code != 429


def test_xff_multiple_header_lines_use_rightmost(client):
    # #46: two separate X-Forwarded-For lines; the proxy's (last) one is the key
    hdrs = [("x-forwarded-for", "6.6.6.6"), ("x-forwarded-for", "9.9.9.9")]
    for i in range(10):
        client.cookies.clear()
        h = [("x-forwarded-for", f"6.6.6.{i}"), ("x-forwarded-for", "9.9.9.9")]
        client.post("/api/session", json={}, headers=h)
    client.cookies.clear()
    assert client.post("/api/session", json={}, headers=hdrs).status_code == 429


def test_post_session_reports_store_reset(session_client):
    # #48: valid cookie, file gone -> UI must learn the store was reset
    store_path(session_client.cookies["sp_session"], get_settings()).unlink()
    j = session_client.post("/api/session", json={}).json()
    assert j["created"] is True and j["store_reset"] is True
    j = session_client.post("/api/session", json={}).json()
    assert j["created"] is False and j["store_reset"] is False


def test_new_visitor_store_reset_false(client):
    assert client.post("/api/session", json={}).json()["store_reset"] is False


def _slow_create(monkeypatch):
    import app.main as main

    calls = []
    real = main.create_store

    def slow(sid, anchor):
        calls.append(sid)
        time.sleep(0.05)  # widen the race window
        real(sid, anchor)

    monkeypatch.setattr(main, "create_store", slow)
    return calls


def _parallel(fn, n=6):
    with ThreadPoolExecutor(n) as pool:
        return [f.result() for f in [pool.submit(fn) for _ in range(n)]]


def test_concurrent_create_respects_cap(client, monkeypatch, tmp_data_dir):
    # #47: sweep+create is serialized, so the store count never passes MAX_SESSIONS
    monkeypatch.setenv("MAX_SESSIONS", "2")
    get_settings.cache_clear()
    _slow_create(monkeypatch)

    def visit():
        with TestClient(client.app, headers=HEADERS) as c:
            return c.post("/api/session", json={}).status_code

    assert _parallel(visit) == [200] * 6
    assert len(list(tmp_data_dir.glob("*.db"))) <= 2


def test_concurrent_same_cookie_reseeds_once(session_client, monkeypatch):
    # #78/#49: parallel GETs after a restart reseed once, cost one session hit, one store_reset
    import app.main as main

    sid = session_client.cookies["sp_session"]
    store_path(sid, get_settings()).unlink()
    main._reset_rate_limits()
    calls = _slow_create(monkeypatch)

    def get():
        with TestClient(session_client.app, headers=HEADERS, cookies={"sp_session": sid}) as c:
            r = c.get("/api/store")
            return r.status_code, r.json().get("store_reset")

    out = _parallel(get)
    assert all(code == 200 for code, _ in out)
    assert calls == [sid] and [reset for _, reset in out].count(True) == 1
    assert len(main._hits.get(("session", "testclient"), [])) == 1


def test_reseed_hits_session_limit(session_client):
    # the reseed still counts against the session bucket (disk flood guard)
    import app.main as main

    sid = session_client.cookies["sp_session"]
    for _ in range(9):  # session_client's POST already used 1 of 10
        main._hit(("session", "testclient"), main.SESSION_LIMIT)
    store_path(sid, get_settings()).unlink()
    assert session_client.get("/api/store").status_code == 429
