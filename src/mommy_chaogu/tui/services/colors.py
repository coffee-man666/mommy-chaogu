"""TUI 语义色板：chrome 颜色的单一真相源，随 ui_theme 切换。

与 CSS 的分工：``styles.tcss`` 用 Textual 主题 token（``$text-muted`` /
``$accent`` / ``$warning``，随 textual-dark/light 自动切换）；本模块服务
Python 侧的 inline markup。**数据红绿（A股涨跌）不在这里**——走
``formatting.change_color``（含色盲映射，深浅主题由 CSS token 管）。

色板约定：
- ``dark`` / ``colorblind`` / ``nord``：深底亮字。colorblind 的 chrome 色沿用
  dark——这里的色表达的是 UI 语义（允许/拒绝/警告），不是涨跌数据。
- ``light`` / ``solarized`` / ``latte``：白底需要更深的前景色，否则对比度不可读。
"""

from __future__ import annotations

from typing import Any

THEMES = ("dark", "light", "colorblind", "solarized", "nord", "latte")

# 浅底主题：前景必须用深色变体（守卫测试据此校验）
LIGHT_BG_THEMES = ("light", "solarized", "latte")

ROLES = ("info", "success", "danger", "warning", "muted", "thinking")

_PALETTES: dict[str, dict[str, str]] = {
    "dark": {
        "info": "#79b8ff",  # 活动圈点 / 选中高亮 / 会话放行
        "success": "#2f9e6e",  # 已允许 / 保存成功
        "danger": "#e5484d",  # 错误 / 已拒绝
        "warning": "#f5a524",  # 确认条 / 重试 / 提示
        "muted": "#8a8f98",  # 次要信息 / 摘要 / 回执
        "thinking": "#a371f7",  # 思考块
    },
    "light": {
        "info": "#0969da",
        "success": "#1a7f37",
        "danger": "#cf222e",
        "warning": "#9a6700",
        "muted": "#57606a",
        "thinking": "#8250df",
    },
    # Solarized Light（日光）：暖白底 #fdf6e3，按 Solarized 色系加深保证对比度
    "solarized": {
        "info": "#268bd2",
        "success": "#5c7a10",
        "danger": "#cb2b28",
        "warning": "#9a6700",
        "muted": "#657b83",
        "thinking": "#5b53a8",
    },
    # Nord（极夜）：冷色深底 #2e3440，前景取 Nord 亮色阶
    "nord": {
        "info": "#88c0d0",
        "success": "#a3be8c",
        "danger": "#bf616a",
        "warning": "#ebcb8b",
        "muted": "#8792a8",
        "thinking": "#b48ead",
    },
    # Catppuccin Latte（拿铁）：暖浅底 #eff1f5，按 Latte 色系加深
    "latte": {
        "info": "#1e66f5",
        "success": "#2f7d1f",
        "danger": "#d20f39",
        "warning": "#9a6700",
        "muted": "#626379",
        "thinking": "#8839ef",
    },
}
_PALETTES["colorblind"] = _PALETTES["dark"]


def current_theme() -> str:
    """当前 App 的 ui_theme；无 App 上下文（纯函数/测试）回退 dark。"""
    try:
        # active_app 是公开 ContextVar 但不在 textual.app 的显式导出里，
        # strict mypy 需要定点 ignore（同 chat.py 对 action_cycle_theme 的处理）。
        from textual.app import active_app  # type: ignore[attr-defined]

        app: Any = active_app.get()
        return str(getattr(app, "ui_theme", "dark"))
    except Exception:
        return "dark"


def color(theme: str, role: str) -> str:
    """按主题取语义色。未知主题回退 dark，未知角色直接 KeyError。"""
    return _PALETTES.get(theme, _PALETTES["dark"])[role]
