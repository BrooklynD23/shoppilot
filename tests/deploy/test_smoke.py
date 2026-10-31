"""scripts/smoke.sh against a local stdlib server (no network, no docker)."""

import os
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "smoke.sh"
WF = Path(__file__).resolve().parents[2] / ".github" / "workflows" / "deploy.yml"


class H(BaseHTTPRequestHandler):
    bug = ""  # "", "garbage_ok", "no_products", "no_csrf"

    def _send(self, code, body, cookie=None):
        self.send_response(code)
        if cookie:
            self.send_header("Set-Cookie", cookie)
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        if self.path != "/api/session" or (
            self.headers.get("X-ShopPilot") != "1" and self.bug != "no_csrf"
        ):
            self._send(403, b'{"error":{"code":"csrf"}}')
            return
        self._send(
            200, b'{"created":true,"store_reset":false}', "sp_session=good; Path=/; HttpOnly"
        )

    def do_GET(self):
        if self.path == "/api/store":
            cookie = self.headers.get("Cookie", "")
            if "sp_session=good" in cookie or self.bug == "garbage_ok":
                body = b'{"products":[]}' if self.bug != "no_products" else b'{"orders":[]}'
                self._send(200, body)
            else:
                self._send(401, b'{"error":{"code":"no_session"}}')
            return
        if self.path == "/healthz":
            body = b'{"ok":true,"version":"abc1234"}'
        elif self.path == "/":
            body = b"<html>ShopPilot</html>"
        else:
            self.send_error(404)
            return
        self.send_response(200)
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *a):
        pass


@pytest.fixture
def base():
    H.bug = ""
    srv = HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_port}"
    srv.shutdown()


def run(*args, env=None):
    return subprocess.run(  # noqa: S603
        ["bash", str(SCRIPT), *args],  # noqa: S607
        capture_output=True,
        text=True,
        timeout=60,
        env={**os.environ, **(env or {})},
    )


def full(base, tmp_path, bug=""):
    H.bug = bug
    jar = tmp_path / "sp.jar"
    return run(base, "", "3", env={"SMOKE_FULL": "1", "SMOKE_JAR": str(jar)}), jar


def test_pass_with_sha(base):
    assert run(base, "abc1234def", "20").returncode == 0


def test_pass_without_sha(base):
    assert run(base).returncode == 0


def test_wrong_sha_fails_with_body(base):
    r = run(base, "0000000", "3")
    assert r.returncode == 1
    assert "abc1234" in r.stdout + r.stderr


def test_unreachable_fails():
    assert run("http://127.0.0.1:1", "", "3").returncode == 1


def test_workflow_shape():
    t = WF.read_text()
    for want in (
        "name: Deploy",
        "workflow_run",
        'workflows: ["CI"]',
        "workflow_dispatch",
        "group: deploy",
        "cancel-in-progress: false",
        "RENDER_DEPLOY_HOOK_URL",
        "scripts/smoke.sh",
    ):
        assert want in t, want
    assert 'echo "$HOOK' not in t and "echo $HOOK" not in t
    assert 'run: bash scripts/smoke.sh "$APP_URL" "$SHA" 600' in t  # no exec bit needed
    assert "permissions:\n  contents: read" in t
    assert "persist-credentials: false" in t
    # dispatch ref resolved to a full 40-hex SHA before the hook fires
    assert "git rev-parse --verify" in t
    assert t.index("rev-parse") < t.index("RENDER_DEPLOY_HOOK_URL")


def test_full_pass_writes_jar(base, tmp_path):
    r, jar = full(base, tmp_path)
    assert r.returncode == 0, r.stdout + r.stderr
    assert "sp_session" in jar.read_text()  # restart check reuses this jar (D3 Step 2)


@pytest.mark.parametrize("bug", ["garbage_ok", "no_products"])
def test_full_fails_on_bug(base, tmp_path, bug):
    r, _ = full(base, tmp_path, bug)
    assert r.returncode == 1
    assert "FAILED" in r.stderr


def test_full_sends_csrf_header(base, tmp_path):
    r, _ = full(base, tmp_path)  # fake 403s a POST without X-ShopPilot: 1
    assert r.returncode == 0, r.stdout + r.stderr


def test_full_off_by_default(base, tmp_path):
    H.bug = "garbage_ok"
    assert run(base, "", "3").returncode == 0
