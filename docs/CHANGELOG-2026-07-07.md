# 项目改进日志：从 EVAL 修复到 Web 仪表盘 + TUI

> 2026-07-07 | 记录本轮开发的完整历程

---

## 一、起点：EVAL 报告暴露的 9 个问题

2026-07-06 的两份评估报告（`EVAL-SAMPLES` + `EVAL-QUALITY`）列出了 9 个问题，全部未修复：

| # | 问题 | 严重度 |
|---|---|---|
| 1 | DB 路径不一致 — `db_paths.py` 是死代码，全项目 30+ 处硬编码 `data/watchlist.db` | 🔴 |
| 2 | semicon 数据丢失 — CLI 读空的 `semicon.db`，不读 `reference.db` | 🔴 |
| 3 | report index 扫描错误路径 — 扫 `data/flows_report_*.md`，报告在 `reports/` | 🟡 |
| 4 | 参数命名不统一 — `--n` / `--limit` / 无分页 | 🟡 |
| 5 | config 测试隔离缺陷 — `load_dotenv()` 读真实 `.env`，4 个测试失败 | 🔴 |
| 6 | flows 模块零测试 — 1,338 行代码无任何测试 | 🔴 |
| 7 | CI 无覆盖率报告 | 🟡 |
| 8 | cli.py 零测试 — 1,492 行 | 🟡 |
| 9 | 206 个 DeprecationWarning | 🟡 |

---

## 二、修复阶段（main 分支）

### P0-1: config 测试隔离 ✅

**问题**：`load_config()` 无条件调 `load_dotenv()`，真实 `.env` 里 `AGENT_PROVIDER=zai` 和 API key 泄漏到测试。断言错误甚至把真实 API key 暴露在输出里。

**修复**：`tests/test_config.py` 加 autouse fixture，每测试前清除所有相关 env var 并 mock `load_dotenv`。

**结果**：4 failed → 8 passed。

### P0-2: 消灭硬编码 DB 路径 ✅

**问题**：`db_paths.py` 定义了四库分离架构（market/portfolio/agent/reference），但几乎没人 import。`cli.py`、`config.py`、`mcp_server.py`、`web/app.py` 等 30+ 处硬编码旧路径。

**修复**：
- `cli.py` — 6 个 `DEFAULT_*_PATH` 常量改为从 `db_paths.py` import
- `config.py` — `db_path` 默认值 + TOML 模板改为 `data/market.db`
- `agent/mcp_server.py` — `_build_context()` 使用 `MARKET_DB` / `PORTFOLIO_DB`
- `agent/reports.py` — `_collect_pool_data()` 使用三个新路径
- `web/app.py` — push_db 路径使用 `PORTFOLIO_DB`
- 所有 store 类的 docstring 示例更新
- `migrate_db_layout.py` — 修复 `copy_table` 缺少 `commit()` 导致 DETACH 失败的 bug

**数据迁移**：手动将 `semicon.db` 的 106 条半导体数据复制到 `reference.db`。

**验证**：`mommy-semicon stats` → 106 只，`mommy-watchlist list` 正常。

### P1-3: report index 扫描路径 ✅

**问题**：`cmd_report_index` 扫描 `data/flows_report_*.md`，报告实际在 `reports/`。

**修复**：`DEFAULT_FLOWS_REPORT_DIR` 改为 `Path("reports/")`，扫描模式改为 `*.md`，加 try/except 跳过非 flows 格式的报告。

### P1-4: flows 模块补测试 ✅

**新增**：4 个测试文件，93 个测试（原零覆盖）。
- `test_signals.py` (31) — FlowRule / evaluate / StockSnapshot.ratio / FlowSignal.format
- `test_pool.py` (20) — CustomPool / SemiconPool / WatchlistPool / build_pool
- `test_service.py` (29) — FlowSummary / PullResult / pull_today / top_today / stats
- `test_report.py` (13) — 格式化辅助函数 / FlowReport.generate()

**附带修复**：`FlowService.clear()` 的 context manager 使用 bug。

---

## 三、Agent 架构讨论

### 问题提出

用户问：用 Kimi Code / Claude 等 coding agent 直接看项目文件跑，和项目设计的 agent 模式有什么区别？

### 四种 Agent 模式分析

| 模式 | 入口 | 推理者 | 数据获取 | 记忆 | 工作流 |
|---|---|---|---|---|---|
| ① 内置 Workflow + AgentService | `uv run mommy` | 项目内置 LLM | 23 个封装工具 | ✅ 5 层 | ✅ 正则优先 |
| ② 外部 Coding Agent | 在项目目录开 agent | 外部 LLM | 读文件/跑命令/查 DB | ❌ | ❌ |
| ③ MCP Server | 外部 agent 连 `mommy-mcp` | 外部 LLM | 通过 MCP 调 23 个工具 | ✅ 查询工具 | ❌ |
| ④ 回测 Agent | `scripts/backtest_llm.py` | 脚本内 LLM | 直接读 SQLite | ✅ 可选 | ❌ |

### 核心洞察

「用 coding agent 直接跑」≠ 项目设计的 agent 模式。Coding agent 是在当临时数据分析师——通过读代码、跑命令、查数据库完成请求。它没有记忆、没有工作流路由、不安全（有写文件权限）、成本高、用户体验差。

项目的设计意图是：**用户只说自然语言 → 正则匹配 80% 常见问题（零成本）→ LLM 自主选工具兜底 20% 复杂问题 → 5 层记忆系统让 agent 越用越懂**。

---

## 四、Web 仪表盘 + TUI 开发（feat/dashboard-tui 分支）

### 需求

提供两个不同形态的前端：
1. **Web 仪表盘** — 面向普通用户（妈妈），浏览器打开就用
2. **TUI 终端** — 面向开发者/高级用户，SSH 友好、快速查看

两者共享同一套 23 个工具 + 5 层记忆系统 + Workflow 引擎。

### Part A: Web 前端升级

#### 现状评估

原有 `web/` 已有 6 个完整页面（行情/持仓/AI对话/个股详情/信号/设置），移动端布局完整可用。后端 API 核心链路全部就绪。

**主要短板**：纯移动端布局、无组件复用、无状态管理、调仓记录半成品、4 个后端模块未暴露 Web 路由。

#### 改进内容

| 改动 | 文件 |
|---|---|
| Pinia 状态管理 | `stores/portfolio.ts` / `watchlist.ts` / `market.ts` |
| 可复用组件 | `components/PriceText` / `ChangePct` / `StockTag` / `LoadingSpinner` / `EmptyState` |
| 格式化工具统一 | `utils/format.ts` — 消除 3+ 页面重复代码 |
| 响应式布局 | `App.vue` — 桌面侧边导航 + 移动底部 tab |
| Dashboard 首页 | 指数卡片 + 自选股 + 持仓 + AI 入口 + 板块排行 + 信号 |
| 调仓记录 UI | 加仓/减仓/分红表单 + 历史时间线 |
| 分组管理 | 新建/删除分组，二次确认防误操作 |
| 路由 | `/` 按设备宽度分流到 `/dashboard` 或 `/market` |

### Part B: TUI 终端界面

Textual 框架，三栏布局：

```
┌──────────────────────────────────────────────────────────┐
│ 指数行: 上证 3245(+0.8%)  深证 10234(+1.1%)          14:30│
├──────────┬─────────────────────────┬─────────────────────┤
│ 自选股树  │  行情表（5秒刷新）       │  AI 对话面板        │
│ ▸ 白酒    │  600519 茅台 1689 +0.5%│  > 今天怎么样       │
│ ▸ 半导体  │  688981 中芯  48.3 +2.3%│  AI: 上证收涨...    │
├──────────┴─────────────────────────┴─────────────────────┤
│ ● efinance+tencent │ 数据年龄: 3s │ 盈亏: +12,340 (+2.1%)│
└──────────────────────────────────────────────────────────┘
```

| 文件 | 功能 |
|---|---|
| `tui/app.py` | `mommy-tui` 入口 |
| `tui/data_service.py` | 异步数据层，直接调内部 adapter/store |
| `tui/screens/dashboard.py` | 三栏主屏 |
| `tui/screens/detail.py` | 个股详情（报价 + Sparkline + K 线表）|
| `tui/widgets/` | QuoteTable / WatchlistTree / ChatPanel / IndexCards / StatusBar |

### 主题观察页面

5 个主题，284 只股票：

| 主题 | 股票数 | 数据来源 |
|---|---|---|
| 🔧 半导体产业链 | 106 | `supply_chains/semiconductor.json` |
| 💊 创新药 | 38 | `supply_chains/innovative_drug.json` |
| 🤖 人形机器人 | 25 | `supply_chains/humanoid_robot.json` |
| 🧱 材料板块 | 41 | `supply_chains/materials.json` |
| 📊 中报观察 | 74 | `earnings_preview.json` |

主题详情页功能：概览栏（涨/跌/平 + 均价 + 主力合计）、子板块统计、成分股表格（按涨跌/主力/增速排序）、子板块过滤、中报特化（增速 badge + 核心驱动）。

---

## 五、Bug 修复

### Bug 1: WebSocket 连接失败

**根因（前端）**：`agentStream()` 创建 WebSocket 后立即返回 `send()` 方法，但连接还在 `CONNECTING` 状态，`ws.send()` 失败。

**根因（后端）**：`agent.router` 有 `prefix="/api/agent"`，WebSocket 注册为 `@router.websocket("/ws/agent")`，实际路径变成 `/api/agent/ws/agent`。前端连 `/ws/agent` 匹配不到 → 落到 StaticFiles mount `/` → `assert scope["type"] == "http"` 崩溃。

**修复**：
- 前端：加 `onopen` + `pendingMessage` 缓冲
- 后端：把 `/ws/agent` 从 `agent.py` 移到 `ws.py`（无 prefix）

### Bug 2: Agent 不知道"半导体供应链"

**根因**：23 个工具里没有任何一个能读 `supply_chains/*.json` 或 `reference.db`。Agent 只有 `search_sector`（搜东财板块 API），东财没有"半导体供应链"概念。

**修复**：新增 2 个工具（21 → 23）：
- `list_themes` — 列出所有主题
- `get_theme_stocks` — 获取主题成分股 + 实时行情

三个入口（Web Agent / CLI Agent / MCP Server）自动共享新工具。

### Bug 3: Web Agent 不按配置的 provider 读 API key

**根因**：`deps.py` 硬编码只查 `DEEPSEEK_API_KEY` 和 `OPENAI_API_KEY`，用 zai/kimi provider 时 key 读不到。

**修复**：改用 `load_config()` 统一解析（shell env > .env > config.toml）。

---

## 六、当前状态

### 测试

```
893 passed, 13 deselected, 233 warnings in 3.3s
```

（修复前：800 passed, 4 failed）

### 工具数

23 个（原 21 个 + `list_themes` + `get_theme_stocks`）

### 记忆系统状态

| 层 | 数据量 | 状态 |
|---|---|---|
| 对话记忆 (agent_memory) | ✅ 正常写入 | Web 对话每轮都记录 |
| 情景记忆 (episodic_events) | 316 条 | 来自回测验证 |
| 预测追踪 (predictions) | 136 条 (67 hit / 69 missed) | 来自回测 |
| 语义知识 (semantic_knowledge) | 12 条 | 含个股命中率 + 市场规律 |
| 向量检索 (episodic_embeddings) | ❌ 表不存在 | sqlite-vec 未加载（有降级） |
| insight_summary | 0 条 | consolidate 需手动触发 |

### 语义知识亮点

- 比亚迪 (002594)：信号命中率 81%（21 条验证）— 信号最准的股
- 五粮液 (000858)：命中率 71%
- 茅台 (600519)：命中率 67%
- 市场规律：「看跌预测命中率 52%，高于看涨 38%。趋势延续性强」
- 市场状态：「2026年6月，空头或震荡占优」

### 入口一览

| 入口 | 命令 | 适合谁 |
|---|---|---|
| Web 仪表盘 | `uv run mommy-web --port 8000` | 妈妈 / 普通用户（浏览器） |
| TUI 终端 | `uv run mommy-tui` | 开发者（终端 / SSH） |
| 自然语言 CLI | `uv run mommy "今天怎么样"` | 快速查询 |
| MCP Server | `uv run mommy-mcp` | Claude Desktop / 外部 agent |
| 回测 | `uv run python scripts/backtest_llm.py` | 离线验证 |

---

## 七、下一步建议

1. **记忆系统 Web 可视化** — 前端页面查看对话历史、预测记录、知识库
2. **向量检索启用** — 加载 sqlite-vec 扩展，让 agent 能语义搜索历史事件
3. **consolidate 定时任务** — 配 cron 定期提炼知识，填充 insight_summary
4. **真流式 WebSocket** — 改造 AgentService 支持 `stream=True`，逐 token 输出
5. **Docker 部署** — 修 Dockerfile + docker-compose.yml，一键部署
6. **PWA** — 加 manifest.json + service worker，手机可添加到桌面
