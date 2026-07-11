"""首次启动交互式配置引导。

当用户没有 .env 文件时，mommy 会启动这个向导：
1. 选择 LLM provider
2. 输入对应的 API key
3. 写入 .env 文件
"""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from pathlib import Path

# InputFunc 接受提示语、返回用户输入
InputFunc = Callable[[str], str]

_PROVIDERS: dict[str, dict[str, str]] = {
    "deepseek": {
        "label": "DeepSeek (推荐，性价比高)",
        "env_key": "DEEPSEEK_API_KEY",
        "hint": "去 platform.deepseek.com 注册获取",
    },
    "openai": {
        "label": "OpenAI / 兼容接口",
        "env_key": "OPENAI_API_KEY",
        "hint": "填入 OpenAI API key",
    },
    "kimi": {
        "label": "Kimi / Moonshot",
        "env_key": "MOONSHOT_API_KEY",
        "hint": "去 platform.moonshot.cn 注册获取",
    },
    "zai": {
        "label": "z.ai / GLM",
        "env_key": "ZAI_API_KEY",
        "hint": "去 open.bigmodel.cn 注册获取",
    },
}


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


def run_setup_wizard(
    env_path: Path | None = None,
    input_func: InputFunc = input,
) -> bool:
    """运行首次配置向导，成功写入 .env 返回 True，用户取消返回 False。"""
    if env_path is None:
        env_path = Path(".env")

    provider_keys = list(_PROVIDERS.keys())

    print("\n🚀 欢迎使用 mommy-chaogu！")
    print("首次启动需要配置 LLM API key，整个过程不到 1 分钟。\n")

    # --- 1. 选择 provider ---
    print("请选择 LLM provider：")
    for idx, name in enumerate(provider_keys, 1):
        print(f"  {idx}. {_PROVIDERS[name]['label']}")
    print()

    choice = _safe_input(input_func, "请输入序号 (1-4)，或 Ctrl-C 跳过：")
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
    print(f"   提示：{info['hint']}\n")

    # --- 2. 输入 API key ---
    api_key = _safe_input(input_func, "请输入 API key：")
    if api_key is None:
        return False
    api_key = api_key.strip()
    if not api_key:
        print("API key 不能为空。")
        return False

    # --- 3. Server酱（可选）---
    server_chan_key: str | None = None
    ans = _safe_input(input_func, "\n是否配置 Server酱 微信推送？(y/N)：")
    if ans is not None and ans.strip().lower() in {"y", "yes"}:
        sck = _safe_input(input_func, "请输入 SERVER_CHAN_KEY：")
        if sck is not None and sck.strip():
            server_chan_key = sck.strip()

    # --- 4. 写入 .env ---
    _write_env_file(env_path, provider, api_key, server_chan_key)
    print(f"\n✅ 配置已写入 {env_path.resolve()}")
    print("现在可以运行 `uv run mommy` 开始使用了！\n")
    return True


def _write_env_file(
    env_path: Path,
    provider: str,
    api_key: str,
    server_chan_key: str | None,
) -> None:
    """生成 .env 文件内容：选中的 provider 取消注释，其余保持注释。"""
    now = datetime.now().strftime("%Y-%m-%d %H:%M")
    lines: list[str] = [
        "# mommy-chaogu 密钥配置（由首次启动向导生成）",
        f"# 生成时间: {now}",
        "",
        "# LLM Provider",
    ]
    for name, info in _PROVIDERS.items():
        line = f"{info['env_key']}={api_key}"
        if name != provider:
            line = f"#{line}"
        lines.append(line)

    lines.append("")
    lines.append(f"AGENT_PROVIDER={provider}")

    lines.append("")
    lines.append("# Server酱 微信推送")
    if server_chan_key:
        lines.append(f"SERVER_CHAN_KEY={server_chan_key}")
    else:
        lines.append("#SERVER_CHAN_KEY=SCTxxxxxxxxxxxxxxxxxxxxxxxx")

    lines.append("")

    env_path.parent.mkdir(parents=True, exist_ok=True)
    env_path.write_text("\n".join(lines), encoding="utf-8")


def check_and_run_setup() -> bool:
    """启动时检查 .env，缺失则运行向导。返回 True 表示有可用配置。"""
    env_path = Path(".env")

    if has_env_file(env_path):
        return True

    print("\n⚠️  未检测到 .env 配置文件，将启动首次配置向导。")
    print("   （或手动运行：cp .env.example .env）\n")

    completed = run_setup_wizard(env_path)
    if completed:
        return True

    print("\n💡 已跳过配置，将在无 AI 功能模式下运行。")
    print("   稍后可手动编辑 .env 或重新启动向导。\n")
    return False
