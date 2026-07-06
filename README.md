# mommy-chaogu

<div align="center">

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.12+](https://img.shields.io/badge/python-3.12+-blue.svg)](https://www.python.org/downloads/)
[![CI](https://github.com/coffee-man666/mommy-chaogu/actions/workflows/ci.yml/badge.svg)](https://github.com/coffee-man666/mommy-chaogu/actions/workflows/ci.yml)
[![Tests](https://img.shields.io/badge/tests-700%2B-brightgreen.svg)](#开发)
[![Code style: ruff](https://img.shields.io/badge/code%20style-ruff-000000.svg)](https://github.com/astral-sh/ruff)
[![Type check: mypy strict](https://img.shields.io/badge/mypy--strict-0%20errors-blue.svg)](https://mypy-lang.org/)

</div>

A 股投研工具集 — 行情监控、资金流分析、AI agent 对话、自进化记忆系统、回测引擎。

从一个「给妈妈用的手机行情工具」起步，逐步演进为涵盖数据采集、信号告警、LLM 分析、预测验证闭环、回测评估的完整投研框架。

---

## 核心能力

| 能力 | 说明 |
|---|---|
| **行情数据** | 多源 fallback（东财 + 腾讯 + 缓存），报价 / K 线 / 资金流 / 板块排行 / 基本面 |
| **资金流分析** | 主力净流入比率 (bp) 信号、板块扫描、收盘日报、历史回测 |
| **AI Agent** | 21 个 function-calling 工具，支持 deepseek / openai / kimi / z.ai (GLM)，Web 聊天 + 流式推送 |
| **自进化记忆** | 5 层记忆架构（工作/情景/预测验证/语义知识/向量检索），MemoryPipeline 全入口激活 |
| **回测引擎** | 规则回测 + LLM 回测 + 组合分析 + walk-forward 过拟合检测 + 市场环境分组分析 |
| **财报窗口** | 业绩前瞻入库 + actual vs predicted 自动打分，4 种 verdict 分级 |
| **信号告警** | 7 条内置规则 + 自定义价格/涨跌幅告警 + Server酱微信推送 |
| **Web UI** | Vite + Vue 3 + FastAPI，手机可访问，WebSocket 实时推送 |

---

## 快速上手

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

### 基础用法

```bash
# 自选股管理
uv run mommy-watchlist add-group 半导体 --description "持仓分组"
uv run mommy-watchlist add 688981 --group 半导体
uv run mommy-watchlist list

# 行情快照
uv run mommy-monitor snapshot

# 资金流扫描（板块维度）
uv run mommy-flows pull --pool semicon --days 30

# Web UI（手机访问）
uv run mommy-web --port 8765
```

### AI Agent 对话

```bash
# 配置 z.ai (GLM) 作为 LLM provider
# .env 中设置 ZAI_API_KEY 和 AGENT_PROVIDER=zai

# 与 agent 对话（自动调用记忆系统）
uv run mommy-agent chat "中芯国际最近资金流怎么样？"

# 生成收盘日报（agent 驱动 + 记忆注入）
uv run mommy-agent report --board-code BK0475 --board-name 半导体

# 盘中智能扫描
uv run mommy-agent scan

# 查看预测历史和验证结果
uv run mommy-agent predictions
uv run mommy-agent verify
```

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

---

## 架构

```
                Web UI (Vite + Vue 3)
                    |
                    | HTTP / WebSocket
                    v
              FastAPI (uvicorn)
               /     |      \
              /      |       \
    Cache Layer   Agent     Data Sources
    (SQLite)    Service    (efinance / tencent)
                  |
           MemoryPipeline ---- EpisodicMemory
                  |          -- PredictionTracker
                  |          -- SemanticMemory
                  |          -- VectorSearch
                  |
           ToolRegistry (21 tools)
```

### 数据库布局

4 个按职责分离的 SQLite 数据库，互不干扰：

| 数据库 | 用途 | 关键表 |
|---|---|---|
| `data/market.db` | 行情数据 | quote_cache, bar_cache, klines, flows |
| `data/portfolio.db` | 用户数据 | groups, stock_entries, positions |
| `data/agent.db` | 记忆系统 | episodic_events, predictions, semantic_knowledge, insight_summary |
| `data/reference.db` | 参考库 | semicon_stocks, earnings_* |

### 核心设计原则

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

```
mommy-chaogu
├── mommy-watchlist    # 自选股管理（分组 / 增删 / 告警 / 导出）
├── mommy-monitor      # 实时监控（快照 / 持续轮询 / 信号日志）
├── mommy-cache        # 缓存管理（命中率 / warmup / refresh）
├── mommy-report       # HTML 报告渲染
├── mommy-flows        # 资金流拉新 + 板块扫描 + 收盘日报
├── mommy-semicon      # 半导体产业链查询
├── mommy-earnings     # 财报前瞻 vs 实际 比对
├── mommy-agent        # AI 行情助手（chat / report / scan / verify / consolidate ...）
├── mommy-mcp          # MCP Server（stdio 协议，可接入 Claude Desktop）
└── mommy-web          # Web 服务（REST API + WebSocket）
```

`mommy-agent` 子命令：

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

---

## 自动化

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

## 开发

### 代码质量

```bash
uv run ruff check .          # lint
uv run ruff format .         # format
uv run mypy --strict src     # type check (0 errors)
uv run pytest -m "not network"  # 700+ 离线测试
```

### 项目结构

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

### 文档

| 文档 | 用途 |
|---|---|
| [PROGRESS.md](docs/PROGRESS.md) | 当前进度 + 里程碑 |
| [DESIGN.md](docs/DESIGN.md) | 架构设计 + ADR |
| [MEMORY-SYSTEM-PLAN.md](docs/MEMORY-SYSTEM-PLAN.md) | 记忆系统设计（5 层架构 + MemoryPipeline） |
| [BACKTEST-REPORT.md](docs/BACKTEST-REPORT.md) | 回测报告（多模型横向对比） |
| [EVALUATION-2026-07-05.md](docs/EVALUATION-2026-07-05.md) | 记忆系统 + 回测系统评估报告 |
| [EARNINGS-HANDBOOK.md](docs/EARNINGS-HANDBOOK.md) | 财报窗口实战手册 |
| [KLINE-SPEC.md](docs/KLINE-SPEC.md) | K 线组件规范 |

---

## 项目数据

| 指标 | 值 |
|---|---|
| 代码量 | ~38,000 行（src ~25,000 + tests ~10,000 + web ~3,000） |
| 测试 | 700+ passed（离线 + 网络 marked） |
| CLI 子应用 | 12 个 / 子命令 50+ |
| Agent 工具 | 21 个 function-calling tools |
| 数据库 | 4 个（market / portfolio / agent / reference） |
| Cron 自动化 | 6 个定时任务 |
| LLM Provider | 4 个（deepseek / openai / kimi / z.ai） |

---

## 贡献

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

## License

[MIT](LICENSE)

---

**免责声明**：本项目仅供学习和个人投资参考，不构成任何投资建议。A 股投资有风险，入市需谨慎。
