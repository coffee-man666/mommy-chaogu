"""集中式配置：dataclasses + TOML + .env + 环境变量覆盖。

设计原则：
- config.toml 提供基础值（可 git 提交不含密钥的版本）
- ``.env`` 文件持久化密钥（gitignore 排除，不入仓）
- 环境变量优先级最高（CI / Docker / cron 场景）
- load_config(path=None) 读默认路径 config.toml，文件不存在则返回全默认值

支持的 .env / 环境变量：
    DEEPSEEK_API_KEY  → agent.api_key（provider=deepseek 时）
    OPENAI_API_KEY    → agent.api_key（provider=openai 时）
    MOONSHOT_API_KEY  → agent.api_key（provider=kimi 时）
    ZAI_API_KEY       → agent.api_key（provider=zai 时）
    SERVER_CHAN_KEY   → push.server_chan_key
    AGENT_PROVIDER    → agent.provider
"""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field, fields
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

from mommy_chaogu.db_paths import MARKET_DB

DEFAULT_CONFIG_PATH = Path("config.toml")

# provider → 对应的环境变量名
_PROVIDER_ENV_KEYS: dict[str, str] = {
    "deepseek": "DEEPSEEK_API_KEY",
    "openai": "OPENAI_API_KEY",
    "kimi": "MOONSHOT_API_KEY",
    "zai": "ZAI_API_KEY",
}


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
class AppConfig:
    """顶层配置，聚合所有子配置。"""

    db_path: str = str(MARKET_DB)
    agent: AgentConfig = field(default_factory=AgentConfig)
    push: PushConfig = field(default_factory=PushConfig)
    cache: CacheConfig = field(default_factory=CacheConfig)
    monitor: MonitorConfig = field(default_factory=MonitorConfig)


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
    kimi → MOONSHOT_API_KEY, zai → ZAI_API_KEY。
    """
    env_provider = os.environ.get("AGENT_PROVIDER")
    if env_provider:
        cfg.agent.provider = env_provider

    # 根据当前 provider 取对应 key
    env_key = _PROVIDER_ENV_KEYS.get(cfg.agent.provider, "")
    if env_key:
        val = os.environ.get(env_key, "")
        if val:
            cfg.agent.api_key = val

    env_sck = os.environ.get("SERVER_CHAN_KEY")
    if env_sck:
        cfg.push.server_chan_key = env_sck

    return cfg


def load_config(path: str | Path | None = None) -> AppConfig:
    """读取 .env + config.toml 并叠加环境变量覆盖。

    加载顺序（后者覆盖前者）：
    1. ``.env`` 文件（项目根目录，持久化密钥，不入仓）
    2. ``config.toml``（基础配置）
    3. 环境变量（CI / Docker / cron 场景，优先级最高）

    - path 为 None 时使用默认路径 config.toml
    - 文件不存在不报错，返回全默认值 + 环境变量
    """
    load_dotenv()  # 从 .env 加载，但不覆盖已有的 env var

    config_path = Path(path) if path is not None else DEFAULT_CONFIG_PATH
    data = _load_toml(config_path)

    agent = _build_section(AgentConfig, data.get("agent", {}))
    push = _build_section(PushConfig, data.get("push", {}))
    cache = _build_section(CacheConfig, data.get("cache", {}))
    monitor = _build_section(MonitorConfig, data.get("monitor", {}))

    cfg = AppConfig(
        db_path=data.get("db_path", str(MARKET_DB)),
        agent=agent,  # type: ignore[arg-type]
        push=push,  # type: ignore[arg-type]
        cache=cache,  # type: ignore[arg-type]
        monitor=monitor,  # type: ignore[arg-type]
    )
    return _apply_env_overrides(cfg)


# TOML 模板（create_default_config 写出）
_CONFIG_TEMPLATE = """\
# mommy-chaogu 配置文件
# 密钥配置有两种方式（优先级从高到低）：
#   1. 环境变量（CI / Docker / cron）
#   2. .env 文件（项目根目录，持久化，已 gitignore）
# 根据 provider 自动读取对应的 key：
#   DEEPSEEK_API_KEY  (provider=deepseek)
#   OPENAI_API_KEY    (provider=openai)
#   MOONSHOT_API_KEY  (provider=kimi)
#   ZAI_API_KEY       (provider=zai)
#   SERVER_CHAN_KEY   → push.server_chan_key
#   AGENT_PROVIDER    → agent.provider

db_path = "{market_db}"

[agent]
provider = "deepseek"          # deepseek / openai / kimi / zai
model = "deepseek-chat"        # 留空则用 provider 默认模型
api_key = ""                   # 建议用 .env 或环境变量
max_tool_calls = 10

[push]
server_chan_key = ""           # 建议用 .env 或环境变量
web_base_url = ""              # 推送消息里 K 线链接的前缀

[cache]
quote_fetch_interval_seconds = 300        # 报价拉新间隔（5 分钟）
bar_fetch_interval_seconds = 86400        # K 线拉新间隔（1 天）
market_snapshot_fetch_interval_seconds = 3600  # 全市场快照（1 小时）

[monitor]
interval_seconds = 30.0        # 监控轮询间隔
with_signals = true            # 同时评估告警信号
"""


def create_default_config(path: str | Path) -> Path:
    """把配置模板写到指定路径，返回最终路径。

    如果父目录不存在会自动创建。
    """
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(_CONFIG_TEMPLATE.format(market_db=MARKET_DB), encoding="utf-8")
    return p
