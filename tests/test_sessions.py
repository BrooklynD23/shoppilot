from unittest.mock import ANY

import pytest

from app.config import get_settings
from app.db import get_db, store_path


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
