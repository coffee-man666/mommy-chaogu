# CLI 样例功能评估报告

> **日期**: 2026-07-06
> **任务**: run-samples — 跑全部 CLI 样例功能，记录每一步输出
> **环境**: macOS, Python 3.12, uv

---

## 总览

项目定义了 11 个 CLI 入口（`pyproject.toml [project.scripts]`）：

| 命令 | 入口模块 |
|---|---|
| `mommy-watchlist` | `cli:main_watchlist` |
| `mommy-monitor` | `cli:main_monitor` |
| `mommy-report` | `cli:main_report` |
| `mommy-cache` | `cli:main_cache` |
| `mommy-semicon` | `cli:main_semicon` |
| `mommy-flows` | `cli:main_flows` |
| `mommy-web` | `cli:main_web` |
| `mommy-earnings` | `earnings.cli:main_earnings` |
| `mommy-agent` | `cli:main_agent` |
| `mommy-mcp` | `agent.mcp_server:main_mcp` |
| `mommy-chaogu` | `cli:main`（总入口） |

本次评估覆盖了任务要求的 12 项检查。整体结论：**所有 CLI 命令均可正常执行（无 crash），但大部分命令因数据库为空而无数据返回**。`data/market.db` 中有实际 K 线 + 资金流历史数据（用于回测），但 `portfolio.db` / `semicon.db` / `earnings` 等用户/参考数据库基本为空。

---

## 逐命令记录

### 1. `mommy-watchlist groups`

**命令**: `uv run mommy-watchlist groups`

**输出**:
```
（暂无分组）
```

**状态**: ✅ 正常执行，无数据。`portfolio.db` 为 0 字节空文件，无任何表。

---

### 2. `mommy-semicon list --limit 10`

**命令**: `uv run mommy-semicon list --limit 10`

**输出**:
```
usage: mommy-semicon [-h] [--db DB]
                     {seed,list,search,get,stats,add,remove} ...
mommy-semicon: error: unrecognized arguments: --limit 10
```

**状态**: ❌ **参数不兼容**。`mommy-semicon list` 不支持 `--limit` 参数。

**修正后**: `uv run mommy-semicon list`

**输出**:
```
（暂无数据）

共 0 条
```

**分析**: `data/semicon.db` 的 `semicon_stocks` 表存在但为空（0 行）。但 `data/reference.db` 的 `stocks` 表有 106 条半导体股票数据。说明 `reference.db` 由迁移脚本生成但 `semicon.db` 未执行 seed。参考库数据存在但命令读不到——**DB 路径与数据实际位置不一致**。

---

### 3. `mommy-semicon stats`

**命令**: `uv run mommy-semicon stats`

**输出**:
```
📊 半导体产业链参考库统计
────────────────────────────────────────────────────────────
  股票总数:    0
  主位置数:    0 (上游 / 中游 / 下游 / 下游 / 末端)
  子分类数:    0
  板块数:      0

按主位置分布:

按子分类分布（chain / subcategory / count）:
```

**状态**: ✅ 正常执行，无数据（原因同上）。

---

### 4. `mommy-cache stats`

**命令**: `uv run mommy-cache stats`

**输出**:
```
📊 缓存统计
────────────────────────────────────────────────────────────
  自选报价缓存: 0 条
  K线缓存:      0 条
  当日资金流:   0 条
  历史资金流:   0 条
  全市场快照:   0 份

💡 拉新统计:
  缓存命中: 0 次
  拉新请求: 0 次 (成功 0 / 失败 0)
  完全 miss: 0 次

（缓存为空，先 mommy-cache warmup）
```

**状态**: ✅ 正常执行。缓存 5 张表（`quote_cache`, `bar_cache`, `today_money_flow_cache`, `money_flow_cache`, `market_snapshot_cache`）均为 0 条。注意：`market.db` 的 `klines` / `flows` 表有数据，但这些是历史回测数据，不属于缓存层。

---

### 5. `mommy-cache config`

**命令**: `uv run mommy-cache config`

**输出**:
```
⚙️ 缓存拉新间隔配置（默认值）
────────────────────────────────────────────────────────────
  quote_fetch_interval_seconds:             300 秒 (5 分钟)
  today_money_flow_fetch_interval_seconds:  300 秒
  market_snapshot_fetch_interval_seconds:   3600 秒 (1 小时)
  bar_fetch_interval_seconds:               86400 秒 (1 天)
  money_flow_history_fetch_interval_seconds:86400 秒
  market_snapshot_history_keep:             30 份
```

**状态**: ✅ 正常执行，展示了 6 个缓存拉新间隔配置（均为默认值）。

---

### 6. `mommy-flows stats`

**命令**: `uv run mommy-flows stats`

**输出**:
```
📊 watchlist (0 只自选股, db=data/watchlist.db) 资金流缓存覆盖度
────────────────────────────────────────────────────────────
  池子总股数: 0
  当日已缓存: 0 (0%)
  历史已缓存: 0 (0%)
```

**状态**: ✅ 正常执行。注意输出显示 db 指向 `data/watchlist.db`（旧路径），而项目已迁移到 `portfolio.db`——**可能存在 DB 路径硬编码遗留**。

---

### 7. `mommy-flows top --limit 10`

**命令**: `uv run mommy-flows top --limit 10`

**输出**:
```
usage: mommy-flows [-h] [--db DB] [--semicon-db SEMICON_DB]
                   [--pool {watchlist,semicon,custom}] [--codes [CODES ...]]
                   [--no-fallback]
                   {pull,top,show,stats,clear,run,report} ...
mommy-flows: error: unrecognized arguments: --limit 10
```

**状态**: ❌ **参数不兼容**。`mommy-flows top` 用 `--n N` 而非 `--limit`。

**修正后**: `uv run mommy-flows top --n 10`

**输出**:
```
🏆 watchlist · 当日 · 按主力净 · 净流入 TOP 10
──────────────────────────────────────────────────────────────────────────────────────────
（无数据，先 mommy-flows pull）
```

**状态**: ✅ 修正后正常执行，无数据（watchlist 池为空）。

**`mommy-flows top` 支持的参数**:
```
--period {today,history}   时间窗（默认 today）
--days DAYS                period=history 时的天数
--n N                      取前 N (默认 20)
--by {main_net,big_money}  排序指标（默认 主力净 = main_net）
--direction {in,out}       净流入 / 净流出（默认 in）
```

---

### 8. `mommy-earnings summary`

**命令**: `uv run mommy-earnings summary`

**输出**:
```
📈 H1 2026 业绩比对摘要:
   (无数据)
```

**状态**: ✅ 正常执行，无数据。`data/reference.db` 中 `earnings_actual` / `earnings_calendar` / `earnings_score` 三张表均为空（0 行）。

---

### 9. `mommy-monitor snapshot`

**命令**: `uv run mommy-monitor snapshot`

**输出**:
```
📊 自选股快照 @ 2026-07-05 21:48:42  共 0 只  ↑0 ↓0 —0  主力净流入 +0.00元

（自选股池为空，先 watchlist add 几只股票）
```

**状态**: ✅ 正常执行（无需联网，因为 watchlist 为空直接返回）。无法评估联网拉新能力（无自选股触发网络请求）。

---

### 10. `mommy-agent --help`

**命令**: `uv run mommy-agent --help`

**输出**:
```
usage: mommy-agent [-h] [--provider PROVIDER] [--model MODEL]
                   [--max-tool-calls MAX_TOOL_CALLS]
                   [query ...]

妈妈炒股 - LLM agent（交互式对话 / 单次提问）

positional arguments:
  query                 提问内容（留空则进入交互式 REPL）

options:
  -h, --help            show this help message and exit
  --provider PROVIDER   LLM provider（deepseek / openai / kimi / zai，默认读 .env）
  --model MODEL         模型名（默认由 provider 决定）
  --max-tool-calls MAX_TOOL_CALLS
                        最大工具调用轮数（默认 10）
```

**状态**: ✅ 正常执行。Agent 支持 4 个 provider（deepseek / openai / kimi / zai），可配置模型和最大工具调用轮数。

---

### 11. `mommy-report index`

**命令**: `uv run mommy-report index`

**输出**:
```
❌ 没有任何报告: data/flows_report_*.md
```

**状态**: ❌ 失败（exit code 1）。`mommy-report index` 扫描的是 `data/flows_report_*.md` 模式，但实际报告在 `reports/` 目录：

```
reports/2026-07-03-innovative-drug.md
reports/2026-07-06-earnings-analysis.md
reports/README.md
reports/index.html
reports/2026-06-29.html
```

**分析**: 报告渲染模块的默认扫描路径（`data/flows_report_*.md`）与实际报告目录（`reports/`）不匹配。这是一个 **bug 或配置遗留**。

---

### 12. `data/market.db` 数据量分析

**数据库文件**: `data/market.db`（458 KB，最后修改 2026-07-03 19:34）

#### 表结构

| 表名 | 用途 |
|---|---|
| `klines` | 历史 K 线（code, date, open, close, high, low, volume） |
| `flows` | 资金流（code, date, main_net, super_large_net, large_net, medium_net, small_net, ratio） |
| `quote_cache` | 报价缓存 |
| `bar_cache` | 分钟 K 线缓存 |
| `today_money_flow_cache` | 当日资金流缓存 |
| `money_flow_cache` | 历史资金流缓存 |
| `market_snapshot_cache` | 全市场快照缓存 |

#### klines 表统计

| 指标 | 值 |
|---|---|
| 总行数 | **4,437** |
| 覆盖股票数 | **106 只** |
| 日期范围 | **2026-05-06 ~ 2026-07-03** |
| 交易日数 | **42 天** |
| 每日股票数 | 105~106 只 |

K 线数据覆盖约 2 个月（5 月初到 7 月初），是回测引擎的主要数据源。数据完整度良好。

#### flows 表统计

| 指标 | 值 |
|---|---|
| 总行数 | **1,917** |
| 覆盖股票数 | **92 只** |
| 日期范围 | **2026-06-04 ~ 2026-07-03** |
| 交易日数 | **21 天** |
| 每日股票数 | 91~92 只 |

资金流数据仅覆盖 1 个月（6 月初到 7 月初），比 K 线短一半。flows 的股票覆盖（92 只）少于 klines（106 只），有 14 只股票缺资金流数据。

#### 缓存表

5 张缓存表全部为空（0 行），说明项目从未在实时模式运行过缓存拉新。

#### 样例数据

```
klines:
301095|2026-05-06|84.443|85.013|87.603|83.803|83087.0
301095|2026-05-07|85.323|92.363|93.043|85.033|126140.0
...

flows:
301095|2026-06-04|-7797998.0|-16259134.0|8461136.0|4500256.0|3297728.0|-0.61
301095|2026-06-05|35085670.0|18370997.0|16714673.0|-56110800.0|21025136.0|3.22
...
```

---

## 其他数据库状态

| 数据库 | 大小 | 状态 |
|---|---|---|
| `data/market.db` | 458 KB | ✅ 有数据（klines + flows） |
| `data/portfolio.db` | 0 字节 | ❌ 空文件（无任何表） |
| `data/reference.db` | 86 KB | ⚠️ 仅 `stocks` 表有 106 行，earnings 3 张表为空 |
| `data/semicon.db` | 29 KB | ⚠️ `semicon_stocks` 表为空（0 行） |
| `data/watchlist.db` | 86 KB | 存在（旧路径，内容待查） |
| `data/agent.db` | 270 KB | ✅ 有数据（记忆系统） |
| `data/eval-agent.db` | 57 KB | ✅ 有数据（回测用） |

---

## 分析结论

### 做得好的地方

1. **CLI 命令全部可执行** — 12 项检查中无 crash，所有 argparse 错误提示清晰
2. **历史数据质量好** — `market.db` 有 4,437 条 K 线 + 1,917 条资金流，覆盖 106 只股票、42 个交易日
3. **错误提示友好** — 所有空数据场景都有中文提示和下一步操作建议（如"先 watchlist add 几只股票"）
4. **缓存配置合理** — 6 个拉新间隔按数据类型分级（5 分钟报价 / 1 小时快照 / 1 天 K 线）
5. **Agent 入口完整** — 支持 4 个 LLM provider、可配置模型和工具调用轮数

### 发现的问题

| # | 严重度 | 问题 | 详情 |
|---|---|---|---|
| 1 | 🔴 高 | **DB 路径不一致** | `mommy-flows` 输出显示 db=`data/watchlist.db`（旧路径），但 AGENTS.md 说已迁移到 `portfolio.db`。`portfolio.db` 为空（0 字节），可能迁移未完成 |
| 2 | 🔴 高 | **semicon 数据丢失** | `reference.db` 有 106 条半导体股票，但 `semicon.db` 的 `semicon_stocks` 表为空。命令读 `semicon.db` → 始终返回 0 条。需运行 `mommy-semicon seed` 或修复路径映射 |
| 3 | 🟡 中 | **mommy-report index 路径错误** | 扫描 `data/flows_report_*.md`，但报告实际在 `reports/` 目录。命令永远失败 |
| 4 | 🟡 中 | **参数命名不统一** | 任务指定的 `--limit` 在 `mommy-semicon list` 和 `mommy-flows top` 均不存在。应统一用 `--limit` 或 `--n` |
| 5 | 🟢 低 | **earnings 表全空** | `earnings_actual` / `earnings_calendar` / `earnings_score` 无数据。可能是季度周期导致（非财报季） |
| 6 | 🟢 低 | **缓存层全空** | 5 张缓存表 0 行，项目从未做过实时缓存拉新（仅离线回测用过） |
| 7 | 🟢 低 | **flows 覆盖率低于 klines** | flows 仅 92 只 / 21 天，klines 有 106 只 / 42 天。14 只股票缺资金流数据 |

---

## 改进建议

### P0 — 必须修复

1. **统一 DB 路径**：运行 `uv run python scripts/migrate_db_layout.py --check` 确认迁移状态，修复 `mommy-flows` 等命令中可能残留的 `data/watchlist.db` 硬编码。`portfolio.db` 为 0 字节说明迁移未执行或失败。
2. **修复 semicon 数据映射**：`reference.db` 的 `stocks` 表（106 行）与 `semicon.db` 的 `semicon_stocks` 表（0 行）需要同步。考虑让 `mommy-semicon` 直接读 `reference.db`，或在 `semicon.db` 中 seed 数据。
3. **修复 `mommy-report index` 扫描路径**：改为扫描 `reports/*.md` 而非 `data/flows_report_*.md`。

### P1 — 建议修复

4. **统一分页参数**：所有 `list` / `top` 类子命令统一使用 `--limit N` 参数名，而非 `--n` / 无分页。
5. **补充 earnings 种子数据**：在非财报季也保留上一季度的基准数据，避免 `mommy-earnings summary` 始终返回空。

### P2 — 体验优化

6. **添加 `mommy-chaogu` 总入口帮助**：`mommy-chaogu` 入口存在但 `mommy` 不是有效命令。考虑在总入口列出所有子命令。
7. **`mommy-cache --db` 默认路径也是 `data/watchlist.db`**：与 `mommy-flows` 同样的旧路径问题，需统一改为 `market.db`。
