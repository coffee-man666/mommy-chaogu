# 详细架构

> 本文档从 README 拆分而来，包含系统的详细设计说明。
> 如果只想快速上手，请看 [README](../README.md)。

---

## 目录

- [数据库布局](#数据库布局)
- [核心设计原则](#核心设计原则)
- [自进化记忆系统](#自进化记忆系统)
- [回测引擎](#回测引擎)
- [CLI 速查](#cli-速查)
- [自动化](#自动化)
- [数据源](#数据源)
- [项目结构](#项目结构)
- [开发](#开发)
- [文档索引](#文档索引)

---

## 数据库布局

4 个按职责分离的 SQLite 数据库，互不干扰：

| 数据库 | 用途 | 关键表 |
|---|---|---|
| `data/market.db` | 行情数据 | quote_cache, bar_cache, klines, flows |
| `data/portfolio.db` | 用户数据 | groups, stock_entries, positions |
| `data/agent.db` | 记忆系统 | episodic_events, predictions, semantic_knowledge, insight_summary |
| `data/reference.db` | 参考库 | semicon_stocks, earnings_* |

路径可通过环境变量覆盖：`MOMMY_MARKET_DB` / `MOMMY_PORTFOLIO_DB` / `MOMMY_AGENT_DB` / `MOMMY_REFERENCE_DB`

定义在 `src/mommy_chaogu/db_paths.py`。

---

## 核心设计原则

1. **Protocol-first** — 所有数据源走 `MarketDataAdapter` Protocol，加新源只需实现接口
2. **Decimal 金额** — 财务数据一律 `Decimal`，不用 `float`
3. **Graceful degradation** — 数据源挂了自动 fallback 到缓存，用户无感
4. **数据库是唯一真相源** — 拉新失败保留旧数据，从不主动清空
5. **记忆系统全入口激活** — 任何分析入口（聊天/回测/报告/监控）都自动读写记忆

---

## 自进化记忆系统

记忆系统让 agent 从「每次从零开始」变成「越用越懂」— 记住过去、讲出脉络、验证判断、沉淀经验。

### 5 层架构

| 层 | 模块 | 职责 |
|---|---|---|
| Working Memory | `ConversationMemory` | 当前对话上下文 |
| Episodic Memory | `EpisodicMemory` | 结构化市场事件流（分析记录、告警信号、验证结果） |
| Prediction Tracking | `PredictionTracker` | 预测记录 + 到期验证 + 命中率统计 |
| Semantic Memory | `SemanticMemory` | 提炼后的知识（板块叙事、市场状态、规律模式、周度复盘） |
| Vector Search | `VectorSearch` | 语义搜索历史事件（sqlite-vec + embedding API） |

### MemoryPipeline

`MemoryPipeline` 是统一入口，任何分析场景一行代码接入：

```python
pipeline = MemoryPipeline(episodic, tracker, semantic, client, model)

# 构建注入了记忆的 prompt（已有认知 + 近期事件 + 判断回顾 + 相似事件）
system_prompt = pipeline.build_prompt(query="中芯国际")

# 分析完成后自动提取 + 存储
pipeline.record_analysis(user_msg, assistant_response)

# 验证到期预测（回填 traceability 链）
pipeline.verify_predictions(adapter)

# 提炼语义知识 + 生成 insight summary
pipeline.consolidate()
```

### 全入口激活

| 入口 | 读取记忆 | 写入记忆 | 提炼知识 |
|---|---|---|---|
| Web/CLI 聊天 | build_prompt | record_analysis | cron |
| LLM 回测 | build_prompt | episodic + source_event_id | 内联 |
| 收盘报告 | build_prompt | analysis_record | cron |
| 监控告警 | build_prompt | signal_event | cron |

### 记忆可见性 CLI

```bash
mommy memory stats        # 记忆统计
mommy memory events       # 近期事件
mommy memory predictions  # 预测历史
mommy memory knowledge    # 活跃知识
mommy memory history      # 对话历史
```

---

## 回测引擎

### 三条回测路径

| 路径 | 脚本 | 评分逻辑 | 数据源 |
|---|---|---|---|
| 规则引擎 | `backtest_evolution.py` | 方向命中率 + ±2% 死区 | 实时拉网络 |
| LLM 驱动 | `backtest_llm.py` | 统一评分 + 交易成本扣减 | market.db 离线 |
| BacktestEngine | `backtest/engine.py` | 做多 P&L + Sharpe | cache SQLite |

### 分析工具

| 模块 | 用途 |
|---|---|
| `backtest/scoring.py` | 统一评分（±2% 死区，neutral 不再固定 hit） |
| `backtest/costs.py` | A 股交易成本模型（佣金 + 印花税 + 过户费 + 滑点 = 0.341%） |
| `backtest/portfolio.py` | 组合层面分析（净值曲线 + max-DD + Sharpe） |
| `backtest/walk_forward.py` | Walk-forward 过拟合检测 |
| `backtest/regime_analysis.py` | 市场环境分组分析（bull/bear/sideways） |
| `backtest_stats.py` | Wilson CI + 精确二项检验（无 scipy 依赖） |

### LLM 回测（带记忆系统）

```bash
# 基本回测（无记忆）
uv run python scripts/backtest_llm.py --model glm-4.7 --provider zai \
  --max-dates 7 --horizon 5

# 带记忆系统的回测（记忆进化 + 知识提炼 + traceability）
uv run python scripts/backtest_llm.py --model glm-4.7 --provider zai \
  --db data/backtest.db --memory-db data/memory.db \
  --max-dates 7 --horizon 5
```

带记忆的回测会在报告中输出记忆进化统计：

```
记忆系统进化
  Episodic events: 27 条
  Predictions: 21 条 (hit 9, missed 12)
  Semantic knowledge: 3 条
  Insight summaries: 2 条
  Traceability: 21/21 条预测关联了 episodic event (100%)
```

### 回测输出示例

```
命中率: 42.9% (Wilson 95% CI: [24.5%, 63.5%], p=0.66)
Buy-and-hold 基准: 67%
Alpha (策略-基准): -24%

分方向
  bullish : 5/8 62.5% (Wilson 95% CI: [30.6%, 86.3%])
  bearish : 4/13 30.8% (Wilson 95% CI: [12.7%, 57.6%])
```

---

## CLI 速查

统一入口 `mommy`，所有子功能通过子命令访问（旧命令 `mommy-watchlist` 等仍兼容）：

```
mommy <自然语言>        # AI 自然语言对话（推荐）
mommy                   # 进入交互式 REPL
mommy watchlist ...     # 自选股管理（分组 / 增删 / 告警 / 导出）
mommy monitor ...       # 实时监控（快照 / 持续轮询 / 信号日志）
mommy cache ...         # 缓存管理（命中率 / warmup / refresh）
mommy flows ...         # 资金流拉新 + 板块扫描 + 收盘日报
mommy report ...        # HTML 报告渲染
mommy semicon ...       # 半导体产业链查询
mommy earnings ...      # 财报前瞻 vs 实际 比对
mommy agent ...         # AI 行情助手（chat / report / scan / verify / consolidate ...）
mommy memory ...        # 记忆系统（stats / events / predictions / knowledge / history）
mommy web ...           # Web 服务（REST API + WebSocket）
mommy tui               # 终端 UI（Textual 双模式：AI 对话 + 数据看板）
mommy mcp               # MCP Server（stdio 协议，可接入 Claude Desktop）
```

`mommy agent` 子命令：

```
chat         与 agent 对话（自动调用记忆系统）
report       生成收盘日报（agent 驱动 + 记忆注入）
scan         盘中智能扫描
monitor      持续监控循环
verify       验证到期预测
predictions  查看预测历史
events       查看近期事件
narrative    生成市场脉络叙述
consolidate  提炼语义知识
knowledge    查看活跃知识
search       向量语义搜索
cleanup      清理旧数据（TTL + 去重）
tools        列出可用工具
```

### 结构化子命令示例

```bash
# 自选股管理
mommy watchlist add-group 半导体 --description "持仓分组"
mommy watchlist add 688981 --group 半导体
mommy watchlist list

# 行情快照
mommy monitor snapshot

# 资金流扫描
mommy flows pull --pool semicon --days 30
```

> **提示**：旧的独立命令（`mommy-watchlist`、`mommy-monitor` 等）仍然可用，向后兼容。

---

## 自动化

### Web 安全边界

- 默认监听 `127.0.0.1`，本机使用无需令牌。
- 非本机监听必须设置 `MOMMY_API_TOKEN`。
- REST API 使用 Bearer token；WebSocket 使用 60 秒有效的 HMAC 签名 ticket。
- `MOMMY_CORS_ORIGINS` 用逗号分隔可信前端 origin；默认不允许跨域。
- Agent REST/WebSocket 共用有界并发槽，防止意外消耗 LLM 配额。
- Web 对话按浏览器会话 ID 隔离；旧数据自动迁移到 `default` 会话。
- 非默认 Web 会话保留 30 天，可用 `[web].session_retention_days` 调整。

### Cron 定时任务

| 脚本 | 时间 | 功能 |
|---|---|---|
| OpenClaw | 周一~五 8:30 | 盘前预热缓存 |
| OpenClaw | 周一~五 9:30 | 启动盘中监控 |
| OpenClaw | 周一~五 15:30 | 收盘日报 + 推送 |
| OpenClaw | 周六 10:00 | 周报汇总 |
| `cron_verify.sh` | 周一~五 16:00 | 验证到期预测 |
| `cron_consolidate.sh` | 周五 18:00 | 验证 + 提炼知识 + 生成 insight |

---

## 数据源

| 数据源 | 用途 | 接口 |
|---|---|---|
| **东方财富 (efinance)** | 主力数据源（行情 / K 线 / 资金流 / 业绩） | `ef.stock.*` |
| **腾讯财经 (Tencent)** | 备援（行情） | `qt.gtimg.cn` |
| **巨潮资讯 (cninfo)** | 公告日历 | `hisAnnouncement/query` |

多源 fallback 链：`CachedMarketDataAdapter(FallbackAdapter([EfinanceAdapter, TencentAdapter]))`

---

## 项目结构

```
mommy-chaogu/
├── src/mommy_chaogu/
│   ├── market_data/         # 数据源适配层（efinance + tencent + fallback）
│   ├── cache/               # SQLite 缓存（5 表 + 节流 + freshness）
│   ├── watchlist/           # 自选股 ORM（SQLAlchemy 2.0）
│   ├── monitor/             # 实时监控
│   ├── signals/             # 告警规则 + Alerter
│   ├── flows/               # 资金流分析 + 信号
│   ├── earnings/            # 财报前瞻 vs 实际比对
│   ├── agent/               # LLM agent（21 工具 + MCP + 记忆系统 + MemoryPipeline）
│   ├── backtest/            # 回测引擎（评分 + 成本 + 组合 + walk-forward + regime）
│   ├── portfolio/           # 持仓 + 组合分析
│   ├── semicon/             # 半导体产业链参考库
│   ├── web/                 # FastAPI + WebSocket
│   ├── push/                # Server酱推送
│   ├── db_paths.py          # 统一数据库路径管理
│   └── cli.py               # CLI 入口（12 个子应用）
├── tests/                   # 700+ 测试
├── scripts/                 # 回测 / 迁移 / cron 脚本
├── docs/                    # 项目文档
├── web/                     # Vite + Vue 3 前端
└── pyproject.toml
```

---

## 开发

### 本地安装（开发者）

```bash
# 安装（需要 Python 3.12+）
git clone https://github.com/coffee-man666/mommy-chaogu.git
cd mommy-chaogu
uv sync --extra dev

# 配置密钥
cp .env.example .env
# 编辑 .env，填入 LLM API key

# 跑测试确认环境正常
uv run pytest -m "not network"
```

### 代码质量

```bash
uv run ruff check .          # lint
uv run ruff format .         # format
uv run mypy --strict src     # type check (0 errors)
uv run pytest -m "not network"  # 700+ 离线测试
```

### 贡献

```bash
# 1. fork → branch
git checkout -b feat/xxx

# 2. 写测试 + 实现功能
uv run ruff format . && uv run ruff check .
uv run mypy --strict src
uv run pytest -m "not network"

# 3. commit + push + PR
git commit -m "feat: xxx"
```

Conventional Commits：`feat / fix / docs / refactor / chore`

---

## 文档索引

| 文档 | 用途 |
|---|---|
| [PROGRESS.md](PROGRESS.md) | 当前进度 + 里程碑 |
| [DESIGN.md](DESIGN.md) | 架构设计 + ADR |
| [MEMORY-SYSTEM-PLAN.md](MEMORY-SYSTEM-PLAN.md) | 记忆系统设计（5 层架构 + MemoryPipeline） |
| [BACKTEST-REPORT.md](BACKTEST-REPORT.md) | 回测报告（多模型横向对比） |
| [EVALUATION-2026-07-05.md](EVALUATION-2026-07-05.md) | 记忆系统 + 回测系统评估报告 |
| [EVALUATION-2026-07-14.md](EVALUATION-2026-07-14.md) | 当前项目生产就绪度评估 |
| [ENHANCEMENT-PLAN-2026-07-14.md](ENHANCEMENT-PLAN-2026-07-14.md) | 可执行的强化计划 + 验收标准 |
| [EARNINGS-HANDBOOK.md](EARNINGS-HANDBOOK.md) | 财报窗口实战手册 |
| [KLINE-SPEC.md](KLINE-SPEC.md) | K 线组件规范 |
| [AGENT-INTERACTION-GUIDE.md](AGENT-INTERACTION-GUIDE.md) | Agent 交互指导 |
