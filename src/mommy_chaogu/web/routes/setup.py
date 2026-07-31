"""/api/setup 路由：本机首次配置向导（provider / model / key 校验与持久化）。

安全模型：
- 这些端点从不无条件公开。OwnerAuthMiddleware 仅在以下两种情况放行：
  (a) create_app 收到 local_setup_enabled=True 且请求来自真实 loopback socket，
  (b) 请求携带严格有效的 owner 凭证（Bearer token 或已签名的会话 cookie），
      且 security.enabled 为真（即 api_token 非空）。
  绝不信任 X-Forwarded-For；--allow-unauthenticated-remote（非 loopback 绑定）
  不会让这些端点对远程开放。

复用而非复制：
- provider 真相源 = agent.llm.SUPPORTED_PROVIDERS
- key 校验 = setup.validate_llm_connection
- 持久化 = setup._write_env_file（0600 原子写）

密钥处理：
- 任何响应都不回显、不记录、不序列化 API key。
"""

from __future__ import annotations

import os

from fastapi import APIRouter, HTTPException, Request

from mommy_chaogu.agent.llm import SUPPORTED_PROVIDERS
from mommy_chaogu.config import load_config
from mommy_chaogu.setup import (
    _PROVIDERS,
    _write_env_file,
    preferred_setup_env_path,
    validate_llm_connection,
)
from mommy_chaogu.web.deps import reload_agent_caches
from mommy_chaogu.web.schemas import (
    SetupProviderOut,
    SetupResultOut,
    SetupSaveIn,
    SetupStatusOut,
    SetupValidateIn,
    SetupWeixinStatusOut,
    WeixinPollIn,
    WeixinPollOut,
    WeixinStartOut,
)
from mommy_chaogu.web.weixin_pairing import WeixinPairingManager

router = APIRouter(prefix="/api/setup", tags=["setup"])


def _weixin_status() -> SetupWeixinStatusOut:
    """读取微信通道配对状态，不做任何网络探测。"""
    try:
        from mommy_chaogu.channels import WeixinStore
        from mommy_chaogu.channels.process import gateway_process_pid
    except Exception:
        # channels 包不可用时降级为"未配对"，不阻塞向导。
        return SetupWeixinStatusOut(connected=False, online=False)

    try:
        store = WeixinStore()
        creds = store.load_credentials()
        connected = creds is not None
        online = connected and gateway_process_pid(store) is not None
    except Exception:
        return SetupWeixinStatusOut(connected=False, online=False)
    return SetupWeixinStatusOut(connected=connected, online=online)


def _provider_label(provider: str) -> str:
    return str(_PROVIDERS.get(provider, {}).get("label", provider))


@router.get("/status", response_model=SetupStatusOut)
def setup_status(request: Request) -> SetupStatusOut:
    """聚合配置状态：认证模式、LLM、微信、数据服务就绪度（无密钥/路径/网络探测）。

    认证模式直接取自 WebSecurity.auth_mode（唯一真相源），而非 cfg.web.api_token：
    本地 CLI 有意忽略陈旧的 MOMMY_API_TOKEN，cfg 可能与实际运行态不一致。
    """
    cfg = load_config()
    wx = _weixin_status()

    # 数据服务就绪度：adapter 单例已构造即视为可用（无网络探测）。
    from mommy_chaogu.web.background import get_service

    try:
        svc = get_service()
        data_ok = svc is not None
    except Exception:
        data_ok = False

    security = request.app.state.web_security
    return SetupStatusOut(
        auth_mode=security.auth_mode,
        llm_configured=bool(cfg.agent.api_key),
        provider=cfg.agent.provider,
        model=cfg.agent.model or "",
        weixin=wx,
        data_ok=data_ok,
    )


@router.get("/providers", response_model=list[SetupProviderOut])
def setup_providers() -> list[SetupProviderOut]:
    """列出可选 provider（无密钥）。真相源 = SUPPORTED_PROVIDERS。"""
    return [
        SetupProviderOut(
            id=name,
            label=_provider_label(name),
            default_model=str(cfg["default_model"]),
            env_key=str(cfg["env_key"]),
        )
        for name, cfg in SUPPORTED_PROVIDERS.items()
    ]


def _validate_provider(provider: str) -> str:
    """Reject unsupported / blank providers before any key handling."""
    normalized = provider.strip().lower()
    if not normalized:
        raise HTTPException(status_code=422, detail="provider 不能为空")
    if normalized not in SUPPORTED_PROVIDERS:
        raise HTTPException(
            status_code=422,
            detail=f"不支持的 provider：{normalized}",
        )
    return normalized


def _validate_model_key(model: str, api_key: str) -> tuple[str, str]:
    """Reject blank model / key. Returns trimmed values."""
    m = model.strip()
    if not m:
        raise HTTPException(status_code=422, detail="model 不能为空")
    if not api_key or not api_key.strip():
        raise HTTPException(status_code=422, detail="api_key 不能为空")
    return m, api_key.strip()


@router.post("/validate", response_model=SetupResultOut)
async def setup_validate(req: SetupValidateIn) -> SetupResultOut:
    """校验 API key（一次最小 completion）。复用 setup.validate_llm_connection。

    网络调用在 threadpool 中执行；响应从不回显 key。
    """
    import asyncio

    provider = _validate_provider(req.provider)
    model, api_key = _validate_model_key(req.model, req.api_key)

    ok, message = await asyncio.to_thread(validate_llm_connection, provider, model, api_key)
    return SetupResultOut(ok=ok, message=message)


@router.post("/save", response_model=SetupResultOut)
async def setup_save(req: SetupSaveIn) -> SetupResultOut:
    """保存 provider/model/key 到私有 .env（0600 原子写）并热更新当前进程。

    复用 setup._write_env_file；随后更新 os.environ 与 AGENT_PROVIDER/AGENT_MODEL，
    再调用 deps.reload_agent_caches() 让新配置在当前进程内立即生效（无需重启）。
    响应从不回显 key。
    """
    import asyncio

    provider = _validate_provider(req.provider)
    model, api_key = _validate_model_key(req.model, req.api_key)

    env_key = str(SUPPORTED_PROVIDERS[provider]["env_key"])
    env_path = preferred_setup_env_path()

    # 先在 threadpool 中校验，避免在请求线程里阻塞；校验失败则不写盘。
    ok, message = await asyncio.to_thread(validate_llm_connection, provider, model, api_key)
    if not ok:
        return SetupResultOut(ok=False, message=message)

    # 文件系统写也在 threadpool 中执行，避免阻塞事件循环。
    await asyncio.to_thread(_write_env_file, env_path, provider, api_key, model=model)

    # 让当前进程立即生效（镜像 setup.run_setup_wizard 的 env 设置）。
    os.environ[env_key] = api_key
    os.environ["AGENT_PROVIDER"] = provider
    os.environ["AGENT_MODEL"] = model

    # 仅失效 LLM 相关缓存（agent / memory / workflow router），不动共享的
    # market/background/alerter 资源。
    reload_agent_caches()

    _label = _provider_label(provider)
    return SetupResultOut(
        ok=True,
        message=f"AI 配置已保存并即时生效：{_label} / {model}",
    )


# ---------- Weixin messaging-channel QR pairing ----------
#
# 仅用于连接/重连微信消息通道（用户可通过微信与 Agent 对话）。
# 不是 Web 认证、不是远程配对、不影响 LLM 配置。所有上游 ID、token、
# 重定向地址只保存在进程内存中，绝不回显给浏览器。


def _get_pairing_manager(request: Request) -> WeixinPairingManager:
    """Return the app-scoped WeixinPairingManager (lazily created for tests)."""
    manager = getattr(request.app.state, "weixin_pairing", None)
    if manager is None:
        from mommy_chaogu.web.weixin_pairing import default_pairing_manager

        manager = default_pairing_manager()
        request.app.state.weixin_pairing = manager
    return manager


@router.post("/weixin/start", response_model=WeixinStartOut)
async def weixin_start(request: Request) -> WeixinStartOut:
    """开始或重启一次微信扫码配对。

    返回浏览器安全的 SVG 二维码数据 URL + 不透明的 pairing_id。
    不暴露 qrcode_id、原始 URL、重定向地址或任何凭据。
    """
    manager = _get_pairing_manager(request)
    result = await manager.start()
    return WeixinStartOut(
        pairing_id=result.pairing_id,
        qr_data_url=result.qr_data_url,
        expires_in_seconds=result.expires_in_seconds,
        status=result.status,
        message=result.message,
    )


@router.post("/weixin/poll", response_model=WeixinPollOut)
async def weixin_poll(req: WeixinPollIn, request: Request) -> WeixinPollOut:
    """查询一次微信扫码状态。

    每次请求最多一次上游 long-poll（在 threadpool 中执行）。
    pairing_id 过期或不存在时返回稳定的 expired 结果，不泄露信息。
    """
    manager = _get_pairing_manager(request)
    result = await manager.poll(req.pairing_id, req.verify_code)
    return WeixinPollOut(
        status=result.status,
        message=result.message,
        gateway_started=result.gateway_started,
        gateway_online=result.gateway_online,
    )
