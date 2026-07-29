"""One-line installer contract tests."""

from __future__ import annotations

import os
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INSTALLER = ROOT / "install.sh"


def test_installer_is_valid_posix_shell() -> None:
    result = subprocess.run(
        ["sh", "-n", str(INSTALLER)],
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr


def test_installer_uses_uv_tool_and_verifies_mommy() -> None:
    text = INSTALLER.read_text(encoding="utf-8")

    assert "uv/install.sh" in text
    assert "tool install" in text
    assert '"$mommy_binary" --help' in text
    assert "curl -LsSf https://github.com/coffee-man666/mommy-chaogu/raw/" in text


def test_installer_runs_with_an_existing_uv(tmp_path: Path) -> None:
    fake_bin = tmp_path / "fake-bin"
    tool_bin = tmp_path / "tool-bin"
    fake_bin.mkdir()
    tool_bin.mkdir()
    log = tmp_path / "uv.log"
    fake_uv = fake_bin / "uv"
    fake_uv.write_text(
        """#!/bin/sh
set -eu
printf '%s\\n' "$*" >> "$FAKE_UV_LOG"
if [ "${1:-} ${2:-} ${3:-}" = "tool dir --bin" ]; then
    printf '%s\\n' "$FAKE_TOOL_BIN"
elif [ "${1:-} ${2:-}" = "tool install" ]; then
    printf '#!/bin/sh\\nexit 0\\n' > "$FAKE_TOOL_BIN/mommy"
    chmod +x "$FAKE_TOOL_BIN/mommy"
fi
""",
        encoding="utf-8",
    )
    fake_uv.chmod(0o755)
    env = {
        **os.environ,
        "PATH": f"{fake_bin}:{os.environ.get('PATH', '')}",
        "HOME": str(tmp_path / "home"),
        "FAKE_UV_LOG": str(log),
        "FAKE_TOOL_BIN": str(tool_bin),
        "MOMMY_INSTALL_SOURCE": "mommy-chaogu @ https://example.test/mommy.tar.gz",
    }

    result = subprocess.run(
        ["sh", str(INSTALLER)],
        env=env,
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert "mommy-chaogu 安装完成" in result.stdout
    calls = log.read_text(encoding="utf-8")
    assert (
        "tool install --quiet --quiet --refresh-package mommy-chaogu "
        "--reinstall-package mommy-chaogu --python 3.12" in calls
    )
    assert "tool dir --bin" in calls
