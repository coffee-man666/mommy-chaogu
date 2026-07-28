"""LLM provider 单一真相源 + client 工厂。

provider 配置（base_url / 默认模型 / env key / 采样温度 / embedding 模型）
只在本模块维护。AgentService、各装配点（CLI / Web / TUI / MCP）、
回测脚本（scripts/backtest_llm.py）统一从这里取配置，避免多份表漂移
（历史上 service.py / backtest_llm.py / config.py 各有一份，kimi 的
base_url 与模型名已经不一致）。

约定：
- ``create_client`` 显式设置 ``timeout`` 并把 SDK 内置重试关掉
  （``max_retries=0``）——重试统一由应用层（``AgentService._create_with_retry``
  / extractor 的本地重试）负责，避免双层重试叠加（单请求最坏 12 次尝试）。
- ``embedding_model`` 为 ``None`` 表示该 provider 没有可用的 OpenAI 兼容
  embedding 接口（deepseek / kimi / zai / nova / minimax 的聊天端点均不提供），
  向量检索路径应据此显式降级，而不是把聊天模型名当 embedding 模型传。
"""

from __future__ import annotations

import os
from typing import Any

# 支持的 provider 配置
SUPPORTED_PROVIDERS: dict[str, dict[str, Any]] = {
    "deepseek": {
        "base_url": "https://api.deepseek.com",
        "default_model": "deepseek-chat",
        "env_key": "DEEPSEEK_API_KEY",
        "temperature": 0.2,
        "embedding_model": None,
    },
    "openai": {
        "base_url": None,  # OpenAI 默认
        "default_model": "gpt-4o-mini",
        "env_key": "OPENAI_API_KEY",
        "temperature": 0.2,
        "embedding_model": "text-embedding-3-small",
    },
    "kimi": {
        "base_url": "https://api.kimi.com/coding/v1",
        "default_model": "kimi-k2.6",
        "env_key": "MOONSHOT_API_KEY",
        "temperature": 1.0,
        "embedding_model": None,
    },
    "zai": {
        "base_url": "https://api.z.ai/api/coding/paas/v4",
        "default_model": "glm-4.7",
        "env_key": "ZAI_API_KEY",
        "temperature": 0.2,
        "embedding_model": None,
    },
    "nova": {
        "base_url": "http://127.0.0.1:9999/v1",
        "default_model": "nova-bridge",
        "env_key": "NOVA_API_KEY",
        "temperature": None,
        "embedding_model": None,
    },
    "minimax": {
        "base_url": "https://api.minimaxi.com/v1",
        "default_model": "MiniMax-M2.7",
        "env_key": "MINIMAX_API_KEY",
        "temperature": 1.0,
        "embedding_model": None,
    },
}

# LLM 调用的默认超时（秒）。SDK 默认 600s 太长，TUI worker / web 线程
# 会被挂住；120s 对长推理也够用，超时后由应用层重试接管。
DEFAULT_TIMEOUT = 120.0


def normalize_provider(provider: str) -> str:
    """规范化 provider 名，不合法时给出 actionable 报错。"""
    normalized = provider.strip().lower()
    if normalized not in SUPPORTED_PROVIDERS:
        supported = ", ".join(SUPPORTED_PROVIDERS)
        raise ValueError(f"Unsupported agent provider {provider!r}; choose one of: {supported}")
    return normalized


def resolve_provider(provider: str | None = None) -> str:
    """确定当前 provider：显式参数 > ``AGENT_PROVIDER`` 环境变量 > deepseek。"""
    return normalize_provider(provider or os.environ.get("AGENT_PROVIDER", "deepseek"))


def provider_config(provider: str) -> dict[str, Any]:
    """取 provider 配置表（先 normalize，非法 provider 抛 ValueError）。"""
    return SUPPORTED_PROVIDERS[normalize_provider(provider)]


def resolve_model(provider: str, model: str | None = None) -> str:
    """Resolve chat model: explicit argument > ``AGENT_MODEL`` > provider default."""
    explicit = (model or "").strip()
    if explicit:
        return explicit
    env_model = os.environ.get("AGENT_MODEL", "").strip()
    if env_model:
        return env_model
    return str(provider_config(provider)["default_model"])


def resolve_api_key(provider: str, api_key: str | None = None) -> str:
    """解析 API key：显式参数 > provider 对应的环境变量。找不到抛 ValueError。"""
    config = provider_config(provider)
    key = api_key or os.environ.get(config["env_key"], "")
    if not key:
        raise ValueError(
            f"未找到 API key。请设置环境变量 {config['env_key']} 或传入 api_key 参数。"
        )
    return key


def detect_provider() -> str | None:
    """探测环境里配了哪个 provider 的 key。

    ``AGENT_PROVIDER`` 显式设置且对应 key 存在时优先（与用户覆盖语义
    一致，和 Web 入口的 load_config() 行为对齐）；否则按声明顺序取
    第一个有 key 的。探测结果必须作为 provider 显式传给 AgentService，
    保证探测链与实际读 key 链一致。
    """
    explicit = os.environ.get("AGENT_PROVIDER", "").strip().lower()
    if explicit in SUPPORTED_PROVIDERS and os.environ.get(SUPPORTED_PROVIDERS[explicit]["env_key"]):
        return explicit
    for name, config in SUPPORTED_PROVIDERS.items():
        if os.environ.get(config["env_key"]):
            return name
    return None


def completion_options(provider: str) -> dict[str, Any]:
    """provider 默认采样参数（temperature 为 None 表示不设置）。"""
    temperature = provider_config(provider)["temperature"]
    return {"temperature": temperature} if temperature is not None else {}


def create_client(
    provider: str,
    api_key: str | None = None,
    *,
    timeout: float = DEFAULT_TIMEOUT,
) -> Any:
    """构造 OpenAI 兼容 client。

    显式 ``timeout``（默认 120s）+ ``max_retries=0``（关闭 SDK 内置重试，
    重试统一由应用层负责，避免双层叠加）。
    """
    from openai import OpenAI

    config = provider_config(provider)
    kwargs: dict[str, Any] = {
        "api_key": resolve_api_key(provider, api_key),
        "timeout": timeout,
        "max_retries": 0,
    }
    if config["base_url"]:
        kwargs["base_url"] = config["base_url"]
    return OpenAI(**kwargs)


def embedding_model_for(provider: str) -> str | None:
    """该 provider 可用的 embedding 模型名；无 OpenAI 兼容 embedding 接口时返回 None。"""
    value = provider_config(provider)["embedding_model"]
    return str(value) if value is not None else None
