import json
import os
import socket
import sqlite3
from datetime import UTC, date, datetime
from secrets import token_urlsafe

import pytest
from fastapi.testclient import TestClient

HEADERS = {"X-ShopPilot": "1"}


def pytest_collection_modifyitems(config, items):
    if os.environ.get("RUN_LIVE") == "1":
        return
    skip = pytest.mark.skip(reason="live test: set RUN_LIVE=1")
    for item in items:
        if "live" in item.keywords:
            item.add_marker(skip)


@pytest.fixture(autouse=True)
def no_network(request, monkeypatch):
    if request.node.get_closest_marker("live"):
        return

    def _blocked(*_a, **_k):
        raise RuntimeError("network disabled in tests")

    for name in ("connect", "connect_ex"):
        monkeypatch.setattr(socket.socket, name, _blocked)
    monkeypatch.setattr(socket, "create_connection", _blocked)


@pytest.fixture(autouse=True)
def tmp_data_dir(tmp_path, monkeypatch):
    monkeypatch.setenv("DATA_DIR", str(tmp_path))
    monkeypatch.setenv("APP_ENV", "test")
    try:
        from app.config import get_settings

        get_settings.cache_clear()
    except ImportError:
        pass
    # in-process limiters/counters are module globals; reset so test order never matters
    import app.main as main
    from app.connect import stripe_calls
    from app.connect.config import connect_settings
    from app.llm import budget
    from app.safety import web

    main._reset_rate_limits()
    web._reset_for_tests()
    connect_settings.cache_clear()  # spec 10: Connect reads env lazily and caches it
    stripe_calls.client.cache_clear()
    with budget._lock:
        budget._calls.clear()
    return tmp_path


@pytest.fixture
def anchor():
    return date(2026, 10, 15)


@pytest.fixture
def fixed_now():
    return datetime(2026, 10, 15, 9, 0, tzinfo=UTC)


@pytest.fixture
def mem_conn():
    from app.db import init_schema

    conn = sqlite3.connect(":memory:")
    init_schema(conn)
    yield conn
    conn.close()


@pytest.fixture
def seeded(mem_conn, anchor):
    from app.seed.generate import seed_store

    seed_store(mem_conn, anchor)
    return mem_conn


@pytest.fixture
def tmp_store(anchor):
    from app.db import create_store

    sid = token_urlsafe(32)
    create_store(sid, anchor)
    return sid


@pytest.fixture
def ctx(tmp_store, fixed_now, anchor):
    from app.db import get_db
    from app.tools.registry import Ctx

    with get_db(tmp_store) as db:
        yield Ctx(tmp_store, db, fixed_now, anchor)


@pytest.fixture
def client():
    from app.main import app

    with TestClient(app, headers=HEADERS) as c:
        yield c


@pytest.fixture
def session_client(client):
    assert client.post("/api/session", json={}).status_code in (200, 201)
    return client


@pytest.fixture
def two_session_clients():
    from contextlib import ExitStack

    from app.main import app

    with ExitStack() as stack:
        out = []
        for _ in range(2):
            c = stack.enter_context(TestClient(app, headers=HEADERS))
            assert c.post("/api/session", json={}).status_code in (200, 201)
            out.append(c)
        yield tuple(out)


class Script:
    """Fake LLM `_send`: pops queued results (dict -> response, Exception -> raised)."""

    def __init__(self, *results):
        self.results, self.sent = list(results), []

    def push(self, *rs):
        self.results.extend(rs)

    def __call__(self, kwargs):
        self.sent.append(json.loads(json.dumps(kwargs, default=str)))
        r = self.results.pop(0)
        if isinstance(r, Exception):
            raise r
        return r

    @property
    def models(self):
        return [k["model"] for k in self.sent]

    @staticmethod
    def text(obj, model="claude-haiku-5-5"):
        usage = {
            "input_tokens": 1,
            "cache_creation_input_tokens": 0,
            "cache_read_input_tokens": 0,
            "output_tokens": 1,
        }
        return {
            "content": [{"type": "text", "text": json.dumps(obj)}],
            "stop_reason": "end_turn",
            "model": model,
            "usage": usage,
        }


@pytest.fixture
def llm_script(monkeypatch):
    """LLM_MODE=live with a scripted fake SDK; no network, no key."""
    import app.llm.client as llm_client
    from app.config import get_settings

    monkeypatch.setenv("LLM_MODE", "live")
    get_settings.cache_clear()
    s = Script()
    monkeypatch.setattr(llm_client, "_send", s)
    return s
