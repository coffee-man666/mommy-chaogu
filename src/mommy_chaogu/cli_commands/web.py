"""web command family."""

from __future__ import annotations

# Shared CLI dependencies are deliberately exported by cli_support.
# ruff: noqa: F403,F405
from mommy_chaogu.cli_support import *

# ============================================================
# web 子命令
# ============================================================


def build_web_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="mommy-web",
        description="妈妈炒股 - Web 后端服务（FastAPI + WebSocket）",
    )
    p.add_argument("--host", default="127.0.0.1", help="监听地址 (默认 127.0.0.1)")
    p.add_argument("--port", type=int, default=8000, help="监听端口 (默认 8000)")
    p.add_argument(
        "--db", default=str(DEFAULT_DB_PATH), help=f"数据库路径 (默认 {DEFAULT_DB_PATH})"
    )
    p.add_argument("--poll-interval", type=float, default=5.0, help="后台轮询间隔（秒）(默认 5)")
    p.add_argument(
        "--server-chan-key",
        default=os.environ.get("SERVER_CHAN_KEY", ""),
        help="Server酱 SendKey（启用微信推送，默认读 $SERVER_CHAN_KEY）",
    )
    p.add_argument(
        "--web-base-url",
        default=os.environ.get("WEB_BASE_URL", ""),
        help="Web 前端的公网/HTTPS URL（推送消息里带 K 线链接用）",
    )
    p.add_argument("--reload", action="store_true", help="开发模式热重载")
    p.add_argument("--log-level", default="info", choices=["debug", "info", "warning", "error"])
    p.add_argument("--api-token", default=os.environ.get("MOMMY_API_TOKEN", ""))
    p.add_argument(
        "--cors-origin",
        action="append",
        default=None,
        help="允许的 Web 前端 origin（可重复）",
    )
    p.add_argument(
        "--allow-unauthenticated-remote",
        action="store_true",
        help="仅用于已由宿主机限制为 localhost 的容器网络",
    )
    return p


def cmd_web_serve(args: argparse.Namespace) -> int:
    """启动 Web 服务。"""
    import uvicorn

    from mommy_chaogu.config import load_config
    from mommy_chaogu.web import create_app

    cfg = load_config()
    api_token = args.api_token or cfg.web.api_token
    is_loopback = args.host in {"127.0.0.1", "localhost", "::1"}
    if not is_loopback and not api_token and not args.allow_unauthenticated_remote:
        print(
            "❌ 非本机 Web 监听必须设置 MOMMY_API_TOKEN（或 --api-token）。",
            file=sys.stderr,
        )
        return 2

    app = create_app(
        db_path=Path(args.db),
        poll_interval_seconds=args.poll_interval,
        server_chan_key=args.server_chan_key or None,
        web_base_url=args.web_base_url,
        api_token=api_token,
        cors_origins=args.cors_origin if args.cors_origin is not None else cfg.web.cors_origins,
        ws_ticket_ttl_seconds=cfg.web.ws_ticket_ttl_seconds,
        agent_max_concurrency=cfg.web.agent_max_concurrency,
        session_retention_days=cfg.web.session_retention_days,
    )
    uvicorn.run(
        app,
        host=args.host,
        port=args.port,
        reload=args.reload,
        log_level=args.log_level,
    )
    return 0


def main_web() -> NoReturn:
    parser = build_web_parser()
    args = parser.parse_args()
    sys.exit(cmd_web_serve(args))
