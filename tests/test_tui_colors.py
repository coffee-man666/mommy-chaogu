"""TUI 颜色体系：语义色板单一真相源（colors.py）+ 防 hex 回潮守卫。

背景：清理前 28 个硬编码 hex 散在 7 个文件，全部是 dark 主题专用字面量，
切浅色主题时 Python 侧不跟随（CSS 侧 $text-muted 等 token 会跟随），两套
体系不一致。收口后：widget 一律经 ``color(theme, role)`` 取 chrome 色，
数据红绿（A股涨跌）仍走 ``formatting.change_color``（含色盲映射）。
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import ClassVar

import pytest

from mommy_chaogu.tui.services.colors import (
    LIGHT_BG_THEMES,
    ROLES,
    THEMES,
    color,
)

_TUI_DIR = (Path(__file__).parent.parent / "src" / "mommy_chaogu" / "tui").resolve()


class TestPalette:
    def test_all_roles_exist_for_every_theme(self) -> None:
        for theme in THEMES:
            for role in ROLES:
                value = color(theme, role)
                assert value.startswith("#"), f"{theme}/{role} -> {value}"
                assert len(value) == 7

    def test_light_palettes_differ_from_dark(self) -> None:
        """所有浅底主题必须换深色前景，否则白底不可读。"""
        assert set(LIGHT_BG_THEMES) <= set(THEMES)
        for theme in LIGHT_BG_THEMES:
            diffs = {role for role in ROLES if color(theme, role) != color("dark", role)}
            # 至少 muted/info/success/danger 要换深色变体
            assert {"muted", "info", "success", "danger"} <= diffs, theme

    def test_unknown_role_raises(self) -> None:
        with pytest.raises(KeyError):
            color("dark", "nope")

    def test_unknown_theme_falls_back_to_dark(self) -> None:
        """未知主题（如未来新增未跟上色板）按 dark 渲染，不崩。"""
        assert color("future-theme", "muted") == color("dark", "muted")


class TestNoHexRegression:
    """守卫：tui 源码不得再出现硬编码 chrome hex（colors.py 白名单）。"""

    ALLOWED: ClassVar[frozenset[Path]] = frozenset({_TUI_DIR / "services" / "colors.py"})
    _HEX_RE = re.compile(r"#[0-9a-fA-F]{6}\b")

    def test_no_hex_literals_outside_colors_module(self) -> None:
        offenders: list[str] = []
        for path in sorted(_TUI_DIR.rglob("*.py")):
            if path.resolve() in {a.resolve() for a in self.ALLOWED}:
                continue
            for lineno, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
                if self._HEX_RE.search(line):
                    offenders.append(f"{path.relative_to(_TUI_DIR)}:{lineno}")
        assert offenders == [], "硬编码 hex 应改走 colors.color(theme, role)"
