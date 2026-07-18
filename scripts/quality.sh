#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

uv run ruff format --check .
uv run ruff check .
uv run mypy --strict src
uv run pytest -m "not network" --cov=mommy_chaogu --cov-report=term --cov-fail-under=65

cd web
npm test
npm run typecheck
npm run build
