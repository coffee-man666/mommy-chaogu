# Agent 接口设计反思

> 记录 agent 接口的进化过程、设计决策、踩过的坑。
> 不记录 bugfix 细节和 changelog，只关注"agent 怎么连接数据和能力"这件事。

---

## 背景：四种 Agent 模式

项目有四个 agent 入口，共享同一套工具层和记忆系统：

| 模式 | 入口 | 推理者 | 数据获取 | 记忆 | 工作流 |
|---|---|---|---|---|---|
| ① 内置 AgentService | `uv run mommy` / `mommy-web` | 项目内置 LLM | 23 个封装工具 | ✅ 5 层 | ✅ 正则优先 |
| ② MCP Server | 外部 agent 连 `mommy-mcp` | 外部 LLM | 通过 MCP 调同样的 23 个工具 | ✅ 查询工具 | ❌ |
| ③ Coding Agent | 在项目目录开 Kimi Code / Claude | 外部 LLM | 读文件 / 跑命令 / 查 DB | ❌ | ❌ |
| ④ 回测 Agent | `scripts/backtest_llm.py` | 脚本内 LLM | 直接读 SQLite | ✅ 可选 | ❌ |

模式 ② 和 ③ 的本质区别：② 通过 MCP 协议调项目封装好的工具（有缓存、有 fallback、有资金流计算），③ 是 agent 自己想办法找数据。② 有记忆查询能力，③ 没有。

模式 ① 是项目的主设计——双层路由（正则工作流优先，LLM 自主对话兜底）+ 5 层记忆系统 + 统一工具层。

---

## 核心设计原则：工具层是能力原语

所有入口共享 `ToolRegistry`。加一个工具 = Web Agent / CLI Agent / MCP Server 三个入口同时获得能力。

```
ToolRegistry (23 tools)
  ├─ Web Agent (deps.py → AgentService)
  ├─ CLI Agent (cli.py → AgentService)
  └─ MCP Server (mcp_server.py)
```

工具是项目的"能力 API"——不是 REST API，而是 LLM 可调用的 function-calling 接口。每个工具是一个独立的能力单元：有明确的 schema（参数 + 返回）、独立的 handler、统一的错误处理（异常返回 `{"error": ...}` 而不是崩溃）。

---

## 进化记录

### v1: 21 工具 — 行情 + 基础分析

初始工具集覆盖了看盘核心需求：

- 行情（7）：报价 / 批量报价 / 指数 / 板块排行 / 搜板块 / 成分股 / K 线
- 资金流（2）：当日 / 历史
- 用户数据（3）：自选股 / 持仓 / 风险分析
- 新闻公告（4）：新闻 / 公告 / 龙虎榜 / 基本面
- 操作（3）：回填历史 / 告警管理 / 市场叙事
- 记忆查询（2）：相似事件检索 / 预测历史

**设计决策**：工具只做数据获取，不做"分析"——分析交给 LLM。工具返回结构化 JSON，LLM 负责解读和叙事。这保证了工具的复用性（工作流和 agent 都能用同一套工具）。

### v2: 23 工具 — 主题/产业链能力补全

**问题暴露**：用户通过 Web 对话问"看看半导体供应链"，agent 用 `search_sector` 搜东财板块 API，东财没有"半导体供应链"这个概念，返回空。agent 回复"暂未获取到数据"。

但项目其实有 106 只半导体产业链股票的完整数据（`supply_chains/semiconductor.json` + `reference.db`），只是工具层访问不到。

**反思**：工具层的覆盖范围决定了 agent 的能力边界。LLM 再聪明，没有工具也拿不到数据。这是一个"能力盲区"——数据在项目里，但没暴露给 agent。

**修复**：加 `list_themes` + `get_theme_stocks` 两个工具。三个入口自动获得能力。

**教训**：每次给项目加新数据源（供应链、业绩、回测结果等），必须同时考虑：agent 能不能访问到？如果不能，要么加工具，要么加 Web API 路由。数据不暴露 = 不存在。

---

## 接口设计中的坑

### 坑 1: 路由 prefix 导致 WebSocket 路径错位

**现象**：Web 对话发消息，WebSocket 崩溃，日志报 `assert scope["type"] == "http"`。

**根因**：`agent.router` 有 `prefix="/api/agent"`，WebSocket 注册为 `@router.websocket("/ws/agent")`，实际路径变成 `/api/agent/ws/agent`。前端连 `/ws/agent` 匹配不到任何路由 → 落到 `app.mount("/", StaticFiles)` → StaticFiles 断言只处理 HTTP → 崩溃。

**教训**：FastAPI 的 prefix 对 WebSocket 路由同样生效，这点容易被忽略。WebSocket 路由应该放在无 prefix 的 router 里，或者注册时使用完整路径。

### 坑 2: 前端 WebSocket 不等连接建立就发消息

**现象**：前端报"WebSocket 连接失败"。

**根因**：`new WebSocket()` 返回时连接还在 `CONNECTING` 状态。前端立即调 `ws.send()`，消息丢失或触发 `onerror`。

**教训**：WebSocket 是异步的。`new WebSocket()` ≠ 已连接。必须等 `onopen` 回调后才能 `send()`，或者用消息缓冲队列。

### 坑 3: Provider 配置读取不统一

**现象**：Web 对话返回"AI 助手未配置"，但 `.env` 里明明配了 `ZAI_API_KEY`。

**根因**：`web/deps.py` 的 `get_agent_service()` 硬编码只查 `DEEPSEEK_API_KEY` 和 `OPENAI_API_KEY`。用 zai/kimi provider 时 key 读不到。

**反思**：项目有三层配置（shell env > .env > config.toml），`config.py` 的 `load_config()` 已经做了统一解析。但 `deps.py` 绕过了它，直接查环境变量。这是一个"配置读取入口不统一"的问题。

**教训**：所有需要读配置的地方都应该走 `load_config()`，不要直接 `os.environ.get()`。配置解析逻辑应该集中在一处。

---

## 当前工具清单（23 个）

| 类别 | 工具 | 数据来源 |
|---|---|---|
| **行情** | get_quote / get_quotes | CachedMarketDataAdapter |
| | get_market_indexes | 东财指数 API |
| | get_sector_ranking / search_sector / get_sector_stocks | 东财板块 API |
| | get_bars | CachedMarketDataAdapter |
| **资金流** | get_money_flow_today / get_money_flow_history | CachedMarketDataAdapter |
| **主题/产业链** | list_themes | supply_chains/*.json + earnings_preview.json |
| | get_theme_stocks | supply_chains JSON + 实时行情 |
| **用户数据** | get_watchlist | WatchlistStore (portfolio.db) |
| | get_portfolio / get_portfolio_analysis | PortfolioStore (portfolio.db) |
| | manage_alert | CustomAlertStore (portfolio.db) |
| **新闻公告** | search_news / get_announcements / get_longhuban / get_fundamentals | 东财 API |
| **操作** | backfill_history | CachedMarketDataAdapter |
| | get_market_narrative | EpisodicMemory + LLM |
| **记忆查询** | search_similar_events | VectorSearch (sqlite-vec) |
| | get_prediction_history | PredictionTracker (agent.db) |

---

## 待解决的接口设计问题

### 1. record_analysis 的静默降级

`MemoryPipeline.record_analysis()` 在对话结束后自动提取 observations + predictions。但它是用 LLM 做提取的——需要额外一次 API 调用。如果这次调用失败（网络/超时/格式错误），静默降级只 log warning。

**结果**：对话记忆（agent_memory）写成功了，但 episodic_events 和 predictions 没有新增。用户以为记忆系统在工作，实际上只工作了一半。

**待思考**：是否应该在 Web UI 上提示"记忆提取失败"？还是保持静默？

### 2. 向量检索层缺失

`episodic_embeddings` 表不存在（sqlite-vec 未加载）。代码有降级——降级为关键词搜索。但 agent 的 `search_similar_events` 工具因此只能做关键词匹配，无法做语义搜索。

**影响**：agent 无法"语义回忆"——比如用户问"上次茅台跌的时候你怎么说的"，agent 无法通过语义找到相关的历史对话。

### 3. Coding Agent 模式的能力边界

当用户用 Kimi Code / Claude 直接在项目目录里操作时（模式 ③），coding agent 有完整的文件系统访问权限。它能读所有 DB、改所有文件、跑所有脚本。这不一定是好事——它可能误删数据、改错配置。

**待思考**：是否需要为 coding agent 提供"安全沙箱"指引？比如在 `AGENTS.md` 里标注哪些路径只读、哪些操作需要确认。

### 4. 工具粒度

当前 23 个工具粒度偏细——`get_quote` 和 `get_quotes` 分开、`get_money_flow_today` 和 `get_money_flow_history` 分开。这对 LLM 来说是好事（schema 清晰），但如果工具数继续增长（30+），LLM 选择工具的准确率会下降。

**待思考**：是否需要引入工具分类/分组？或者让 NLRouter 的工作流也覆盖更多场景，减少 LLM 需要自主选工具的频率？

---

## 设计原则总结

1. **工具是能力原语** — 每个工具是一个独立能力单元，三个入口共享。加数据源 = 加工具。
2. **数据不暴露 = 不存在** — 项目里有的数据，必须通过工具或 API 暴露给 agent，否则 agent 用不了。
3. **工具只做数据获取，分析交给 LLM** — 保证工具的复用性。
4. **统一配置入口** — 所有配置读取走 `load_config()`，不要直接查环境变量。
5. **记忆系统可选可降级** — 任何一层记忆组件失败都不阻塞主流程，但要有手段让用户知道。
