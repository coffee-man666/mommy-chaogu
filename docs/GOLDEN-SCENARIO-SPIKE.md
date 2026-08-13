# Golden Scenario Spike：半导体 ETF 均线假跌破

> ⚠️ **状态：已封存（Superseded）**。2026-08-12 main 完成 Strategy Distillation 纠偏，
> 本文描述的 Golden Scenario / ExperimentSpec / 回测轨道不再是产品交付方向。
> 当前有效方向见 `docs/STRATEGY-DISTILLATION-RFC.md`，本分支的新使命见
> `docs/STRATEGY-CONDITION-CHECKER-PLAN.md`。本文保留仅作历史记录，不再更新。

> 原状态：进行中（封存前）
> 分支：`feat/experiment-engine-spike`
> 依据：docs/AGENT-FIRST-RESEARCH-LAB-RFC.md §8（该 RFC 已从 main 删除，见 git 历史）
> 性质：可丢弃的薄原型。目标是回答 RFC §8.2 的问题，不是建设通用引擎。

## 1. 规则澄清（默认值）

RFC §4.1 的观点中有四处歧义，按「至多一次澄清」的要求给出默认值。
**作者已确认：均线类口径一律采用 `quant/ma-suppression-monitor` 这套方法。**

| 原表述 | 默认解释 | 理由 |
|---|---|---|
| 中期均线 | EMA55/89 云带：收盘 < cloud_lo 视为跌破，收盘 > cloud_hi 视为收复 | 作者实盘口径；站上整个云带才算收复，避免在云带内部反复触发 |
| 几个交易日内收复 | 5 个交易日 | 太短信号稀少，太长与「假跌破」语义矛盾 |
| 重新进入通道 | 收盘价回到 60 日回归通道（k=2σ）下轨之上 | 工具箱 `linreg_channel`：每根 bar 有定义、无拟合失败，适合日线批量；回归窗口含当日（通道是对当前位置的描述而非突破判定），不产生前向偏差 |
| 持有多久 | 固定 20 个交易日，8% 止损 / 15% 止盈提前退出 | 与方法的中期波段属性匹配 |

触发定义：收盘价跌破云带下沿记为破位日 T0；T0 起 5 个交易日内，某日收盘价
同时满足「高于云带上沿」且「高于回归通道下轨」，信号于当日收盘确认，
**下一交易日开盘价成交**（对齐工具箱核心惯例，避免「收盘同时判断并成交」的近似偏差）。

## 2. 代码资产盘点

| 资产 | 状态 | Spike 处置 |
|---|---|---|
| `quant/ma-suppression-monitor` | 已入库（PR #41）：EMA55/89 云带、枢轴/回归通道、压制状态机、底部评分、无未来函数回测 | **均线/通道的唯一口径来源**；`linreg_channel` 由运行时直接调用，内核不重复实现 |
| `experiment/indicators.py` | 本分支指标内核 | EMA / EMA 云带 / ATR 已与工具箱同口径（TradingView 递推 EMA、TR 简单均值），pandas 交叉校验测试锁定 |
| `backtest/engine.py` | 绑定 flow_in_spike 资金流信号与缓存表，无成本/基准 | 不复用，只参考统计口径 |
| `backtest/costs.py` | 独立成本模块 | 复用，验证接口是否通用 |
| `backtest/portfolio.py` | 组合层 | 复用，记录绑定点 |
| `backtest/walk_forward.py` | Walk-forward | 复用 |
| `backtest/regime_analysis.py` | Regime 分析 | 复用 |
| `backtest/scoring.py` | 统一评分 | 复用 |
| `workflow/spec.py` | 通用编排 spec | 不扩展，ExperimentSpec 独立（本分支 `experiment/spec.py`） |
| `market_data` 美股源 | Massive/Polygon + Yahoo 兜底 | 数据快照走 Yahoo 兜底（免 key，可复现） |
| `tests/offline_market_adapter.py` | 合成行情的测试桩（无网络） | 运行时单元测试的确定性 fixture |

复用失败的模块必须在「观察记录」中写明原因，这是 RFC §8.1 的硬性要求。

## 3. 实施步骤

- [x] 3.1 `experiment/spec.py`：ExperimentSpec 最小 schema（结构化规则，不发明表达式 DSL）
- [x] 3.2 `experiment/indicators.py`：确定性指标内核，均线类口径对齐工具箱
- [ ] 3.3 数据快照：SOXX / SMH / QQQ / SPY，2016-01-01 ~ 2026-07-31 调整后日线，
      落盘 CSV + manifest（source、retrieved_at、sha256），固定数据版本
- [ ] 3.4 薄运行时：spec → 逐日信号 → 逐笔交易 → 成本/基准 → BacktestRun JSON
      （云带/回归通道由工具箱计算；成交价=信号日次日开盘）
- [ ] 3.5 复用 walk_forward / regime_analysis，记录接口不适配点
- [ ] 3.6 ResearchMemo 模板（支持证据 / 反面证据 / 失效条件 / 下一个实验）
- [ ] 3.7 手工模拟 MonitorCandidate（不接调度）

## 4. 复现方式

```bash
uv sync --frozen --extra dev
uv run pytest tests/test_experiment_spec.py tests/test_experiment_indicators.py
uv run ruff check src/mommy_chaogu/experiment tests/test_experiment_spec.py tests/test_experiment_indicators.py
uv run mypy --strict src/mommy_chaogu/experiment
```

## 5. Spike 对 RFC §13 待决问题的初步回答

1. 规则表达：纯声明式结构化 condition + params，不允许自由表达式。
2. 数据版本：快照 manifest 记录 source / retrieved_at / sha256，BacktestRun 引用 manifest 哈希。
3. 美股成本口径：佣金 0 + 单边滑点 5bp，benchmark 为 SPY 调整后收盘。
4. 监控：先复用现有 signals/monitor，写 experiment monitor adapter。
5. 实验存储：先本地 JSON 文件，稳定后再评估是否入库 agent.db。
6. 编译入口：Coding Agent + Skill 直接产出 spec，不扩 WorkflowCompiler。
7. 外部均线/通道代码：已入库 `quant/ma-suppression-monitor`，保持独立包形态，
   作为均线/通道的唯一口径来源；内核均线类指标与其同口径并有 pandas 交叉校验。

以上为 Spike 工作假设，最终以 RFC §8.3 通过标准的验证结果为准。

## 6. 观察记录

（每完成一步追加：命令、耗时、样本数、复用失败点、意外发现）

- 3.1/3.2 完成：spec + 指标内核，35 个单元测试通过。通道采用 shift(1) 口径后，
  「突破当日高点」不再污染通道边界（唐奇安通道仅作通用工具保留，不参与 Golden Scenario）。
- 合并 main（PR #40：coding agent memory acceptance；PR #42：quant 工具箱）。
- 作者指定均线类口径一律采用工具箱方法后，内核完成口径迁移并对账：
  ① EMA 改为 TradingView 递推口径（从首值递推，与 pandas `ewm(adjust=False)` 误差 < 1e-9）；
  ② ATR 由 Wilder 平滑改为 TR 简单滚动均值，首根 bar TR 退化为 high-low
  （与 pandas `max(skipna=True)` 一致），与工具箱逐点一致；
  ③ Golden Scenario 通道采用工具箱 `linreg_channel`（60 窗，k=2σ），运行时直接调用，
  内核不重复实现。对账结果固化为 pandas 交叉校验测试，防止未来口径漂移。
