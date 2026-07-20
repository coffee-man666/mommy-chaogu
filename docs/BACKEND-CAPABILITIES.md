# 后端能力与用法参考（前端 / TUI 设计用）

> 读者：设计或开发 Web App / TUI / 任何新前端的人（或 AI agent）。
> 本文只描述**后端能给你什么、怎么拿、什么形状、什么坑**，不描述前端怎么画。
> 最后核对：2026-07-18（v1.0.0 之后的 main）。契约事实均标注源码位置，发现出入以代码为准。

---

## 1. 三种消费方式

后端同一套能力有三条入口，按你的前端形态选：

| 方式 | 适用前端 | 入口 | 特点 |
|---|---|---|---|
| **HTTP + WebSocket API** | 浏览器 / 手机 / 远程 | FastAPI（默认 `127.0.0.1:8000`） | 有鉴权、限流、降级约定；跨进程 |
| **Python 服务层（in-proc）** | TUI / CLI / 脚本 | 各模块 Store/Service 直接 import | 无鉴权；类型是 dataclass/Decimal；本项目 TUI 就是这么做的（`tui/services/bootstrap.py`） |
| **CLI 子命令** |  shell / cron / 人类 | `mommy <cmd>` + 14 个入口 | 非程序化接口，仅供参考能力边界 |

API 与服务层是**同一批能力**的两层皮：web routes 调用模块 Store/Service，agent tools 也是。
`services/` 目录目前只有 `ThemeService` 一个统一服务，其余能力由模块级 Store/Service 直接提供。

---

## 2. 通用约定（设计前必读）

### 2.1 数字与金额

- **金额一律 `Decimal`，禁止 float**。HTTP JSON 中 Decimal 序列化为**字符串**（如 `"1850.00"`）；手写 dict 的路由也显式 `str(...)`。`int` 只用于 volume/shares/计数。
- 前端做加总/比较前先把字符串转回高精度数；展示用 万/亿 格式化（参考实现 `tui/services/formatting.py`：`format_amount` 1.2亿 / 10.0万 / 99.00，`format_flow` 带符号）。
- 比值类字段：`main_net_ratio`（主力净流入/流通市值）、`change_pct` 等是 Decimal 或 null。

### 2.2 时间

- datetime → ISO 8601 字符串；naive 一律按 UTC；date → `"YYYY-MM-DD"`。
- **市场阶段按 Asia/Shanghai**（参考实现 `tui/widgets/top_bar.py` 的 `market_phase()`）：
  `集合竞价`（9:15–9:30）/ `交易中`（9:30–11:30, 13:00–15:00）/ `午休`（11:30–13:00）/ `已收盘`（其余 + 周末）。
- 刷新节奏建议（TUI 现行值）：交易中 5s、午休 60s、收盘/周末不自动刷。Web 端由服务端 poller 统一 5s 推送（`--poll-interval` 可调）。

### 2.3 配色（A 股约定）

- **红涨绿跌**：涨/净流入 → 红 `#e5484d`；跌/净流出 → 绿 `#2f9e6e`；平/无数据 → 灰 `#8a8f98`。
- 色盲友好模式：绿 → 蓝 `#3b82f6`（红不变）。参考实现 `change_color()`（`tui/services/formatting.py`）。

### 2.4 数据新鲜度（必须展示）

行情可能来自实时接口或本地缓存，**前端必须展示来源标签**，否则用户会误判：

- `CachedMarketDataAdapter.format_source_label()` → `"东方财富 实时"` / `"腾讯财经 实时"` / `"本地缓存"` / `""`
- 底层 `last_source` 五态：`network / cache / stale_cache / snapshot / stale_snapshot`
- 约定：**拉新失败保留旧数据**（stale_cache），数据库是唯一真相源；QuoteOut 里有 `data_age_seconds` 可直接显示"数据年龄"。

### 2.5 错误形状与降级

- 业务错误：`{"detail": str}` + 状态码（400/404/409/503）；参数校验 422（FastAPI 默认）。
- 认证 401 `{"detail": "Missing or invalid owner token"}`；限流 429 `{"detail": "Agent is busy; retry shortly"}` + `Retry-After: 1`。
- **降级约定**：财报/预测/历史类路由失败时返回空列表 + 200（不报错）——前端要把"空"和"出错"分开处理不了，只能按空态展示。
- 快照未生成时 `GET /api/quotes` 返回 503（启动后极短窗口，重试即可）。

### 2.6 安全边界（远程访问时）

- 默认只监听 `127.0.0.1`；非本机监听必须配置 `MOMMY_API_TOKEN`（否则拒绝启动）。
- 所有 `/api/*` 受 Bearer 保护（唯一公开：`GET /api/health`）。token 未配置 = 全部放行（本机模式）。
- WebSocket 用短期 ticket：`POST /api/auth/ws-ticket`（本身需 Bearer）→ `{ticket, expires_at}`，TTL 默认 60s；WS URL 带 `?ticket=`；**ticket 一次性握手用，重连需重新取**。
- Agent 并发槽位默认 2，占满返回 429——前端要排队或提示"助手忙"。
- CORS 默认关闭，需显式配置 origin。

---

## 3. 数据能力目录

每个领域给出：能力 / REST 入口 / Python 入口 / 关键数据形状 / 边界情况。
CLI 对照见 §7；完整 REST 契约见 §4；Python 签名见 §6。

### 3.1 行情（quotes / market）

**能力**：个股实时报价、K 线（8 种周期 × 3 种复权）、5 档盘口、大盘 6 指数、板块排行、涨跌榜。

- REST：`/api/quotes`、`/api/quotes/{code}`、`/bars`、`/orderbook`、`/api/market/indexes|sectors|gainers|losers`
- Python：`MarketDataAdapter` Protocol（`market_data/adapter.py:33`）：`get_quote / get_quotes / list_market_quotes / get_bars / get_order_book / get_ticks / health_check`
- 关键形状：`QuoteOut` = `{code, name, market("SH"|"SZ"), price, change, change_pct, volume, turnover, open, high, low, prev_close, pe, pb(恒null), turnover_rate, volume_ratio, main_net_inflow, timestamp, fetched_at, data_age_seconds}`
- `SnapshotOut`（全池快照）= `{timestamp, quotes[], total_main_net, n_codes, n_up, n_down, n_flat}`
- bars 参数：interval ∈ `1m/5m/15m/30m/60m/1d/1w/1M`；adjustment ∈ `none/forward/backward`；limit ≤ 500
- **边界**：涨跌榜已过滤 ST/退市/涨跌幅>11%；`get_quote` 未找到返回 404；多空盘接口（orderbook）仅交易时段有数据。

**Fallback 语义**：适配器按 `[东财 → 腾讯]` 顺序逐源尝试，单方法独立 fallback；`FallbackAdapter.stats()` 暴露 `{primary_hits, fallback_hits, all_fail}`（`market_data/fallback_adapter.py`）。前端无需感知，只需展示 `format_source_label()`。

### 3.2 资金流（flows）

**能力**：当日资金流分时/累计、历史资金流（≤365 天）、主力净流入 ratio（bp）信号、排行、收盘日报。

- REST：`/api/quotes/{code}/money_flow/today|history`（注意：实际 JSON 字段是 `main_net, super_net, big_net, medium_net, small_net, main_ratio`）
- Python：`FlowService.from_default(db_path)`：`pull_today/pull_history(pool, force) -> PullResult{ok, failed, failed_codes, elapsed_seconds}`；`top_today/top_history(pool, n, by, direction) -> list[FlowSummary]`；`show(code, days)`；`stats/clear(pool)`
- `FlowSummary` = `{code, name, main_net, super_large_net, large_net, medium_net, small_net, main_net_ratio, sample_count, period}`
- ratio 信号（`flows/signals.py`）：默认 **4 条**规则（流入/流出 × spike 5bp WARN / surge 10bp CRIT，全部 delta_5min 口径）；`FlowSignal{rule_id, code, name, severity, metric, ratio, delta_ratio, main_net, float_market_cap, note, triggered_at}`
- 股票池抽象 `PoolSource`：`WatchlistPool / SemiconPool / CustomPool`，`build_pool(name, db_path, custom_codes)`
- 收盘日报：`FlowReport.generate(pool, output=...)` → markdown（板块 ratio 汇总 + 净流入/流出 TOP10 + 矛盾股）
- **边界**：ratio 需要流通市值，拉不到市值的股票不参与 ratio 信号；history 按日期永久缓存。

### 3.3 自选股（watchlist）

**能力**：分组 CRUD + 组内股票条目（同一股票可属多组）。

- REST：`/api/watchlist`、`/groups`（POST/DELETE）、`/stocks`（POST/DELETE，**group 走 query 参数**）
- Python：`WatchlistStore(db_path)`：`add_group`（重名抛 `GroupAlreadyExistsError`）/ `get_or_create_group` / `list_groups() -> [(Group, n_entries)]` / `add_entry`（同组重复幂等）/ `remove_entry` / `list_entries_by_group()` / `get_all_codes()` / `stats()`
- 形状：entry = `{code, name, group, note, added_at}`；`(code, group_id)` 唯一
- **边界**：删分组级联删股（REST 返回 204）；条目 name 可后补（`backfill_name`）。

### 3.4 持仓（portfolio）

**能力**：持仓 CRUD + 加仓/减仓/分红调整 + 加权平均成本 + 实时盈亏快照。

- REST：`/api/portfolio`（汇总）、`/positions`（POST/DELETE）、`/positions/{id}/adjustments`
- Python：`PortfolioStore`：`add_position / add_adjustment(action: buy|sell|dividend) / cost_basis(position) -> (avg_cost, shares) / summary(current_prices)`
- `PortfolioSummaryOut` = `{positions: [{id, code, name, avg_cost, shares, current_price, market_value, total_cost, unrealized_pnl, unrealized_pnl_pct, ...}], total_cost, total_market_value, total_unrealized_pnl, total_unrealized_pnl_pct, n_positions}`
- **边界**：行情拉取失败时 pnl/market_value 为 **null**（前端要区分"亏 0"和"暂无数据"）；buy/sell 调整自动重算股数与加权成本。

### 3.5 信号（signals）

**能力**：7 条内置监控规则 + 用户自定义价格告警 + 触发历史。

- REST：`/api/signals/recent`、`/api/signals/history?limit&rule_id`
- Python：`Alerter.default(log_path=...)` + `signals/rules.py:default_rules()`；`Snapshot.build(rows, id)` 为输入
- `SignalOut` = `{timestamp, code, name, rule_id, severity: info|warning|critical, title, detail, trigger_value, threshold_value}`；组合类信号 code 固定 `"PORTFOLIO"`

7 条内置规则（`signals/rules.py:423`）：

| rule_id | 含义 | 默认阈值 |
|---|---|---|
| `price_change_threshold` | 涨跌幅 | warn 3% / crit 5% |
| `gap_open` | 跳空 | 1.5% |
| `main_flow_threshold` | 主力净流入 | warn 5 千万 / crit 2 亿 |
| `volume_surge` | 量比 | ≥ 2.0 |
| `turnover_surge` | 换手率 | ≥ 5%（INFO） |
| `portfolio_breadth` | 池内同向占比 | 70%（INFO） |
| `portfolio_main_flow` | 池合计主力净流入 | warn 1 亿 / crit 5 亿 |

- 自定义告警（`signals/custom_alerts.py`，agent 的 `manage_alert` 工具底层）：`CustomAlert{code, name, condition, threshold, enabled}`，condition ∈ `price_above / price_below / change_pct_above / change_pct_below`
- **边界**：history 从 `data/signals.log` 文本解析而来，不是结构化表——展示以 `rule_id` 归类即可，别依赖 detail 文本格式。

### 3.6 财报（earnings）

**能力**：披露日历、业绩 actual 拉取、前瞻 vs actual 打分（6 档 verdict）、watch 清单。

- REST：`/api/earnings/calendar`、`/stock/{code}`、`/scores/{code}`（⚠️ scores 路由目前有 bug 恒空，见 §9）
- Python：`EarningsService`：`pull_actual(codes, period) / fetch_calendar / score_one / score_all / watch_calendar(days_ahead=7) / summary(period) -> verdict 分布`
- `EarningsScore` = `{code, name, period, predicted_low/mid/high(%), actual_value(元), actual_growth, gap_to_mid/high, verdict, confidence(0~1)}`
- verdict 六种：`super_beat / beat / meet / miss / deep_miss / unknown`（中文标签见 `earnings/types.py:VERDICT_LABEL`）
- **边界**：actual 来源分 forecast/express/report/guidance 四种（业绩预告/快报/正式报告/指引），优先级不同；period 格式如 `"2026H1"`。

### 3.7 主题产业链（themes / semicon）

**能力**：主题清单（半导体/创新药/机器人/材料/中报观察）+ 成分股 + 主题实时行情合成。

- REST：`/api/themes`、`/api/themes/{id}`、`/api/themes/{id}/quotes`
- Python：`services/theme_service.py` 的 `ThemeService`：`list_themes() / get_theme(id) / get_theme_quotes(id, limit)`
- 主题 = `{id, name, description, total_stocks, subcategories[], source: supply_chain|earnings_preview}`
- 成分股字段随源不同：供应链类 `{code, name, role, level, subcategory, board, note}`；中报观察类另有 `{growth_text, growth_low, growth_high, core_driver, highlight}`
- 半导体库（`semicon/`）枚举：`ChainPosition` 上/中/下游+末端；15 个 `Subcategory`（EDA/存储/MCU/…）；`Board` 主板/创业板/科创板/北交所
- **边界**：主题行情是逐股实时拉取的合成结果，失败个股带 `error` 字段且行情字段为空字符串——前端要画"加载失败"而非"跌停"。

### 3.8 记忆系统（agent memory）

**能力**：对话历史、情景事件、预测跟踪（含验证状态机）、语义知识、向量检索。

- REST：仅 `GET /api/agent/history`（对话）和 `GET /api/agent/predictions`（⚠️ 恒空 bug，见 §9）；其余走 CLI/Python
- Python/CLI（`mommy memory` 背后）：`ConversationMemory.recent()` / `EpisodicMemory.recent(days, scope, limit)` / `PredictionTracker.all(status)` / `SemanticMemory.get_active()`
- 预测状态枚举：`pending / hit / missed / expired / unverifiable`；timeframe ∈ `1d/3d/5d/10d/20d/60d`
- predictions 关键字段：`prediction, direction, rationale, target_price, entry_price, stop_loss, timeframe, verify_after, status, actual_price, actual_change_pct, accuracy_score`
- **设计建议**：预测卡片的重点视觉是 direction（看多/看空）+ status 徽章 + 到期日 verify_after；hit/missed 用红/绿以外的颜色（避免与涨跌混淆，如蓝/橙）。

### 3.9 回测（backtest）

**能力**：规则/LLM 回测、统一评分、成本模型、组合回测、walk-forward、regime 分析。

- 无 REST API；入口是 CLI/脚本（`scripts/backtest_*.py`、`uv run mommy ...` 相关工作流）
- 前端若要做回测页：目前只能展示**已生成的报告产物**（`reports/` 下的 html/md），不适合做交互式回测。

---

## 4. HTTP API 速查表

服务：`uv run mommy-web`（默认 `127.0.0.1:8000`；`$PORT` 可覆盖）。基路径 `/api`。
除 `GET /api/health` 外全部需要 `Authorization: Bearer <MOMMY_API_TOKEN>`。

| 方法 路径 | 用途 | 注意 |
|---|---|---|
| GET `/api/health` | 健康检查（公开） | `{ok, adapter_name, uptime_seconds, last_snapshot_at}` |
| GET `/api/quotes` | 自选池快照 | 未生成时 503 |
| GET `/api/quotes/{code}` | 单股报价 | 404 |
| GET `/api/quotes/{code}/bars` | K 线 | `interval/limit/adjustment` |
| GET `/api/quotes/{code}/orderbook` | 5 档盘口 | 404 |
| GET `/api/quotes/{code}/money_flow/today` | 当日资金流 | items 累计序列 + cumulative |
| GET `/api/quotes/{code}/money_flow/history?days=` | 历史资金流 | days ≤ 365 |
| GET `/api/market/indexes` | 6 大指数 | |
| GET `/api/market/sectors?limit=` | 板块排行 | 行业+概念合并 |
| GET `/api/market/gainers|losers?limit=` | 涨跌榜 | 已滤 ST |
| GET `/api/watchlist` | 全部条目 | |
| GET/POST `/api/watchlist/groups` | 分组列表/新建 | 重名 409 |
| DELETE `/api/watchlist/groups/{name}` | 删分组 | 级联 |
| POST `/api/watchlist/stocks` | 加股票 | body `{code, group, note?}` |
| DELETE `/api/watchlist/stocks/{code}?group=` | 删股票 | group 是 query 参数 |
| GET `/api/portfolio` | 持仓汇总（含实时盈亏） | pnl 可为 null |
| GET/POST `/api/portfolio/positions` | 持仓列表/新建 | buy_date `"YYYY-MM-DD"` |
| DELETE `/api/portfolio/positions/{id}` | 删持仓 | 级联 adjustments |
| GET/POST `/api/portfolio/positions/{id}/adjustments` | 调整记录/新增 | action ∈ buy/sell/dividend |
| GET `/api/signals/recent` | 最近触发 | |
| GET `/api/signals/history?limit=&rule_id=` | 触发历史 | 源自 signals.log |
| GET `/api/cache/stats` | 缓存命中率 + freshness | |
| POST `/api/agent/route` | 工作流路由 | `{matched, workflow_id, reply, steps[]}` |
| POST `/api/agent/chat` | 单轮对话 | `{reply, tools_used[], rounds}`；429 限流 |
| GET `/api/agent/history?session_id=` | 对话历史 | session_id 正则 `[\w-]{1,64}` |
| GET `/api/agent/predictions` | 预测列表 | 按 created_at 降序 |
| GET `/api/earnings/calendar?since=&days_ahead=` | 披露日历 | |
| GET `/api/earnings/stock/{code}` | 个股业绩 | |
| GET `/api/earnings/scores/{code}` | 业绩打分 | 完整比对字段（§9） |
| GET `/api/themes` | 主题列表 | |
| GET `/api/themes/{id}` | 主题详情 | 404 |
| GET `/api/themes/{id}/quotes?limit=` | 主题行情合成 | 失败个股带 error |
| POST `/api/auth/ws-ticket` | WS 票据 | `{ticket, expires_at}`，TTL 60s |

静态资源：`/` 挂载前端 dist（hash 路由，无 SPA fallback 问题）；无 dist 时 `/` 返回服务信息 JSON。

---

## 5. WebSocket 协议

三个端点都在 `/ws/*`，握手需 `?ticket=`（见 §2.6）。断线后**无消息缓存/重放**，重连需重新取 ticket。

| 端点 | 推送 | 说明 |
|---|---|---|
| `/ws/quotes` | 连接即推一份快照，之后每个 poll 周期推 `{"type":"quote_update","snapshot":SnapshotOut}` | 默认 5s |
| `/ws/signals` | 有信号才推 `{"type":"signal_triggered","signals":[SignalOut,…]}` | ⚠️ 字段是 `signals` 复数（§9） |
| `/ws/agent` | 流式对话（见下） | 与 REST 共用并发槽位 |

**心跳**：客户端发纯文本 `"ping"` → 服务端回纯文本 `"pong"`（非 JSON）；服务端不主动 ping。

**`/ws/agent` 帧协议**：

- 客户端发：`{"message": str, "session_id"?: str}`
- 服务端帧序列：
  1. `{"type":"thinking"}`
  2. `{"type":"chunk","text":str}` × N —— **伪流式**：完整回复按 12 字符切片、10ms 间隔发送（不是真 token 流）
  3. `{"type":"done","tools_used":[str],"rounds":int}`
- 错误帧：`{"type":"error","message":str}`（无效 JSON / 无效 session_id / "AI 助手忙，请稍后重试"）
- agent 未配置：`{"type":"done","text":"AI 助手未配置。",...}`
- **设计建议**：chunk 期间渲染打字机效果；`done.tools_used` 只有工具名数组，要做工具耗时/参数可视化需要用 REST `/chat` 拿不到、WS 也没有——目前只有 TUI 走 Python 回调能拿到完整工具事件（§6.4）。

---

## 6. Python 服务层速查（TUI / 桌面前端用）

### 6.1 装配（照抄 TUI 的 bootstrap）

`src/mommy_chaogu/tui/services/bootstrap.py:Services.bootstrap()`：

```python
base = FallbackAdapter([EfinanceAdapter(), TencentAdapter()])
adapter = CachedMarketDataAdapter(base, CacheStore(MARKET_DB))
# adapter: get_quote/get_quotes/get_bars/get_today_money_flow/... + format_source_label()
watchlist_store = WatchlistStore(PORTFOLIO_DB)
portfolio_store = PortfolioStore(PORTFOLIO_DB)
# agent: AgentService(ToolContext(adapter, watchlist_store, portfolio_store, AGENT_DB), ...)
# router: NLRouter(get_default_registry(), WorkflowExecutor(ToolRegistry(ctx), llm_summarizer))
```

数据库路径统一从 `mommy_chaogu.db_paths` 取（`MARKET_DB / PORTFOLIO_DB / AGENT_DB / REFERENCE_DB`，可用环境变量覆盖），**不要硬编码**。

### 6.2 各 Store/Service 方法

见 §3 各领域"Python 入口"，签名与返回字段以源码为准：`market_data/adapter.py`（Protocol）、`watchlist/store.py`、`portfolio/store.py`、`flows/service.py`、`earnings/service.py`、`services/theme_service.py`、`signals/custom_alerts.py`。

### 6.3 工作流路由（NLRouter）

```python
route = router.route(text)          # RouteResult{matched, workflow, fallback_reason}
result = router.execute_route(      # WorkflowResult{workflow_id, steps, summary, fallback_to_agent}
    route, text,
    on_step_start=lambda display_name: ...,        # 步骤开始
    on_step_done=lambda display_name, success: ..., # 步骤结束
)
```

9 个预定义工作流（触发词 → 步骤链）：

| id | 触发示例 | 步骤（→ optional） |
|---|---|---|
| `morning_brief` | 今天怎么样 / 早盘 | 指数 → 板块 → 自选 |
| `market_check` | 大盘怎么样 | 指数 → 板块 |
| `stock_analysis` | 分析 600519 / 600519 怎么样 | 报价 → K线 → 资金流→ |
| `sector_scan` | 半导体板块怎么样 | 搜板块 → 成分股 |
| `flow_check` | 主力在买什么 | 资金流→ → 板块 |
| `portfolio_review` | 持仓怎么样 | 持仓 → 批量报价 → 组合分析→ |
| `earnings_check` | 中报怎么样 | 基本面 → 公告→ |
| `close_report` | 收盘报告 | 指数 → 板块 → 自选 → 持仓→ |
| `add_watchlist` | 加自选 | （引导式占位） |

前端行为约定：命中时先显示 `[匹配: 工作流名]` + 步骤进度（`on_step_*` 驱动），完成后显示 `summary`；未命中 fallback 到 agent 对话。

### 6.4 Agent 工具事件（做工具可视化的关键）

`AgentService.chat(..., on_tool_call=..., on_tool_result=...)`（`agent/service.py`）：

```python
def on_tool_call(fn_name: str, fn_args: dict) -> None: ...      # 执行前
def on_tool_result(fn_name: str, ok: bool, elapsed_ms: int, result: str) -> None: ...  # 执行后
```

24 个工具的**中文显示名映射**（前端可直接复用，`tui/widgets/tool_indicator.py:TOOL_DISPLAY_NAMES`）：

| 工具 | 显示名 | 工具 | 显示名 |
|---|---|---|---|
| get_quote | 查行情 | get_quotes | 批量查行情 |
| get_market_indexes | 查大盘指数 | get_sector_ranking | 查板块排行 |
| search_sector | 搜板块 | get_sector_stocks | 查板块成分股 |
| get_money_flow_today | 查今日资金流 | get_money_flow_history | 查资金流历史 |
| get_bars | 查K线 | get_watchlist | 查自选股 |
| get_portfolio | 查持仓 | search_news | 搜新闻 |
| get_announcements | 查公告 | get_longhuban | 查龙虎榜 |
| get_fundamentals | 查基本面 | get_portfolio_analysis | 持仓分析 |
| backfill_history | 补历史数据 | manage_alert | 管理告警 |
| search_similar_events | 搜相似事件 | get_prediction_history | 查预测记录 |
| get_market_narrative | 查市场叙事 | list_themes | 查主题列表 |
| get_theme_stocks | 查主题个股 | get_memory_context | 查记忆 |

工具结果摘要/耗时渲染规范（dexter 风格）：`⏺ 查行情(code=600519)` → `⎿ 首行摘要 · 1.2s`，参考实现 `tui/widgets/tool_indicator.py`（含 `format_tool_args / format_result_digest / format_elapsed` 可直接复用逻辑）。

### 6.5 记忆系统读取

`MemoryService`（`agent/memory_service.py`）门面：`get_context(query)`（system prompt 注入）、`get_recent_messages()`、`record_conversation()`、`stats()`。
只读展示直接查库：`ConversationMemory / EpisodicMemory / PredictionTracker / SemanticMemory`（均接收 `AGENT_DB` 路径），字段见 §3.8。

---

## 7. CLI 入口对照

`pyproject.toml [project.scripts]`，共 14 个：

| 入口 | 用途 |
|---|---|
| `mommy` | 自然语言主入口（REPL/单发/--setup/--verbose） |
| `mommy-tui` / `mommy-web` | 两个前端 |
| `mommy watchlist/monitor/cache/semicon/flows/report/agent/memory/earnings/...` | 透传子命令 |
| `mommy-mcp` | MCP server（把 24 工具暴露给外部 MCP client） |

`--verbose` 输出路由决策 + 工具调用过程，是调试前端路由展示的参考输出。

---

## 8. 空态 / 错误态 / 加载态清单（设计 checklist)

| 场景 | 后端表现 | 前端应该 |
|---|---|---|
| 未配置 LLM key | `/chat` 返回降级文案；TUI 提示"未配置 AI agent" | 引导配 key；行情/工作流仍可用 |
| 自选股为空 | `quotes` 快照空 / watchlist `[]` | 空态 + `mommy watchlist add` 引导 |
| 持仓为空 | positions `[]`，汇总字段为 0/null | 空态 + 添加持仓引导 |
| 行情接口全崩 | fallback 失败 → stale_cache / `data_age_seconds` 增大 | 展示来源标签"本地缓存" + 数据年龄 |
| 快照未生成 | `/api/quotes` 503 | 启动加载态，自动重试 |
| Agent 忙 | 429 + `Retry-After: 1` | 排队/禁用发送 + 提示 |
| WS 断线 | 无重放 | 自动重连：重新取 ticket → quotes 会立即补一份最新快照 |
| 主题个股拉取失败 | item 带 `error`，行情字段空串 | 显示"加载失败"，不要画成 0 或跌停 |
| 持仓行情缺失 | pnl/market_value 为 null | 显示 "—"，不要显示 0 |
| 财报/预测路由异常 | 空列表 + 200 | 空态（无法与真无数据区分） |

---

## 9. 已知坑的历史记录（2026-07-18 已修复）

以下三个坑曾影响前端，已在 `fix/web-api-pitfalls` 分支修复并附回归测试
（`tests/test_web/test_api_pitfalls.py`）：

1. `GET /api/agent/predictions` 曾调用 `PredictionTracker` 不存在的方法恒返空——
   已改为 `tracker.all(limit=...)`，正常返回预测记录（按 created_at 降序）。
2. `GET /api/earnings/scores/{code}` 曾访问 `EarningsScore` 不存在的 `.score` 属性
   恒返空——已改为返回完整比对字段：`{code, name, period, predicted_low/high/mid,
   actual_value, actual_growth, gap_to_mid, gap_to_high, verdict, confidence}`。
3. `/ws/signals` 推送字段实际是 `signals`（复数数组）——`WSSignalMessage` schema
   已改为与实际一致。

修复前的行为曾记录于此，供旧客户端排查参考。

---

## 10. 现有两个前端样板

- **Web**（`web/src`，Vue 3 + shadcn/vue + Tailwind v4，hash 路由）：9 页——仪表盘/行情/主题/持仓/AI对话/个股详情/信号/设置/主题详情。消费 REST + `/ws/quotes` + `/ws/agent`；token 存浏览器会话（设置页输入）。
- **TUI**（`src/mommy_chaogu/tui`，Textual，双模式 Tab 切换）：AI 对话（工作流路由 + 工具事件可视化 + slash 命令）+ 数据看板（自选/持仓/主题/信号四页）。全部走 Python in-proc 服务层（§6）。

**新前端最小功能集建议**：① 自选股快照 + 来源标签 ② AI 对话（route → chat，展示 `[匹配: X]` 与工具调用）③ 持仓盈亏 ④ 空态/降级处理（§8）。其余能力按 §3 目录逐步叠加。

---

## 相关文档

- [详细架构](DETAILED-ARCHITECTURE.md) · [DESIGN](DESIGN.md) · [K 线规范](KLINE-SPEC.md) · [AGENT 交互指南](AGENT-INTERACTION-GUIDE.md) · [技术债](TECH-DEBT.md)
