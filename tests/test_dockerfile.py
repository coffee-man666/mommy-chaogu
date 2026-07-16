"""Deployment image regression checks."""

from __future__ import annotations

from pathlib import Path

DOCKERFILE = (Path(__file__).resolve().parents[1] / "Dockerfile").read_text()


def test_runtime_user_can_write_efinance_cache() -> None:
    cache_dir = "/app/.venv/lib/python3.12/site-packages/efinance/data"

    assert DOCKERFILE.count(cache_dir) == 2
    assert "mkdir -p \\" in DOCKERFILE
    assert "chown -R mommy:mommy \\" in DOCKERFILE


def test_web_process_and_healthcheck_use_railway_port() -> None:
    assert "${PORT:-8000}" in DOCKERFILE
    assert "os.environ.get('PORT', '8000')" in DOCKERFILE
