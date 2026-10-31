"""FE-INT: the built Astro site is served by the last-mounted StaticFiles; /api and /healthz win."""

import pytest
from starlette.routing import Mount
from starlette.staticfiles import StaticFiles

PAGES = ["index.html", "how-it-works/index.html", "report/index.html", "app/index.html", "404.html"]


@pytest.fixture
def site_client(client, tmp_path, monkeypatch):
    from app.main import app

    site = tmp_path / "site"
    for page in PAGES:
        f = site / page
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(f"<!doctype html><html><body>{page}</body></html>")
    mount = next(r for r in app.routes if isinstance(r, Mount) and r.name == "static")
    assert mount is app.routes[-1]  # mounted last so API routes win
    monkeypatch.setattr(mount, "app", StaticFiles(directory=site, html=True))
    return client


@pytest.mark.parametrize("path", ["/", "/app/", "/how-it-works/", "/report/"])
def test_pages_served_with_csp(site_client, path):
    r = site_client.get(path)
    assert r.status_code == 200 and r.headers["content-type"].startswith("text/html")
    assert "default-src 'self'" in r.headers["content-security-policy"]


def test_healthz_still_json(site_client):
    r = site_client.get("/healthz")
    assert r.status_code == 200 and r.json()["ok"] is True


@pytest.mark.parametrize("method", ["get", "post"])
def test_unknown_api_is_json_404(site_client, method):
    r = getattr(site_client, method)("/api/nope")
    assert r.status_code == 404 and r.headers["content-type"].startswith("application/json")
    assert r.json()["error"]["code"] == "not_found"


def test_missing_static_path_404(site_client):
    assert site_client.get("/no/such/page/").status_code == 404
