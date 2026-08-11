"""setup 模块测试：has_env_file / run_setup_wizard / check_and_run_setup。"""

from __future__ import annotations

import sys
from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from mommy_chaogu.setup import (
    _PROVIDERS,
    _write_env_file,
    build_setup_parser,
    choose_interface,
    configured_interface,
    has_env_file,
    main_setup,
    preferred_setup_env_path,
    run_setup_wizard,
)

if TYPE_CHECKING:
    from collections.abc import Sequence


@pytest.fixture(autouse=True)
def _isolate_setup_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    for info in _PROVIDERS.values():
        monkeypatch.setenv(info["env_key"], "")
    monkeypatch.setenv("AGENT_PROVIDER", "")
    monkeypatch.setenv("AGENT_MODEL", "")
    monkeypatch.setenv("MOMMY_INTERFACE", "")
    monkeypatch.setenv("MOMMY_CONFIG_DIR", str(tmp_path / "user-config"))
    monkeypatch.setenv("MOMMY_CHANNEL_STATE_DIR", str(tmp_path / "channel-state"))


def make_input(answers: Sequence[str]):
    """从列表构造 mock input 函数，依次返回每个答案。"""
    it = iter(answers)

    def _input(_prompt: str) -> str:
        return next(it)

    return _input


# ---------- has_env_file ----------


def test_has_env_file_no_file(tmp_path: Path):
    assert has_env_file(tmp_path / ".env") is False


def test_has_env_file_empty(tmp_path: Path):
    env = tmp_path / ".env"
    env.write_text("", encoding="utf-8")
    assert has_env_file(env) is False


def test_has_env_file_only_comments(tmp_path: Path):
    env = tmp_path / ".env"
    env.write_text(
        "# 这是注释\n\n#DEEPSEEK_API_KEY=sk-xxx\n#AGENT_PROVIDER=deepseek\n",
        encoding="utf-8",
    )
    assert has_env_file(env) is False


def test_has_env_file_with_key(tmp_path: Path):
    env = tmp_path / ".env"
    env.write_text(
        "# 注释\nDEEPSEEK_API_KEY=sk-realtoken\nAGENT_PROVIDER=deepseek\n",
        encoding="utf-8",
    )
    assert has_env_file(env) is True


def test_has_env_file_with_different_provider(tmp_path: Path):
    env = tmp_path / ".env"
    env.write_text("ZAI_API_KEY=abc123\n", encoding="utf-8")
    assert has_env_file(env) is True


def test_has_env_file_ignores_deprecated_provider_key(tmp_path: Path):
    env = tmp_path / ".env"
    env.write_text("NOVA_API_KEY=legacy-placeholder\n", encoding="utf-8")
    assert has_env_file(env) is False


# ---------- run_setup_wizard ----------


def test_wizard_writes_env_deepseek(tmp_path: Path):
    env = tmp_path / ".env"
    result = run_setup_wizard(
        env,
        input_func=make_input(["1", "", "sk-my-deepseek-key"]),
        verify_llm=False,
        offer_weixin=False,
    )
    assert result is True
    content = env.read_text(encoding="utf-8")

    # 选中 provider 取消注释
    assert "DEEPSEEK_API_KEY=sk-my-deepseek-key" in content
    assert "AGENT_PROVIDER=deepseek" in content
    assert "AGENT_MODEL=deepseek-chat" in content

    # 未配置的 provider 不写空占位，避免看起来像待办项。
    assert "OPENAI_API_KEY" not in content
    assert "MOONSHOT_API_KEY" not in content
    assert "ZAI_API_KEY" not in content
    assert content.count("sk-my-deepseek-key") == 1

    assert "SERVER_CHAN_KEY" not in content


def test_wizard_writes_env_zai(tmp_path: Path):
    env = tmp_path / ".env"
    result = run_setup_wizard(
        env,
        input_func=make_input(["4", "glm-5", "zai-token-xyz"]),
        verify_llm=False,
        offer_weixin=False,
    )
    assert result is True
    content = env.read_text(encoding="utf-8")
    assert "ZAI_API_KEY=zai-token-xyz" in content
    assert "DEEPSEEK_API_KEY" not in content
    assert "AGENT_PROVIDER=zai" in content
    assert "AGENT_MODEL=glm-5" in content


def test_wizard_writes_env_minimax_paygo(tmp_path: Path):
    env = tmp_path / ".env"
    result = run_setup_wizard(
        env,
        input_func=make_input(["5", "", "minimax-paygo-key"]),
        verify_llm=False,
        offer_weixin=False,
    )
    assert result is True
    content = env.read_text(encoding="utf-8")
    assert "MINIMAX_API_KEY=minimax-paygo-key" in content
    assert "AGENT_PROVIDER=minimax" in content
    assert "AGENT_MODEL=MiniMax-M3" in content


def test_wizard_saves_selected_interface(tmp_path: Path):
    env = tmp_path / ".env"
    result = run_setup_wizard(
        env,
        input_func=make_input(["1", "", "sk-test", "3"]),
        verify_llm=False,
        offer_weixin=False,
        offer_interface=True,
    )
    assert result is True
    assert "MOMMY_INTERFACE=web" in env.read_text(encoding="utf-8")


def test_choose_interface_defaults_to_cli():
    assert choose_interface(make_input([""])) == "cli"


def test_choose_interface_retries_invalid_choice():
    assert choose_interface(make_input(["9", "2"])) == "tui"


def test_configured_interface_keeps_legacy_default(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("MOMMY_INTERFACE", "unknown")
    assert configured_interface() == "cli"
    monkeypatch.setenv("MOMMY_INTERFACE", "TUI")
    assert configured_interface() == "tui"


def test_wizard_cancel_at_provider(tmp_path: Path):
    """EOFError 视为取消。"""
    env = tmp_path / ".env"

    def _eof(_prompt: str) -> str:
        raise EOFError

    result = run_setup_wizard(env, input_func=_eof)
    assert result is False
    assert not env.exists()


def test_wizard_invalid_choice(tmp_path: Path):
    env = tmp_path / ".env"
    result = run_setup_wizard(env, input_func=make_input(["9"]))
    assert result is False
    assert not env.exists()


def test_wizard_non_numeric_choice(tmp_path: Path):
    env = tmp_path / ".env"
    result = run_setup_wizard(env, input_func=make_input(["abc"]))
    assert result is False


def test_wizard_empty_api_key(tmp_path: Path):
    env = tmp_path / ".env"
    result = run_setup_wizard(
        env,
        input_func=make_input(["1", "", ""]),
        verify_llm=False,
        offer_weixin=False,
    )
    assert result is False


def test_wizard_keyboard_interrupt(tmp_path: Path):
    env = tmp_path / ".env"

    def _interrupt(_prompt: str) -> str:
        raise KeyboardInterrupt

    result = run_setup_wizard(env, input_func=_interrupt)
    assert result is False


# ---------- _write_env_file 单独测试 ----------


def test_write_env_file_contains_only_configured_provider_keys(tmp_path: Path):
    env = tmp_path / ".env"
    _write_env_file(env, "kimi", "moonshot-key")
    content = env.read_text(encoding="utf-8")

    # 新配置只包含选中的 key，不生成其他 provider 的空占位。
    moonshot_lines = [ln for ln in content.splitlines() if "MOONSHOT_API_KEY" in ln]
    assert len(moonshot_lines) == 1
    assert moonshot_lines[0].startswith("MOONSHOT_API_KEY=")
    assert content.count("moonshot-key") == 1
    for name, info in _PROVIDERS.items():
        if name != "kimi":
            assert info["env_key"] not in content


def test_write_env_file_creates_parents(tmp_path: Path):
    env = tmp_path / "nested" / "dir" / ".env"
    _write_env_file(env, "deepseek", "sk-x")
    assert env.is_file()
    assert env.stat().st_mode & 0o777 == 0o600


def test_write_env_file_preserves_unmanaged_and_supported_provider_keys(
    tmp_path: Path,
):
    env = tmp_path / ".env"
    env.write_text(
        "CUSTOM_SETTING=keep\nOPENAI_API_KEY=existing-openai\nSERVER_CHAN_KEY=legacy\n",
        encoding="utf-8",
    )

    _write_env_file(env, "zai", "new-zai", model="glm-5")
    content = env.read_text(encoding="utf-8")

    assert "CUSTOM_SETTING=keep" in content
    assert "OPENAI_API_KEY=existing-openai" in content
    assert "ZAI_API_KEY=new-zai" in content
    assert "SERVER_CHAN_KEY=legacy" in content

    _write_env_file(env, "zai", "newer-zai", model="glm-5")
    rewritten = env.read_text(encoding="utf-8")
    assert rewritten.count("mommy-chaogu managed configuration") == 2
    assert rewritten.count("# mommy-chaogu 密钥配置") == 1
    assert "ZAI_API_KEY=newer-zai" in rewritten
    assert "new-zai" not in rewritten


def test_reconfiguration_removes_deprecated_secrets_and_versions_profile(tmp_path: Path):
    """Migration keeps supported credentials but drops obsolete providers."""
    env = tmp_path / ".env"
    env.write_text(
        "DEEPSEEK_API_KEY=old-deepseek-secret\n"
        "NOVA_API_KEY=obsolete-secret\n"
        "AGENT_PROVIDER=deepseek\n"
        "AGENT_MODEL=deepseek-chat\n",
        encoding="utf-8",
    )

    _write_env_file(env, "zai", "new-zai-secret", model="glm-4.7")
    content = env.read_text(encoding="utf-8")

    assert "ZAI_API_KEY=new-zai-secret" in content
    assert "DEEPSEEK_API_KEY=old-deepseek-secret" in content
    assert "obsolete-secret" not in content
    assert "NOVA_API_KEY" not in content
    assert "MOMMY_CONFIG_VERSION=2" in content
    assert "AGENT_PROVIDER=zai" in content
    assert "AGENT_MODEL=glm-4.7" in content


def test_setup_parser_and_preferred_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.chdir(tmp_path)
    args = build_setup_parser().parse_args(["--local", "--no-verify", "--no-weixin"])
    assert args.local is True
    assert args.no_verify is True
    assert args.no_weixin is True
    user_args = build_setup_parser().parse_args(["--user"])
    assert user_args.user is True
    with pytest.raises(SystemExit):
        build_setup_parser().parse_args(["--local", "--user"])
    assert preferred_setup_env_path() != Path(".env")

    Path(".env.example").write_text("", encoding="utf-8")
    Path(".env").write_text("", encoding="utf-8")
    # A copied/blank template is not an intentional project-scoped profile.
    assert preferred_setup_env_path() != Path(".env")

    Path(".env").write_text("AGENT_PROVIDER=zai\n", encoding="utf-8")
    assert preferred_setup_env_path() == Path(".env")


def test_setup_check_reports_effective_sources_without_exposing_secret(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
):
    user_config = tmp_path / "user-config"
    user_config.mkdir()
    secret = "never-print-this-secret"
    (user_config / ".env").write_text(
        f"AGENT_PROVIDER=zai\nZAI_API_KEY={secret}\n",
        encoding="utf-8",
    )
    (user_config / ".env").chmod(0o600)
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("MOMMY_CONFIG_DIR", str(user_config))
    for key in ("AGENT_PROVIDER", "AGENT_MODEL", "ZAI_API_KEY"):
        monkeypatch.delenv(key)
    monkeypatch.setattr(sys, "argv", ["mommy-setup", "--check"])

    with pytest.raises(SystemExit) as exc_info:
        main_setup()

    assert exc_info.value.code == 0
    output = capsys.readouterr().out
    assert "配置状态：可用" in output
    assert "Provider：zai（用户级配置）" in output
    assert "Model：glm-4.7（Provider 默认）" in output
    assert "API key：ZAI_API_KEY（用户级配置，已设置）" in output
    assert secret not in output


def test_wizard_can_pair_weixin_in_same_flow(tmp_path: Path):
    env = tmp_path / ".env"
    paired: list[bool] = []

    result = run_setup_wizard(
        env,
        input_func=make_input(["4", "glm-5", "zai-key", "y"]),
        verify_llm=False,
        weixin_connector=lambda: paired.append(True) or True,
    )

    assert result is True
    assert paired == [True]
    assert "AGENT_MODEL=glm-5" in env.read_text(encoding="utf-8")


def test_wizard_restarts_online_weixin_after_llm_reconfiguration(tmp_path: Path):
    env = tmp_path / ".env"
    refreshed: list[bool] = []
    paired: list[bool] = []

    result = run_setup_wizard(
        env,
        input_func=make_input(["1", "", "new-deepseek-key"]),
        verify_llm=False,
        weixin_refresher=lambda: refreshed.append(True) or True,
        weixin_connector=lambda: paired.append(True) or True,
    )

    assert result is True
    assert refreshed == [True]
    assert paired == []


def test_wizard_retries_after_failed_validation(tmp_path: Path):
    env = tmp_path / ".env"
    attempts: list[tuple[str, str, str]] = []

    def validate(provider: str, model: str, key: str) -> tuple[bool, str]:
        attempts.append((provider, model, key))
        return (len(attempts) > 1, "连接成功" if len(attempts) > 1 else "API key 无效")

    result = run_setup_wizard(
        env,
        input_func=make_input(["4", "glm-5", "bad-key", "y", "4", "glm-5", "good-key"]),
        offer_weixin=False,
        validator=validate,
    )

    assert result is True
    assert [item[2] for item in attempts] == ["bad-key", "good-key"]
    assert "ZAI_API_KEY=good-key" in env.read_text(encoding="utf-8")
    assert "bad-key" not in env.read_text(encoding="utf-8")


# ---------- check_and_run_setup ----------


def test_check_and_run_setup_skips_when_env_exists(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    env = tmp_path / ".env"
    env.write_text("DEEPSEEK_API_KEY=sk-present\n", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    for key in ("DEEPSEEK_API_KEY", "AGENT_PROVIDER", "AGENT_MODEL"):
        monkeypatch.delenv(key)

    from mommy_chaogu import setup

    # 向导不应该被调用——用会失败的 mock 验证
    monkeypatch.setattr(
        setup, "run_setup_wizard", lambda *a, **kw: pytest.fail("wizard should not run")
    )

    assert setup.check_and_run_setup() is True


def test_check_and_run_setup_runs_wizard(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.chdir(tmp_path)

    from mommy_chaogu import setup

    monkeypatch.setattr(setup, "run_setup_wizard", lambda *a, **kw: True)
    assert setup.check_and_run_setup() is True


def test_check_and_run_setup_repairs_provider_key_mismatch(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    (tmp_path / ".env").write_text(
        "AGENT_PROVIDER=zai\nDEEPSEEK_API_KEY=wrong-provider-key\n",
        encoding="utf-8",
    )
    monkeypatch.chdir(tmp_path)

    from mommy_chaogu import setup

    calls: list[bool] = []
    monkeypatch.setattr(
        setup,
        "run_setup_wizard",
        lambda *a, **kw: calls.append(True) or True,
    )

    assert setup.check_and_run_setup() is True
    assert calls == [True]


def test_check_and_run_setup_accepts_shell_configuration(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setenv("AGENT_PROVIDER", "zai")
    monkeypatch.setenv("ZAI_API_KEY", "shell-key")

    from mommy_chaogu import setup

    monkeypatch.setattr(
        setup, "run_setup_wizard", lambda *a, **kw: pytest.fail("wizard should not run")
    )
    assert setup.check_and_run_setup() is True


def test_check_and_run_setup_declined(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.chdir(tmp_path)

    from mommy_chaogu import setup

    monkeypatch.setattr(setup, "run_setup_wizard", lambda *a, **kw: False)
    assert setup.check_and_run_setup() is False
