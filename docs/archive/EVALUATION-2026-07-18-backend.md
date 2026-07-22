# 后端系统评估：Agent / LLM 连接 / 记忆系统

> 日期：2026-07-18（v1.1.0 之后的 main，`2684ae9`）
> 范围：`agent/`（service、tools/ 包、记忆系统 9 模块、MCP）、LLM provider 连接层、`workflow/`。
> 方法：三轮并行源码深挖 + 生产库 `data/agent.db` 实测 + 关键结论人工复核
> （本报告中标注 ✅已复核 的结论均由评估者在当前检出上亲自复现）。
> 读者：维护者。结论用于下一轮改进计划（可视为 PLAN-2 的输入）。

---

## 0. 总评

**骨架方向正确，但存在多个"设计已落地、接线未完成"的子系统，以及两个影响数据正确性的实际 bug。**

好的方面（应予保留）：

- Provider 表驱动抽象（`SUPPORTED_PROVIDERS`）、工具定义单一真相源（LLM / MCP / workflow 三方复用 `ToolDef`）、`_run_loop` 单工具失败隔离（异常转 error JSON 继续推理）。
- 记忆系统五层概念分层清晰；extractor / consolidator 的降级路径（LLM 失败跳过、组件缺失跳过）设计良好且有测试。
- SQL 全部参数化绑定，无注入面；`session()` 事务管理统一；WAL/busy_timeout 收口在 `db.py`。
- `tests/test_agent/` 约 190 个用例，覆盖面在同量级项目里算好的。

**但**：本次评估在三个子系统里共发现 **17 个问题**，其中 **7 个为 P0/P1 级**（数据错误、链路断裂、指标失真）。一个反复出现的模式是：某能力"接口和实现都在，但生产装配从不调用它"（向量检索、TokenTracker、ctx.client、cron 入口），且失败时静默降级，用户无感知。

---

## 1. 记忆系统（5 层 + 固化 + 验证）

### 1.1 分层评价

`memory.py`（原始对话）→ `extractor.py`（在线抽取）→ `episodic_memory.py` / `prediction_tracker.py` → `verify_engine.py`（验证）→ `consolidator.py`（离线归纳）→ `semantic_memory.py`（知识），概念边界总体清晰。存在的重叠：

- **两套平行向量实现**：`vector_search.py` 与 `semantic_memory.py:107-197` 内置 vec 逻辑完全重复（pack/unpack、扩展加载、meta 表），无共享 helper。
- `extractor` 越界承担网络 I/O（抽取时逐条预测调 `adapter.get_quote` 补 entry_price，extractor.py:290）。
- facade 层数偏多：MemoryPipeline → MemoryService → prompt_builder，`stats()` 在 pipeline 与 service 间重复。

### 1.2 问题清单（按严重度）

**P1 — `mommy-agent verify` 启动即崩，两条 cron 链路全断。** ✅已复核
`cli_commands/agent.py:78` `VectorSearch(AGENT_DB)` 把 `Path` 当 `EpisodicMemory` 传且缺必填 `client` 参数，`uv run mommy-agent verify` 直接 `TypeError`。`cron_verify.sh`、`cron_consolidate.sh` 都走这条命令。当前唯一可用入口是裸跑 `scripts/cron_verify.py`。

**P2 — 验证窗口宽度为零：到期预测全部直接 expired，从不被验证。**
`verify_after = created_at + timeframe`（prediction_tracker.py:73-81），`get_pending` 取 `verify_after <= now`，而 `verify_one` 的过期判定是 `now > created_at + 同样的天数`（verify_engine.py:47-57,143-144）——两个条件互补，真实窗口只剩同一微秒。内存库实测：`results={'expired': 1}` 且 adapter 未被调用。生产库佐证：136 条预测的 `verified_at` 全部落在 2026-07-06 同一秒（批量回填产物），没有一条是 `verify_pending` 实时验证的。**预测验证闭环实际上从未运行过。**

**P3 — 方向验证口径错误 + neutral 计入 hit，命中率双向灌水。**
`verify_one` 用验证当日的单日 `change_pct` 判定一条 5 日方向预测（verify_engine.py:178,207），而非相对 `entry_price` 的窗口涨跌幅（entry_price 已落库却未用）；`_score_direction` 对 `neutral` 恒返 hit（verify_engine.py:87-88），配合 extractor 缺省 `direction="neutral"`（extractor.py:301），hit_rate 被系统性高估。`tracker.stats()`、consolidator 置信度校准、insight 注入全部建立在这个失真指标上。

**P4 — 向量子系统端到端未接线（死代码），且失败静默。**
`embed_pending()` 与 `attach_vector_search()` 在 src/scripts 中**无任何生产调用方**；`ToolContext.client` 在 CLI/Web/TUI 装配处从不赋值；生产库连向量表都不存在。`search_similar_events` 工具、prompt_builder 的"相似历史事件"段永远走关键词降级。失败路径是裸 `except Exception` 且无日志（semantic_memory.py:147-148,160-161）——坏了也看不见。另：默认 provider 为 DeepSeek 时，其 endpoint 无 embedding 接口，且 `tools/memory.py:117` 把聊天模型名当 embedding 模型传。

**P5 — `store_extraction` 不写 `trade_date`，下游按日期查询静默失效。**
extractor.py:259-271 调 `episodic.write()` 不传 `trade_date`（生产库 317 条事件 137 条为 NULL），而 `query(start_date, end_date)` 过滤的正是 `trade_date`（episodic_memory.py:250-255）→ `narrative.detect_changes()` 的"前 10 天"、`compare_periods()`、`consolidator._consolidate_market_regime` 的 prior 窗口对抽取类事件永远查空，无任何报错。

**P6 — 对话后提取链同步阻塞响应。**
`chat()` 返回前同步执行：一次提取 LLM 调用（extractor.py:174）+ 每条预测一次实时报价。慢调用无超时、无异步化，全部叠加到每轮对话延迟上。

**次要**：`cron_verify.py:71` 用 `CacheStore(AGENT_DB)` 把缓存表写进记忆库（布局污染，生产 agent.db 已被污染）；predictions 价格字段用 `REAL` 存（违反"金额一律 Decimal"约定，prediction_tracker.py:31-41）；`cleanup_*` 不清理向量/meta 表（orphan 只增不减）；同时传 `memory` 且 MemoryService 带 memory 时消息双写（service.py:249-255，当前装配未触发）。

---

## 2. LLM 连接与 AgentService

### 2.1 设计评价

表驱动 provider 抽象方向正确，密钥优先级链（shell env > .env > config.toml）文档清晰。但同一份 provider 表实际有三份：`service.py:47`、`scripts/backtest_llm.py:366-386`（kimi 的 base_url/model 已漂移）、`config.py:36-43`。

### 2.2 问题清单（按严重度）

**L1 — 流式实现：双重计费 + 空串覆盖完整答案。** ✅已复核
最终回答先由非流式调用得出，`_stream_final_answer` 再把**全量 messages 重发一次** stream=True 调用（service.py:496-501）——provider 照常计费，但 usage 刻意不计这次（注释"避免计两次"，service.py:489-491），**token 统计系统性偏低近 2 倍**。更严重的是：流式迭代在第一个 chunk 前异常时返回 `""`（service.py:519-522），调用方 `if streamed is not None: text = streamed`（service.py:367-368）→ **完整的非流式兜底答案被空串覆盖**，用户看到空回答。
另：流式调用独立采样，文本与非流式答案不保证一致，且 `resp.text` 被替换后写入记忆。

**L2 — 零 context 管理。**
循环内 messages 只增不减，唯一上限是 max_tool_calls=10 轮；工具结果零截断——`get_bars` 的 `limit` 无上限（bars.py:56），120 根 K 线 ≈ 8-12k tokens 原样进 history 且后续每轮重复计费；跨轮历史按条数不按 token；prompt_builder 的 insight summary/key_observations 完全不截断（prompt_builder.py:93-98）。估算首轮 baseline ~4-7k tokens，10 轮打满 + 长工具结果可到 50-150k input，**超 context window 的失败无任何防护**。

**L3 — TokenTracker 是孤儿模块，成本可观测性实际为零。**
473 行（SQLite 表、按 model/phase/day 聚合、定价表成本估算）生产零接线；AgentService 只在内存 dict 累加（service.py:355）。定价表缺 kimi-k2.6 / glm-4.7 / nova 三个在产 provider（token_tracker.py:57-65）。

**L4 — TUI 密钥探测链与实际读 key 链不一致，agent 静默不可用。**
`tui/services/bootstrap.py:199-204` 按 `DEEPSEEK→OPENAI→ZAI→MOONSHOT` 探测"有 key"，但构造 AgentService 时不传 api_key，实际由 `AGENT_PROVIDER`（默认 deepseek）决定读哪个 env。场景：只配 `OPENAI_API_KEY` 且未设 `AGENT_PROVIDER` → 探测通过 → 初始化抛 ValueError → 被 catch 成 warning → **agent 静默不可用**。Web 入口走 `load_config()` 反而一致——两个入口行为不对称。

**L5 — LLM 调用无超时、双层重试叠加。**
`OpenAI(...)` 未传 timeout/max_retries（service.py:157-160）→ SDK 默认 600s + 内置重试 2 次；应用层 `_create_with_retry` 再重试 3 次 → 最坏 **12 次尝试、单请求最长 10 分钟**，TUI worker / web to_thread 被长时间挂住。Rate limit 重试不读 `Retry-After`。

**L6 — 每轮对话后一次隐形 LLM 调用（提取），无重试、无计费、temperature=1。**
extractor.py:174-187：JSON 提取任务用 temperature=1（稳定性差），调用不进 `_create_with_retry`，token 不进任何统计。

**次要**：中断时 `"（已中断）"` 会被当 assistant 回复写入记忆（service.py:255-257 不检查 `resp.interrupted`）；`msg.model_dump()` 原样入 history 对严格 provider 可能带多余字段；`usage_out` 共享 dict 依赖 CPython 原子性（实际可接受但脆弱）。

---

## 3. 工具系统、MCP 与 workflow

### 3.1 亮点

- 拆分后的 `tools/` 包域划分清晰；`ToolDef` 单一定义同时喂 LLM function-calling 和 MCP server，无重复实现（mcp_server.py:96-119）。
- 工具 description 质量整体好（中文、带示例、有调用顺序提示和消歧提示）。
- 24 个工具全部有 type/properties/required 的 JSON Schema。

### 3.2 问题清单（按严重度）

**T1 — `ctx.db_path` 一物三用，agent 写的数据监控读不到（DI 设计缺陷）。** ✅已复核
同一字段三种语义：`tools/alerts.py:65` → CustomAlertStore（设计是与 watchlist 共用 **portfolio.db**，custom_alerts.py:122）；`tools/bars.py:83` → CacheStore（应写 **market.db**）；`tools/memory.py` → 记忆（应用 **agent.db**）。而所有入口统一传 `AGENT_DB`（cli.py:336、web/deps.py:183、bootstrap.py:217），MCP 传 `MARKET_DB`（mcp_server.py:54）。后果：**agent 对话里设的自定义告警写进 agent.db，监控进程读 portfolio.db → 告警静默失效**；`backfill_history` 回填进 agent.db，缓存层读 market.db → 回填无效；MCP 查记忆读到 market.db → 记忆分裂。

**T2 — 错误语义在 registry/workflow 边界丢失，`optional`/`break` 是死逻辑。**
`registry.call` 把一切异常转成 error JSON 字符串永不抛出（registry.py:56-60，docstring 声称 Raises 已过期）；`WorkflowExecutor` 只 catch 异常、不检查 payload 的 `"error"` 键（engine.py:205-216）→ 工具失败一律 `success=True`，"非可选步骤失败即终止"（engine.py:228-231）**永不触发**。叠加实例：**`flow_check` 工作流第一步必然失败**——`_extract_codes_from_watchlist` 返回 `{"codes": [...]}`（definitions.py:78）而 `get_money_flow_today` 要单数 `code`（flows.py:41），每次 KeyError，每次被记为成功，LLM 拿错误 JSON 硬总结。

**T3 — 工作流定义自身有 bug。**
`add_watchlist` 名为加自选，实际调的是**告警工具** `manage_alert`，还传非法参数 `alert_type`（应为 `condition`）+ 占位 `threshold=0`——工具集里根本没有 watchlist 写入工具，这个工作流是空壳（definitions.py:269-297）。`stock_analysis` 给 `get_bars` 传 `count: 20`，工具只认 `limit`（definitions.py:321 vs bars.py:56），静默忽略。

**T4 — `ctx.client`/`ctx.model` 从未被任何入口赋值，记忆工具高级路径全死。**
`search_similar_events` 向量搜索（memory.py:114-134）与 `get_market_narrative` 的 LLM 叙事（memory.py:218-226）都以 `ctx.client is not None` 为前提，但全仓库没有任何地方设置它（AgentService 自建 `self._client` 却不回写 ctx）——永远走"2 字滑窗关键词"降级，与 P4 同根。

**T5 — 返回体量无治理 + MCP 阻塞 event loop。**
`get_bars(120)`、`get_theme_stocks` 全量成分股等可一次灌入数万 token；治理挂点（截断/分页/schema 校验）在架构上无处可挂——`registry.call` 是天然挂点，目前只做 try/except。MCP `call_tool` 在 async handler 里同步跑阻塞网络 IO（mcp_server.py:117-119），一个慢请求卡死整个 MCP 会话。

**次要**：参数校验缺失（LLM 漏参 → KeyError → 对自恢复不友好的报错文案）；股票代码无 `pattern: "^\d{6}$"`；limit/days 无 min/max；sector/intel 工具绕过 adapter 直调裸函数（无缓存无 fallback，sector.py:68 等）；DEFS/HANDLERS 靠名字手工对齐无一致性校验；mcp_server.py:4 docstring "14 个工具"过期（实际 24）。

---

## 4. 共性根因

三个子系统的问题呈现出三个共同模式，比单个 bug 更值得注意：

1. **"接线缺失"型死代码**：向量检索（P4）、TokenTracker（L3）、ctx.client（T4）、cron 入口（P1）——接口、实现、测试都在，唯独生产装配不调用。**根因是缺少"装配冒烟测试"**：每个能力应有至少一个走生产装配路径（bootstrap/deps/CLI 入口）的用例，而不是只测组件本身。
2. **静默降级过度**：向量失败无日志（P4）、agent 初始化失败被 catch 成 warning（L4）、error-as-JSON 被 workflow 当成功（T2）。降版本意是韧性，但**没有"降级必须可见"的配套**（指标/日志级别/启动自检），韧性变成了故障隐身衣。
3. **测试状态与生产状态脱节**：verify_engine 测试用裸 SQL 构造了生产不可能的 `verify_after`/`created_at` 关系，恰好掩盖 P2；无测试断言 workflow 参数名与工具签名的一致性（T2/T3）。**关键链路的测试应基于生产数据形状**（本报告 P2/P5 均靠生产库实测才发现）。

---

## 5. 建议行动清单（按优先级）

| # | 项 | 根问题 | 工作量 |
|---|---|---|---|
| 1 | 修 `mommy-agent` CLI 启动崩溃（VectorSearch 构造 + verify 子命令路由） | P1 | S |
| 2 | 修验证窗口：expired 判定改为 `now > verify_after + 宽限（如 2×timeframe）`；方向验证改用 `(actual-entry)/entry`；neutral 不计入 hit | P2/P3 | M |
| 3 | 修 `ctx.db_path` 语义分裂：ToolContext 拆为 `agent_db/market_db/portfolio_db` 三个字段，各入口分别装配 | T1 | M |
| 4 | 修流式：`_stream_final_answer` 空串不得覆盖（`streamed or None`）；流式 usage 单独记账并计入统计 | L1 | S |
| 5 | WorkflowExecutor 检查 payload `"error"` 键 + 修 flow_check/add_watchlist/stock_analysis 三处定义 bug | T2/T3 | S |
| 6 | `store_extraction` 补写 `trade_date`；存量 NULL 行回填脚本 | P5 | S |
| 7 | LLM 调用显式 timeout（如 120s）+ 统一重试层（去掉 SDK 内置重试或应用层二选一） | L5 | S |
| 8 | context 治理第一步：工具结果在 `registry.call` 统一截断（如 8KB），`get_bars` limit 加上限 120 | L2/T5 | S |
| 9 | TUI 探测链与 `AGENT_PROVIDER` 对齐（探测结果作为 provider 传入 AgentService） | L4 | S |
| 10 | 决策向量子系统：要么接线（装配 client、embed cron、失败日志），要么标记 experimental 并从工具描述中降级 | P4/T4 | M |
| 11 | TokenTracker 接线进 `_create_with_retry`，补三个 provider 定价 | L3 | M |
| 12 | 装配冒烟测试套件：mommy-agent verify/consolidate、TUI bootstrap、MCP stdio 各一个走真实入口的用例 | 根因 1 | M |

> 建议：#1-#5 为数据正确性修复，应进 v1.1.1；#6-#9 进 v1.2.0；#10-#12 进 PLAN-2 规划。

---

## 附：评估方法与复核记录

- 三路并行源码深挖：记忆系统（10 模块）、LLM 连接层（service/prompt/token_tracker/provider 链）、工具与 MCP（tools/ 包、mcp_server、workflow）。
- 生产库实测：`data/agent.db` 的 predictions（136 条 verified_at 同秒）与 episodic_events（317 条，137 条 trade_date 为 NULL）。
- 人工复核（本检出亲自复现）：`uv run mommy-agent verify` 崩溃栈（P1）；`_stream_final_answer` 空串覆盖路径（L1）；custom_alerts 默认 portfolio.db vs 全入口 AGENT_DB（T1）。
- 未覆盖区：consolidator/narrative 的 LLM prompt 内容质量未做逐字评审（属于效果调优，非正确性）。
