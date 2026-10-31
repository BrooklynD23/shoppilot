"""render.yaml checks by line match (no PyYAML dependency)."""

from pathlib import Path

TEXT = (Path(__file__).resolve().parents[2] / "render.yaml").read_text()
LINES = [ln.strip() for ln in TEXT.splitlines()]


def test_service_fields():
    for want in (
        "- type: web",
        "name: shoppilot",
        "runtime: docker",
        "plan: free",
        "region: oregon",
        "dockerfilePath: ./Dockerfile",
        "healthCheckPath: /healthz",
        'autoDeployTrigger: "off"',
    ):
        assert want in LINES, want
    assert not any(ln.startswith("disk") for ln in LINES)
    assert TEXT.count("- type:") == 1


def test_env_vars():
    keys = [ln.split(": ", 1)[1] for ln in LINES if ln.startswith("- key:")]
    assert keys == ["APP_ENV", "DATA_DIR", "ANTHROPIC_API_KEY", "STRIPE_SECRET_KEY"]
    assert "value: prod" in LINES and "value: /tmp/shoppilot" in LINES
    assert LINES.count("sync: false") == 2
    for bad in ("sk_", "sk-ant-", "sk_test_", "sk_live_", "rk_test_", "rk_live_"):
        assert bad not in TEXT, bad
    for secret in ("ANTHROPIC_API_KEY", "STRIPE_SECRET_KEY"):
        assert LINES[LINES.index(f"- key: {secret}") + 1] == "sync: false", secret
