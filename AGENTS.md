# AGENTS.md

> 给 AI agent（和人类开发者）的项目指南。开始工作前先读这份。

## 快速上手

```bash
uv sync --extra dev      # 安装依赖
uv run pytest -m "not network"   # 跑测试（1,090 个离线用例，另有 13 个网络探针）
uv run ruff check .      # lint
uv run mypy --strict src # type check
```

## 密钥配置

LLM API key 和推送 key 通过 `.env` 文件持久化（不入仓）：

```bash
cp .env.example .env       # 复制模板
# 编辑 .env，填入需要的 key
```

支持的 key（根据 `config.toml` 里的 `agent.provider` 自动读取对应的）：

| Provider | 环境变量 | 说明 |
|---|---|---|
| deepseek（默认） | `DEEPSEEK_API_KEY` | DeepSeek API |
| openai | `OPENAI_API_KEY` | OpenAI / 兼容接口 |
| kimi | `MOONSHOT_API_KEY` | Moonshot / Kimi |
| zai | `ZAI_API_KEY` | z.ai / GLM-4.7 |
| nova | `NOVA_API_KEY` | Nova Bridge（本地桥接） |
| — | `SERVER_CHAN_KEY` | Server酱微信推送 |
| — | `AGENT_PROVIDER` | 覆盖 provider（不重启改 .env） |

优先级：shell 环境变量 > `.env` 文件 > `config.toml`。

## 数据库布局（2026-07-03 重组）

**⚠️ 如果你是从旧版本升级，请先跑迁移脚本：**

```bash
uv run python scripts/migrate_db_layout.py --check   # 先检查
uv run python scripts/migrate_db_layout.py            # 执行迁移
```

迁移会把旧 `data/watchlist.db`（所有表混在一起）拆分到 4 个按职责分离的数据库：

| 数据库 | 用途 | 关键表 |
|---|---|---|
| `data/market.db` | 行情数据（缓存 + 历史 K 线 + 资金流） | quote_cache, bar_cache, klines, flows |
| `data/portfolio.db` | 用户数据（自选股 + 持仓 + 告警） | groups, stock_entries, positions |
| `data/agent.db` | 记忆系统（对话 + 事件 + 预测 + 知识 + 向量） | agent_memory, episodic_events, predictions, semantic_knowledge |
| `data/reference.db` | 参考库（半导体产业链 + 业绩） | semicon_stocks, earnings_* |

路径可通过环境变量覆盖：`MOMMY_MARKET_DB` / `MOMMY_PORTFOLIO_DB` / `MOMMY_AGENT_DB` / `MOMMY_REFERENCE_DB`

定义在 `src/mommy_chaogu/db_paths.py`。

## 项目结构

```
src/mommy_chaogu/
├── market_data/     # 数据源适配层（efinance + tencent + fallback）
├── cache/           # SQLite 缓存（5 张表 + 节流 + freshness）
├── watchlist/       # 自选股（SQLite + SQLAlchemy 2.0）
├── monitor/         # 实时监控
├── signals/         # 7 条内置告警规则 + 自定义告警
├── flows/           # 资金流 ratio 信号 + 监控 + 收盘日报
├── earnings/        # 业绩前瞻 vs 实际 比对
├── agent/           # LLM agent（24 工具 + MCP + 记忆系统 5 层 + MemoryService 独立服务）
├── workflow/        # 自然语言工作流引擎（9 个预定义工作流 + NLRouter + Executor）
├── portfolio/       # 持仓 + 组合分析
├── backtest/        # 回测引擎（引擎 + 统一评分 + 成本 + 组合 + walk-forward + regime）
├── semicon/         # 半导体产业链参考库
├── web/             # FastAPI + WebSocket
├── tui/             # Textual 终端 UI（沉浸式 AI 对话 + 数据看板双模式）
├── services/        # 统一数据服务层（工具层和 API 层共用）
├── push/            # Server酱微信推送
├── db_paths.py      # 统一数据库路径管理
└── cli.py           # argparse 入口（含 mommy 自然语言入口 + 10 个透传子命令）
```

## 自然语言入口

项目有两层 CLI 入口：

1. **`mommy` — 面向用户的自然语言入口**（主要入口）
   - 输入自然语言，系统自动匹配预定义工作流或 fallback 到 LLM agent
   - `uv run mommy` → 交互式 REPL
   - `uv run mommy 今天怎么样` → 单次查询
   - `uv run mommy watchlist list` → 结构化子命令（直接透传，不需要 --raw）
   - `uv run mommy --setup` → 首次配置引导
   - `uv run mommy -v "今天怎么样"` → 显示详细路由 + 工具调用信息

2. **底层 CLI 子命令**（向后兼容，高级用户 + CI）
   - `mommy-watchlist` / `mommy-monitor` / `mommy-cache` / `mommy-flows` 等
   - 这些命令保留向后兼容，推荐使用 `mommy <子命令>` 风格

工作流引擎见 `src/mommy_chaogu/workflow/`：
- `engine.py` — Workflow / WorkflowRegistry / WorkflowExecutor
- `definitions.py` — 9 个预定义工作流（morning_brief / stock_analysis / sector_scan 等）
- `router.py` — NLRouter（正则匹配优先，fallback 到 AgentService）

Agent 交互指导见 `docs/AGENT-INTERACTION-GUIDE.md`。

## TUI 终端界面

`uv run mommy-tui` → 沉浸式双模式终端（类似 Claude Code CLI），Tab 键切换：

- **模式 A：AI 对话** — Markdown 流式渲染 + 工具调用折叠 + 底部输入框
- **模式 B：数据看板** — TabbedContent（自选股/持仓/主题/信号）+ 状态栏

- `src/mommy_chaogu/tui/app.py` — App 主类（ContentSwitcher 双模式）+ `main()` 入口
- `tui/services/bootstrap.py` — Services 容器（DataService / AgentBridge / FakeServices）
- `tui/views/chat.py` — AI 对话视图（dexter 风格工具指示 + slash 命令 + HintBar）
- `tui/views/dashboard.py` — 数据看板视图（TabbedContent：自选/持仓/主题/信号）
- `tui/screens/stock_detail.py` — 个股详情屏（报价 + K 线表）
- `tui/widgets/` — TopBar / ToolIndicator / WorkingIndicator / HintBar

## Web 前端

`uv run mommy-web` → Vue 3 + shadcn/vue + Tailwind v4。

- 桌面端侧边导航 + 移动端底部 tab（响应式）
- 9 个页面：仪表盘/行情/主题/持仓/AI对话/个股详情/信号/设置/主题详情
- shadcn 组件（reka-ui）+ lucide 图标
- A 股配色（红涨绿跌）+ 深色/浅色模式
- klinecharts K 线图 + WebSocket 实时推送

## 开发规范

- **Python 3.12+**，用 `uv` 管理依赖
- **ruff format + ruff check** — 代码风格
- **mypy --strict** — 类型检查（豁免模块清单与收敛方向见 `docs/TECH-DEBT.md`）
- **Conventional Commits** — `feat / fix / docs / refactor / chore`
- 数据金额一律 `Decimal`，不用 `float`
- 数据源走 `MarketDataAdapter` Protocol，加新源只实现 Protocol
- 拉新失败保留旧数据（数据库是唯一真相源）
- 新增模块在 `db_paths.py` 里定义数据库路径，不要硬编码
