"""FastAPI app factory。

用法：
    from mommy_chaogu.web import create_app
    app = create_app()

    # 开发模式
    uvicorn mommy_chaogu.web.app:create_app --factory --reload
"""

from __future__ import annotations

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from mommy_chaogu.db_paths import PORTFOLIO_DB
from mommy_chaogu.web.background import BackgroundService, set_service
from mommy_chaogu.web.deps import (
    close_cached_dependencies,
    get_adapter,
    get_agent_memory,
    get_alerter,
    get_watchlist_store,
)
from mommy_chaogu.web.routes import (
    agent,
    cache,
    earnings,
    market,
    portfolio,
    quotes,
    signals,
    themes,
    watchlist,
    ws,
)
from mommy_chaogu.web.schemas import HealthOut
from mommy_chaogu.web.security import OwnerAuthMiddleware, WebSecurity

_log = logging.getLogger(__name__)


def create_app(
    db_path: Path | None = None,
    poll_interval_seconds: float = 5.0,
    server_chan_key: str | None = None,
    web_base_url: str = "",
    api_token: str = "",
    cors_origins: list[str] | None = None,
    ws_ticket_ttl_seconds: int = 60,
    agent_max_concurrency: int = 2,
    session_retention_days: int = 30,
) -> FastAPI:
    """FastAPI app 工厂。

    参数：
        db_path: 自选股/缓存数据库路径（None 用默认 data/portfolio.db）
        poll_interval_seconds: 后台轮询间隔（秒）
    """
    if db_path is not None:
        # 覆盖默认 db 路径
        from mommy_chaogu.web import deps

        deps.get_db_path.cache_clear()  # type: ignore[attr-defined]

        def _custom_db_path() -> Path:
            return db_path

        deps.get_db_path = _custom_db_path  # type: ignore[assignment]
        deps.get_adapter.cache_clear()  # type: ignore[attr-defined]
        deps.get_watchlist_store.cache_clear()  # type: ignore[attr-defined]
        deps.get_alerter.cache_clear()  # type: ignore[attr-defined]
        deps.get_portfolio_store.cache_clear()  # type: ignore[attr-defined]

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        """后台轮询启停。"""
        adapter = get_adapter()
        watchlist_store = get_watchlist_store()
        alerter = get_alerter()
        if session_retention_days > 0:
            memory = get_agent_memory()
            pruned = memory.prune_inactive_sessions(session_retention_days)  # type: ignore[attr-defined]
            if pruned:
                _log.info("pruned %d inactive conversation messages", pruned)

        # 初始化推送（如果配置了 Server酱 SendKey）
        notifier = None
        if server_chan_key:
            from mommy_chaogu.push import (
                JsonFileDeduper,
                ServerChanPusher,
                SignalNotifier,
            )
            from mommy_chaogu.signals import SignalSeverity

            push_db = (db_path or PORTFOLIO_DB).parent / "pushed.json"
            try:
                pusher = ServerChanPusher(
                    send_key=server_chan_key,
                    web_base_url=web_base_url,
                )
                deduper = JsonFileDeduper(push_db)
                notifier = SignalNotifier(
                    pusher=pusher,
                    deduper=deduper,
                    severity_threshold=SignalSeverity.WARNING,  # info 不推
                    web_base_url=web_base_url,
                )
                _log.info(
                    "✅ Server酱推送已启用（web_base_url=%s, dedup=%s）",
                    web_base_url or "(none)",
                    push_db,
                )
            except Exception:
                _log.exception("推送初始化失败，将以无推送模式运行")
                notifier = None
        else:
            _log.info("未配置 Server酱 SendKey，跳过推送（仅 Web UI）")

        service = BackgroundService(
            adapter=adapter,
            watchlist=watchlist_store,
            alerter=alerter,
            poll_interval_seconds=poll_interval_seconds,
            notifier=notifier,
        )
        set_service(service)
        await service.start()
        try:
            yield
        finally:
            await service.stop()
            close_cached_dependencies()

    app = FastAPI(
        title="mommy-chaogu API",
        description="妈妈炒股的 Web 后端",
        version="0.1.0",
        lifespan=lifespan,
    )

    security = WebSecurity(
        api_token=api_token,
        ticket_ttl_seconds=ws_ticket_ttl_seconds,
        agent_max_concurrency=agent_max_concurrency,
    )
    app.state.web_security = security
    app.add_middleware(OwnerAuthMiddleware, security=security)

    # CORS（开发期 H5 跨域）
    if cors_origins:
        app.add_middleware(
            CORSMiddleware,
            allow_origins=cors_origins,
            allow_credentials=False,
            allow_methods=["*"],
            allow_headers=["Authorization", "Content-Type"],
        )

    # 路由
    app.include_router(quotes.router)
    app.include_router(market.router)
    app.include_router(watchlist.router)
    app.include_router(portfolio.router)
    app.include_router(signals.router)
    app.include_router(cache.router)
    app.include_router(agent.router)
    app.include_router(earnings.router)
    app.include_router(themes.router)
    app.include_router(ws.router)

    @app.post("/api/auth/ws-ticket")
    def issue_ws_ticket() -> dict[str, str | int]:
        ticket, expires_at = security.issue_ws_ticket()
        return {"ticket": ticket, "expires_at": expires_at}

    # 健康检查
    @app.get("/api/health")
    def health() -> HealthOut:
        from mommy_chaogu.web.background import get_service

        svc = get_service()
        adapter = get_adapter()
        return HealthOut(
            ok=True,
            adapter_name=adapter.name,
            uptime_seconds=svc.uptime_seconds(),
            last_snapshot_at=svc.last_poll_at(),
        )

    # 静态文件（构建后的前端）
    # 优先用 Vite 输出的 web/dist（H5 更快）；如果有 frontend/dist（Taro 输出）也可以
    static_candidates = [
        Path(__file__).parent.parent.parent.parent / "web" / "dist",
        Path(__file__).parent.parent.parent.parent / "frontend" / "dist",
    ]
    static_dir = next((d for d in static_candidates if d.exists()), static_candidates[0])
    if static_dir.exists():
        # 静态文件优先（挂载在根），API 路由已在上面注册
        app.mount("/", StaticFiles(directory=str(static_dir), html=True), name="frontend")
        _log.info("static files mounted at %s", static_dir)
    else:
        _log.info("frontend dist not found at %s — API only", static_dir)

        # 没有静态文件时保留 API 根信息
        @app.get("/")
        def root() -> dict[str, str]:
            return {
                "name": "mommy-chaogu",
                "version": "0.1.0",
                "docs": "/docs",
                "health": "/api/health",
            }

    return app


__all__ = ["create_app"]
