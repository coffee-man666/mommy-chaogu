"""setup 模块测试：has_env_file / run_setup_wizard / check_and_run_setup。"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from mommy_chaogu.setup import (
    _PROVIDERS,
    _write_env_file,
    build_setup_parser,
    has_env_file,
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

    # 其余 provider 保持注释
    assert "#OPENAI_API_KEY=" in content
    assert "#MOONSHOT_API_KEY=" in content
    assert "#ZAI_API_KEY=" in content
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
    assert "#DEEPSEEK_API_KEY=" in content
    assert "AGENT_PROVIDER=zai" in content
    assert "AGENT_MODEL=glm-5" in content


def test_wizard_writes_env_nova(tmp_path: Path):
    env = tmp_path / ".env"
    result = run_setup_wizard(
        env,
        input_func=make_input(["5", "", "dummy"]),
        verify_llm=False,
        offer_weixin=False,
    )
    assert result is True
    content = env.read_text(encoding="utf-8")
    assert "NOVA_API_KEY=dummy" in content
    assert "AGENT_PROVIDER=nova" in content


def test_wizard_writes_env_minimax_paygo(tmp_path: Path):
    env = tmp_path / ".env"
    result = run_setup_wizard(
        env,
        input_func=make_input(["6", "", "minimax-paygo-key"]),
        verify_llm=False,
        offer_weixin=False,
    )
    assert result is True
    content = env.read_text(encoding="utf-8")
    assert "MINIMAX_API_KEY=minimax-paygo-key" in content
    assert "AGENT_PROVIDER=minimax" in content
    assert "AGENT_MODEL=MiniMax-M3" in content


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


def test_write_env_file_all_providers_present(tmp_path: Path):
    env = tmp_path / ".env"
    _write_env_file(env, "kimi", "moonshot-key")
    content = env.read_text(encoding="utf-8")

    # 所有 provider 的 env key 都应出现（选中或注释）
    for info in _PROVIDERS.values():
        assert info["env_key"] in content

    # 恰好一行无注释（选中的），其余 provider 只保留空占位，不复制 key
    moonshot_lines = [ln for ln in content.splitlines() if "MOONSHOT_API_KEY" in ln]
    assert len(moonshot_lines) == 1
    assert moonshot_lines[0].startswith("MOONSHOT_API_KEY=")
    assert content.count("moonshot-key") == 1


def test_write_env_file_creates_parents(tmp_path: Path):
    env = tmp_path / "nested" / "dir" / ".env"
    _write_env_file(env, "deepseek", "sk-x")
    assert env.is_file()
    assert env.stat().st_mode & 0o777 == 0o600


def test_write_env_file_preserves_unmanaged_and_existing_provider_keys(tmp_path: Path):
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
    assert content.count("OPENAI_API_KEY=") == 1

    _write_env_file(env, "zai", "newer-zai", model="glm-5")
    rewritten = env.read_text(encoding="utf-8")
    assert rewritten.count("mommy-chaogu managed configuration") == 2
    assert rewritten.count("# mommy-chaogu 密钥配置") == 1
    assert "ZAI_API_KEY=newer-zai" in rewritten
    assert "new-zai" not in rewritten


def test_setup_parser_and_preferred_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.chdir(tmp_path)
    args = build_setup_parser().parse_args(["--local", "--no-verify", "--no-weixin"])
    assert args.local is True
    assert args.no_verify is True
    assert args.no_weixin is True
    assert preferred_setup_env_path() != Path(".env")

    Path(".env.example").write_text("", encoding="utf-8")
    Path(".env").write_text("", encoding="utf-8")
    assert preferred_setup_env_path() == Path(".env")


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
