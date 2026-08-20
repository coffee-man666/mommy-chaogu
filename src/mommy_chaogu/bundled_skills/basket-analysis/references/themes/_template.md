# 主题配置模板 (Theme Config Template)

> 复制此文件 → 改名 (e.g. `innovative-drugs.md`) → 修改 4 变量 + basket + 搜索 query
> 然后 `python scripts/analyze.py --data data.json --out ...` (data.json 里 `theme.name_en` 必须跟文件名一致)

## 基本信息

- **中文名**: <主题名>
- **英文名**: `<theme-name-en>`  ← 必须用 kebab-case, e.g. `innovative-drugs`, `new-energy`, `coal`
- **一句话**: <一句话描述这个主题是什么>

## 篮子 (basket)

```yaml
basket:
  size: <N>                           # 篮子里有多少只股票
  source: "<how to pull>"              # 三种来源任选一种:
  source_options:
    - "mommy <cli-name>"              #   (a) 用 mommy CLI (推荐, 自动有 seed/list/stats 子命令)
    - "mommy watchlist <group_name>"  #   (b) 用 watchlist 的某个 group
    - "manual: <comma-separated codes>"  # (c) 手动指定股票列表
```

## 4 变量触发 (trigger_variables)

每个变量必须包含: `label` (中文), `threshold` (字符串, 给报告用), `search_query` (web 搜索模板, 运行时替换 {placeholders})

```yaml
trigger_variables:
  - id: <var_id_1>                     # snake_case, 唯一
    label: "<变量 1 中文名>"
    threshold: "<阈值描述, e.g. ≥ +2%>"
    search_query: "web search 模板 {month} {year}"  # 可用 {month}, {month_before}, {year}, {today}
    search_freshness: month              # day / week / month
    status_now: ✅ 触发 / ❌ 未触发     # 跑的时候填, 报告展示用

  - id: <var_id_2>
    ...

  - id: <var_id_3>
    ...

  - id: <var_id_4>
    ...
```

## 全局背景搜索 (global_context_searches)

主题相关的全球/全国宏观背景查询, 报告"全球 {主题} 驱动"章节会用到.

```yaml
global_context_searches:
  - key: <key_1>                       # 写到 data.json["global_context"][<key_1>] 里
    label: "<背景描述>"
    query: "web search 模板"
    freshness: month
```

## 触发档位 (trigger_thresholds, 可选)

```yaml
trigger_thresholds:
  <var_id>:
    values: [<low>, <mid>, <high>]     # 数值门槛
    labels: ["<低档名>", "<中档名>", "<高档名>"]  # 对应 values
```

## 例外 (excluded_codes, 可选)

```yaml
excluded_codes:
  - <code_1>    # ST 标的 / 边缘标的 / 不计入 Top 5
  - <code_2>
```

## 报告叙事钩子 (narrative_hooks, 可选)

```yaml
narrative_hooks:
  full_trigger: "4 变量全部触发, 主题可超配"
  partial: "3 触发 1 中性, 主题标配"
  weak: "2 触发, 主题低配"
  none: "< 2 触发, 主题规避"
```

## 关键个股观察 (key_stocks, 可选, narrative 参考)

```yaml
key_stocks:
  - subcategory: "<子分类 e.g. 创新药-CRO>"
    stocks:
      - {code: 300347, name: 泰格医药, why: "国内 CRO 龙头"}
      - {code: 603259, name: 药明康德, why: "全球 CXO 龙头"}
```

## 失败模式 (failure_notes, 可选)

记录这个主题常见的爬数据失败模式, 给未来的 runner 参考.

```yaml
failure_notes:
  - "数据源 X 在 Y 情况下会 rate-limit"
  - "股票 Z 是 ST 标的, 自动排除"
```

## 例: 创新药 (innovative-drugs) 配置骨架

```yaml
basket:
  size: 25
  source: "manual: 300347,603259,300759,688180,002821,300122,600276,688321,300142,300601,300630,688505,600196,300003,002422,600867,300558,002030,688266,300181,688192,688302,688180,300601,688617"

trigger_variables:
  - id: cxo_revenue_yoy
    label: "CXO 行业收入同比"
    threshold: "≥ +10%"
    search_query: "中国 CXO 行业 2026 上半年 收入同比 药明康德 泰格医药"
    search_freshness: month
    status_now: "待查"
  - id: nmpa_approval_count
    label: "NMPA 新药批准数量"
    threshold: "≥ 30 个/年"
    search_query: "NMPA 2026 新药批准 创新药"
    search_freshness: month
    status_now: "待查"
  - id: fpi_pe_pctile_drugs
    label: "创新药板块 PE 分位"
    threshold: "≤ 30%"
    search_query: null
    status_now: "待查"
  - id: outlicensing_deal_count
    label: "海外授权交易数量"
    threshold: "≥ 20 笔/季度"
    search_query: "中国创新药 海外授权 license out 2026 季度"
    search_freshness: month
    status_now: "待查"

global_context_searches:
  - key: fda_approval_count
    label: "FDA 创新药批准数量"
    query: "FDA novel drug approval 2026"
    freshness: month
  - key: asco_highlights
    label: "ASCO 年会中国创新药数据"
    query: "ASCO 2026 中国 创新药 数据 表现"
    freshness: year
```

把这个 YAML 落到 `innovative-drugs.md` 后, 跑:

```bash
python3 scripts/analyze.py \
  --data /path/to/innovative-drugs-data.json \
  --out /workspace/mommy-deliverables/innovative-drugs/2026-08-19/run1/ \
  --session my-session-id
```

data.json 里 `theme.name_en` 必须 = "innovative-drugs" 才能匹配这个 config.
