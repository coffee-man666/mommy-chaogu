"""TUI 语义色板：chrome 颜色的单一真相源，随 ui_theme 切换。

与 CSS 的分工：``styles.tcss`` 用 Textual 主题 token（``$text-muted`` /
``$accent`` / ``$warning``，随 textual-dark/light 自动切换）；本模块服务
Python 侧的 inline markup。**数据红绿（A股涨跌）不在这里**——走
``formatting.change_color``（含色盲映射，深浅主题由 CSS token 管）。

色板约定：
- ``dark`` / ``colorblind`` / ``nord`` / ``atom`` / ``github`` / ``dracula`` /
  ``tokyo``：深底亮字。colorblind 的 chrome 色沿用 dark——这里的色表达的是
  UI 语义（允许/拒绝/警告），不是涨跌数据。
- ``light`` / ``solarized`` / ``latte`` / ``github-light``：白底需要更深的
  前景色，否则对比度不可读。
"""

from __future__ import annotations

from typing import Any

from textual.theme import Theme

THEMES = (
    "dark",
    "light",
    "colorblind",
    "solarized",
    "nord",
    "latte",
    "atom",
    "github",
    "github-light",
    "dracula",
    "tokyo",
)

# 浅底主题：前景必须用深色变体（守卫测试据此校验）
LIGHT_BG_THEMES = ("light", "solarized", "latte", "github-light")

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
    # Atom One Dark（Atom 编辑器经典）：深蓝灰底 #282c34，One 色系
    "atom": {
        "info": "#61afef",
        "success": "#98c379",
        "danger": "#e06c75",
        "warning": "#e5c07b",
        "muted": "#828997",
        "thinking": "#c678dd",
    },
    # GitHub Dark（Primer dark）：近黑底 #0d1117
    "github": {
        "info": "#58a6ff",
        "success": "#3fb950",
        "danger": "#f85149",
        "warning": "#d29922",
        "muted": "#8b949e",
        "thinking": "#bc8cff",
    },
    # GitHub Light（Primer light）：纯白底；与 light 色板同源（GitHub Primer light）
    "github-light": {
        "info": "#0969da",
        "success": "#1a7f37",
        "danger": "#cf222e",
        "warning": "#9a6700",
        "muted": "#57606a",
        "thinking": "#8250df",
    },
    # Dracula：紫黑底 #282a36，高饱和 Dracula 色板
    "dracula": {
        "info": "#8be9fd",
        "success": "#50fa7b",
        "danger": "#ff5555",
        "warning": "#f1fa8c",
        "muted": "#6272a4",
        "thinking": "#bd93f9",
    },
    # Tokyo Night：深蓝紫底 #1a1b26，VS Code 热门配色
    "tokyo": {
        "info": "#7aa2f7",
        "success": "#9ece6a",
        "danger": "#f7768e",
        "warning": "#e0af68",
        "muted": "#565f89",
        "thinking": "#bb9af7",
    },
}
_PALETTES["colorblind"] = _PALETTES["dark"]

# GitHub Primer 官方配色（textual 无内置，app.py on_mount 时注册）。
# chrome 色板见上面 github / github-light；这里补齐 textual 主题的
# 背景/表面/主色，让 CSS token 跟随官方观感。
GITHUB_TEXTUAL_THEMES: tuple[Theme, ...] = (
    Theme(
        name="mommy-github-dark",
        primary="#58a6ff",
        secondary="#bc8cff",
        accent="#f0883e",
        warning="#d29922",
        error="#f85149",
        success="#3fb950",
        foreground="#e6edf3",
        background="#0d1117",
        surface="#161b22",
        panel="#21262d",
        dark=True,
    ),
    Theme(
        name="mommy-github-light",
        primary="#0969da",
        secondary="#8250df",
        accent="#bc4c00",
        warning="#9a6700",
        error="#cf222e",
        success="#1a7f37",
        foreground="#24292f",
        background="#ffffff",
        surface="#f6f8fa",
        panel="#f6f8fa",
        dark=False,
    ),
)


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
