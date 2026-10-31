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
