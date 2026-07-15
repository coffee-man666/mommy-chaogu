"""config 模块测试：load_config / create_default_config / 环境变量覆盖。"""

from __future__ import annotations

from pathlib import Path

import pytest

from mommy_chaogu.config import (
    AppConfig,
    create_default_config,
    load_config,
)

# 所有可能影响测试的 env var
_ENV_KEYS = (
    "DEEPSEEK_API_KEY",
    "OPENAI_API_KEY",
    "MOONSHOT_API_KEY",
    "ZAI_API_KEY",
    "NOVA_API_KEY",
    "SERVER_CHAN_KEY",
    "AGENT_PROVIDER",
)


@pytest.fixture(autouse=True)
def _isolate_env(monkeypatch: pytest.MonkeyPatch):
    """每个测试前清除所有相关 env var，mock 掉 load_dotenv 防止 .env 泄漏。"""
    for key in _ENV_KEYS:
        monkeypatch.delenv(key, raising=False)
    monkeypatch.setattr("mommy_chaogu.config.load_dotenv", lambda *a, **kw: False)


# ---------- 默认值 ----------


def test_load_config_defaults_when_no_file(tmp_path: Path):
    """文件不存在时返回全默认值。"""
    cfg = load_config(tmp_path / "nonexistent.toml")
    assert isinstance(cfg, AppConfig)
    assert cfg.agent.provider == "deepseek"
    assert cfg.agent.max_tool_calls == 10
    assert cfg.cache.quote_fetch_interval_seconds == 300
    assert cfg.monitor.interval_seconds == 30.0
    assert cfg.db_path == "data/market.db"


def test_load_config_reads_toml(tmp_path: Path):
    """能正确读取 TOML 里的自定义值。"""
    toml = tmp_path / "config.toml"
    toml.write_text(
        """
db_path = "custom/data.db"

[agent]
provider = "kimi"
model = "moonshot-v1-8k"
max_tool_calls = 5

[push]
server_chan_key = "toml_key"
web_base_url = "https://mama.example.com"

[cache]
quote_fetch_interval_seconds = 120
""",
        encoding="utf-8",
    )
    cfg = load_config(toml)
    assert cfg.db_path == "custom/data.db"
    assert cfg.agent.provider == "kimi"
    assert cfg.agent.model == "moonshot-v1-8k"
    assert cfg.agent.max_tool_calls == 5
    assert cfg.push.server_chan_key == "toml_key"
    assert cfg.push.web_base_url == "https://mama.example.com"
    assert cfg.cache.quote_fetch_interval_seconds == 120


# ---------- 环境变量覆盖 ----------


@pytest.mark.parametrize(
    "env_key,env_val,attr,expected",
    [
        ("DEEPSEEK_API_KEY", "env_secret", "agent.api_key", "env_secret"),
        ("AGENT_PROVIDER", "openai", "agent.provider", "openai"),
        ("SERVER_CHAN_KEY", "env_sck", "push.server_chan_key", "env_sck"),
    ],
)
def test_env_overrides(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, env_key, env_val, attr, expected
):
    """环境变量覆盖 TOML / 默认值。"""
    toml = tmp_path / "config.toml"
    toml.write_text(
        """
[agent]
provider = "deepseek"
api_key = "toml_key"

[push]
server_chan_key = "toml_sck"
""",
        encoding="utf-8",
    )
    monkeypatch.setenv(env_key, env_val)
    cfg = load_config(toml)

    obj: object = cfg
    for part in attr.split("."):
        obj = getattr(obj, part)
    assert obj == expected


def test_env_override_when_no_file(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """没有 TOML 文件时，环境变量也能生效。"""
    # provider=kimi → 读 MOONSHOT_API_KEY
    monkeypatch.setenv("MOONSHOT_API_KEY", "kimi_env_key")
    monkeypatch.setenv("AGENT_PROVIDER", "kimi")
    cfg = load_config(tmp_path / "missing.toml")
    assert cfg.agent.api_key == "kimi_env_key"
    assert cfg.agent.provider == "kimi"


def test_nova_env_override_when_no_file(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """provider=nova 时从 NOVA_API_KEY 读取 bridge key。"""
    monkeypatch.setenv("NOVA_API_KEY", "dummy")
    monkeypatch.setenv("AGENT_PROVIDER", "nova")
    cfg = load_config(tmp_path / "missing.toml")
    assert cfg.agent.api_key == "dummy"
    assert cfg.agent.provider == "nova"


# ---------- create_default_config ----------


def test_create_default_config(tmp_path: Path):
    """生成的模板能被 load_config 正确读回。"""
    target = tmp_path / "config.toml"
    p = create_default_config(target)
    assert p == target
    assert target.exists()

    cfg = load_config(target)
    # 模板里的值和默认值一致
    assert cfg.agent.provider == "deepseek"
    assert cfg.agent.model == "deepseek-chat"
    assert cfg.agent.max_tool_calls == 10
    assert cfg.cache.quote_fetch_interval_seconds == 300


def test_create_default_config_creates_parent_dirs(tmp_path: Path):
    """父目录不存在时自动创建。"""
    target = tmp_path / "deep" / "nested" / "config.toml"
    create_default_config(target)
    assert target.exists()
