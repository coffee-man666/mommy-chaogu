"""数据源工厂：统一构建 fallback 链。

业务层不要直接 ``FallbackAdapter([EfinanceAdapter(), TencentAdapter()])``，
而是调 ``build_default_adapter()``，由这里决定加什么源、顺序怎么排。

未来要加新数据源、调整顺序、改成完全不同的链，都改这一个文件。

链顺序（详见 docs/adr/0002-akshare-integration.md / docs/adr/0003-tushare-integration.md）：

1. **EfinanceAdapter** (主源) — 实时 + K 线 + 资金流 + 板块，覆盖最全
2. **TencentAdapter** (兜底 1) — 实时报价的真正异构兜底（东财挂腾讯不一定挂）
3. **TushareAdapter** (兜底 2) — 海外 IP 友好（阿里云）的金融数据云，
   K 线/资金流/财务三表/分红最强；实时报价是 EOD 合成快照（可能滞后 30 天），
   所以排在腾讯之后，避免截胡真正的实时兜底
   （仅在 ``TUSHARE_TOKEN`` 环境变量配置时启用；Tushare 是付费档数据源）
4. **AkShareAdapter** (兜底 3) — 字段补全源；和 efinance 同走东财后端，
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
    from mommy_chaogu.market_data.tushare_adapter import TushareAdapter

_log = logging.getLogger(__name__)


def _akshare_available() -> bool:
    """akshare 是否已安装（避免 import 时把 100MB 依赖强加载给所有人）。"""
    try:
        import akshare  # noqa: F401
    except ImportError:
        return False
    return True


def _tushare_available() -> tuple[bool, TushareAdapter]:
    """Tushare 是否可用（token 配置且能初始化 pro_api）。

    返回 ``(available, adapter)``：
    - available=True 时 adapter 是可用的 TushareAdapter
    - available=False 时 adapter 是占位的 TushareAdapter 实例（仅供判断）
    """
    from mommy_chaogu.market_data.tushare_adapter import TushareAdapter

    adp = TushareAdapter()
    return adp.is_available, adp


def build_default_adapter(
    *,
    with_cache: bool = False,
    cache_store: CacheStore | None = None,
    cache_config: CacheConfig | None = None,
) -> MarketDataAdapter:
    """构造默认的多源 fallback 适配器。

    顺序：

    1. EfinanceAdapter（主源，实时/K 线/资金流/板块覆盖最全）
    2. TencentAdapter（实时报价的真异构兜底）
    3. TushareAdapter（境外 IP / K 线 / 财务首选；仅 TUSHARE_TOKEN 配置时启用，
       没 token 自动跳过。其 get_quote 是 EOD 合成快照，故排在腾讯之后）
    4. AkShareAdapter（字段补全 + 备用 K 线；仅 akshare 已安装时启用）

    ``with_cache=True`` 时套一层 CachedMarketDataAdapter。
    """
    # 链顺序：efinance → tencent → tushare → akshare
    # - efinance 放最前：国内 IP 实时报价最快、覆盖最全
    # - tencent 第二位：实时报价的真异构兜底（东财挂腾讯不一定挂）
    # - tushare 第三位：境外 IP / K 线 / 财务首选；没 token 时自动跳过；
    #   其 get_quote 是 EOD 快照（可能滞后），不能截胡腾讯的实时兜底
    # - akshare 最末：字段补全源，仅在 akshare 已安装时启用
    # TencentAdapter.get_bars 用 **kw，跟 Protocol 强类型签名不一致（运行时兼容）。
    adapters: list[MarketDataAdapter] = [
        EfinanceAdapter(),
        TencentAdapter(),  # type: ignore[list-item]
    ]

    sources = ["efinance", "tencent"]

    tushare_ok, tushare_adp = _tushare_available()
    if tushare_ok:
        adapters.append(tushare_adp)
        sources.append("tushare")

    if _akshare_available():
        from mommy_chaogu.market_data.akshare_adapter import AkShareAdapter

        adapters.append(AkShareAdapter())
        sources.append("akshare")

    _log.info("data sources: %s", " + ".join(sources))

    chain = FallbackAdapter(adapters)

    if with_cache:
        # 延迟 import 避免循环依赖
        from mommy_chaogu.cache import CacheStore
        from mommy_chaogu.cache.adapter import CachedMarketDataAdapter
        from mommy_chaogu.db_paths import MARKET_DB

        store = cache_store or CacheStore(MARKET_DB)
        return CachedMarketDataAdapter(chain, store, config=cache_config)  # type: ignore[arg-type]

    return chain  # type: ignore[return-value]
