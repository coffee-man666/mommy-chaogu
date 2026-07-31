"""market_data 工具函数：跨 adapter 共用。

目前包含：
- `detect_market`: 根据 6 位代码头推断市场类型（沪深北）

放在这里是为了避免在每个 adapter 里复制粘贴（之前 efinance 和 tushare 两边都写
一遍，且都有漏掉北交所的 bug）。
"""

from __future__ import annotations

from mommy_chaogu.market_data.types import MarketType

# A 股代码前缀规则（按出现频率排序，靠前的先匹配）
# 参考：
# - 沪 A 主板：60xxxx, 601xxx, 603xxx, 605xxx
# - 沪 A 科创板：688xxx, 689xxx
# - 深 A 主板：000xxx, 001xxx, 002xxx, 003xxx
# - 深 A 创业板：300xxx, 301xxx
# - 北 A（北交所）：83xxxx, 87xxxx, 88xxxx, 92xxxx（新）
#               40xxxx, 42xxxx, 43xxxx（老三板）
# - 沪基金/债券：51xxxx, 56xxxx, 15xxxx, 16xxxx, 18xxxx
# - 深基金/债券：10xxxx, 11xxxx, 12xxxx, 13xxxx, 14xxxx
# 注：本函数只做"股票/基金"的市场归属判断，更细的品种分类（QuoteType）由 adapter 处理

# 北交所代码前缀（独立最优先，避免被其它规则误匹配）
_BJ_PREFIXES: tuple[str, ...] = ("83", "87", "88", "92", "40", "42", "43")

# 上证（SH）股票/基金/债券前缀
_SH_STOCK_PREFIXES: tuple[str, ...] = ("60", "68")  # 主板 + 科创板
_SH_FUND_BOND_PREFIXES: tuple[str, ...] = ("51", "56", "15", "16", "18")

# 深证（SZ）股票/基金/债券前缀
_SZ_STOCK_PREFIXES: tuple[str, ...] = ("00", "30")  # 主板 + 创业板
_SZ_FUND_BOND_PREFIXES: tuple[str, ...] = ("10", "11", "12", "13", "14")


def detect_market(code: str) -> MarketType:
    """根据 6 位 A 股代码推断所属市场（SH/SZ/BJ）。

    Args:
        code: 6 位股票代码（不含后缀），如 '600519' / '830799' / '000001'

    Returns:
        MarketType.SH / MarketType.SZ / MarketType.BJ / MarketType.UNKNOWN

    规则（按优先级）：
        1. 北交所前缀 → BJ
        2. 沪股票前缀（60, 68）→ SH
        3. 深股票前缀（00, 30）→ SZ
        4. 沪基金/债券前缀 → SH
        5. 深基金/债券前缀 → SZ
        6. 其它 → UNKNOWN

    Examples:
        >>> detect_market("600519")
        <MarketType.SH: 'SH'>
        >>> detect_market("830799")  # 北交所
        <MarketType.BJ: 'BJ'>
        >>> detect_market("000001")
        <MarketType.SZ: 'SZ'>
        >>> detect_market("301236")  # 创业板
        <MarketType.SZ: 'SZ'>
        >>> detect_market("688981")  # 科创板
        <MarketType.SH: 'SH'>
        >>> detect_market("920xxx")  # 北证
        <MarketType.BJ: 'BJ'>
    """
    # 非字符串（None / int / 异常类型）一律 UNKNOWN，避免 AttributeError
    if not isinstance(code, str) or not code or not code.isdigit() or len(code) < 2:
        return MarketType.UNKNOWN

    prefix2 = code[:2]
    prefix3 = code[:3] if len(code) >= 3 else prefix2

    # 1. 北交所：83/87/88/92/40/42/43
    if prefix2 in _BJ_PREFIXES or prefix3 in _BJ_PREFIXES:
        return MarketType.BJ

    # 2. 沪股票：60, 68（科创板 688/689）
    if prefix2 in _SH_STOCK_PREFIXES:
        return MarketType.SH

    # 3. 深股票：00, 30（创业板 300/301）
    if prefix2 in _SZ_STOCK_PREFIXES:
        return MarketType.SZ

    # 4. 沪基金/债券：51, 56, 15, 16, 18
    if prefix2 in _SH_FUND_BOND_PREFIXES:
        return MarketType.SH

    # 5. 深基金/债券：10, 11, 12, 13, 14
    if prefix2 in _SZ_FUND_BOND_PREFIXES:
        return MarketType.SZ

    return MarketType.UNKNOWN
