"""setup 模块测试：has_env_file / run_setup_wizard / check_and_run_setup。"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

import pytest

from mommy_chaogu.setup import (
    _PROVIDERS,
    _write_env_file,
    has_env_file,
    run_setup_wizard,
)

if TYPE_CHECKING:
    from collections.abc import Sequence


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
        input_func=make_input(["1", "sk-my-deepseek-key", "n"]),
    )
    assert result is True
    content = env.read_text(encoding="utf-8")

    # 选中 provider 取消注释
    assert "DEEPSEEK_API_KEY=sk-my-deepseek-key" in content
    assert "AGENT_PROVIDER=deepseek" in content

    # 其余 provider 保持注释
    assert "#OPENAI_API_KEY=sk-my-deepseek-key" in content
    assert "#MOONSHOT_API_KEY=sk-my-deepseek-key" in content
    assert "#ZAI_API_KEY=sk-my-deepseek-key" in content

    # 没配置 Server酱，保持注释
    assert "#SERVER_CHAN_KEY" in content
    assert "SERVER_CHAN_KEY=" not in content.split("\n")  # 不会出现无注释版本


def test_wizard_writes_env_zai(tmp_path: Path):
    env = tmp_path / ".env"
    result = run_setup_wizard(
        env,
        input_func=make_input(["4", "zai-token-xyz", "n"]),
    )
    assert result is True
    content = env.read_text(encoding="utf-8")
    assert "ZAI_API_KEY=zai-token-xyz" in content
    assert "#DEEPSEEK_API_KEY=zai-token-xyz" in content
    assert "AGENT_PROVIDER=zai" in content


def test_wizard_writes_env_nova(tmp_path: Path):
    env = tmp_path / ".env"
    result = run_setup_wizard(
        env,
        input_func=make_input(["5", "dummy", "n"]),
    )
    assert result is True
    content = env.read_text(encoding="utf-8")
    assert "NOVA_API_KEY=dummy" in content
    assert "AGENT_PROVIDER=nova" in content


def test_wizard_with_server_chan(tmp_path: Path):
    env = tmp_path / ".env"
    result = run_setup_wizard(
        env,
        input_func=make_input(["1", "sk-key", "y", "SCT-my-sck"]),
    )
    assert result is True
    content = env.read_text(encoding="utf-8")
    assert "SERVER_CHAN_KEY=SCT-my-sck" in content


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
    result = run_setup_wizard(env, input_func=make_input(["1", "", "n"]))
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
    _write_env_file(env, "kimi", "moonshot-key", None)
    content = env.read_text(encoding="utf-8")

    # 所有 provider 的 env key 都应出现（选中或注释）
    for info in _PROVIDERS.values():
        assert info["env_key"] in content

    # 恰好一行无注释（选中的），三行带注释（其余）
    moonshot_lines = [ln for ln in content.splitlines() if "MOONSHOT_API_KEY" in ln]
    assert len(moonshot_lines) == 1
    assert moonshot_lines[0].startswith("MOONSHOT_API_KEY=")


def test_write_env_file_creates_parents(tmp_path: Path):
    env = tmp_path / "nested" / "dir" / ".env"
    _write_env_file(env, "deepseek", "sk-x", None)
    assert env.is_file()


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


def test_check_and_run_setup_declined(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.chdir(tmp_path)

    from mommy_chaogu import setup

    monkeypatch.setattr(setup, "run_setup_wizard", lambda *a, **kw: False)
    assert setup.check_and_run_setup() is False
