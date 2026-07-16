"""Deployment image regression checks."""

from __future__ import annotations

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DOCKERFILE = (ROOT / "Dockerfile").read_text()
ENTRYPOINT = ROOT / "docker" / "entrypoint.sh"
ENTRYPOINT_TEXT = ENTRYPOINT.read_text()


def test_runtime_user_can_write_efinance_cache() -> None:
    cache_dir = "/app/.venv/lib/python3.12/site-packages/efinance/data"

    assert DOCKERFILE.count(cache_dir) == 2
    assert "chown -R mommy:mommy" in DOCKERFILE


def test_web_process_and_healthcheck_use_platform_port() -> None:
    assert "os.environ.get('PORT', '8000')" in DOCKERFILE
    assert 'CMD ["mommy-web", "--host", "0.0.0.0"]' in DOCKERFILE
    assert "${PORT" not in DOCKERFILE


def test_volume_entrypoint_is_installed_before_non_root_runtime() -> None:
    assert "apt-get install -y --no-install-recommends gosu" in DOCKERFILE
    assert "COPY --chmod=755 docker/entrypoint.sh" in DOCKERFILE
    assert 'ENTRYPOINT ["mommy-entrypoint"]' in DOCKERFILE
    assert DOCKERFILE.index("ENTRYPOINT") > DOCKERFILE.index("USER mommy")


def test_volume_entrypoint_seeds_data_and_drops_privileges() -> None:
    assert "RAILWAY_VOLUME_MOUNT_PATH" in ENTRYPOINT_TEXT
    assert 'chown -R "$EXPECTED_USER:$EXPECTED_USER" "$DATA_DIR"' in ENTRYPOINT_TEXT
    assert 'exec gosu "$EXPECTED_USER" "$@"' in ENTRYPOINT_TEXT
    assert 'cp -R "$SEED_DIR"/. "$DATA_DIR"/' in ENTRYPOINT_TEXT


def test_volume_entrypoint_has_valid_shell_syntax() -> None:
    subprocess.run(["/bin/sh", "-n", str(ENTRYPOINT)], check=True)
