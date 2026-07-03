"""集中式配置：dataclasses + TOML + 环境变量覆盖。

设计原则：
- config.toml 提供基础值（可 git 提交不含密钥的版本）
- 环境变量优先级更高（密钥类配置走 env，不落盘）
- load_config(path=None) 读默认路径 config.toml，文件不存在则返回全默认值
- create_default_config(path) 写一份模板到指定路径

支持的环境变量覆盖：
    DEEPSEEK_API_KEY → agent.api_key
    SERVER_CHAN_KEY  → push.server_chan_key
    AGENT_PROVIDER   → agent.provider
"""
from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field, fields
from pathlib import Path

DEFAULT_CONFIG_PATH = Path("config.toml")


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

    db_path: str = "data/watchlist.db"
    agent: AgentConfig = field(default_factory=AgentConfig)
    push: PushConfig = field(default_factory=PushConfig)
    cache: CacheConfig = field(default_factory=CacheConfig)
    monitor: MonitorConfig = field(default_factory=MonitorConfig)


def _load_toml(path: Path) -> dict:
    """安全读取 TOML，文件不存在返回空 dict。"""
    if not path.exists():
        return {}
    with path.open("rb") as f:
        return tomllib.load(f)


def _build_section(dataclass_type: type, raw: dict) -> object:
    """从 dict 里取出 dataclass 已知字段（忽略多余 key），构造实例。"""
    valid_names = {f.name for f in fields(dataclass_type)}
    filtered = {k: v for k, v in raw.items() if k in valid_names}
    return dataclass_type(**filtered)


def _apply_env_overrides(cfg: AppConfig) -> AppConfig:
    """环境变量覆盖（优先级最高）。"""
    env_key = os.environ.get("DEEPSEEK_API_KEY")
    if env_key:
        cfg.agent.api_key = env_key

    env_sck = os.environ.get("SERVER_CHAN_KEY")
    if env_sck:
        cfg.push.server_chan_key = env_sck

    env_provider = os.environ.get("AGENT_PROVIDER")
    if env_provider:
        cfg.agent.provider = env_provider

    return cfg


def load_config(path: str | Path | None = None) -> AppConfig:
    """读取 config.toml 并叠加环境变量覆盖。

    - path 为 None 时使用默认路径 config.toml
    - 文件不存在不报错，返回全默认值 + 环境变量
    """
    config_path = Path(path) if path is not None else DEFAULT_CONFIG_PATH
    data = _load_toml(config_path)

    agent = _build_section(AgentConfig, data.get("agent", {}))
    push = _build_section(PushConfig, data.get("push", {}))
    cache = _build_section(CacheConfig, data.get("cache", {}))
    monitor = _build_section(MonitorConfig, data.get("monitor", {}))

    cfg = AppConfig(
        db_path=data.get("db_path", "data/watchlist.db"),
        agent=agent,  # type: ignore[arg-type]
        push=push,  # type: ignore[arg-type]
        cache=cache,  # type: ignore[arg-type]
        monitor=monitor,  # type: ignore[arg-type]
    )
    return _apply_env_overrides(cfg)


# TOML 模板（create_default_config 写出）
_CONFIG_TEMPLATE = """\
# mommy-chaogu 配置文件
# 环境变量优先级更高（密钥建议走 env，不要写在这里）：
#   DEEPSEEK_API_KEY → agent.api_key
#   SERVER_CHAN_KEY  → push.server_chan_key
#   AGENT_PROVIDER   → agent.provider

db_path = "data/watchlist.db"

[agent]
provider = "deepseek"          # deepseek / openai / kimi
model = "deepseek-chat"        # 留空则用 provider 默认模型
api_key = ""                   # 建议用环境变量 DEEPSEEK_API_KEY
max_tool_calls = 10

[push]
server_chan_key = ""           # 建议用环境变量 SERVER_CHAN_KEY
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
    p.write_text(_CONFIG_TEMPLATE, encoding="utf-8")
    return p
