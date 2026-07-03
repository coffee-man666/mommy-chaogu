FROM python:3.12-slim

WORKDIR /app

# 安装 uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

# 先拷贝依赖文件（利用 Docker 层缓存）
COPY pyproject.toml uv.lock ./
RUN uv sync --extra dev --no-dev 2>/dev/null || uv sync --extra dev

# 拷贝源码
COPY src/ ./src/
COPY tests/ ./tests/
COPY web/dist/ ./web/dist/
COPY docs/ ./docs/

# 创建 data 目录
RUN mkdir -p data

# 默认启动 Web 服务
EXPOSE 8000
CMD ["uv", "run", "mommy-web", "--host", "0.0.0.0", "--port", "8000"]
