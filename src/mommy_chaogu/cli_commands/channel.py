"""Local messaging-channel commands."""

from __future__ import annotations

import argparse
import sys
from contextlib import suppress
from pathlib import Path
from typing import NoReturn

from mommy_chaogu.channels import WeixinClient, WeixinCredentials, WeixinGateway, WeixinStore
from mommy_chaogu.channels.weixin import WeixinApiError


def build_channel_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="mommy-channel",
        description="连接本地个人助手与微信",
    )
    parser.add_argument("--state-dir", type=Path, default=None, help="覆盖本地频道状态目录")
    channel = parser.add_subparsers(dest="channel", required=True)
    weixin = channel.add_parser("weixin", help="腾讯微信 iLink（二维码登录）")
    action = weixin.add_subparsers(dest="action", required=True)
    action.add_parser("login", help="显示二维码并保存本地授权")
    action.add_parser("status", help="查看本地连接状态")
    action.add_parser("logout", help="删除本地微信授权")
    run = action.add_parser("run", help="启动微信消息网关")
    run.add_argument("--once", action="store_true", help="只轮询一次（诊断用）")
    connect = action.add_parser("connect", help="未登录时扫码，然后启动消息网关")
    connect.add_argument("--once", action="store_true", help="只轮询一次（诊断用）")
    return parser


def _display_qr(url: str) -> None:
    print("\n请用手机微信扫描二维码并确认：\n")
    try:
        import qrcode  # type: ignore[import-untyped]

        qr = qrcode.QRCode(border=1)
        qr.add_data(url)
        qr.make(fit=True)
        qr.print_ascii(invert=True)
    except Exception:
        print("终端无法渲染二维码，请在浏览器中打开下面的链接：")
    print(f"\n{url}\n")


def _login(store: WeixinStore, client: WeixinClient) -> WeixinCredentials:
    existing = store.load_credentials()
    local_tokens = [existing.token] if existing is not None else []
    result = client.login(on_qr=_display_qr, local_tokens=local_tokens)
    if result.already_connected and existing is not None:
        print("✅ 微信已经连接，本地授权继续有效。")
        return existing
    if not result.connected:
        raise WeixinApiError(result.message)
    credentials = WeixinCredentials(
        account_id=result.account_id,
        token=result.bot_token,
        base_url=result.base_url,
        owner_user_id=result.owner_user_id,
    )
    store.save_credentials(credentials)
    print("✅ 微信连接成功。授权只保存在当前设备。")
    return credentials


def _run_gateway(store: WeixinStore, client: WeixinClient, *, once: bool) -> None:
    credentials = store.load_credentials()
    if credentials is None:
        raise WeixinApiError("尚未连接微信，请先运行 mommy channel weixin login")

    from mommy_chaogu.agent.memory import ConversationMemory
    from mommy_chaogu.web.deps import (
        close_cached_dependencies,
        get_agent_db,
        get_agent_service,
    )

    agent = get_agent_service()
    if agent is None:
        raise WeixinApiError("尚未配置 LLM，请先运行 mommy setup")
    memory = ConversationMemory(get_agent_db())

    def respond(session_id: str, message: str) -> str:
        scoped = memory.for_session(session_id)
        response = agent.chat(message, memory=scoped)  # type: ignore[attr-defined]
        return str(response.text)

    gateway = WeixinGateway(
        client=client,
        store=store,
        credentials=credentials,
        respond=respond,
    )
    print("✅ 微信助手已上线，只接受扫码账号的私聊。按 Ctrl+C 停止。")
    try:
        if once:
            with suppress(WeixinApiError):
                client.notify(
                    base_url=credentials.base_url,
                    token=credentials.token,
                    started=True,
                )
            try:
                handled = gateway.run_once()
                print(f"本次处理 {handled} 条消息。")
            finally:
                with suppress(WeixinApiError):
                    client.notify(
                        base_url=credentials.base_url,
                        token=credentials.token,
                        started=False,
                    )
        else:
            gateway.run_forever()
    finally:
        flush = getattr(agent, "flush", None)
        if callable(flush):
            flush(timeout=10)
        memory.close()
        close_cached_dependencies()


def cmd_channel(args: argparse.Namespace) -> int:
    if args.channel != "weixin":
        return 2
    store = WeixinStore(args.state_dir)
    client = WeixinClient()
    try:
        if args.action == "login":
            _login(store, client)
        elif args.action == "status":
            credentials = store.load_credentials()
            if credentials is None:
                print("微信未连接。")
            else:
                print(f"微信已连接：{credentials.account_id}（凭据保存在 {store.root}）")
        elif args.action == "logout":
            store.clear()
            print("✅ 已删除当前设备上的微信授权。")
        elif args.action == "connect":
            if store.load_credentials() is None:
                _login(store, client)
            _run_gateway(store, client, once=args.once)
        elif args.action == "run":
            _run_gateway(store, client, once=args.once)
        else:
            return 2
    except WeixinApiError as exc:
        print(f"❌ {exc}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        print("\n微信助手已停止。")
    return 0


def main_channel() -> NoReturn:
    parser = build_channel_parser()
    raise SystemExit(cmd_channel(parser.parse_args()))


__all__ = ["build_channel_parser", "cmd_channel", "main_channel"]
