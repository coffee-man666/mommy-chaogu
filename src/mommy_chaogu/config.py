"""集中式配置：受管 LLM profile + 可选高级 TOML + 环境变量覆盖。

设计原则：
- ``mommy setup`` 原子管理 provider / model / 对应 key
- 用户级或项目 ``.env`` 持久化私密 profile（gitignore 排除，不入仓）
- config.toml 仅提供可选、非敏感的高级 Web 参数；旧字段兼容读取
- 环境变量优先级最高（CI / Docker / cron 场景）
- provider / model 按来源成组解析，禁止跨配置层拼接

支持的 .env / 环境变量：
    DEEPSEEK_API_KEY  → agent.api_key（provider=deepseek 时）
    OPENAI_API_KEY    → agent.api_key（provider=openai 时）
    MOONSHOT_API_KEY  → agent.api_key（provider=kimi 时）
    ZAI_API_KEY       → agent.api_key（provider=zai 时）
    MINIMAX_API_KEY   → agent.api_key（provider=minimax 时）
    SERVER_CHAN_KEY   → push.server_chan_key
    AGENT_PROVIDER    → agent.provider
    AGENT_MODEL       → agent.model
    MOMMY_API_TOKEN   → web.api_token
    MOMMY_CORS_ORIGINS → web.cors_origins（逗号分隔）
"""

from __future__ import annotations

import os
import threading
import tomllib
from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import Any

from dotenv import dotenv_values

from mommy_chaogu.agent.llm import SUPPORTED_PROVIDERS as _LLM_PROVIDERS
from mommy_chaogu.agent.llm import normalize_provider as validate_agent_provider
from mommy_chaogu.db_paths import MARKET_DB

DEFAULT_CONFIG_PATH = Path("config.toml")

_RUNTIME_ENV_LOCK = threading.RLock()
_RUNTIME_FILE_VALUES: dict[str, str] = {}


def default_user_config_dir() -> Path:
    """Return the per-user configuration directory used by installed CLIs."""
    override = os.environ.get("MOMMY_CONFIG_DIR", "").strip()
    if override:
        return Path(override).expanduser()
    return Path.home() / ".config" / "mommy-chaogu"


def default_user_env_path() -> Path:
    """Return the private user-level env file populated by onboarding."""
    return default_user_config_dir() / ".env"


@dataclass(frozen=True, slots=True)
class RuntimeEnvStatus:
    """Safe, redacted description of the effective LLM environment."""

    provider: str
    model: str
    provider_source: str
    model_source: str
    api_key_env: str
    api_key_source: str
    configured: bool
    warnings: tuple[str, ...] = ()


def load_runtime_env() -> RuntimeEnvStatus:
    """Load runtime files with reload-safe, source-aware precedence.

    Precedence is shell > project ``.env`` > user ``.env``. Values previously
    injected by this function are detached before every load, so editing or
    deleting a file takes effect in long-running processes instead of becoming
    permanently stuck in ``os.environ``.

    ``AGENT_PROVIDER`` and ``AGENT_MODEL`` are resolved as one profile. A file
    that selects a provider but omits its model receives that provider's
    default; a model from a lower-priority file is never borrowed.
    """
    with _RUNTIME_ENV_LOCK:
        shell_values = dict(os.environ)
        for key, previous in tuple(_RUNTIME_FILE_VALUES.items()):
            if os.environ.get(key) == previous:
                os.environ.pop(key, None)
                shell_values.pop(key, None)
        _RUNTIME_FILE_VALUES.clear()

        local_env = Path(".env")
        local_values = {
            key: str(value) for key, value in dotenv_values(local_env).items() if value is not None
        }
        user_env = default_user_env_path()
        user_values: dict[str, str] = {}
        if user_env.absolute() != local_env.absolute():
            user_values = {
                key: str(value)
                for key, value in dotenv_values(user_env).items()
                if value is not None
            }

        # General settings merge field-by-field. Provider/model are excluded
        # and handled atomically below. Only the selected provider key is
        # injected into the process; other saved credentials remain dormant.
        merged_file_values = {**user_values, **local_values}
        provider_env_keys = {str(info["env_key"]) for info in _LLM_PROVIDERS.values()}
        for key, value in merged_file_values.items():
            if (
                key in {"AGENT_PROVIDER", "AGENT_MODEL"}
                or key in provider_env_keys
                or key in shell_values
            ):
                continue
            os.environ[key] = value
            _RUNTIME_FILE_VALUES[key] = value

        shell_provider_present = "AGENT_PROVIDER" in shell_values
        shell_provider = shell_values.get("AGENT_PROVIDER", "").strip()
        shell_model = shell_values.get("AGENT_MODEL", "").strip()
        profile_provider = ""
        profile_model = ""
        provider_source = "代码默认"
        model_source = "Provider 默认"
        if shell_provider_present:
            profile_provider = shell_provider
            profile_model = shell_model
            provider_source = "Shell 环境变量"
            model_source = "Shell 环境变量" if shell_model else "Provider 默认"
        elif str(local_values.get("AGENT_PROVIDER", "")).strip():
            profile_provider = local_values["AGENT_PROVIDER"].strip()
            profile_model = shell_model or local_values.get("AGENT_MODEL", "").strip()
            provider_source = "项目 .env"
            model_source = (
                "Shell 环境变量"
                if shell_model
                else "项目 .env"
                if local_values.get("AGENT_MODEL", "").strip()
                else "Provider 默认"
            )
        elif str(user_values.get("AGENT_PROVIDER", "")).strip():
            profile_provider = user_values["AGENT_PROVIDER"].strip()
            profile_model = shell_model or user_values.get("AGENT_MODEL", "").strip()
            provider_source = "用户级配置"
            model_source = (
                "Shell 环境变量"
                if shell_model
                else "用户级配置"
                if user_values.get("AGENT_MODEL", "").strip()
                else "Provider 默认"
            )
        elif shell_model:
            # A model-only shell override intentionally customizes the code
            # default provider. File-based orphan models remain ignored.
            profile_model = shell_model
            model_source = "Shell 环境变量"

        normalized = profile_provider.lower()
        warnings: list[str] = []
        if profile_provider:
            if "AGENT_PROVIDER" not in shell_values:
                os.environ["AGENT_PROVIDER"] = normalized
                _RUNTIME_FILE_VALUES["AGENT_PROVIDER"] = normalized
            if normalized in _LLM_PROVIDERS and "AGENT_MODEL" not in shell_values:
                resolved_model = profile_model or str(_LLM_PROVIDERS[normalized]["default_model"])
                os.environ["AGENT_MODEL"] = resolved_model
                _RUNTIME_FILE_VALUES["AGENT_MODEL"] = resolved_model
            elif normalized not in _LLM_PROVIDERS:
                warnings.append(f"不支持的 Provider：{profile_provider}")

        effective_provider = normalized or "deepseek"
        provider_info = _LLM_PROVIDERS.get(effective_provider)
        effective_model = profile_model
        api_key_env = ""
        if provider_info is not None:
            effective_model = effective_model or str(provider_info["default_model"])
            api_key_env = str(provider_info["env_key"])

        api_key_source = "未设置"
        api_key_present = False
        if api_key_env:
            if shell_values.get(api_key_env, ""):
                api_key_source = "Shell 环境变量"
                api_key_present = True
            elif local_values.get(api_key_env, "") and api_key_env not in shell_values:
                api_key_source = "项目 .env"
                api_key_present = True
            elif user_values.get(api_key_env, "") and api_key_env not in shell_values:
                api_key_source = "用户级配置"
                api_key_present = True
            if api_key_present and api_key_env not in shell_values:
                selected_key = local_values.get(api_key_env) or user_values.get(api_key_env)
                if selected_key:
                    os.environ[api_key_env] = selected_key
                    _RUNTIME_FILE_VALUES[api_key_env] = selected_key

        for path, values, label in (
            (local_env, local_values, "项目 .env"),
            (user_env, user_values, "用户级配置"),
        ):
            has_secret = any(
                value and (key.endswith("API_KEY") or key in {"MOMMY_API_TOKEN", "SERVER_CHAN_KEY"})
                for key, value in values.items()
            )
            if has_secret and path.is_file() and path.stat().st_mode & 0o077:
                warnings.append(f"{label} 权限过宽；请设置为 0600：{path}")

        if local_values.get("AGENT_MODEL") and not local_values.get("AGENT_PROVIDER"):
            warnings.append("项目 .env 的 AGENT_MODEL 没有同层 Provider，已忽略")
        if user_values.get("AGENT_MODEL") and not user_values.get("AGENT_PROVIDER"):
            warnings.append("用户级配置的 AGENT_MODEL 没有同层 Provider，已忽略")

        return RuntimeEnvStatus(
            provider=effective_provider,
            model=effective_model,
            provider_source=provider_source,
            model_source=model_source,
            api_key_env=api_key_env,
            api_key_source=api_key_source,
            configured=api_key_present,
            warnings=tuple(warnings),
        )


# provider → 对应的环境变量名（单一真相源在 agent/llm.py，这里派生）
_PROVIDER_ENV_KEYS: dict[str, str] = {
    name: str(cfg["env_key"]) for name, cfg in _LLM_PROVIDERS.items()
}
SUPPORTED_AGENT_PROVIDERS = tuple(_PROVIDER_ENV_KEYS)


@dataclass
class AgentConfig:
    """LLM agent 配置。"""

    provider: str = "deepseek"
    model: str | None = None
    api_key: str = ""
    max_tool_calls: int = 10


@dataclass
class PushConfig:
    """微信推送（Server酱）配置。"""

    server_chan_key: str = ""
    web_base_url: str = ""


@dataclass
class CacheConfig:
    """缓存拉新间隔配置（秒）。"""

    quote_fetch_interval_seconds: int = 300
    bar_fetch_interval_seconds: int = 86400
    market_snapshot_fetch_interval_seconds: int = 3600


@dataclass
class MonitorConfig:
    """行情监控轮询配置。"""

    interval_seconds: float = 30.0
    max_iterations: int | None = None
    with_signals: bool = True


@dataclass
class WebConfig:
    """Web security and browser-access configuration."""

    api_token: str = ""
    cors_origins: list[str] = field(default_factory=list)
    ws_ticket_ttl_seconds: int = 60
    agent_max_concurrency: int = 2
    session_retention_days: int = 30


@dataclass
class AppConfig:
    """顶层配置，聚合所有子配置。"""

    db_path: str = str(MARKET_DB)
    agent: AgentConfig = field(default_factory=AgentConfig)
    push: PushConfig = field(default_factory=PushConfig)
    cache: CacheConfig = field(default_factory=CacheConfig)
    monitor: MonitorConfig = field(default_factory=MonitorConfig)
    web: WebConfig = field(default_factory=WebConfig)


def _load_toml(path: Path) -> dict[str, Any]:
    """安全读取 TOML，文件不存在返回空 dict。"""
    if not path.exists():
        return {}
    with path.open("rb") as f:
        return tomllib.load(f)


def _build_section(dataclass_type: type, raw: dict[str, Any]) -> object:
    """从 dict 里取出 dataclass 已知字段（忽略多余 key），构造实例。"""
    valid_names = {f.name for f in fields(dataclass_type)}
    filtered = {k: v for k, v in raw.items() if k in valid_names}
    return dataclass_type(**filtered)


def _apply_env_overrides(cfg: AppConfig) -> AppConfig:
    """环境变量覆盖（优先级最高）。

    根据 provider 自动选择对应的 env var 读 key：
    deepseek → DEEPSEEK_API_KEY, openai → OPENAI_API_KEY,
    kimi → MOONSHOT_API_KEY, zai → ZAI_API_KEY,
    minimax → MINIMAX_API_KEY。
    """
    env_provider = os.environ.get("AGENT_PROVIDER")
    if env_provider:
        cfg.agent.provider = env_provider

    cfg.agent.provider = validate_agent_provider(cfg.agent.provider)

    env_model = os.environ.get("AGENT_MODEL", "").strip()
    if env_model:
        cfg.agent.model = env_model

    # 根据当前 provider 取对应 key
    env_key = _PROVIDER_ENV_KEYS.get(cfg.agent.provider, "")
    if env_key:
        val = os.environ.get(env_key, "")
        if val:
            cfg.agent.api_key = val

    env_sck = os.environ.get("SERVER_CHAN_KEY")
    if env_sck:
        cfg.push.server_chan_key = env_sck

    env_api_token = os.environ.get("MOMMY_API_TOKEN")
    if env_api_token:
        cfg.web.api_token = env_api_token

    env_cors = os.environ.get("MOMMY_CORS_ORIGINS")
    if env_cors is not None:
        cfg.web.cors_origins = [origin.strip() for origin in env_cors.split(",") if origin.strip()]

    return cfg


def load_config(path: str | Path | None = None) -> AppConfig:
    """读取受管环境 profile + 可选 config.toml。

    生效优先级：shell > 项目 ``.env`` > 用户级 ``.env`` > 代码默认。
    Provider 和 model 在每一层作为同一个 profile 解析；高优先级层只
    指定 Provider 时使用它的默认模型，不继承低优先级层的 model。

    ``config.toml`` 现在只推荐配置高级 Web 参数。为兼容旧安装，仍会
    读取其中已存在的 legacy 字段，但新模板不再生成 LLM/cache 等配置。

    - path 为 None 时使用默认路径 config.toml
    - 文件不存在不报错，返回全默认值 + 环境变量
    """
    load_runtime_env()

    config_path = Path(path) if path is not None else DEFAULT_CONFIG_PATH
    data = _load_toml(config_path)

    agent = _build_section(AgentConfig, data.get("agent", {}))
    push = _build_section(PushConfig, data.get("push", {}))
    cache = _build_section(CacheConfig, data.get("cache", {}))
    monitor = _build_section(MonitorConfig, data.get("monitor", {}))
    web = _build_section(WebConfig, data.get("web", {}))

    cfg = AppConfig(
        db_path=data.get("db_path", str(MARKET_DB)),
        agent=agent,  # type: ignore[arg-type]
        push=push,  # type: ignore[arg-type]
        cache=cache,  # type: ignore[arg-type]
        monitor=monitor,  # type: ignore[arg-type]
        web=web,  # type: ignore[arg-type]
    )
    return _apply_env_overrides(cfg)


# 可选高级 TOML 模板（create_default_config 写出）。
# LLM profile 和密钥统一由 ``mommy setup`` 管理，不在这里重复配置。
_CONFIG_TEMPLATE = """\
# mommy-chaogu 可选高级配置
# 日常安装与模型配置请运行：mommy setup
# 本文件不保存 Provider、模型或任何密钥。

[web]
# 远程认证密钥使用 MOMMY_API_TOKEN 环境变量。
# cors_origins 也可由 MOMMY_CORS_ORIGINS（逗号分隔）覆盖。
cors_origins = []
ws_ticket_ttl_seconds = 60
agent_max_concurrency = 2
session_retention_days = 30
"""


def create_default_config(path: str | Path) -> Path:
    """把配置模板写到指定路径，返回最终路径。

    如果父目录不存在会自动创建。
    """
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(_CONFIG_TEMPLATE, encoding="utf-8")
    return p
