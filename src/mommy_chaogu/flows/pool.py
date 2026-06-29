"""PoolSource：资金流要监控的「股票池」抽象。

为什么需要这个：
- 旧 monitor 写死了「从 watchlist 拉」——但产业链研究需要拉 106 只
- 把「拉哪几只」做成可插拔的：watchlist / semicon / 自定义 codes
- 上层 FlowService 只跟 PoolSource 接口打交道，不耦合具体数据源
"""
from __future__ import annotations

from pathlib import Path
from typing import Protocol


class PoolSource(Protocol):
    """股票池接口。任何提供 codes() 的对象都算。"""

    @property
    def name(self) -> str:
        """池子标识，用于日志/CLI 展示。"""
        ...

    def codes(self) -> list[str]:
        """返回去重后的股票代码列表。"""
        ...

    def describe(self) -> str:
        """人类可读的一行描述。"""
        ...


class WatchlistPool:
    """自选股池（mommy-chaogu 自选股表）。"""

    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path

    @property
    def name(self) -> str:
        return "watchlist"

    def codes(self) -> list[str]:
        from mommy_chaogu.watchlist import WatchlistStore
        store = WatchlistStore(self._db_path)
        return store.get_all_codes()

    def describe(self) -> str:
        codes = self.codes()
        return f"watchlist ({len(codes)} 只自选股, db={self._db_path})"


class SemiconPool:
    """半导体产业链池（mommy-chaogu.semicon 表）。"""

    def __init__(self, db_path: Path) -> None:
        self._db_path = db_path

    @property
    def name(self) -> str:
        return "semicon"

    def codes(self) -> list[str]:
        from mommy_chaogu.semicon import SemiconStore
        store = SemiconStore(self._db_path)
        return store.list_codes()

    def describe(self) -> str:
        codes = self.codes()
        return f"semicon ({len(codes)} 只产业链股, db={self._db_path})"


class CustomPool:
    """用户手动指定的 codes 列表（CLI --codes）。"""

    def __init__(self, codes: list[str]) -> None:
        # 保留顺序去重
        seen: set[str] = set()
        self._codes: list[str] = []
        for c in codes:
            c = c.strip()
            if c and c not in seen:
                seen.add(c)
                self._codes.append(c)

    @property
    def name(self) -> str:
        return "custom"

    def codes(self) -> list[str]:
        return list(self._codes)

    def describe(self) -> str:
        return f"custom ({len(self._codes)} 只手动指定)"


def build_pool(name: str, db_path: Path, custom_codes: list[str] | None = None) -> PoolSource:
    """工厂：根据 name 构造 pool。

    Args:
        name: "watchlist" | "semicon" | "custom"
        db_path: watchlist.db / semicon.db 等
        custom_codes: name="custom" 时必填
    """
    if name == "watchlist":
        return WatchlistPool(db_path)
    if name == "semicon":
        return SemiconPool(db_path)
    if name == "custom":
        if not custom_codes:
            raise ValueError("custom pool 需要 --codes 参数")
        return CustomPool(custom_codes)
    raise ValueError(f"未知 pool: {name!r}，可选 watchlist/semicon/custom")
