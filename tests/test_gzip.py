"""GZip: static and JSON compressed; CSP/security headers and streaming intact."""

from pathlib import Path

import pytest
from starlette.responses import StreamingResponse
from starlette.routing import Route

import app.main as main

STATIC = Path(main.__file__).parent / "static"
GZ = {"Accept-Encoding": "gzip"}
CHUNKS = [f"chunk {i} ".encode() * 200 for i in range(3)]


def _secure(h):
    csp = h["content-security-policy"]
    assert "default-src 'self'" in csp and "object-src 'none'" in csp  # main + web.py
    assert h["x-content-type-options"] == "nosniff" and "camera=()" in h["permissions-policy"]


def _largest(ext: str) -> str:
    files = sorted(STATIC.rglob(f"*{ext}"), key=lambda p: p.stat().st_size)
    if not files or files[-1].stat().st_size < 1000:
        pytest.skip(f"no static {ext} over 1000 bytes")
    return "/" + files[-1].relative_to(STATIC).as_posix()


@pytest.mark.parametrize("ext", [".html", ".css", ".js"])
def test_static_gzipped_with_security_headers(client, ext):
    r = client.get(_largest(ext), headers=GZ)
    assert r.status_code == 200 and r.headers["content-encoding"] == "gzip"
    assert "accept-encoding" in r.headers["vary"].lower()
    _secure(r.headers)


def test_json_gzipped_with_api_headers(session_client):
    r = session_client.get("/api/store", headers=GZ)
    assert r.headers["content-encoding"] == "gzip" and r.json()["products"]
    assert int(r.headers["content-length"]) < len(r.content) / 2  # not chunked; real savings
    assert r.headers["cache-control"] == "no-store"
    _secure(r.headers)


def test_small_or_identity_not_gzipped(client):
    assert "content-encoding" not in client.get("/healthz", headers=GZ).headers  # < 1000 bytes
    r = client.get("/", headers={"Accept-Encoding": "identity"})
    assert "content-encoding" not in r.headers and "ShopPilot" in r.text


@pytest.fixture
def stream_route():
    async def chunks():
        for c in CHUNKS:
            yield c

    async def endpoint(request):
        return StreamingResponse(chunks(), media_type=request.query_params["type"])

    route = Route("/__stream", endpoint)
    main.app.router.routes.insert(0, route)
    yield
    main.app.router.routes.remove(route)


@pytest.mark.parametrize(
    ("ctype", "encoding"), [("text/plain", "gzip"), ("text/event-stream", None)]
)
def test_streaming_intact(client, stream_route, ctype, encoding):
    with client.stream("GET", f"/__stream?type={ctype}", headers=GZ) as r:
        body = b"".join(r.iter_bytes())
    assert body == b"".join(CHUNKS) and "content-length" not in r.headers  # still chunked
    assert r.headers.get("content-encoding") == encoding  # SSE never buffered by gzip
    _secure(r.headers)
