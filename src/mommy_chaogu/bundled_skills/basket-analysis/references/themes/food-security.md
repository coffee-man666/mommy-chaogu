# 主题配置: 粮食安全/危机 (food-security)

> 第一作者: Mavis (session 431666932195605), v1.0 起 2026-08-13, v1.2 重构 2026-08-19

## 基本信息

- **中文名**: 粮食安全/危机
- **英文名**: `food-security`
- **一句话**: 全球粮价 + 极端天气 + 出口受阻 + 国内政策密集, A 股 35 只农业/农资/化肥/种业/农药/化纤/流通标的的资金画像

## 篮子 (basket)

- **size**: 35
- **source**: `mommy food-security` (自建 CLI, 跟 `mommy semicon` 平行)
- **chain 分布**: 4 chain × 14 subcategory
  - 上游 (农资, 19): 农药-综合 5 / 农药-调节剂 1 / 农药-杀虫剂 2 / 农药-除草剂 1 / 农药-杀菌剂 1 / 化肥-复合肥 4 / 化肥-钾肥 1 / 化肥-磷肥 2 / 化纤-粘胶 1 / 化纤-涤纶 1
  - 中游 (生产加工, 8): 粮食加工 3 / 油脂加工 2 / 饲料 3
  - 下游 (流通, 5): 粮食流通 3 / 猪肉 2
  - 末端 (基础设施, 3): 港口/物流 2 / 农田水利 1
- **seed**: `mommy food-security seed`
- **stats**: `mommy food-security stats`
- **list**: `mommy food-security list --chain 上游`

## 4 变量触发 (trigger_variables)

| # | label | current | threshold | status_label |
|---|---|---|---|---|
| 1 | FAO 谷物月度环比 | +3.4% | ≥ +2% | ✅ 触发 |
| 2 | 黑海海运量同比 | -75% | ≤ -30% | ✅ 触发 |
| 3 | 厄尔尼诺强度 | 强 (90%+ 概率非常强) | ≥ 强 | ✅ 触发 |
| 4 | 399365 粮食主题 PE 分位 | 36.5% | ≤ 40% | ✅ 触发 |

### 搜索 query 模板 (运行时替换 {placeholders})

```yaml
trigger_variables:
  - id: fao_cereal_mom
    label: "FAO 谷物月度环比"
    threshold: "≥ +2%"
    threshold_value: 0.02
    search_query: "FAO Food Price Index {month_before} wheat corn"
    search_freshness: month
    parse_regex: "Cereal Price Index.{0,100}?(\\d+\\.\\d+)\\s*points.{0,50}?(\\d+\\.\\d+)\\s*percent"
    parse_current: lambda m: float(m.group(2))/100
    
  - id: black_sea_yoy
    label: "黑海海运量同比"
    threshold: "≤ -30%"
    threshold_value: -0.30
    search_query: "Black Sea grain corridor {month_before} Russia Ukraine export"
    search_freshness: month
    
  - id: el_nino_oni
    label: "厄尔尼诺强度 (ONI)"
    threshold: "≥ 强"
    threshold_value: 1.5
    search_query: "El Nino ONI {year} strength"
    search_freshness: month
    
  - id: fpi_pe_pctile
    label: "399365 粮食主题 PE 分位"
    threshold: "≤ 40%"
    threshold_value: 0.40
    search_query: null  # 内部数据, 不需要 web
```

## 全局背景搜索 (global_context_searches)

```yaml
global_context_searches:
  - key: fao_july_2026
    label: "FAO 食品价格指数 (7 月)"
    query: "FAO Food Price Index {month} wheat corn"
    freshness: month
    parse_field: fao_index  # 存到 global_context.fao_july_2026
    
  - key: black_sea_status
    label: "黑海谷物出口状态"
    query: "Black Sea grain corridor {month} Russia Ukraine"
    freshness: month
    
  - key: el_nino_status
    label: "厄尔尼诺强度 (NOAA 周报)"
    query: "El Nino ONI {year} strength advisory"
    freshness: month
```

## 4 变量阈值与档位

```yaml
trigger_thresholds:
  fao_cereal_mom:
    values: [0.01, 0.02, 0.04]  # 弱/中/强触发
    labels: ["持平", "⚠️ 边际", "✅ 触发", "🔴 强触发"]
  
  black_sea_yoy:
    values: [-0.20, -0.30, -0.50]
    labels: ["正常", "⚠️ 边际", "✅ 触发", "🔴 严重"]
  
  el_nino_oni:
    values: [0.5, 1.0, 1.5]  # 弱/中/强
    labels: ["中性", "⚠️ 弱", "✅ 强", "🔴 极强"]
  
  fpi_pe_pctile:
    values: [0.30, 0.40, 0.60]
    labels: ["低估", "✅ 触发", "正常", "高估"]
```

## 关键个股观察 (curated, 跟 Top 5 ranking 无关)

> 不是"自动 Top 5", 是 analyst 手动标注的主题核心标的. 报告 Top 5 仍按资金画像自动生成, 这里只是 narrative 参考.

- **粮食安全主线** (种业): 002041 登海种业, 000998 隆平高科, 300189 神农种业, 600313 农发种业
- **化肥-钾肥** (国内最紧缺): 000408 藏格矿业 (钾+锂)
- **化肥-磷肥**: 600096 云天化, 000902 新洋丰
- **大米流通**: 600127 金健米业
- **猪肉** (替代蛋白): 000876 新希望, 002714 牧原股份 (注: 牧原不在 35 只篮子里, 仅供参考)

## 例外 (excluded_codes)

- 300087 ST 荃银高科 (ST 标的, 风险太高, 自动从 Top 5 排除)
- 300021 大禹节水 (有时被算为水利, 主题相关性边缘)

## 报告叙事钩子 (narrative_hooks)

- 4 变量共振时: 主题可超配
- 4 变量中 3 触发 1 中性: 主题标配
- 4 变量 2 触发: 主题可低配
- 4 变量 < 2 触发: 主题规避

## 已知失败模式 (failure_notes)

- efinance K 线: 沙箱里全限流, 用腾讯 raw HTTP API 兜底 (1.3s/只)
- efinance 资金流: 35 只常掉 6-9 只 (限流), retry 1-2 次接受部分覆盖
- 5 维指数 (上证/深成/创业/科创/北证) 5 个指数要 web search 一次性拉
