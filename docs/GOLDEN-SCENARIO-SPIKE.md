# Golden Scenario Spike：半导体 ETF 均线假跌破

> 状态：进行中
> 分支：`feat/experiment-engine-spike`
> 依据：docs/AGENT-FIRST-RESEARCH-LAB-RFC.md §8
> 性质：可丢弃的薄原型。目标是回答 RFC §8.2 的问题，不是建设通用引擎。

## 1. 规则澄清（默认值）

RFC §4.1 的观点中有四处歧义，按「至多一次澄清」的要求，先给出默认值，
运行结果对这些默认值做敏感性说明，而非静默优化：

| 原表述 | 默认解释 | 理由 |
|---|---|---|
| 中期均线 | SMA20（约一个交易月） | 日线级别最常用的中期口径，人工可核验 |
| 几个交易日内收复 | 5 个交易日 | 太短信号稀少，太长与「假跌破」语义矛盾 |
| 重新进入通道 | 收盘价回到 20 日通道下轨之上 | 通道按 shift(1) 计算，不含当日，避免未来函数 |
| 持有多久 | 固定 20 个交易日，8% 止损 / 15% 止盈提前退出 | 与方法的中期波段属性匹配 |

触发定义：收盘价跌破 SMA20 记为破位日 T0；T0 起 5 个交易日内，某日收盘价
同时满足「重新站上 SMA20」且「高于 20 日通道下轨」，当日收盘入场（信号价即成交价，
成本模型另计）。

## 2. 代码资产盘点

| 资产 | 状态 | Spike 处置 |
|---|---|---|
| `backtest/engine.py` | 绑定 flow_in_spike 资金流信号与缓存表，无成本/基准 | 不复用，只参考统计口径 |
| `backtest/costs.py` | 独立成本模块 | 复用，验证接口是否通用 |
| `backtest/portfolio.py` | 组合层 | 复用，记录绑定点 |
| `backtest/walk_forward.py` | Walk-forward | 复用 |
| `backtest/regime_analysis.py` | Regime 分析 | 复用 |
| `backtest/scoring.py` | 统一评分 | 复用 |
| `workflow/spec.py` | 通用编排 spec | 不扩展，ExperimentSpec 独立（本分支 `experiment/spec.py`） |
| `market_data` 美股源 | Massive/Polygon + Yahoo 兜底 | 数据快照走 Yahoo 兜底（免 key，可复现） |
| 外部均线/通道实现 | 作者另有实现 | 以移植方式进入 `experiment/indicators.py`，零外部依赖 |

复用失败的模块必须在「观察记录」中写明原因，这是 RFC §8.1 的硬性要求。

## 3. 实施步骤

- [x] 3.1 `experiment/spec.py`：ExperimentSpec 最小 schema（结构化规则，不发明表达式 DSL）
- [x] 3.2 `experiment/indicators.py`：确定性指标内核（SMA/EMA/通道/ATR/RSI/量比/相对强度，含 look-ahead 防护）
- [ ] 3.3 数据快照：SOXX / SMH / QQQ / SPY，2016-01-01 ~ 2026-07-31 调整后日线，
      落盘 CSV + manifest（source、retrieved_at、sha256），固定数据版本
- [ ] 3.4 薄运行时：spec → 逐日信号 → 逐笔交易 → 成本/基准 → BacktestRun JSON
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
7. 外部均线/通道代码：移植进指标内核，保持零外部依赖。

以上为 Spike 工作假设，最终以 RFC §8.3 通过标准的验证结果为准。

## 6. 观察记录

（每完成一步追加：命令、耗时、样本数、复用失败点、意外发现）

- 3.1/3.2 完成：spec + 指标内核，29 个单元测试通过。通道采用 shift(1) 口径后，
  「突破当日高点」不再污染通道边界，与外部实现口径一致（待交叉校验）。
