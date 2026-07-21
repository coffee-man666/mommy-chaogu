# 改进计划（v1.1.0 及以后）

> 来源：2026-07-18 复盘（dexter 对标 + BACKEND-CAPABILITIES.md 编写过程中发现的问题）。
> 用法：每项独立可交付，按档内顺序执行；完成后在条目头部打 `~~删除线~~` 并注明完成提交。
> 工作量：S = 半天内，M = 半天到一天，L = 一天以上。
>
> **状态：12/12 已全部完成（2026-07-18）** — 一档见 main（f5188e5 / ea1ba25 / 89a162f），
> 二档见 PR #22（feat/tier2-ux），三档见 feat/tier3-eng-debt（fba937b，3aa321e 合入）。

---

## 一档：收尾杂事

### ~~1. 合并 fix/web-api-pitfalls 【S】~~ ✅ f5188e5

- **现状**：分支已推送（`e4b5eca`），但 main 被 tools/ 拆分重构（PR #20）抢先，尚未合并。
- **设计**：直接 `git merge fix/web-api-pitfalls`（非 squash，保留修复叙事）；两边改的文件不重叠（fix 改 `web/routes/*`、`web/schemas.py`；重构改 `agent/tools/*`），预期零冲突。
- **验收**：合并后 `ruff format --check` / `ruff check` / `mypy --strict src` / `pytest -m "not network"` 全绿；`tests/test_web/test_api_pitfalls.py` 6 个回归测试在 main 上通过。

### ~~2. 发布 v1.1.0 【M】~~ ✅ ea1ba25

- **现状**：未发布内容已积累四块——dexter 风 TUI（⏺/⎿ 工具指示、WorkingIndicator、HintBar）、slash ↑↓ 循环选择、3 个 API 修复、tools/ 包拆分重构。v1.0.0 的 GitHub Release 页面至今未建。
- **设计**：
  1. CHANGELOG 新增 `## [1.1.0] - <date>`，按 新增/改进/修复 三组归纳上述四块；
  2. `src/mommy_chaogu/version.py` bump 到 `1.1.0`（SemVer：有向后兼容的新能力 → minor）；
  3. 参照 `docs/RELEASE-CHECKLIST.md` 跑发布门禁（质量门 + Docker 构建）；
  4. 打 tag `v1.1.0` 推送；在 GitHub 网页补建 v1.0.0 和 v1.1.0 两个 Release（正文分别贴 CHANGELOG 对应段；v1.1.0 附 `dist/` 新构建的 wheel/sdist）。
- **验收**：`git describe --tags` 显示 v1.1.0；GitHub Releases 页面两个版本均可访问。

### ~~3. AGENTS.md 同步 tools/ 包结构 【S】~~ ✅ 89a162f

- **现状**：`agent/` 一节仍描述单文件 `tools.py` 时代（"24 工具"），重构后已拆为 `agent/tools/` 包（registry/quote/flows/sector/holdings/intel/alerts/memory/themes/bars/base）；mypy 豁免也已随重构收窄（TECH-DEBT.md 已同步）。
- **设计**：更新 AGENTS.md 两处——项目结构树的 agent 行（改为"24 工具（tools/ 包按域拆分）+ MCP + 记忆系统"）和"数据源走 Protocol"之外的工具扩展指引（新工具放哪个域文件、如何注册到 `tools/registry.py`）。
- **验收**：AGENTS.md 中不再有对 `agent/tools.py` 单文件的引用。

---

## 二档：体验深化

### ~~4. 真·流式输出（TUI + Web）【L】~~ ✅ PR #22

- **现状**：TUI 整段返回后一次性渲染；`/ws/agent` 把完整回复切 12 字符、10ms 间隔"伪流式"（`web/routes/ws.py:164-169`）。`tui/messages.py` 里有从未使用的 `AgentChunk` 消息类。这是与 dexter 体验差距最大的一项。
- **设计**：
  1. **agent 层**：`_run_loop` 的 `chat.completions.create` 增加 `stream=True` 路径——仅在"本轮无工具定义或预期为最终回答"时启用（最稳妥方案：学 dexter，工具循环结束后单独发起一次无 tools 绑定的流式调用生成最终回答）；新增回调 `on_chunk: Callable[[str], None] | None`，逐 delta 转发；收集完整文本后走原有返回路径。
  2. **兼容**：provider 不支持 stream 时 try/except 回退非流式，行为不变；`chat_raw` 同步支持。
  3. **TUI**：`AgentBridge.chat` 透传 `on_chunk`；`app.py` worker 线程 `call_from_thread` 转发；ChatView 复用/新写流式 Markdown widget——挂载后即 `update(累计文本)`，节流 50ms（`textual` 的 `set_timer` 合并高频 delta）。
  4. **Web**：`/ws/agent` 改为直接转发真实 delta 帧（帧格式不变 `{type:"chunk","text":...}`，前端零改动受益）。
- **涉及文件**：`agent/service.py`、`tui/services/bootstrap.py`、`tui/app.py`、`tui/views/chat.py`、`web/routes/ws.py`、`web/routes/agent.py`（REST 保持整段返回，不动）。
- **验收**：mock stream chunks 的单测（agent 层 on_chunk 序列 + 完整文本拼接正确）；TUI pilot 测试流式 widget 增量更新；`/ws/agent` e2e 帧序列 thinking→chunk×N→done；全质量门绿。

### ~~5. Esc 真取消 【M】~~ ✅ PR #22

- **现状**：Esc 只置标志位抑制结果展示，worker 线程把 agent 循环跑完才停（`tui/views/chat.py:action_cancel_chat`）。LLM 调用慢时用户要等几十秒。
- **设计**：
  1. `AgentService.chat/_run_loop` 增加 `cancel_event: threading.Event | None` 参数；在**每轮 LLM 调用前**和**每个工具执行前**检查 `is_set()`，命中即返回 `AgentResponse(text="（已中断）", interrupted=True)`（AgentResponse 加字段，默认 False 兼容）。
  2. TUI：`handle_chat_message` 时新建 Event 存 `self._cancel_event`；Esc → `set()`；`_on_agent_done` 收到 interrupted 时不渲染回答、只显示 `⎿ 已中断`。流式（#4）落地后，chunk 回调里也检查一次。
  3. 工作流路径：`WorkflowExecutor.execute` 每个步骤前检查同一个 Event（`on_step_start` 回调链里传入）。
- **涉及文件**：`agent/service.py`、`workflow/engine.py`、`tui/app.py`、`tui/views/chat.py`。
- **验收**：pilot 测试——慢假 agent（sleep 循环检查 event）下 Esc 后 1s 内 worker 退出且 UI 显示已中断；不打断时行为不变。

### ~~6. WorkingIndicator token 统计 【S】~~ ✅ PR #22

- **现状**：只显示 `(12s)` 耗时；dexter 显示 `(12s · ↓ 1.2k tokens)`。
- **设计**：`_run_loop` 累加每轮 `response.usage`（prompt_tokens/completion_tokens）存入 `AgentResponse.usage: dict`；TUI 侧做 dexter 的 `TurnStats` 模式——`WorkingIndicator.set_stats_provider(callable)`，worker 线程更新共享 dict（streamed_chars 或 usage），indicator tick 时渲染；平滑追赶动画直接移植 dexter `advanceDisplayedChars` 的分档逻辑（gap<70→+3，<200→15%，否则+50）。
- **依赖**：与 #4 同做体验最佳（流式时按 chars/4 估算，非流式用 usage 精确值）。
- **验收**：非流式回合显示真实 token 数；mock usage 单测。

### ~~7. /flows 与 /memory slash 命令兑现 【M】~~ ✅ PR #22

- **现状**：`/flows 688981` 和 `/memory` 只回一句"请在终端运行 xxx"（`tui/views/chat.py:_dispatch_slash`）。
- **设计**：
  1. `/flows <code>`：worker 线程调 `FlowService.show(code, days=30)`（today/history FlowSummary + 缓存天数），渲染为对话流里的 Markdown 卡片（主力/超大单/大单净额 + ratio + 30 日对比）；复用 `format_flow/format_amount`。
  2. `/memory`：查 `EpisodicMemory.summary()` + `PredictionTracker.stats()` + `SemanticMemory.summary()`（`AGENT_DB`），渲染统计卡片（事件数、预测命中率、知识条目数），附"详细：`mommy memory events`"引导。
  3. 两者都走 `Services` 容器装配（bootstrap 里加 `flows_service` / 直接按路径 new 只读 store）。
- **验收**：pilot 测试两个命令渲染卡片且不再出现"请在终端运行"文案。

### ~~8. Web 预测跟踪页面 【M】~~ ✅ PR #22

- **现状**：`/api/agent/predictions` 修复后有数据，但 Vue 前端无页面消费；预测验证闭环（hit/missed + 命中率）是记忆系统最大差异化能力，只躺在 CLI 里。
- **设计**：
  1. 新视图 `web/src/views/PredictionsView.vue`：顶部统计条（total/hit/missed/pending/hit_rate——需新增 `GET /api/agent/predictions/stats`，背后是 `PredictionTracker.stats()`，~20 行）；下方预测卡片列表：方向徽章（看多红/看空绿，**不用**涨跌色，建议蓝/橙防混淆）、status 徽章（pending 灰/hit 绿/missed 红/expired 暗）、target/entry/stop 三价位、`verify_after` 倒计时、actual vs predicted 偏差（已验证的）。
  2. 路由 + 侧边导航项 + 移动端底部 tab（放进"更多"或替换最低频项）。
  3. API client 加 `getPredictions(limit)` / `getPredictionStats()`（`web/src/api/`）。
- **涉及文件**：`web/routes/agent.py`（stats 端点）、`web/src/router`、`web/src/views/PredictionsView.vue`、`web/src/api/*`、导航组件。
- **验收**：Vitest 单测（client 解析）+ Playwright 页面冒烟（mock 数据渲染卡片）；后端 stats 端点单测。

---

## 三档：工程债

### ~~9. 清理 tui/messages.py 死代码 【S】~~ ✅ PR #22

- **现状**：11 个 Message 类只有 `StepStatus` 被用（`AgentChunk/ToolCallStarted/ToolCallFinished/AgentDone` 等 10 个是未落地的设计稿；实际通信走了直接方法调用）。
- **设计**：全仓 grep 确认无引用后删除未用类；#4 实施时会用到 `AgentChunk`——若#4 先做，则保留它并删除其余。**执行顺序：放在 #4 之后**。
- **验收**：messages.py 只剩实际使用的类；测试全绿。

### ~~10. 信号历史结构化 【M】~~ ✅ fba937b

- **现状**：`/api/signals/history` 从 `data/signals.log` 文本行正则解析（`web/routes/signals.py:60-85`），脆且无法按字段查询。
- **设计**：新建 `signal_events` 表（放 `market.db`：信号属于行情事件；字段 timestamp/code/name/rule_id/severity/title/detail/trigger_value/threshold_value，TEXT 存 Decimal）；`Alerter` 在 `write_signals_log` 同时写库（双写过渡）；API 改为读库、读库失败/为空时回退日志解析；迁移脚本把既有 log 回填入库（`scripts/migrate_signals_log.py`，幂等）。
- **验收**：历史接口字段完整且不再依赖文本格式；回填脚本重复执行不产生重复行。

### ~~11. 看板性能与线程修正 【S】~~ ✅ fba937b

- **现状**：`ThemeListWidget._load_data` 在 UI 线程同步读 SQLite（`views/dashboard.py:321-340`）；`DataService.watchlist_quotes` 逐 code 串行两次 adapter 调用（`tui/services/bootstrap.py:42-66`），自选 20+ 只时刷新明显慢。
- **设计**：主题加载挪进 `run_worker(thread=True)`，回来再 mount；报价改 `adapter.get_quotes(codes)` 批量（Protocol 已有该方法）+ 资金流仅对可见行或并发度≤4 的 `ThreadPoolExecutor`；加一个简单的刷新耗时日志便于回归对比。
- **验收**：20 只自选刷新耗时较串行下降 ≥50%（本地计时）；UI 线程无 SQLite 调用。

### ~~12. 覆盖率门禁 65% → 70% 【M】~~ ✅ fba937b（70.07% 过线）

- **现状**：CI `--cov-fail-under=65`（分支覆盖），`docs/TECH-DEBT.md` 有台账。
- **设计**：`coverage json` 找出覆盖最低的 5 个模块（预期 web/routes 部分、flows/report、tui 部分），优先补纯逻辑单测（不补为了数字而写的空转测试）；门禁每次只拧 5%，拧到 70% 后稳定一个版本。
- **验收**：CI 65→70 通过；新增测试均为行为断言。

---

## 执行顺序建议

```
一档 1 → 2 → 3（出 v1.1.0）
二档 4（流式，最大体验项）→ 5（取消，依赖 4 的回调链）→ 6（依附 4）→ 7 → 8
三档 9（等 4 完成）→ 10 → 11 → 12
```

## 明确不做

- TUI K 线 sparkline（引入 textual-plotext 新依赖，等真有人用 TUI 看图再说）
- 多用户/多会话的 Web 鉴权体系（单用户边界是 v1.0.0 的明确决策）
- 回测交互式页面（回测无 API，只展示已有报告产物）

## 合并后 backlog（review 遗留，非阻塞）

- `tui/services/bootstrap.py` 批量报价/并发资金流逻辑无直接测试（文件覆盖 28.7%）
- `/api/signals/history` 回退路径的正则与真实 `format_log` 格式仍不匹配（主路径已是 DB，影响小）
- `signals/store.py list()` 用位置索引取值（其他 store 用列名，风格不统一）
