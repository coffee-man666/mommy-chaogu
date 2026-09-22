"""工具表面镜像防漂移测试（评审 F3/F5 的回归闸）。

工具表面（schema 正则 + 展示标签）曾在多处手抄并实际漂移：
- ``codes.py`` 立了代码正则单一真相源后，agent/tools 里 19 处 DEFS 仍是
  手抄旧式（不收 BRK.B），同一个 MCP server 的 research_stock 与 get_quote
  对同一输入给出两种答案；
- TUI ``TOOL_DISPLAY_NAMES`` 注释自称「覆盖全部工具」实缺 5 个，web 侧
  缺 12 个。

本文件把两条纪律焊死：
1. DEFS 里 code/codes 的 pattern 必须直接引用 ``codes.py`` 常量
   （canonical / A 股收窄变体二选一），禁止再手抄正则字符串；
2. TUI 与 web 的展示标签表必须覆盖 registry 的全部工具——新工具上线
   漏配标签直接红灯，而不是静默 fallback 到英文名。
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

import mommy_chaogu.agent.tools as tools_pkg
from mommy_chaogu.agent.tools.base import ToolContext
from mommy_chaogu.agent.tools.registry import ToolRegistry
from mommy_chaogu.codes import (
    A_SHARE_CODE_PATTERN,
    INDEX_OR_STOCK_CODE_PATTERN,
    STOCK_CODE_PATTERN,
)
from mommy_chaogu.market_data.massive_adapter import MassiveAdapter
from mommy_chaogu.tui.widgets.tool_indicator import TOOL_DISPLAY_NAMES as TUI_LABELS

REPO_ROOT = Path(__file__).resolve().parent.parent

_DOMAINS = (
    "alerts",
    "analysis",
    "backtest",
    "bars",
    "flows",
    "holdings",
    "intel",
    "memory",
    "quote",
    "sector",
    "strategies",
    "themes",
)

_ALLOWED_PATTERNS = {
    STOCK_CODE_PATTERN: "STOCK_CODE_PATTERN",
    INDEX_OR_STOCK_CODE_PATTERN: "INDEX_OR_STOCK_CODE_PATTERN",
    A_SHARE_CODE_PATTERN: "A_SHARE_CODE_PATTERN",
}


def _all_defs() -> list[tuple[str, dict[str, object]]]:
    """(tool_name, parameters) 全集。"""
    result: list[tuple[str, dict[str, object]]] = []
    for domain in _DOMAINS:
        defs = getattr(tools_pkg, domain).DEFS
        for tool in defs:
            result.append((tool.name, tool.parameters))
    return result


class TestDefsPatternsDerivedFromCodes:
    """F3 元测试：code/codes 的 pattern 必须由 codes.py 常量生成。"""

    def test_every_code_pattern_is_a_codes_constant(self) -> None:
        offenders: list[str] = []
        for name, params in _all_defs():
            assert isinstance(params, dict)
            props = params.get("properties", {})
            assert isinstance(props, dict)
            for key in ("code", "codes"):
                spec = props.get(key)
                if not isinstance(spec, dict) or "pattern" not in spec:
                    continue
                pattern = spec["pattern"]
                if pattern not in _ALLOWED_PATTERNS:
                    offenders.append(f"{name}.{key}: {pattern!r}")
        assert not offenders, (
            "DEFS 里出现手抄正则（必须 import codes.py 常量，宽窄二选一：\n"
            f"canonical={STOCK_CODE_PATTERN!r} / {INDEX_OR_STOCK_CODE_PATTERN!r}，"
            f"A 股收窄={A_SHARE_CODE_PATTERN!r}）:\n" + "\n".join(offenders)
        )

    def test_wide_tools_accept_brk_b(self) -> None:
        """宽面工具（行情/公告/基本面/策略卡）接受带后缀美股代码。"""
        wide = {
            "get_quote",
            "get_quotes",
            "get_bars",
            "backfill_history",
            "get_announcements",
            "get_fundamentals",
            "strategy_prepare_application",
        }
        patterns: dict[str, str] = {}
        for name, params in _all_defs():
            if name not in wide:
                continue
            props = params.get("properties", {})
            assert isinstance(props, dict)
            spec = props.get("code") or props.get("codes")
            assert isinstance(spec, dict), f"{name} 无 code/codes 参数"
            pattern = spec.get("pattern") or spec.get("items", {}).get("pattern")
            assert isinstance(pattern, str)
            patterns[name] = pattern
        assert set(patterns) == wide
        assert re.match(patterns["get_quote"], "BRK.B")
        assert re.match(patterns["get_bars"], "BF-B")
        assert re.match(patterns["get_announcements"], "AAPL")
        assert re.match(patterns["strategy_prepare_application"], "BRK.B")

    def test_a_share_only_tools_reject_us_letters(self) -> None:
        """A 股特有域（资金流/业绩催化/金叉/主力筛选/信号回放）诚实收窄。"""
        narrow = {
            "get_money_flow_today",
            "get_money_flow_history",
            "check_earnings_catalyst",
            "check_kline_signal",
            "screen_inflow_stocks",
            "run_backtest",
        }
        found = 0
        for name, params in _all_defs():
            if name not in narrow:
                continue
            found += 1
            props = params.get("properties", {})
            assert isinstance(props, dict)
            spec = props.get("code") or props.get("codes")
            assert isinstance(spec, dict)
            pattern = spec.get("pattern") or spec.get("items", {}).get("pattern")
            assert pattern == A_SHARE_CODE_PATTERN, f"{name} 应为 A 股收窄正则"
            assert re.match(pattern, "AAPL") is None, f"{name} 不应放行美股字母"
        assert found == len(narrow)


class TestDisplayLabelMirrors:
    """F5 完备性断言：TUI / web 标签表覆盖 registry 全部工具。"""

    @pytest.fixture()
    def registry_names(self) -> set[str]:
        registry = ToolRegistry(ToolContext(adapter=MassiveAdapter()))
        return {d["function"]["name"] for d in registry.definitions()}

    def test_tui_labels_cover_all_tools(self, registry_names: set[str]) -> None:
        missing = registry_names - set(TUI_LABELS)
        assert not missing, f"TUI TOOL_DISPLAY_NAMES 缺标签: {sorted(missing)}"

    def test_web_labels_cover_all_tools(self, registry_names: set[str]) -> None:
        source = (REPO_ROOT / "web" / "src" / "lib" / "toolNames.ts").read_text(encoding="utf-8")
        block = re.search(r"TOOL_DISPLAY_NAMES[^=]*=\s*\{(.*?)\}", source, re.S)
        assert block is not None, "web toolNames.ts 结构变化，找不到表体"
        web_names = set(re.findall(r"(\w+):", block.group(1)))
        missing = registry_names - web_names
        assert not missing, f"web toolNames.ts 缺标签: {sorted(missing)}"
