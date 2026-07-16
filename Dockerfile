# syntax=docker/dockerfile:1

# ---- pinned tool image ----
FROM ghcr.io/astral-sh/uv:0.7.19 AS uv-bin

# ---- frontend builder ----
FROM node:22-bookworm-slim AS web-builder

WORKDIR /web
COPY web/package.json web/package-lock.json ./
RUN npm ci

COPY web/ ./
RUN npm run typecheck && npm run build

# ---- Python dependency builder ----
FROM python:3.12-slim AS python-builder

WORKDIR /app
COPY --from=uv-bin /uv /usr/local/bin/uv

ENV UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1

COPY pyproject.toml uv.lock README.md ./
COPY src/ ./src/
RUN uv sync --frozen --no-dev --no-editable

# ---- runtime ----
FROM python:3.12-slim AS runtime

WORKDIR /app

RUN groupadd --gid 1000 mommy \
    && useradd --uid 1000 --gid mommy --create-home mommy

COPY --from=python-builder /app/.venv /app/.venv
COPY --from=web-builder /web/dist /app/web/dist
COPY --chown=mommy:mommy data/supply_chains/ /app/data/supply_chains/
COPY --chown=mommy:mommy data/earnings_preview.json /app/data/earnings_preview.json

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1

RUN mkdir -p \
        /app/data \
        /app/.venv/lib/python3.12/site-packages/efinance/data \
    && chown -R mommy:mommy \
        /app/data \
        /app/.venv/lib/python3.12/site-packages/efinance/data

EXPOSE 8000

USER mommy

HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
    CMD python -c "import os, urllib.request; urllib.request.urlopen(f\"http://localhost:{os.environ.get('PORT', '8000')}/api/health\", timeout=5)" || exit 1

CMD ["sh", "-c", "exec mommy-web --host 0.0.0.0 --port \"${PORT:-8000}\""]
