# 加新主题 — 操作指南

## Step 1: 复制模板

```bash
cp /workspace/.skills/basket-analysis/references/themes/_template.md \
   /workspace/.skills/basket-analysis/references/themes/my-new-theme.md
```

## Step 2: 改 metadata

打开 `my-new-theme.md` 编辑:

```yaml
- **中文名**: 我的新主题
- **英文名**: `my-new-theme`   ← 必填, kebab-case, 跟文件名一致
- **一句话**: <描述>
```

## Step 3: 定义篮子

3 种来源任选:

**(a) 用 mommy CLI** (推荐):
```yaml
basket:
  size: 30
  source: "mommy my-cli"   # 用 mommy my-cli list / stats 验证
```

**(b) 用现成的 watchlist group**:
```yaml
basket:
  size: 30
  source: "mommy watchlist my-group-name"
```

**(c) 手动列股票**:
```yaml
basket:
  size: 30
  source: "manual: 600519,000858,600809,..."   # 30 个代码
```

## Step 4: 定义 4 变量

每个变量 = (label, threshold, search_query, freshness).

模板:
```yaml
trigger_variables:
  - id: var1
    label: "变量 1 中文名"
    threshold: "≥ 阈值描述"
    search_query: "web 搜索 query, 可用 {year} {month} {month_before} {today} 替换"
    search_freshness: month
  - id: var2
    ...
  - id: var3
    ...
  - id: var4
    ...
```

## Step 5: 全局背景搜索 (可选但推荐)

```yaml
global_context_searches:
  - key: some_key
    label: "描述"
    query: "搜索 query"
    freshness: month
```

## Step 6: 跑一次

1. Agent 读你的主题 config
2. 跑 `mommy {source}` / `mommy flows --pool custom` 拉数据
3. Agent 把数据塞进 `data.json` (`theme` 字段 = 主题 metadata, `basket_flow` = 资金流, `top5_tech` = K 线, `fundamentals` = 财务)
4. 跑 `analyze.py --data data.json --out deliverables/my-new-theme/2026-08-19/run1/`
5. 拿 9 文件 + ZIP

## Step 7: (可选) 注册到 SKILL.md description

编辑 `/workspace/.skills/basket-analysis/SKILL.md` 的 frontmatter `description`, 把你的主题加进 "适用场景" 部分.

## 已注册主题

- `food-security` (粮食安全/危机) — 35 只, FAO + 黑海 + 厄尔尼诺 + 399365 PE
- `coal` (煤炭) — 15 只, 焦煤价格 + 秦港库存 + 火电 + 煤炭 PE 分位
- `semiconductor` (半导体) — 106 只, 费半 SOX + 存储芯片现货价 + 国内晶圆厂稼动率 + 北向科技净流入
- `innovative-drugs` (创新药) — 25 只, CXO 收入 + NMPA 批准 + 创新药 PE 分位 + 海外授权

(后 3 个 config 文件待写, 可按需补)
