"""首次启动交互式配置引导。

TUI（mommy-tui）首启且无可用 API key 时自动进入本向导；
CLI 用户可随时用 ``mommy setup``（或兼容入口 ``mommy --setup``）手动运行：
1. 选择 LLM provider
2. 选择默认模型并隐藏输入 API key
3. 验证模型连接并写入用户级私有配置
4. 可选扫码连接微信
"""

from __future__ import annotations

import argparse
import getpass
import os
import tempfile
from collections.abc import Callable
from contextlib import suppress
from datetime import datetime
from pathlib import Path

from mommy_chaogu.agent.llm import SUPPORTED_PROVIDERS
from mommy_chaogu.config import default_user_env_path, load_runtime_env

# InputFunc 接受提示语、返回用户输入
InputFunc = Callable[[str], str]
LLMValidator = Callable[[str, str, str], tuple[bool, str]]
WeixinConnector = Callable[[], bool]

_MANAGED_BEGIN = "# >>> mommy-chaogu managed configuration >>>"
_MANAGED_END = "# <<< mommy-chaogu managed configuration <<<"

_PROVIDER_DETAILS: dict[str, dict[str, str]] = {
    "deepseek": {
        "label": "DeepSeek (推荐，性价比高)",
        "hint": "去 platform.deepseek.com 注册获取",
    },
    "openai": {
        "label": "OpenAI / 兼容接口",
        "hint": "填入 OpenAI API key",
    },
    "kimi": {
        "label": "Kimi / Moonshot",
        "hint": "去 platform.moonshot.cn 注册获取",
    },
    "zai": {
        "label": "z.ai / GLM",
        "hint": "去 open.bigmodel.cn 注册获取",
    },
    "nova": {
        "label": "Nova Bridge (本地)",
        "hint": "先启动 localhost:9999 的 Nova Bridge，key 可为任意非空值",
    },
    "minimax": {
        "label": "MiniMax（国内 OpenAI 兼容接口）",
        "hint": "去 platform.minimaxi.com 获取 API key",
    },
}

_PROVIDERS: dict[str, dict[str, str]] = {
    name: {
        **details,
        "env_key": str(SUPPORTED_PROVIDERS[name]["env_key"]),
        "default_model": str(SUPPORTED_PROVIDERS[name]["default_model"]),
    }
    for name, details in _PROVIDER_DETAILS.items()
}


def preferred_setup_env_path() -> Path:
    """Update an existing project config; otherwise use the user-level config."""
    local_env = Path(".env")
    if local_env.is_file() and Path(".env.example").is_file():
        return local_env
    return default_user_env_path()


def has_env_file(env_path: Path) -> bool:
    """检查 .env 是否存在且至少含一行非注释的 API key。"""
    if not env_path.is_file():
        return False
    for line in env_path.read_text(encoding="utf-8").splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        if "=" not in stripped:
            continue
        key = stripped.split("=", 1)[0].strip()
        if "API_KEY" in key:
            return True
    return False


def _safe_input(input_func: InputFunc, prompt: str) -> str | None:
    """包装 input()，捕获 EOFError / KeyboardInterrupt，返回 None 表示取消。"""
    try:
        return input_func(prompt)
    except (EOFError, KeyboardInterrupt):
        return None


def _ask_yes_no(input_func: InputFunc, prompt: str, *, default: bool) -> bool | None:
    suffix = "(Y/n)" if default else "(y/N)"
    answer = _safe_input(input_func, f"{prompt} {suffix}：")
    if answer is None:
        return None
    normalized = answer.strip().lower()
    if not normalized:
        return default
    return normalized in {"y", "yes", "是"}


def validate_llm_connection(provider: str, model: str, api_key: str) -> tuple[bool, str]:
    """Make one tiny completion so onboarding catches bad keys and model names."""
    from mommy_chaogu.agent import llm

    try:
        client = llm.create_client(provider, api_key)
        response = client.chat.completions.create(
            model=model,
            messages=[{"role": "user", "content": "Reply with OK."}],
            max_tokens=8,
        )
        if not getattr(response, "choices", None):
            return False, "模型服务没有返回有效响应"
        return True, "连接成功"
    except Exception as exc:
        message = str(exc).lower()
        if "authentication" in message or "401" in message:
            return False, "API key 无效或已失效"
        if "model" in message and any(word in message for word in ("not", "invalid", "不存在")):
            return False, f"模型 {model} 不可用"
        if "rate" in message or "429" in message:
            return False, "模型服务限流，请稍后重试"
        return False, f"连接失败（{type(exc).__name__}）"


def connect_weixin() -> bool:
    """Run the existing QR login flow and persist authorization locally."""
    from mommy_chaogu.channels import WeixinClient, WeixinStore
    from mommy_chaogu.cli_commands.channel import _login

    _login(WeixinStore(), WeixinClient())
    return True


def run_setup_wizard(
    env_path: Path | None = None,
    input_func: InputFunc = input,
    *,
    secret_input_func: InputFunc | None = None,
    verify_llm: bool = True,
    offer_weixin: bool = True,
    validator: LLMValidator = validate_llm_connection,
    weixin_connector: WeixinConnector = connect_weixin,
) -> bool:
    """Run the unified LLM + optional Weixin onboarding wizard."""
    if env_path is None:
        env_path = preferred_setup_env_path()
    if secret_input_func is None:
        # Tests and embedding callers that provide their own input function keep
        # one deterministic input stream; real terminals use hidden input.
        secret_input_func = getpass.getpass if input_func is input else input_func

    provider_keys = list(_PROVIDERS.keys())

    print("\n🚀 欢迎使用 mommy-chaogu！")
    print("接下来会配置 AI 模型，并可选连接微信。配置只保存在你的设备上。\n")

    while True:
        # --- 1. 选择 provider ---
        print("请选择 LLM Provider：")
        for idx, name in enumerate(provider_keys, 1):
            info = _PROVIDERS[name]
            print(f"  {idx}. {info['label']}（默认模型 {info['default_model']}）")
        print()

        choice = _safe_input(input_func, f"请输入序号 (1-{len(provider_keys)})，或 Ctrl-C 退出：")
        if choice is None:
            return False
        try:
            idx = int(choice.strip())
            if not 1 <= idx <= len(provider_keys):
                print(f"无效序号: {choice}")
                return False
        except ValueError:
            print(f"无效输入: {choice}")
            return False

        provider = provider_keys[idx - 1]
        info = _PROVIDERS[provider]
        print(f"\n✅ 已选择 {info['label']}")
        print(f"   提示：{info['hint']}")

        # --- 2. 选择模型 ---
        model_input = _safe_input(
            input_func,
            f"模型名（回车使用 {info['default_model']}，也可填写兼容模型）：",
        )
        if model_input is None:
            return False
        model = model_input.strip() or info["default_model"]

        # --- 3. 隐藏输入 API key ---
        api_key_raw = _safe_input(secret_input_func, "API key（输入不会显示）：")
        if api_key_raw is None:
            return False
        api_key = api_key_raw.strip()
        if not api_key:
            print("API key 不能为空。")
            return False

        if verify_llm:
            print(f"\n⠹ 正在验证 {provider} / {model}...")
            valid, detail = validator(provider, model, api_key)
            if valid:
                print(f"✅ {detail}")
                break
            print(f"❌ {detail}")
            retry = _ask_yes_no(input_func, "重新配置 LLM？", default=True)
            if retry:
                print()
                continue
            return False
        break

    # --- 4. 私密写入配置并让当前进程立即可用 ---
    _write_env_file(env_path, provider, api_key, model=model)
    os.environ[str(info["env_key"])] = api_key
    os.environ["AGENT_PROVIDER"] = provider
    os.environ["AGENT_MODEL"] = model
    print(f"\n✅ AI 配置已保存：{provider} / {model}")
    print(f"   私有配置文件：{env_path.resolve()}")

    # --- 5. 微信扫码（可选）---
    if offer_weixin:
        pair_weixin = _ask_yes_no(input_func, "\n现在连接微信？", default=True)
        if pair_weixin:
            try:
                weixin_connector()
            except Exception as exc:
                print(f"⚠️ 微信连接暂未完成（{type(exc).__name__}），AI 配置已经保存。")
                print("   稍后运行 `mommy channel weixin login` 可继续扫码。")

    print("\n🎉 配置完成！")
    print("   mommy                         打开交互式助手")
    print("   mommy channel weixin run      启动微信助手\n")
    return True


def _write_env_file(
    env_path: Path,
    provider: str,
    api_key: str,
    *,
    model: str | None = None,
) -> None:
    """Merge managed settings into a private env file without duplicating secrets."""
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    existing_lines: list[str] = []
    with suppress(FileNotFoundError):
        existing_lines = env_path.read_text(encoding="utf-8").splitlines()

    managed_keys = {
        *(info["env_key"] for info in _PROVIDERS.values()),
        "AGENT_PROVIDER",
        "AGENT_MODEL",
        "SERVER_CHAN_KEY",
    }
    active_values: dict[str, str] = {}
    preserved: list[str] = []
    in_managed_block = False
    for line in existing_lines:
        stripped = line.strip()
        if stripped == _MANAGED_BEGIN:
            in_managed_block = True
            continue
        if stripped == _MANAGED_END:
            in_managed_block = False
            continue
        candidate = stripped[1:].strip() if stripped.startswith("#") else stripped
        key = candidate.split("=", 1)[0].strip() if "=" in candidate else ""
        if key in managed_keys:
            if not stripped.startswith("#") and "=" in stripped:
                active_values[key] = stripped.split("=", 1)[1]
            continue
        if in_managed_block:
            continue
        preserved.append(line)

    while preserved and not preserved[-1].strip():
        preserved.pop()

    selected_env_key = _PROVIDERS[provider]["env_key"]
    active_values[selected_env_key] = api_key
    resolved_model = (model or _PROVIDERS[provider]["default_model"]).strip()

    lines = [*preserved]
    if lines:
        lines.append("")
    lines.extend(
        [
            _MANAGED_BEGIN,
            "# mommy-chaogu 密钥配置（由首次启动向导生成）",
            f"# 生成时间: {now}",
            "",
            "# LLM Provider",
        ]
    )
    for info in _PROVIDERS.values():
        env_key = info["env_key"]
        value = active_values.get(env_key, "")
        lines.append(f"{env_key}={value}" if value else f"#{env_key}=")

    lines.append("")
    lines.append(f"AGENT_PROVIDER={provider}")
    lines.append(f"AGENT_MODEL={resolved_model}")

    # Server酱不再属于新用户 onboarding；旧配置若已有 key，仅无损保留。
    if active_values.get("SERVER_CHAN_KEY"):
        lines.append("")
        lines.append(f"SERVER_CHAN_KEY={active_values['SERVER_CHAN_KEY']}")

    lines.append(_MANAGED_END)
    lines.append("")

    env_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    with suppress(OSError):
        os.chmod(env_path.parent, 0o700)
    fd, temp_name = tempfile.mkstemp(prefix=f".{env_path.name}.", dir=env_path.parent)
    temp_path = Path(temp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write("\n".join(lines))
        os.chmod(temp_path, 0o600)
        os.replace(temp_path, env_path)
    finally:
        with suppress(FileNotFoundError):
            temp_path.unlink()


def check_and_run_setup() -> bool:
    """Start onboarding when neither project-local nor user config is usable."""
    load_runtime_env()
    from mommy_chaogu.config import load_config

    try:
        if load_config().agent.api_key:
            return True
    except ValueError:
        # An invalid provider is recoverable through onboarding.
        pass
    env_paths = (Path(".env"), default_user_env_path())

    if any(has_env_file(path) for path in env_paths):
        return True

    print("\n⚠️ 未检测到可用的 AI 配置，将启动首次配置向导。")
    print("   稍后也可运行 `mommy setup` 重新配置。\n")

    completed = run_setup_wizard()
    if completed:
        return True

    print("\n💡 已跳过配置，将在无 AI 功能模式下运行。")
    print("   稍后可手动编辑 .env 或重新启动向导。\n")
    return False


def build_setup_parser() -> argparse.ArgumentParser:
    """Build the standalone onboarding command parser."""
    parser = argparse.ArgumentParser(
        prog="mommy-setup",
        description="配置 AI Provider、模型、API key 和微信连接",
    )
    parser.add_argument(
        "--local",
        action="store_true",
        help="写入当前目录 .env，而不是用户级私有配置",
    )
    parser.add_argument("--no-verify", action="store_true", help="跳过 LLM 连通性验证")
    parser.add_argument("--no-weixin", action="store_true", help="跳过微信扫码步骤")
    return parser


def main_setup() -> None:
    """Standalone ``mommy setup`` / ``mommy-setup`` entry point."""
    args = build_setup_parser().parse_args()
    env_path = Path(".env") if args.local else preferred_setup_env_path()
    completed = run_setup_wizard(
        env_path,
        verify_llm=not args.no_verify,
        offer_weixin=not args.no_weixin,
    )
    raise SystemExit(0 if completed else 1)
