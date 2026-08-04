"""主题/产业链数据服务。

工具层（agent tools）和 API 层（web routes）共用，
消除重复的数据读取逻辑。

数据来源：
- data/supply_chains/*.json — 供应链 JSON（半导体/创新药/机器人/材料）
- data/earnings_preview.json — 中报观察列表

ThemeService 的 list_themes / get_theme 不依赖 adapter（只读 JSON），
只有 get_theme_quotes 需要 adapter 拉实时行情。
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any

from mommy_chaogu.market_data.adapter import MarketDataAdapter
from mommy_chaogu.market_data.types import Quote

_log = logging.getLogger(__name__)

# Installed wheels carry the read-only seeds. Source checkouts and Docker can
# still override them with repository-level data assets.
_BUNDLED_DATA_ROOT = Path(__file__).resolve().parents[1] / "bundled_data"

# Tencent supports up to 80 codes per request. Keep a smaller batch size so
# this remains safe when the adapter falls back to another source.
THEME_QUOTE_BATCH_SIZE = 50


def _theme_data_dir() -> Path:
    local = Path("data/supply_chains")
    return local if local.is_dir() else _BUNDLED_DATA_ROOT / "supply_chains"


def _earnings_file() -> Path:
    local = Path("data/earnings_preview.json")
    return local if local.is_file() else _BUNDLED_DATA_ROOT / "earnings_preview.json"


def _load_json(path: Path) -> dict[str, Any]:
    """安全加载 JSON 文件。"""
    try:
        data: dict[str, Any] = json.loads(path.read_text(encoding="utf-8"))
        return data
    except FileNotFoundError:
        _log.warning("theme file not found: %s", path)
        return {}
    except Exception as e:
        _log.warning("failed to load %s: %s", path, e)
        return {}


class ThemeService:
    """主题/产业链数据服务。

    提供三个核心能力：
    - list_themes: 所有主题摘要
    - get_theme: 单个主题详情（含成分股）
    - get_theme_quotes: 主题成分股实时行情（需 adapter）
    """

    def __init__(self, adapter: MarketDataAdapter | None = None) -> None:
        self._adapter = adapter

    # ---------- 内部：加载原始数据 ----------

    def _load_all_themes(self) -> dict[str, dict[str, Any]]:
        """加载所有主题数据，返回 {theme_id: theme_dict}。"""
        themes: dict[str, dict[str, Any]] = {}

        # supply_chains/*.json
        data_dir = _theme_data_dir()
        if data_dir.exists():
            for f in sorted(data_dir.glob("*.json")):
                data = _load_json(f)
                if not data:
                    continue
                meta = data.get("meta", {})
                theme_id = meta.get("id", f.stem)
                stocks = data.get("stocks", [])
                themes[theme_id] = {
                    "id": theme_id,
                    "name": meta.get("name", f.stem),
                    "description": meta.get("description", ""),
                    "subcategories": meta.get("subcategories", []),
                    "chain_positions": meta.get("chain_positions", []),
                    "total_stocks": len(stocks),
                    "stocks": stocks,
                    "source": "supply_chain",
                }

        # earnings_preview.json → 中报观察
        earnings_file = _earnings_file()
        if earnings_file.exists():
            data = _load_json(earnings_file)
            stocks = data.get("stocks", [])
            if stocks:
                themes["earnings_watch"] = {
                    "id": "earnings_watch",
                    "name": "中报观察",
                    "description": data.get("meta", {}).get(
                        "description", "2026 H1 中报高增长观察列表"
                    ),
                    "subcategories": sorted(
                        {s.get("sector", "") for s in stocks if s.get("sector")}
                    ),
                    "chain_positions": [],
                    "total_stocks": len(stocks),
                    "stocks": stocks,
                    "source": "earnings_preview",
                }

        return themes

    # ---------- 对外 API ----------

    def list_themes(self) -> list[dict[str, Any]]:
        """列出所有主题摘要。

        返回每个主题的摘要信息（不含成分股详情）：
        id / name / description / total_stocks / subcategories / source
        """
        themes = self._load_all_themes()
        return [
            {
                "id": t["id"],
                "name": t["name"],
                "description": t["description"],
                "total_stocks": t["total_stocks"],
                "subcategories": t["subcategories"],
                "source": t["source"],
            }
            for t in themes.values()
        ]

    def list_theme_details(self) -> list[dict[str, Any]]:
        """List complete definitions for services that need their members."""
        return list(self._load_all_themes().values())

    def get_theme(self, theme_id: str) -> dict[str, Any] | None:
        """获取主题详情（含成分股）。

        找不到返回 None。
        """
        themes = self._load_all_themes()
        return themes.get(theme_id)

    def get_theme_quotes(self, theme_id: str, limit: int = 100) -> list[dict[str, Any]]:
        """获取主题成分股实时行情。

        返回 canonical 列表，每个 item 包含成分股元数据 + 行情字段。
        行情字段（price/change_pct/volume/turnover_rate/pe/main_net_inflow）
        在 adapter 缺失或拉取失败时为 None；error 字段在异常时填错误信息。

        调用方（工具层 / API 层）各自决定如何序列化这些字段。
        """
        theme = self.get_theme(theme_id)
        if theme is None:
            return []

        stocks = theme["stocks"]
        results: list[dict[str, Any]] = []
        items_by_code: dict[str, list[dict[str, Any]]] = {}

        for stock in stocks[:limit]:
            code = stock.get("code", "")
            if not code:
                continue

            item: dict[str, Any] = {
                "code": code,
                "name": stock.get("name", ""),
                "subcategory": stock.get("subcategory", stock.get("sector", "")),
                "level": stock.get("level", stock.get("chain_position", "")),
                "role": stock.get("role", ""),
                "chain_position": stock.get("chain_position", ""),
                "sector": stock.get("sector", ""),
                "growth_text": stock.get("growth_text", ""),
                "growth_low": stock.get("growth_low"),
                "growth_high": stock.get("growth_high"),
                "core_driver": stock.get("core_driver", ""),
                "highlight": stock.get("highlight", ""),
                # 行情字段，默认 None
                "price": None,
                "change_pct": None,
                "volume": None,
                "turnover_rate": None,
                "pe": None,
                "main_net_inflow": None,
                "error": None,
            }

            items_by_code.setdefault(code, []).append(item)
            results.append(item)

        if self._adapter is None:
            return results

        codes = list(items_by_code)
        quotes_by_code: dict[str, Quote] = {}
        for start in range(0, len(codes), THEME_QUOTE_BATCH_SIZE):
            batch = codes[start : start + THEME_QUOTE_BATCH_SIZE]
            try:
                quotes = self._adapter.get_quotes(batch)
            except Exception as e:
                error = f"批量行情请求失败: {e}"
                for code in batch:
                    for item in items_by_code[code]:
                        item["error"] = error
                _log.warning("theme quotes batch failed (%d codes): %s", len(batch), e)
                continue

            for item_quote in quotes:
                if item_quote.code in items_by_code:
                    quotes_by_code[item_quote.code] = item_quote

            # Batch adapters may skip individual failed codes. Preserve the
            # successful results and expose missing codes as partial failures.
            for code in batch:
                if code not in quotes_by_code:
                    for item in items_by_code[code]:
                        item["error"] = "行情未返回"

        for code, items in items_by_code.items():
            selected_quote = quotes_by_code.get(code)
            if selected_quote is None:
                continue
            for item in items:
                item["price"] = selected_quote.price
                item["change_pct"] = selected_quote.change_pct
                item["volume"] = selected_quote.volume
                item["turnover_rate"] = selected_quote.turnover_rate
                item["pe"] = selected_quote.pe_dynamic
                item["main_net_inflow"] = selected_quote.extra.get("main_net_inflow")

        return results
