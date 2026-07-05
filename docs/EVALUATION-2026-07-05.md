# 记忆系统 & 回测系统评估报告

> 2026-07-05 基于代码审查的全面评估。两个探索 agent 分别通读了记忆系统（9 个模块）和回测系统（3 条路径 + 引擎）的全部代码。

---

## 一、记忆系统评估

### 当前状态：架构完整，但集成断裂

5 层全部实现（Working / Episodic / Prediction / Semantic / Vector），模块代码和测试都没问题。但设计文档构想的闭环——**事件流入 → 预测定时验证 → 知识周度提炼 → 洞察注入 prompt**——在自动化环节上几乎全断。只有「对话后事实抽取 → 写入情景记忆 → 注入 prompt」这一条边是通的。

### 闭环断裂地图

```
设计文档构想的闭环：
  reports/monitor → episodic → [verify cron] → predictions → [consolidate cron] → semantic → prompt_builder
                                                                ↓
                                                            insight_summary → prompt_builder

实际运行状态：
  chat → extractor → episodic ✅ → prompt_builder ✅
  reports/monitor → episodic ❌（不写）
  verify cron → predictions ❌（无 cron，手动 CLI）
  consolidate cron → semantic ❌（无 cron，手动 CLI）
  insight_summary → prompt_builder ❌（表从未创建）
  vector_search → agent tools ❌（没注册为工具）
  narrative → agent tools ❌（没注册为工具）
```

### 🔴 严重问题（破坏核心闭环）

#### 1. Agent 没有记忆查询工具

18 个 agent 工具里没有一个能查 episodic / semantic / prediction / vector。Agent 无法主动问"我上周对茅台说了什么"——只能看到 prompt 静态注入的那几条。

- 设计文档 §7 要求注册 `get_market_narrative` 工具 → ❌ 不在 `tools.py`
- 设计文档 §11 要求注册 `search_similar_events` 工具 → ❌ 不在 `tools.py`
- 影响：agent 的记忆是被动的、不完整的，用户无法通过对话触发记忆检索

#### 2. Traceability 链断裂

`prediction.source_event_id` 和 `event.prediction_id` 在 schema 里存在但主流程从不填。

- `extractor.store_extraction()` 创建 prediction 时不传 `source_event_id`
- `verify_engine` 验证后写回 event 时不填 `prediction_id`
- `prediction.insight_event_id`（知识回写链接）也从未被填

影响：consolidator 的置信度校准（`_recalibrate_confidence` 依赖 event↔prediction 链接）实际上是空操作。设计文档的核心目标"可溯源修正"落空。

#### 3. report/monitor 不写事件

项目最丰富的分析数据从不写入 episodic memory：

- `reports.py` 不写 `analysis_record` 事件（计划 §5.2 要求）
- `monitor.py` 不写 `signal_event` 事件（计划 §5.2 要求）
- 15:30 `market_snapshot` cron 不存在（计划 §5.1/§12.5 要求）

影响：narrative 和 consolidator 在实际运行中几乎没有事件可分析。情景记忆里只有对话抽取出来的少量观察，缺少系统性的市场事件流。

#### 4. 验证没有 cron

预测创建后一直 pending，除非人手动跑 `mommy-agent verify`。计划文档 §12.5 要求 16:00 自动验证，从未实现。

影响：预测追踪系统的核心价值（"推荐 → 验证 → 学习"闭环）在生产环境中不闭环。预测可能永远 pending。

### 🟡 中等问题（影响准确性）

| 问题 | 详情 | 影响 |
|---|---|---|
| **timeframe 不一致** | `prediction_tracker._TIMEFRAME_DAYS["5d"] = 3`（日历天），`verify_engine._TIMEFRAME_DAYS["5d"] = 5`（日历天）。两个模块对"5 天预测"的含义不一致 | 预测可能在自己预期的窗口外被验证 |
| **`data_coverage` 是 LLM 猜的** | extractor 让 LLM 自报数据可用性（"你觉得基于了哪些数据"），不交叉检查 adapter 实际返回了什么 | 设计原则"诚实记录数据可用性"落空；后续无法做"数据缺失下的表现分析" |
| **extractor 输入截断** | `user_message[:500]` + `assistant_response[:1000]` | 长 agent 分析的后半段预测/观察全部丢失 |
| **neutral 评分有偏差** | verify_engine 给 neutral 方向固定 0.5 分算 "hit" | 虚增命中率 |
| **`insight_summary` 表从未创建** | 计划 §4.4 的周度复盘→注入 prompt 循环完全缺失 | agent 无法从"上周自己的综合复盘"中学习 |
| **向量搜索没接入** | Phase 5 实现了但 agent 不能用（没注册为工具），prompt_builder 也不注入相似历史事件 | 最先进的检索能力闲置 |
| **semantic_memory 搜索太弱** | 只有 `LIKE '%query%'`，无语义/关键词排序 | "知识检索"能力形同虚设 |
| **consolidator 模式过粗** | `_consolidate_patterns` 把所有已验证预测一次性喂给 LLM 生成单条 `pattern_observed`，scope 固定为 `market` | 无法区分"bullish-5d 模式"和"flow-signal 模式" |

### 🟢 低优先（技术债）

- 4 个 SQLite store（memory / episodic / tracker / semantic）各开独立连接池操作同一个 `agent.db`，并发 web 请求时有锁竞争风险
- 无 TTL / 清理（计划 §15 提了 90 天 TTL，未实现），表无限增长
- 无去重（重复提问产生重复 observation / prediction）
- 所有 LLM 调用的 JSON 解析用脆弱的行切片（`lines[1:-1]`）剥 markdown fence

---

## 二、回测系统评估

### 当前状态：三条路径互不统一

| 路径 | 脚本 | 评分逻辑 | 数据源 | 评分标准 |
|---|---|---|---|---|
| BacktestEngine | `backtest/engine.py` | 做多 P&L（return > 0 = win） | cache SQLite | Rubric B：win_rate + Sharpe + max-DD |
| 规则引擎 | `backtest_evolution.py` | 方向命中率 + ±2% 死区 | 实时拉网络 | Rubric A：hit / missed / expired |
| LLM | `backtest_llm.py` | 同规则 + neutral 分支 | market.db 离线 | Rubric A 变体（neutral = hit if ≤2%） |
| Agent 原生 | `prepare_agent_backtest.py` | 手动实现 | market.db 离线 | Rubric A（手动） |

**Rubric A 和 Rubric B 不可比**——一个是方向命中率，一个是做多 P&L。但报告 TL;DR 里混在一起用了。

### 🔴 严重问题（影响结论有效性）

#### 1. 没有基准对照

53% 命中率到底好不好？在 6 月半导体板块整体上涨的环境下，等权买入持有的"命中率"可能也是 80%+。没有 buy-and-hold / 随机基线，所有结论都是空中楼阁。

- 报告 §5 item 5 自己承认："后续加入「等权持有」「均线择时」等 naive 基线"
- `backtest_llm.py:558` 硬编码了 `"规则: 53%"` 作为字符串字面量对比——不是计算出来的

#### 2. 没有统计显著性检验

53% vs 50% vs 47%，样本量 70-154 条——这个差异大概率在统计噪声范围内。

- 没有置信区间
- 没有二项检验（binomial test）
- 没有 bootstrap CI
- 报告 §5 item 2 承认"样本小，统计显著性有限"

#### 3. 单一市场环境

所有回测都落在 2026 年 6 月（强势上涨期）。

- bearish 13-18% 的命中率是市场环境 artifact（上涨趋势中看跌当然错），不是 LLM 分析能力差
- bullish 89-96% 也可能只是 beta 暴露，不是 alpha
- 需要下跌区间数据验证，但东财资金流从美国 IP 拿不到（见 §6 数据源限制）

#### 4. 没有交易成本

A 股实际成本 ≈ 0.1% 佣金 + 0.1% 印花税（卖出）+ 滑点。一个 5bp（=0.05%）的 ratio 信号触发的策略，信号本身就比交易成本还小。扣掉成本后可能亏钱。

### 🟡 中等问题

| 问题 | 详情 |
|---|---|
| **两套评分标准不兼容** | 报告里混用方向命中率和 P&L 指标 |
| **没有组合层面分析** | 逐条预测独立评分，无仓位管理、资金分配、净值曲线 |
| **BacktestEngine 市值快照问题** | 用当前市值而非时点市值算 ratio → 轻微 look-ahead |
| **token_tracker 没复用** | `backtest_llm.py` 重写了简化版 TokenUsage（¥ 计价），没用生产级 TokenTracker（$ 计价） |
| **进化回测无 out-of-sample** | evolution 脚本在同一个窗口里提炼知识又评估——没有留出集 |
| **`--detail` CLI 可能坏了** | `cmd_flows_backtest` 读 `s["main_net"]` 但引擎输出的是 `main_net_yi` |

### 🟢 低优先

- `prepare_agent_backtest.py` 不带验证脚本（验证是 docstring 示例）
- `/tmp/backtest_multi/run_model.py` 不在仓库里
- `backtest_evolution.py` 每次跑都重新拉网络数据，结果不完全可复现

---

## 三、改进建议（按投入产出比排序）

### 记忆系统

| 优先级 | 改进 | 工作量 | 价值 |
|---|---|---|---|
| P0 | **给 agent 加记忆查询工具** — 注册 `search_similar_events` / `get_prediction_history` / `get_market_narrative` 为 agent 工具 | 中 | 让 agent 从被动记忆变为主动记忆 |
| P0 | **修 traceability 链** — `store_extraction` 传 `source_event_id`，verify 回填 `event.prediction_id` | 低 | 恢复置信度校准闭环 |
| P1 | **加验证 cron** — 每天 16:00 自动验证到期预测 | 低 | 预测不再无限 pending |
| P1 | **report/monitor 写入 episodic** — 盘后报告和告警信号写入事件流 | 中 | 为 narrative / consolidator 提供数据 |
| P1 | **修 timeframe 不一致** — 统一两个模块的 `_TIMEFRAME_DAYS` | 低 | 预测在正确的时间窗口被验证 |
| P2 | **创建 `insight_summary` 表 + 注入** — 实现周度复盘→prompt 循环 | 中 | agent 从自己的综合复盘中学习 |
| P2 | **向量搜索接入 prompt_builder** — 自动注入相似历史事件 | 低 | 最先进的检索能力上线 |
| P2 | **extractor 不截断** — 用 token 计数代替字符截断 | 低 | 长分析的后半段不再丢失 |
| P3 | **TTL / 清理** — 90 天后自动清理原始事件 | 低 | 防止表无限增长 |
| P3 | **去重** — 重复提问不产生重复 observation | 中 | 减少噪声 |

### 回测系统

| 优先级 | 改进 | 工作量 | 价值 |
|---|---|---|---|
| P0 | **加 buy-and-hold 基准** — 每次回测同时算等权持有同期的命中率 | 低 | 一列代码，立刻知道策略是否跑赢基准 |
| P0 | **加统计显著性** — 二项检验或 bootstrap CI | 低 | 判断 53% vs 50% 是否是噪声 |
| P1 | **统一评分标准** — 所有路径用同一套 verify 逻辑 | 中 | 消除 Rubric A/B 不兼容 |
| P1 | **加交易成本模型** — 佣金 + 印花税 + 滑点 | 中 | 看清策略扣费后的真实收益 |
| P1 | **组合层面分析** — 仓位管理 + 净值曲线 | 中 | 从"单条预测准不准"到"整体赚不赚钱" |
| P2 | **下跌区间验证** — 需要更长历史数据（依赖数据源修复） | 高 | 验证 bearish 策略有效性 |
| P2 | **out-of-sample 测试** — 留出集 / walk-forward | 中 | 验证进化系统是否过拟合 |
| P2 | **token_tracker 复用** — backtest_llm.py 改用生产级 TokenTracker | 低 | 代码一致性 |
| P3 | **修 `--detail` CLI** — key 名称对齐 | 低 | CLI 不再崩溃 |
| P3 | **run_model.py 入仓** — 从 /tmp 移到 scripts/ | 低 | 可复现 |

---

## 四、执行计划

### 依赖关系图

```
Sprint 1（并行启动，互不依赖）
  ├── A1: 加 buy-and-hold 基准 ──────────────────────┐
  ├── A2: 加统计显著性（二项检验 + bootstrap CI）     │
  ├── B1: 修 traceability 链                          │
  ├── B2: 修 timeframe 不一致                         │
  └── B3: 加验证 cron（16:00 自动 verify）            │
                                                       │
Sprint 2（A1/A2 完成后 + B1/B2 完成后，两组并行）      │
  ├── A3: 统一评分标准（依赖 A1 的 verify 逻辑梳理）   │
  ├── A4: 加交易成本模型（独立）                        │
  ├── B4: 给 agent 加记忆查询工具（独立）                │
  └── B5: extractor 不截断 + 修 data_coverage（独立）    │
                                                       │
Sprint 3（B4 完成后 + 数据积累后）                      │
  ├── A5: 组合层面分析（依赖 A3 统一评分）               │
  ├── B6: report/monitor 写入 episodic（独立）           │
  ├── B7: 创建 insight_summary 表 + 注入循环（独立）     │
  └── B8: 向量搜索接入 prompt_builder（独立）            │
                                                       │
Sprint 4（需要数据源修复 / 较大改造）                    │
  ├── A6: out-of-sample / walk-forward 测试             │
  ├── A7: 下跌区间验证（依赖资金流数据源修复）            │
  ├── B9: semantic_memory 搜索升级（向量召回）            │
  └── B10: TTL / 清理 / 去重                             │
```

### Sprint 1 — 快速修复（全部可并行，预估 1-2 小时）

这 5 个任务互相完全独立，可以用 swarm 并行：

| 任务 ID | 任务 | 文件 | 并行组 |
|---|---|---|---|
| **A1** | 在 `verify_prediction` 旁边加 `compute_buyhold_baseline`——对同股票同期算等权持有的方向命中率 | `scripts/backtest_evolution.py` + `backtest_llm.py` | 组 A |
| **A2** | 加 `compute_ci(hit, total, confidence=0.95)`——二项检验 + Wilson CI，在每个报告的命中率后面输出 CI 区间 | 新文件 `scripts/backtest_stats.py` | 组 A |
| **B1** | `extractor.store_extraction()` 创建 prediction 时传 `source_event_id`；`verify_engine` 验证后回填 event 的 `prediction_id` | `agent/extractor.py` + `agent/verify_engine.py` | 组 B |
| **B2** | 统一 `prediction_tracker._TIMEFRAME_DAYS` 和 `verify_engine._TIMEFRAME_DAYS` 为同一个映射 | `agent/prediction_tracker.py` + `agent/verify_engine.py` | 组 B |
| **B3** | 写 cron 脚本（或 OpenClaw job）每天 16:00 调 `mommy-agent verify` | `scripts/cron_verify.sh` 或文档说明 | 独立 |

**并行策略**：A1+A2 可以一个 agent 做（都在回测脚本里），B1+B2 可以一个 agent 做（都在 agent 模块里），B3 独立。→ **3 个 agent 并行**。

### Sprint 2 — 核心增强（部分依赖 Sprint 1，预估 2-4 小时）

| 任务 ID | 任务 | 依赖 | 并行组 |
|---|---|---|---|
| **A3** | 抽取 `verify_prediction` 为独立模块 `backtest/scoring.py`，让三个回测路径都引用同一套逻辑 | A1 | 组 A |
| **A4** | 写 `backtest/costs.py`——A 股交易成本模型（佣金 0.0255% + 印花税 0.05% 卖出 + 过户费 0.02% + 滑点 0.1%），在 verify 后扣减实际收益 | 无 | 组 A |
| **B4** | 注册 3 个 agent 工具：`search_similar_events`（调 vector_search）、`get_prediction_history`（调 tracker）、`get_market_narrative`（调 narrative） | 无 | 组 B |
| **B5** | extractor 用 token 计数（tiktoken）代替字符截断；`data_coverage` 从 adapter 返回结果推断而非 LLM 自报 | 无 | 组 B |

**并行策略**：A3+A4 一个 agent，B4 一个 agent（需要理解 tools.py 注册模式），B5 一个 agent。→ **3 个 agent 并行**。

### Sprint 3 — 数据流打通（可并行，预估 3-5 小时）

| 任务 ID | 任务 | 依赖 | 并行组 |
|---|---|---|---|
| **A5** | 写 `backtest/portfolio.py`——模拟等权组合、净值曲线、max-DD、Sharpe | A3 | 独立 |
| **B6** | `reports.py` 写 `analysis_record` 事件到 episodic；`monitor.py` 写 `signal_event` 事件 | B1（traceability） | 独立 |
| **B7** | 创建 `insight_summary` 表 + consolidator 写入 + prompt_builder 注入 | 无 | 独立 |
| **B8** | prompt_builder 在每次构建时调 `vector_search.search_similar(user_message)` 注入 Top-3 相似历史事件 | B4（vector_search 工具已注册） | 独立 |

**并行策略**：4 个任务完全独立，→ **4 个 agent 并行**。

### Sprint 4 — 深度优化（需要数据 / 较大改造，预估 5+ 小时）

| 任务 ID | 任务 | 依赖 |
|---|---|---|
| **A6** | walk-forward 测试框架——将数据分为训练集（提炼知识）和测试集（评估），验证进化系统不过拟合 | A3 + 数据 |
| **A7** | 扩展到 2025 年全年数据 + 多行业（沪深 300 / 科创板 / 创业板），覆盖下跌区间 | 数据源修复 |
| **B9** | semantic_memory 搜索从 `LIKE` 升级为向量召回 + 关键词混合排序 | B4（向量工具） |
| **B10** | 90 天 TTL 清理 + 对话去重（hash 检查） | 无 |

### 总结：并行时间线

```
时间 →   1h        2h        3h        4h        5h+
       
Sprint 1 ██████████
         A1+A2 | B1+B2 | B3         (3 并行)

Sprint 2           ██████████████
                   A3+A4 | B4 | B5              (3 并行)

Sprint 3                       ██████████████████
                               A5 | B6 | B7 | B8          (4 并行)

Sprint 4                                    ██████████████...
                                            A6 | A7 | B9 | B10  (依赖数据)
```

**最短路径**：如果用 swarm 并行跑，Sprint 1-3 理论上可以在 ~5 小时内完成（不含 Sprint 4 的数据依赖）。Sprint 1 的 5 个快速修复是最值得先做的——低工作量、高价值、全部独立。

---

## 五、执行结果（2026-07-05）

**全部 4 个 Sprint 完成。** 用 AgentSwarm 并行执行，每个 Sprint 内任务分组并行。

### 完成统计

| Sprint | 任务 | 新增测试 | Commit |
|---|---|---|---|
| Sprint 1 | A1+A2 / B1+B2 / B3 | +31 | `37b92d4` |
| Sprint 2 | A3+A4 / B4 / B5 | +49 | `a19dc3f` |
| Sprint 3 | A5 / B6 / B7 / B8 | +42 | `68aaa19` |
| Sprint 4 | A6+B9 / A7 / B10 | +58 | `4424628` |
| **合计** | **17 个改进** | **+180** | 518→698 |

### 闭环状态（修复后）

```
修复后的闭环：
  chat → extractor → episodic ✅ → prompt_builder ✅
  reports/monitor → episodic ✅（B6 修复）
  verify cron → predictions ✅（B3 修复，16:00 自动验证）
  consolidate → semantic ✅ → insight_summary ✅ → prompt_builder ✅（B7 修复）
  vector_search → agent tools ✅（B4 修复）
  vector_search → prompt_builder ✅（B8 修复）
  traceability 链 ✅（B1 修复：event↔prediction 完整链接）
  TTL/清理/去重 ✅（B10 修复）
```

### 回测系统改进

- ✅ buy-and-hold 基准（A1）
- ✅ Wilson CI + 二项检验（A2）
- ✅ 统一评分模块 backtest/scoring.py（A3）
- ✅ 交易成本模型 backtest/costs.py（A4）
- ✅ 组合层面分析 backtest/portfolio.py（A5）
- ✅ Walk-forward 过拟合检测 backtest/walk_forward.py（A6）
- ✅ 市场环境分组分析 backtest/regime_analysis.py（A7）
