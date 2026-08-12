# AGENTS.md

> 给 AI agent（和人类开发者）的项目指南。开始工作前先读这份。

## 快速上手

```bash
uv sync --extra dev      # 安装依赖
uv run pytest -m "not network"   # 跑测试（2,082 个离线用例，另有 14 个网络探针）
uv run ruff check .      # lint
uv run mypy --strict src # type check
```

## 密钥配置

推荐运行 `uv run mommy setup`，交互式选择 Provider / 模型、隐藏输入并验证 Key，
还可继续扫码连接微信。安装用户的配置默认保存到
`~/.config/mommy-chaogu/.env`（`0600`，不入仓）；只有当前仓库的项目 `.env` 已包含
有效 Provider 或 API key 时才会就地更新。可用 `--local` / `--user` 显式选择作用域，
用 `--check` 脱敏检查生效来源：

```bash
cp .env.example .env       # 复制模板
# 编辑 .env，填入需要的 key
```

支持的 key（根据生效的 `AGENT_PROVIDER` 自动读取对应的一项）：

| Provider | 环境变量 | 说明 |
|---|---|---|
| deepseek（默认） | `DEEPSEEK_API_KEY` | DeepSeek API |
| openai | `OPENAI_API_KEY` | OpenAI / 兼容接口（有 embedding 接口，向量检索可用） |
| kimi | `MOONSHOT_API_KEY` | Moonshot / Kimi |
| zai | `ZAI_API_KEY` | z.ai / GLM-4.7 |
| minimax | `MINIMAX_API_KEY` | MiniMax 开放平台按量 API（M3，非 Coding Plan） |
| — | `SERVER_CHAN_KEY` | Server酱微信推送 |
| — | `AGENT_PROVIDER` | 覆盖 provider（不重启改 .env） |
| — | `AGENT_MODEL` | 覆盖聊天模型名 |

优先级：shell 环境变量 > 项目 `.env` > 用户级 `.env` > 代码默认值。Provider 与 model
按来源成组解析，禁止跨层拼接；`config.toml` 仅用于可选高级 Web 参数。provider 配置表
（base_url / 默认模型 / env key / 温度 / embedding 模型）的单一真相源是
`src/mommy_chaogu/agent/llm.py`——改 provider 只动它，不要另起表。

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
| `data/agent.db` | Agent 个人数据（记忆 + 策略卡） | agent_memory, episodic_events, predictions, semantic_knowledge, strategy_cards |
| `data/reference.db` | 参考库（半导体产业链 + 业绩） | semicon_stocks, earnings_* |

数据根目录可通过 `MOMMY_DATA_DIR` 覆盖，单库路径可通过环境变量覆盖：
`MOMMY_MARKET_DB` / `MOMMY_PORTFOLIO_DB` / `MOMMY_AGENT_DB` / `MOMMY_REFERENCE_DB`。
源码仓库默认使用 `data/`；全局安装默认使用 `~/.local/share/mommy-chaogu/`。

定义在 `src/mommy_chaogu/db_paths.py`。

## 项目结构

```
src/mommy_chaogu/
├── market_data/     # 数据源适配层（massive + yahoo 美股 + efinance + tencent fallback）
├── cache/           # SQLite 缓存（5 张表 + 节流 + freshness）
├── watchlist/       # 自选股（SQLite + SQLAlchemy 2.0）
├── monitor/         # 实时监控
├── signals/         # 7 条内置告警规则 + 自定义告警
├── flows/           # 资金流 ratio 信号 + 监控 + 收盘日报
├── earnings/        # 业绩前瞻 vs 实际 比对
├── agent/           # LLM agent（llm.py provider 真相源 + tools/ 包按域拆分 36 工具 + MCP + 记忆系统 5 层 + Strategy Cards）
├── strategy/        # 用户确认的策略卡校验、版本、来源与监控关联
├── workflow/        # 自然语言工作流引擎（9 个预定义工作流 + NLRouter + Executor）
├── portfolio/       # 持仓 + 组合分析
├── backtest/        # 回测引擎（引擎 + 统一评分 + 成本 + 组合 + walk-forward + regime）
├── semicon/         # 半导体产业链参考库
├── web/             # FastAPI + WebSocket
├── tui/             # Textual 终端 UI（单屏对话即界面的投研 Coding Agent CLI）
├── services/        # 统一数据服务层（工具层和 API 层共用）
├── push/            # Server酱微信推送
├── channels/        # 本地消息网关（微信二维码授权 + 私聊长轮询）
├── db_paths.py      # 统一数据库路径管理
└── cli.py           # argparse 入口（含 mommy 自然语言入口 + 13 个透传子命令）
```

## 自然语言入口

项目有两层 CLI 入口：

1. **`mommy` — 面向用户的自然语言入口**（主要入口）
   - 输入自然语言，系统自动匹配预定义工作流或 fallback 到 LLM agent
   - `uv run mommy` → 交互式 REPL
   - `uv run mommy 今天怎么样` → 单次查询
   - `uv run mommy watchlist list` → 结构化子命令（直接透传，不需要 --raw）
   - `uv run mommy setup` → Provider / 模型 / Key / 微信统一配置引导
   - `uv run mommy -v "今天怎么样"` → 显示详细路由 + 工具调用信息

2. **底层 CLI 子命令**（向后兼容，高级用户 + CI）
   - `mommy-watchlist` / `mommy-monitor` / `mommy-cache` / `mommy-flows` 等
   - 这些命令保留向后兼容，推荐使用 `mommy <子命令>` 风格
   - `mommy agent detect|plan|connect|doctor|repair --json` → Agent-managed 安装/诊断契约；plan
     先展示文件和权限，真实 MCP 探针通过也不等于首次价值完成
   - `mommy connect claude|kimi|cline|codex` → 兼容入口，安装 onboard/research/strategy 三个
     Skill + 注册本地 MCP；新连接默认 market-only，显式 `--profile personal` 才开放个人能力

工作流引擎见 `src/mommy_chaogu/workflow/`：
- `engine.py` — Workflow / WorkflowRegistry / WorkflowExecutor
- `definitions.py` — 9 个预定义工作流（morning_brief / stock_analysis / sector_scan 等）
- `router.py` — NLRouter（正则匹配优先，fallback 到 AgentService）

Agent 交互指导见 `docs/AGENT-INTERACTION-GUIDE.md`。

## TUI 终端界面

`uv run mommy-tui` → 单屏对话即界面的投研 Coding Agent CLI（类似 Claude Code CLI），
无模式切换：TopBar（指数 + AI 状态 + 时钟）+ 对话流 + 输入框，启动焦点在输入框。

- 对话流内渲染富卡片（不跳屏）：slash 命令 `/today` `/watch` `/portfolio`
  `/flows [code]` `/quote <code>` `/predictions` `/signals` `/memory` `/status`
  `/help` `/clear` `/theme` `/quit`
- `@` 股票联想（自选股 + 半导体库 + quote_cache 名称模糊匹配，Tab 插入代码）；
  直接输入 6 位代码 Enter 看报价卡
- agent 工具结果 → 富卡片渲染器（`tui/services/renderers.py`）：get_quote→报价卡、
  get_money_flow_today→资金流卡、get_bars→迷你表、get_prediction_history→预测卡
- 键盘：Enter 发送（busy 时排队，轮次结束自动发）；Esc 中断当前轮（保留已流部分）；
  PgUp/PgDn 滚动；Ctrl+P 命令面板；Ctrl+C 双击退出

- `src/mommy_chaogu/tui/app.py` — App 主类（单屏 compose）+ `main()` 入口
- `tui/services/bootstrap.py` — Services 容器（DataService / AgentBridge / FakeServices
  + 指数/信号/@联想数据源）
- `tui/services/renderers.py` — 工具结果 → 卡片分发；`tui/services/errors.py` — 错误文案友好映射
- `tui/views/chat.py` — 对话视图（流式 + 卡片容器 + slash/@ 联想 + busy 排队 + Esc）
- `tui/widgets/` — TopBar / cards（10 种富卡片）/ ToolIndicator / WorkingIndicator / HintBar

## Web 前端

`uv run mommy-web` → Vue 3 + shadcn/vue + Tailwind v4。

- 桌面端侧边导航 + 移动端底部 tab（响应式）
- 9 个页面：仪表盘/行情/主题/持仓/AI对话/个股详情/信号/设置/主题详情
- shadcn 组件（reka-ui）+ lucide 图标
- A 股配色（红涨绿跌）+ 深色/浅色模式
- klinecharts K 线图 + WebSocket 实时推送

## 产品交付原则（高于工程偏好）

mommy-chaogu 是直接服务最终用户的应用，不是为其他应用提供抽象能力的平台。工程正确性用于
支撑用户结果，不能取代用户结果。规划、实现和评审时遵守以下顺序：

1. **先定义用户可感知的完成事件**：写清目标用户、当前问题、最短使用路径，以及用户最终能
   看到、理解或完成什么。代码存在、schema 完整、测试通过、hash 可复现都不能单独算功能完成。
2. **先做最小纵向闭环**：优先交付一条用户能实际走通的路径，再补通用 runtime、抽象层、发布
   矩阵和广泛兼容性。每个技术任务必须说明它直接解锁哪一个用户步骤；说不清则默认延后。
3. **先盘点现实资源**：立项前核实现有数据覆盖与时间语义、可复用算法、存储/监控入口、外部
   依赖稳定性和维护成本。缺少关键前提时缩小目标或明确降级，不用未来能力假装当前可交付。
4. **最小必要工程与验证**：复用现有服务和入口，只建设当前闭环必需的支持；验证力度与实际风险
   和项目成熟度相称。不得用额外框架、通用编译器、复杂 gate 或大规模工程加固替代用户验收。
5. **产品来源不得倒置**：当前用户确认的意图和已批准产品文档高于 Draft RFC、示例、测试夹具和
   临时 spike。后者只能验证产品，不能自行定义产品。发现实现开始围绕夹具或技术指标优化时，
   立即停止并回到原始用户旅程复核。
6. **研究能力诚实命名**：没有确认的数据复权/时间语义、样本覆盖、信号定义、组合构造和评价方法
   时，不得承诺或宣称“真实回测”。可将结果标为示例计算、探索性观察或当前状态评估；如果它不
   改善当前用户体验，就不进入本阶段。

计划中的每个阶段至少包含一个用户可观察的产物或行为及其验收方式。评审优先询问“用户现在多了
什么能力、能否亲自感受到”，再检查支撑它的工程是否足够正确；不要反过来以工程完成度推导产品完成。

## 开发规范

- **Python 3.12+**，用 `uv` 管理依赖
- **ruff format + ruff check** — 代码风格
- **mypy --strict** — 类型检查（豁免模块清单与收敛方向见 `docs/TECH-DEBT.md`）
- **Conventional Commits** — `feat / fix / docs / refactor / chore`
- 数据金额一律 `Decimal`，不用 `float`
- 数据源走 `MarketDataAdapter` Protocol，加新源只实现 Protocol
- provider 配置只改 `agent/llm.py` 的 `SUPPORTED_PROVIDERS`（service/config/backtest/MCP 全部引用它）；LLM client 一律经 `llm.create_client()` 构造（显式 timeout + 关 SDK 内置重试，重试由应用层统一）
- 新增 agent 工具：在 `agent/tools/` 对应域模块（quote/sector/flows/bars/holdings/intel/alerts/memory/themes）的 `DEFS` 与 `HANDLERS` 各加一项，`registry.py` 自动聚合（import 时校验两边名字一致），无需改注册表
- 拉新失败保留旧数据（数据库是唯一真相源）
- 新增模块在 `db_paths.py` 里定义数据库路径，不要硬编码
