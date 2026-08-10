"""config 模块测试：load_config / create_default_config / 环境变量覆盖。"""

from __future__ import annotations

import os
import re
from pathlib import Path

import pytest

from mommy_chaogu.agent.llm import SUPPORTED_PROVIDERS
from mommy_chaogu.config import (
    AppConfig,
    create_default_config,
    load_config,
    load_runtime_env,
)

# 所有可能影响测试的 env var
_ENV_KEYS = (
    "DEEPSEEK_API_KEY",
    "OPENAI_API_KEY",
    "MOONSHOT_API_KEY",
    "ZAI_API_KEY",
    "MINIMAX_API_KEY",
    "SERVER_CHAN_KEY",
    "AGENT_PROVIDER",
    "AGENT_MODEL",
    "MOMMY_CONFIG_DIR",
    "MOMMY_API_TOKEN",
    "MOMMY_CORS_ORIGINS",
)


@pytest.fixture(autouse=True)
def _isolate_env(monkeypatch: pytest.MonkeyPatch):
    """每个测试前用空 shell 覆盖隔离本机配置文件。"""
    for key in _ENV_KEYS:
        monkeypatch.setenv(key, "")


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
        ("AGENT_MODEL", "gpt-5-mini", "agent.model", "gpt-5-mini"),
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


def test_user_env_is_fallback_when_project_env_missing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    user_config = tmp_path / "user-config"
    user_config.mkdir()
    (user_config / ".env").write_text(
        "AGENT_PROVIDER=zai\nAGENT_MODEL=glm-5\nZAI_API_KEY=user-key\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("MOMMY_CONFIG_DIR", str(user_config))
    monkeypatch.delenv("AGENT_PROVIDER")
    monkeypatch.delenv("AGENT_MODEL")
    monkeypatch.delenv("ZAI_API_KEY")

    monkeypatch.chdir(tmp_path)
    cfg = load_config(tmp_path / "missing.toml")

    assert cfg.agent.provider == "zai"
    assert cfg.agent.model == "glm-5"
    assert cfg.agent.api_key == "user-key"


def test_project_env_overrides_user_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    user_config = tmp_path / "user-config"
    user_config.mkdir()
    (user_config / ".env").write_text(
        "AGENT_PROVIDER=zai\nAGENT_MODEL=glm-5\nZAI_API_KEY=user-key\n",
        encoding="utf-8",
    )
    (tmp_path / ".env").write_text(
        "AGENT_PROVIDER=openai\nAGENT_MODEL=gpt-5-mini\nOPENAI_API_KEY=project-key\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("MOMMY_CONFIG_DIR", str(user_config))
    for key in ("AGENT_PROVIDER", "AGENT_MODEL", "ZAI_API_KEY", "OPENAI_API_KEY"):
        monkeypatch.delenv(key)

    monkeypatch.chdir(tmp_path)
    cfg = load_config(tmp_path / "missing.toml")

    assert cfg.agent.provider == "openai"
    assert cfg.agent.model == "gpt-5-mini"
    assert cfg.agent.api_key == "project-key"


def test_project_provider_without_model_uses_its_default_instead_of_user_model(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    """A project provider selection is an atomic profile boundary.

    A lower-priority user model belongs to the user's provider and must not be
    combined with the project provider.  Missing project models resolve to the
    selected provider's default instead.
    """
    user_config = tmp_path / "user-config"
    user_config.mkdir()
    (user_config / ".env").write_text(
        "AGENT_PROVIDER=deepseek\nAGENT_MODEL=deepseek-v4-flash\nDEEPSEEK_API_KEY=user-key\n",
        encoding="utf-8",
    )
    (tmp_path / ".env").write_text(
        "AGENT_PROVIDER=zai\nZAI_API_KEY=project-key\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("MOMMY_CONFIG_DIR", str(user_config))
    for key in (
        "AGENT_PROVIDER",
        "AGENT_MODEL",
        "DEEPSEEK_API_KEY",
        "ZAI_API_KEY",
    ):
        monkeypatch.delenv(key)

    monkeypatch.chdir(tmp_path)
    cfg = load_config(tmp_path / "missing.toml")

    assert cfg.agent.provider == "zai"
    assert cfg.agent.model == "glm-4.7"
    assert cfg.agent.api_key == "project-key"


def test_runtime_env_reload_replaces_values_injected_by_previous_file(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    """Reconfiguration takes effect in a long-running process."""
    user_config = tmp_path / "user-config"
    user_config.mkdir()
    env_file = user_config / ".env"
    env_file.write_text(
        "AGENT_PROVIDER=deepseek\nAGENT_MODEL=deepseek-chat\nDEEPSEEK_API_KEY=old-key\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("MOMMY_CONFIG_DIR", str(user_config))
    for key in (
        "AGENT_PROVIDER",
        "AGENT_MODEL",
        "DEEPSEEK_API_KEY",
        "ZAI_API_KEY",
    ):
        monkeypatch.delenv(key)

    monkeypatch.chdir(tmp_path)
    load_runtime_env()
    assert os.environ["AGENT_PROVIDER"] == "deepseek"

    env_file.write_text(
        "AGENT_PROVIDER=zai\nZAI_API_KEY=new-key\n",
        encoding="utf-8",
    )
    load_runtime_env()

    assert os.environ["AGENT_PROVIDER"] == "zai"
    assert os.environ["AGENT_MODEL"] == "glm-4.7"
    assert os.environ["ZAI_API_KEY"] == "new-key"


def test_inactive_saved_provider_key_stays_out_of_process_environment(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    (tmp_path / ".env").write_text(
        "AGENT_PROVIDER=deepseek\nDEEPSEEK_API_KEY=active-key\nOPENAI_API_KEY=dormant-key\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)
    for key in (
        "AGENT_PROVIDER",
        "AGENT_MODEL",
        "DEEPSEEK_API_KEY",
        "OPENAI_API_KEY",
    ):
        monkeypatch.delenv(key)

    cfg = load_config(tmp_path / "missing.toml")

    assert cfg.agent.api_key == "active-key"
    assert os.environ["DEEPSEEK_API_KEY"] == "active-key"
    assert "OPENAI_API_KEY" not in os.environ


def test_shell_model_override_is_reported_with_default_provider(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
):
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("AGENT_PROVIDER")
    monkeypatch.setenv("AGENT_MODEL", "deepseek-reasoner")

    status = load_runtime_env()

    assert status.provider == "deepseek"
    assert status.model == "deepseek-reasoner"
    assert status.provider_source == "代码默认"
    assert status.model_source == "Shell 环境变量"


def test_minimax_env_override_when_no_file(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    """provider=minimax 时从 MINIMAX_API_KEY 读取 API key。"""
    monkeypatch.setenv("MINIMAX_API_KEY", "minimax_env_key")
    monkeypatch.setenv("AGENT_PROVIDER", "minimax")
    cfg = load_config(tmp_path / "missing.toml")
    assert cfg.agent.api_key == "minimax_env_key"
    assert cfg.agent.provider == "minimax"


def test_invalid_provider_fails_fast(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    monkeypatch.setenv("AGENT_PROVIDER", "typo-provider")
    with pytest.raises(ValueError, match="Unsupported agent provider"):
        load_config(tmp_path / "missing.toml")


def test_web_security_env_overrides(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    monkeypatch.setenv("MOMMY_API_TOKEN", "owner-secret")
    monkeypatch.setenv("MOMMY_CORS_ORIGINS", "https://one.example.com, https://two.example.com")
    cfg = load_config(tmp_path / "missing.toml")
    assert cfg.web.api_token == "owner-secret"
    assert cfg.web.cors_origins == ["https://one.example.com", "https://two.example.com"]


# ---------- create_default_config ----------


def test_create_default_config(tmp_path: Path):
    """生成的模板能被 load_config 正确读回。"""
    target = tmp_path / "config.toml"
    p = create_default_config(target)
    assert p == target
    assert target.exists()
    content = target.read_text(encoding="utf-8")
    assert "[agent]" not in content
    assert "[cache]" not in content
    assert "[monitor]" not in content
    assert "[push]" not in content
    assert "db_path" not in content
    assert "[web]" in content

    cfg = load_config(target)
    # 高级模板未设置的部分继续使用代码默认值。
    assert cfg.agent.provider == "deepseek"
    assert cfg.agent.model is None
    assert cfg.agent.max_tool_calls == 10
    assert cfg.cache.quote_fetch_interval_seconds == 300


def test_create_default_config_creates_parent_dirs(tmp_path: Path):
    """父目录不存在时自动创建。"""
    target = tmp_path / "deep" / "nested" / "config.toml"
    create_default_config(target)
    assert target.exists()


def test_env_example_matches_supported_llm_profiles():
    """The manual-install template cannot advertise stale providers."""
    root = Path(__file__).resolve().parent.parent
    content = (root / ".env.example").read_text(encoding="utf-8")
    keys = set(re.findall(r"^#?([A-Z][A-Z0-9_]*API_KEY)=", content, re.MULTILINE))
    expected = {str(info["env_key"]) for info in SUPPORTED_PROVIDERS.values()}

    assert keys == expected
    assert "NOVA" not in content
    assert "AGENT_PROVIDER=" in content
    assert "AGENT_MODEL=" in content
    assert "mommy setup" in content
