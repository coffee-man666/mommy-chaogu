"""Frontend static build discovery tests."""

from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from mommy_chaogu.web.app import (
    _frontend_dist_candidates,
    _resolve_frontend_dist,
    create_app,
)


def _write_frontend(dist: Path) -> None:
    dist.mkdir(parents=True)
    (dist / "index.html").write_text('<div id="app"></div>')


def test_configured_frontend_dist_has_priority(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    configured = tmp_path / "configured-dist"
    _write_frontend(configured)
    monkeypatch.setenv("MOMMY_WEB_DIST", str(configured))

    assert _frontend_dist_candidates()[0] == configured
    assert _resolve_frontend_dist() == configured


def test_incomplete_configured_dist_falls_back_to_working_directory(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    configured = tmp_path / "empty-dist"
    configured.mkdir()
    fallback = tmp_path / "web" / "dist"
    _write_frontend(fallback)
    monkeypatch.setenv("MOMMY_WEB_DIST", str(configured))
    monkeypatch.chdir(tmp_path)

    assert _resolve_frontend_dist() == fallback


def test_configured_frontend_is_served_at_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    configured = tmp_path / "configured-dist"
    _write_frontend(configured)
    monkeypatch.setenv("MOMMY_WEB_DIST", str(configured))

    response = TestClient(create_app()).get("/")

    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/html")
    assert '<div id="app"></div>' in response.text
