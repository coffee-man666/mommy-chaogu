# ---- builder stage: install dependencies ----
FROM python:3.12-slim AS builder

WORKDIR /app

# 安装 uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# Docker 构建时没有符号链接，用 copy 模式更稳定
ENV UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1

# 先拷贝依赖文件（利用 Docker 层缓存）
COPY pyproject.toml uv.lock ./

# 安装生产依赖到 .venv（不含 dev 依赖）
RUN uv sync --no-dev

# ---- runtime stage: slim image ----
FROM python:3.12-slim AS runtime

WORKDIR /app

# 拷贝 uv 运行时和虚拟环境
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv
COPY --from=builder /app/.venv /app/.venv

# 将 .venv 加入 PATH，这样可以直接调用 mommy-web
ENV PATH="/app/.venv/bin:$PATH" \
    UV_LINK_MODE=copy \
    PYTHONUNBUFFERED=1

# 拷贝项目文件
COPY src/ ./src/
COPY tests/ ./tests/
COPY web/dist/ ./web/dist/
COPY docs/ ./docs/
COPY pyproject.toml uv.lock ./
COPY .env.example ./.env.example

# 创建 data 目录并声明为 VOLUME（数据库持久化）
RUN mkdir -p data
VOLUME ["/app/data"]

# 默认启动 Web 服务
EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=10s --start-period=15s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/api/health', timeout=5)" || exit 1

CMD ["mommy-web", "--host", "0.0.0.0", "--port", "8000"]
