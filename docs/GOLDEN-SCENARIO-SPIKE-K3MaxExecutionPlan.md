# Golden Scenario Spike — K3 Max Execution Plan

> 状态：执行中（3.3 就绪，未开始）
> 分支：`feat/experiment-engine-spike`
> companion 文档：docs/GOLDEN-SCENARIO-SPIKE.md（规则默认值、资产盘点、观察记录）
> 依据：docs/AGENT-FIRST-RESEARCH-LAB-RFC.md §8
> 作者：K3（Coding Agent）
> 目的：让任意 Coding Agent 只读本文件 + Spike 文档即可接续执行，无需口头上下文。

## 1. 已锁定决策（不再变更，除非作者明确推翻）

| # | 决策 | 来源 |
|---|---|---|
| D1 | Golden Scenario = 美股半导体 ETF 均线假跌破（SOXX/SMH/QQQ，SPY 基准） | RFC §4 |
| D2 | 「中期均线」= EMA55/89 云带：收盘 < cloud_lo 为跌破，收盘 > cloud_hi 为收复 | 作者指定，一律采用 quant/ma-suppression-monitor 口径 |
| D3 | 「重新进入通道」= 收盘回到 60 日回归通道（k=2σ）下轨之上（工具箱 `linreg_channel`） | 作者指定方法体系 + 工具箱自身定位（日线批量用回归通道） |
| D4 | 「几个交易日」= 5；持有 = 20 交易日 + 8% 止损 / 15% 止盈 | Spike §1 默认值，作者未异议 |
| D5 | 成交口径：信号当日收盘确认，下一交易日开盘价成交 | 工具箱核心惯例 |
| D6 | 成本口径：佣金 0 + 单边滑点 5bp；基准 SPY 调整后收盘 | Spike §5.3 |
| D7 | ExperimentSpec 与 WorkflowSpec 分离；规则用结构化 condition + params，不发明表达式 DSL | RFC §6.1 |
| D8 | 数据即常量：快照 CSV + manifest（source/retrieved_at/sha256），BacktestRun 引用哈希 | RFC §8.3 可复现要求 |
| D9 | 均线/通道唯一口径来源 = quant/ma-suppression-monitor；内核同口径函数用 pandas 交叉校验测试锁定 | 作者指定 |
| D10 | 实验存储先落本地 JSON/Markdown，不入库、不做 Web 页面、不接监控调度 | RFC §4.3 / §7 |

## 2. 架构取舍（为什么这么做）

1. **新代码集中在 `src/mommy_chaogu/experiment/`**，不动既有模块；与主包同工程规范
   （ruff line-length 100、mypy strict、中文错误信息、dataclass + to_dict/from_dict）。
2. **指标双轨**：`experiment/indicators.py` 提供零依赖纯函数（EMA/云带/ATR 与工具箱同口径，
   pandas 交叉校验测试锁定）；`linreg_channel` 不重复实现，运行时直接调工具箱——
   口径只有一个事实来源，避免两份实现漂移。
3. **现有 backtest 引擎不复用**（绑定资金流信号与缓存表），仅复用 costs / portfolio /
   walk_forward / regime_analysis / scoring 五个独立模块；任何复用失败写入 Spike §6 观察记录。
4. **薄运行时**：spec → 逐日信号 → 逐笔交易 → 成本/基准 → BacktestRun JSON。
   运行时是唯一允许产生收益结论的路径，禁止 Agent 绕开它自己拼数字（RFC §6.3）。

## 3. 已完成（现状快照）

- `experiment/spec.py`：ExperimentSpec schema（spec_version=1），含字段校验与 JSON round-trip；
  特征类型含 ema_cloud / linreg_channel；Golden Scenario payload 作为测试夹具。
- `experiment/indicators.py`：SMA/EMA/云带/唐奇安通道/ATR/RSI/量比/相对强度；
  均线类与工具箱逐点对账（误差 < 1e-9）；唐奇安通道 shift(1) 防未来函数（备用，不进 Golden Scenario）。
- 35 个单元测试全部通过（含 pandas 口径交叉校验）。
- 已合并 main 两次（PR #40 memory acceptance、PR #42 quant 工具箱），分支无分叉负担。
- Spike 文档 §6 观察记录已记三笔：初始完成、两次合并、口径迁移对账。

## 4. 剩余步骤执行细案

### 3.3 数据快照（下一步，预计 2 个 commit）

**目标**：把数据从外部变量变成实验常量。

做法：
1. `scripts/snapshot_us_daily.py`（一次性脚本，可重跑）：经 `market_data` Yahoo 兜底适配器
   拉取 SOXX / SMH / QQQ / SPY 调整后日线，区间 **2015-06-01 ~ 2026-07-31**
   （比 spec 的 2016-01-01 多留约 7 个月 warm-up：EMA89 + 60 窗通道需要前置数据，
   否则 2016 年上半年的信号口径与之后不一致——这是必须向用户暴露的数据语义，写进
   DataReadinessReport 而非静默截断）。
2. 落盘 `data/snapshots/us_daily_2016_2026/{SYMBOL}.csv`
   （date,open,high,low,close,volume,adjusted=true,source=yahoo）。
3. 生成 `manifest.json`：每文件 sha256、行数、首末日期、拉取时间、数据源、复权口径；
   总哈希 = 各文件哈希排序后拼接再 sha256。
4. `experiment/data_readiness.py`：读取快照，输出 DataReadinessReport JSON——
   覆盖区间、缺失交易日（对照 NYSE 日历近似）、warm-up 充分性、复权/时区语义说明、
   降级/缺口对实验的影响（如某标的区间不足则明确降级，不静默）。

验收：两次重跑脚本 manifest 总哈希一致；DataReadinessReport 对四只标的给出明确
「可用 / 降级可用 / 不可用」结论；观察记录追加一笔（拉取耗时、行数、缺口）。

备选：Yahoo 拉取失败或区间不足 → 换 Massive/Polygon（需 key，请作者提供或本地配置）；
仍失败 → 缩短 date_range.start 并在 spec.assumptions 与报告中同时声明。

### 3.4 薄运行时（核心工作量，预计 3~4 个 commit）

**目标**：spec 进、BacktestRun 出，纯本地纯确定性。

模块（都在 `experiment/` 下）：
1. `runtime.py`：读 spec → 载快照 → 校验 DataReadinessReport 无「不可用」→ 逐标的计算。
2. 特征计算：云带用内核 `ema_cloud()`；回归通道调工具箱 `linreg_channel(window=60, k=2)`；
   工具箱以 editable 方式引入（quant/ 已在仓库内），若打包引入有障碍则临时 sys.path
   并记录为技术债。
3. `signals.py`：`false_breakdown_reclaim` 状态机——
   收盘 < cloud_lo 进入 BROKEN（记 T0）；T0 起 5 个交易日内收盘 > cloud_hi
   且收盘 > 通道下轨 → SIGNAL（当日收盘确认）；超过 5 日未收复 → 复位并记录为
   「真跌破」样本（反证素材，ResearchMemo 要用）。再入 BROKEN 需先复位，防连发。
4. `execution.py`：信号日 T 收盘确认 → T+1 开盘价成交；退出三条件取先触发者：
   20 交易日到期（T+20 开盘）、盘中触及 8% 止损 / 15% 止盈（当日止损/止盈价成交）；
   单边滑点 5bp 计入成交价。持仓期信号去重（已有持仓不再开新仓）。
5. `metrics.py`：样本数、胜率、平均收益、最大回撤、Sharpe（口径对齐现有 engine.py
   统计函数，便于对照）、基准对比（同期 SPY 买入持有）。
6. `run.py` 产物：`reports/experiments/exp_semicon_false_break_v1/BacktestRun.json`
   ——spec 全文、manifest 总哈希、代码版本（git sha）、逐信号/逐笔记录、汇总指标。

验收：同一 spec + 快照连跑两次 BacktestRun 逐字节一致（除生成时间戳）；
用 `tests/offline_market_adapter.py` 风格合成数据写状态机单测（含「第 5 日收复」
边界、止损早于到期、持仓期去重）；mypy strict / ruff 通过。

### 3.5 Walk-forward 与 Regime 接入（预计 1~2 个 commit）

1. 读 `backtest/walk_forward.py` 与 `regime_analysis.py` 接口，能复用则薄封装
   `experiment/robustness.py` 调它们；接口绑定资金流路径无法复用时，
   **在 Spike §6 记录具体原因**（RFC 硬性要求），再按同口径写薄实现。
2. Walk-forward：按年度滚动（如 4 年训练/1 年验证，参数不优化只复算），
   输出各窗口指标稳定性。
3. Regime：用工具箱 regime 模块（BULL/BEAR 云带状态）或现有 regime_analysis
   划分环境，分桶统计信号表现——回答「什么时候失效」。

### 3.6 ResearchMemo（预计 1 个 commit）

`reports/experiments/exp_semicon_false_break_v1/ResearchMemo.md`，固定结构：
用户原始观点 / spec 解释与全部假设 / 数据事实（覆盖率、缺口）/ 结果（含成本、基准）/
**支持证据 ≥1 / 反面证据 ≥1（真跌破样本、失效 regime）/ 失效条件 / 局限
（过拟合、样本数、生存者偏差说明——ETF 无退市问题但需声明）/ 一个最有价值的后续实验**。
先手写模板填真实结果，再考虑模板化。

### 3.7 MonitorCandidate（预计 1 个 commit，手工模拟）

从 BacktestRun 提取规则，生成 `MonitorCandidate.json`：与 spec 同口径的监控条件
（云带跌破 → 5 日观察窗 → 收复确认），字段映射到现有 signals/monitor 的概念，
**不接调度、不启用**，只验证「规则无损转监控」这一 RFC 通过标准。

## 5. 工程质量约束（每个 commit 自查）

- `uv run pytest tests/test_experiment_*` 全绿；`ruff check` 无新增告警；
  `mypy --strict src/mommy_chaogu/experiment` 通过。
- 任何指标口径改动必须同步更新 pandas 交叉校验测试。
- 任何「当天判断」只用截至前一交易日已确认数据；成交价永远次根 bar 开盘。
- 观察记录（Spike §6）每完成一步追加：命令、耗时、样本数、复用失败点、意外发现。
- commit message 遵循仓库现有风格（type(scope): 中文摘要）。

## 6. RFC §8.3 通过标准对照（收尾时逐条打勾）

| 标准 | 验证方式 |
|---|---|
| 观点到首次有效结果 ≤ 5 分钟 | 3.4 完成后掐表，记录 |
| 至多一次澄清 | 已发生（均线口径一次指定），记录于 Spike §1 |
| 同 spec+数据+代码重复运行一致 | manifest 哈希 + BacktestRun 双跑 diff |
| 输出含样本数/基准/成本/回撤/Walk-forward/Regime | 3.4 + 3.5 产物检查 |
| 数据缺口与假设可见 | DataReadinessReport + spec.assumptions + Memo |
| ≥1 支持证据、≥1 反面证据、明确失效条件 | ResearchMemo 结构强制 |
| 另一 Coding Agent 只读文档可重现 | 本文件 + Spike 文档 + 快照 + 命令，收尾时请作者用干净环境验证 |
| 规则可无损转监控候选 | 3.7 MonitorCandidate.json |

## 7. 明确不做（防止范围蔓延）

- 不优化参数、不搜索最优窗口（RFC §5.2：先证伪）；
- 不做 Web 页面、不入库、不接调度、不自动下单（RFC §7.2）；
- 不扩展特征/规则类型清单，除非 Golden Scenario 真卡住；
- 不动 quant/ 工具箱本身（口径问题回报作者，不改源头）。
