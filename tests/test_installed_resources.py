"""Installed-tool defaults and bundled-resource tests."""

from __future__ import annotations

import tomllib
from pathlib import Path

import pytest

from mommy_chaogu.db_paths import default_data_dir
from mommy_chaogu.services.theme_service import ThemeService


def test_installed_tool_uses_user_data_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workdir = tmp_path / "unrelated-project"
    workdir.mkdir()
    monkeypatch.chdir(workdir)
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    monkeypatch.delenv("XDG_DATA_HOME", raising=False)
    monkeypatch.delenv("MOMMY_DATA_DIR", raising=False)

    assert default_data_dir() == tmp_path / "home" / ".local" / "share" / "mommy-chaogu"


def test_data_directory_can_be_overridden(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    selected = tmp_path / "private-data"
    monkeypatch.setenv("MOMMY_DATA_DIR", str(selected))

    assert default_data_dir() == selected


def test_bundled_themes_work_outside_source_checkout(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.chdir(tmp_path)

    themes = ThemeService().list_themes()

    assert len(themes) >= 5
    assert {item["id"] for item in themes} >= {"semiconductor", "earnings_watch"}


def test_release_artifacts_exclude_runtime_output_and_local_test_skills() -> None:
    root = Path(__file__).resolve().parents[1]
    config = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
    excluded = set(config["tool"]["hatch"]["build"]["exclude"])

    assert "/output/**" in excluded
    assert "/src/mommy_chaogu/bundled_skills/market-monitoring-test/**" in excluded
