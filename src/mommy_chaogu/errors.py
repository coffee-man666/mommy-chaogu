"""错误文案友好映射（入口层共享）。

底层异常（openai / requests / sqlite）的英文堆栈不直接糊用户一脸，
映射成妈妈能看懂的中文提示。CLI 单发 / CLI REPL / TUI chat 的错误
路径共用这一个入口——放在包根是因为 tui/__init__ 会连带导入 Textual，
CLI 不应为了一条错误文案背上 GUI 依赖。
"""

from __future__ import annotations


def friendly_error(error: object) -> str:
    """把异常/错误消息映射为人话。

    - 401 / Unauthorized → API key 无效，请重新运行配置向导
    - 429 / RateLimit → 限流，请稍后再试
    - quota / insufficient → 额度用完，请检查账户余额
    - timeout / 超时 → 网络超时，请稍后重试
    - connection → 网络连接失败，请检查网络
    - 其他 → 原文首行（截断 120 字）兜底
    """
    text = str(error)
    low = text.lower()
    if (
        "401" in text
        or "unauthorized" in low
        or "authentication" in low
        or "invalid api key" in low
    ):
        return "API key 无效，请运行 mommy setup 重新配置"
    if "429" in text or "rate limit" in low or "ratelimit" in low or "限流" in text:
        return "请求被限流，请稍后再试"
    if "quota" in low or "insufficient" in low:
        return "API 额度已用完，请检查账户余额"
    if "timeout" in low or "timed out" in low or "超时" in text:
        return "网络超时，请稍后重试"
    if "connection" in low or "连接失败" in text or "无法连接" in text:
        return "网络连接失败，请检查网络"
    first_line = text.strip().splitlines()[0] if text.strip() else "未知错误"
    return f"出错了：{first_line[:120]}"
