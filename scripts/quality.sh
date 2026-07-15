#!/usr/bin/env bash

set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

uv run ruff format --check .
uv run ruff check .
uv run mypy --strict src
uv run pytest -m "not network"

cd web
npm run typecheck
npm run build
