"""Versioned Railway service configuration checks."""

from __future__ import annotations

import tomllib
from pathlib import Path

CONFIG_PATH = Path(__file__).resolve().parents[1] / "railway.toml"


def test_railway_healthcheck_and_restart_policy() -> None:
    config = tomllib.loads(CONFIG_PATH.read_text())
    deploy = config["deploy"]

    assert deploy["healthcheckPath"] == "/api/health"
    assert deploy["healthcheckTimeout"] == 120
    assert deploy["restartPolicyType"] == "ON_FAILURE"
    assert deploy["restartPolicyMaxRetries"] == 10
