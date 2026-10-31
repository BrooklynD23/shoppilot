"""scripts/smoke.sh against a local stdlib server (no network, no docker)."""
import subprocess
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[2] / "scripts" / "smoke.sh"
WF = Path(__file__).resolve().parents[2] / ".github" / "workflows" / "deploy.yml"


class H(BaseHTTPRequestHandler):
    def do_GET(self):
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
    srv = HTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield f"http://127.0.0.1:{srv.server_port}"
    srv.shutdown()


def run(*args):
    return subprocess.run(["bash", str(SCRIPT), *args], capture_output=True, text=True, timeout=60)  # noqa: S603,S607


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
    for want in ("name: Deploy", "workflow_run", 'workflows: ["CI"]', "workflow_dispatch",
                 "group: deploy", "cancel-in-progress: false", "RENDER_DEPLOY_HOOK_URL",
                 "scripts/smoke.sh"):
        assert want in t, want
    assert "echo \"$HOOK" not in t and "echo $HOOK" not in t
