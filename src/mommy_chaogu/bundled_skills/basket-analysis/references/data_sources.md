# 数据源 · 限流兜底 · 失败处理

> 沙箱 (cloud sandbox, 非 4 个 managed host 之一) 下, efinance 部分接口会限流。
> 所有数据源都有明确的兜底路径, 失败时优先降级而不是放弃整次分析。

---

## 1. A 股大盘指数 (mommy 无直接子命令 → 走 web)

### 来源
- `web_search(query="A股 {YYYY-MM-DD} 上证指数 深证成指 创业板 收盘", freshness="day", search_type="news")`
- 主要来源: 新浪财经 / 东方财富 / 中国经济网 午间/收盘快讯
- 通常每日 12:00 (午间) 和 15:30 (收盘) 各有一波报道

### 提取字段
- 上证指数 收盘 + 涨跌%
- 深证成指 收盘 + 涨跌%
- 创业板指 收盘 + 涨跌%
- 科创 50 / 科创综指 / 北证 50 涨跌%
- 涨停潮板块列表
- 拖累板块列表
- 半日/全日成交额

### 失败处理
- 搜索 0 结果: 报告标注 `A 股快照: 暂不可用, 当日 web 报道未发布`, 不要编造数据
- 部分字段缺失: 标记 `字段 X 暂不可用`

---

## 2. 全球粮食危机背景 (走 web)

### 4 变量触发条件
| 变量 | 来源 | 阈值 |
|---|---|---|
| ① FAO FPI 月度环比 | web_search "FAO Food Price Index {YYYY-MM}" | ≥ +2% |
| ② 黑海海运量同比 | web_search "Black Sea grain exports {YYYY-MM}" | ≤ -30% |
| ③ ONI 厄尔尼诺指数 | web_search "El Nino ONI {YYYY}" | ≥ 1.5 |
| ④ 399365 PE 分位 | 公开估值数据, 静态 (399365 自 2015 年) | ≤ 40% |

### 主要 web 来源
- FAO: https://www.fao.org/worldfoodsituation/foodpricesindex/en/
- Reuters/Guardian/Bloomberg: FAO 7 月/8 月数据报道
- foodsecurityportal.org: 黑海扰动 / 全球小麦 / USDA 数据

### 失败处理
- FAO 数据缺失: 用上月数据, 报告标注"基于 {YYYY-MM} 数据"
- 黑海 / ONI 数据缺失: 跳过对应触发变量, 报告标注

---

## 3. 资金流 (mommy flows + 限流兜底)

### 主路径
```bash
mommy flows --db portfolio.db --pool watchlist pull --target today --force
```

### 限流兜底
- 单次失败 codes < 10/35: 重试 1 次
- 重试仍失败: 接受部分覆盖, 报告标注 `资金流覆盖: 26/35 (74%)` 等
- 完全失败 (0/35): 不放弃, 用 web 搜索"今日 主力资金流入 农业板块"作为定性数据

### 历史资金流
- momday 默认只缓存 today, 30 天历史需要 `mommy flows pull --target history --days 30`
- 历史数据对复盘/回测关键, 但拉一次很慢 (5-10 分钟)

---

## 4. K 线数据 (沙箱限流严重 → 走腾讯原始 API)

### 限流根源
- `mommy_chaogu.market_data.efinance_adapter.EfinanceAdapter.get_bars()` 在 sandbox 几乎总是返回 `[]` (限流)
- `mommy_chaogu.market_data.tencent_adapter.TencentAdapter.get_bars()` 是空 stub: `def get_bars(...): return []`

### 兜底方案: 腾讯原始 HTTP API

```python
import requests
from pathlib import Path

def fetch_kline_tencent(code: str, days: int = 60) -> list[dict]:
    """腾讯 K线原始 API, 1.3s/code, 100% 成功 (sandbox 验证).

    URL: http://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={market}{code},day,,,{days},qfq
    返回 qfqday 或 day 数组, 每行 [date, open, close, high, low, volume]
    """
    market = "sh" if code.startswith(("6", "5", "9")) else "sz"
    full = f"{market}{code}"
    url = f"http://web.ifzq.gtimg.cn/appstock/app/fqkline/get?param={full},day,,,{days},qfq"
    headers = {
        "User-Agent": "Mozilla/5.0",
        "Referer": "https://stockapp.finance.qq.com/",
    }
    r = requests.get(url, headers=headers, timeout=15)
    r.raise_for_status()
    d = r.json()
    data = d.get("data", {}).get(full, {})
    rows = data.get("qfqday") or data.get("day") or []
    parsed = []
    for row in rows:
        try:
            parsed.append({
                "date": row[0],
                "open": float(row[1]),
                "close": float(row[2]),
                "high": float(row[3]),
                "low": float(row[4]),
                "volume": float(row[5]),
            })
        except (ValueError, TypeError, IndexError):
            continue
    return parsed
```

### 限流与超时
- HTTP 端口易超时: `timeout=15` 是经验值
- HTTPS 在某些代码上 SSL EOFError: 改 HTTP (端口 80) 解决
- 重试 3 次, sleep 2s: 失败 codes 几乎都是 SSL 抖动
- 35 只全量 60 根日线, 1.3s/只 ≈ 45s 总耗时

### 失败处理
- 单只失败: 重试 3 次, 最终仍失败则该只标记为 `kline: unavailable`, 不进 Top 5
- 批量失败 (>30%): 报告标注 `K线数据源异常, 今日技术面分析不可靠`

---

## 5. 基本面 (走 web, 因为 efinance 限流 + announcement 接口复杂)

### 主路径
```python
web_search(query="{name} {code} PE ROE 2026 中报 业绩")
```

### 主要数据点
- PE-TTM
- 2025 年报: 营收/归母/扣非/毛利率
- 2026 Q1: 营收/归母 同比
- 2026 H1: 业绩预告 (8 月披露季) 或 实际数据
- ROE (季报或年报)
- 关键催化剂: 转基因/钾肥/厄尔尼诺/补贴 等

### 失败处理
- 单只搜索 0 结果: 标 `fundamentals: 待补充`, 改用 web_search "市值 估值" 兜底
- 部分字段缺失: 标 "PE 暂不可用" 等
- 严禁编造数字: 任何标"暂不可用"的字段, 在报告里明说

---

## 6. 报价 (走 mommy, 不限流)

```bash
mommy watchlist list              # 报价快照
```

`TencentAdapter.get_quote()` 已在 v1.4.0 实现, 不限流, 沙箱可用。

---

## 7. 主题篮子 (走 mommy food-security CLI)

```bash
mommy food-security list --chain 上游
mommy food-security list --subcategory 化肥-钾肥
mommy food-security search 钾
mommy food-security stats
```

数据存在 `reference.db`, 自建 CLI (跟 semicon 平行), 100% 可用。

---

## 8. 整体限流应对原则

1. **优先用兜底, 不要反复撞限流**: efinance 限流时, 立刻切腾讯, 而不是等/重试
2. **覆盖度比 100% 重要**: 26/35 (74%) 数据 + 明确标注 > 100% 假数据
3. **数据缺失标"暂不可用", 不编**: 这是 mommy 框架的核心原则, 也是事实的边界
4. **web 限流时缓存**: 同一数据可缓存 24h (FAO 7 月数据, 黑海扰动等), 不要每次重新搜

---

## 9. 已知数据源 URL (供 web_fetch / web_search 兜底)

| 用途 | URL 模式 |
|---|---|
| FAO 食品价格指数 | https://www.fao.org/worldfoodsituation/foodpricesindex/en/ |
| 财经新闻 | https://finance.sina.com.cn (新浪财经) |
| 美股/A 股 | https://stockapp.finance.qq.com (腾讯) |
| 黑海扰动 | https://www.foodsecurityportal.org/ |
| USDA WASDE | https://www.usda.gov/oce/commodity/wasde |
| 东方财富研报 | https://emweb.eastmoney.com/ |
| 巨潮资讯 (公告) | http://www.cninfo.com.cn |
| 国家统计局 | http://www.stats.gov.cn |

---

## 10. 限流总表

| 数据源 | 沙箱状态 | 兜底 |
|---|---|---|
| efinance get_bars (K线) | ❌ 几乎全失败 | 腾讯原始 API |
| efinance get_today_money_flow | ⚠️ 20-35 只池子 26/35 成功 | 重试 + 接受部分 |
| efinance get_quote (报价) | ✅ 可用 | — |
| 腾讯 get_quote | ✅ 可用 | — |
| 腾讯 get_bars (K线) | ❌ stub | 腾讯原始 API (绕过) |
| 雅虎 yfinance | ✅ 偶尔限流 | efinance + 腾讯 |
| web_search (A 股 + 全球) | ✅ 稳定 | — |
| mommy food-security / semicon | ✅ 100% 可用 | — |
