import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
CFG = tomllib.loads((ROOT / "pyproject.toml").read_text())


def test_ruff_skips_docs():
    assert "docs" in CFG["tool"]["ruff"]["extend-exclude"]


def test_plain_uv_sync_installs_dev_tools():
    assert CFG["dependency-groups"]["dev"] == ["shoppilot[dev]"]


def test_docker_and_ci_use_lockfile():
    assert "uv.lock" in (ROOT / "Dockerfile").read_text()
    assert "--locked" in (ROOT / ".github/workflows/ci.yml").read_text()


def test_cov_gate_lives_in_ci_not_addopts():
    # #76: per-file pytest runs must not fail on whole-app coverage
    assert "--cov-fail-under" not in CFG["tool"]["pytest"]["ini_options"]["addopts"]
    assert "--cov-fail-under=80" in (ROOT / ".github/workflows/ci.yml").read_text()


def test_dockerfile_builds_web_and_slims():
    d = (ROOT / "Dockerfile").read_text()
    assert "FROM node:22-slim AS web" in d and "npm ci" in d
    assert d.index("COPY app ./app") < d.index("COPY --from=web /web/dist ./app/static")
    assert d.index("COPY --from=web") < d.index("pip install --no-deps .")
    assert "pip uninstall -y uv" in d and "rm /tmp/req.txt" in d
    ignore = (ROOT / ".dockerignore").read_text().split()
    assert {"web/node_modules", "web/dist", "web/.astro", "web/review"} <= set(ignore)


def test_ci_docker_smoke_needs_no_real_keys():
    ci = (ROOT / ".github/workflows/ci.yml").read_text()
    assert "--memory=512m" in ci and "GOOGLE_API_KEY=dummy" in ci
    assert "sleep 5" not in ci and "docker logs sp" in ci
    assert "grep -qi '<html'" in ci
