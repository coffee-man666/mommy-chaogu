"""数据源工厂：统一构建 fallback 链。

业务层不要直接 ``FallbackAdapter([EfinanceAdapter(), TencentAdapter()])``，
而是调 ``build_default_adapter()``，由这里决定加什么源、顺序怎么排。

未来要加新数据源、调整顺序、改成完全不同的链，都改这一个文件。

链顺序（详见 docs/ADR/akshare-integration）：

1. **EfinanceAdapter** (主源) — 实时 + K 线 + 资金流 + 板块，覆盖最全
2. **TencentAdapter** (兜底 1) — 实时报价的真正异构兜底（东财挂腾讯不一定挂）
3. **AkShareAdapter** (兜底 2) — 字段补全源；和 efinance 同走东财后端，
   但 ``stock_zh_a_spot_em`` 给 PE/PB/市值更稳，K 线是另一个实现路径
   （仅在 akshare 已安装时启用，避免把 100MB 依赖强加给所有人）
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from mommy_chaogu.market_data.adapter import MarketDataAdapter
from mommy_chaogu.market_data.efinance_adapter import EfinanceAdapter
from mommy_chaogu.market_data.fallback_adapter import FallbackAdapter
from mommy_chaogu.market_data.tencent_adapter import TencentAdapter

if TYPE_CHECKING:
    from mommy_chaogu.cache import CacheConfig, CacheStore

_log = logging.getLogger(__name__)


def _akshare_available() -> bool:
    """akshare 是否已安装（避免 import 时把 100MB 依赖强加载给所有人）。"""
    try:
        import akshare  # noqa: F401
    except ImportError:
        return False
    return True


def build_default_adapter(
    *,
    with_cache: bool = False,
    cache_store: CacheStore | None = None,
    cache_config: CacheConfig | None = None,
) -> MarketDataAdapter:
    """构造默认的多源 fallback 适配器。

    顺序：

    1. EfinanceAdapter（主源，实时/K 线/资金流/板块覆盖最全）
    2. TencentAdapter（实时报价的异构兜底）
    3. AkShareAdapter（字段补全 + 备用 K 线；仅 akshare 已安装时启用）

    ``with_cache=True`` 时套一层 CachedMarketDataAdapter。
    """
    # TencentAdapter.get_bars 用 **kw，跟 Protocol 强类型签名不一致（运行时兼容），
    # 与 flows/service.py 同样的处理：用 type: ignore 转一道。
    adapters: list[MarketDataAdapter] = [
        EfinanceAdapter(),
        TencentAdapter(),  # type: ignore[list-item]
    ]

    if _akshare_available():
        from mommy_chaogu.market_data.akshare_adapter import AkShareAdapter

        adapters.append(AkShareAdapter())
        _log.info("data sources: efinance + tencent + akshare")
    else:
        _log.info("data sources: efinance + tencent (akshare not installed)")

    chain = FallbackAdapter(adapters)

    if with_cache:
        # 延迟 import 避免循环依赖
        from mommy_chaogu.cache import CacheStore
        from mommy_chaogu.cache.adapter import CachedMarketDataAdapter
        from mommy_chaogu.db_paths import MARKET_DB

        store = cache_store or CacheStore(MARKET_DB)
        return CachedMarketDataAdapter(chain, store, config=cache_config)  # type: ignore[arg-type]

    return chain  # type: ignore[return-value]
