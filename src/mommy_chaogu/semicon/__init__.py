"""半导体产业链股票参考库。

定位：
- 与 watchlist 分离的「只读参考」库，给妈妈/团长盘前盘后查产业链用
- 一张表 semicon_stocks，按 (chain_position, subcategory) 双维度组织
- chain_position: 上游 / 中游 / 下游 / 末端
- subcategory: EDA / IP / 设备 / 材料 / 存储 / MCU / 处理器 / 模拟 / 射频 / 功率 / 传感器 / FPGA / 制造 / 封测 / 分销
- product: 具体产品（如「介质刻蚀」「NOR Flash」）

不做：
- 不与 watchlist 同步（妈妈可能临时从产业链里捞几只观察，不入自选）
- 不拉实时行情（需要时让用户从 watchlist / monitor 走）
"""
from __future__ import annotations

from mommy_chaogu.semicon.models import SemiconBase, SemiconStock
from mommy_chaogu.semicon.seed import SEED_STOCKS, seed_store
from mommy_chaogu.semicon.store import (
    ChainPosition,
    SemiconStore,
    Subcategory,
)

__all__ = [
    "SEED_STOCKS",
    "ChainPosition",
    "SemiconBase",
    "SemiconStock",
    "SemiconStore",
    "Subcategory",
    "seed_store",
]

