# Strategy Condition Checker — 云带条件自动检查计划

> 状态：进行中
> 分支：`feat/experiment-engine-spike`（使命已于 2026-08-13 改写，分支名留作历史）
> 依据：docs/STRATEGY-DISTILLATION-RFC.md、docs/STRATEGY-DISTILLATION-RECOVERY-PLAN.md、
> AGENTS.md「产品定位 / 产品交付原则」
> 前身（已封存）：docs/GOLDEN-SCENARIO-SPIKE.md、docs/GOLDEN-SCENARIO-SPIKE-K3MaxExecutionPlan.md

## 1. 使命

让策略卡上的 EMA 云带 / ATR / 通道条件，能从 `unavailable` 诚实地升级为 `supported`。

docs/examples/ma-suppression-strategy-card.md 中 6 个条件有 4 个标「当前不可用」，
原因相同：*独立算法包尚未接入主程序的可靠 OHLC/时间口径*。本计划只填这一个缺口，
不扩张到其他能力。

## 2. 明确的不是

遵守 STRATEGY-DISTILLATION-RFC §8.2 与恢复计划 §2：

- 不是回测，不做收益统计、Walk-forward、Regime、Sharpe；
- 不是通用 ExperimentSpec / 策略 DSL / 因子编译器；
- 不新增监控规则类型（仍只有价格/涨跌幅四类）；
- 不替用户判断策略有效性；`supported` 只表示「现有工具能提供所需当前证据」。

## 3. 已完成的改造（2026-08-13）

- 合并 main（含策略卡体系、AGENTS.md 产品原则、iOS、cache 修复）。
- `experiment/` 包下架：ExperimentSpec（执行 DSL）删除，git 历史留痕。
- 指标内核迁入 `src/mommy_chaogu/strategy/indicators.py`：
  EMA / EMA 云带（55/89）/ ATR 与 quant/ma-suppression-monitor 同口径，
  pandas 交叉校验测试锁定（tests/test_strategy_indicators.py，35 个用例）。
- 两份 spike 文档标记 Superseded 封存。

## 4. 下一步：当前状态评估器（最小纵向闭环）

**用户可感知产物**：Agent 按策略卡回答「SOXX 今天处于什么状态」时，云带条件
逐条给出「满足 / 不满足 / 无法判断」+ 证据读数 + 数据口径说明。

做法（按 AGENTS.md 原则：最小必要工程）：

1. `strategy/condition_check.py`（薄层，不建通用 runtime）：
   - 输入：策略卡条件中已结构化的少数几种云带检查（先支持：收盘 vs cloud_lo /
     cloud_hi 的位置关系、cloud 牛熊排列、ATR 距离）+ 标的代码；
   - 经现有 `market_data` Yahoo 适配器拉**近期约 300 根日线**（够 EMA89 稳态 +
     60 窗通道读数；不是十年快照，不做历史审计）；
   - 输出：`满足 / 不满足 / 无法判断` + 证据值（日期、close、cloud_lo、cloud_hi、
     ATR、口径与缺口说明）。数据不足或口径不明时一律「无法判断」，不猜。
2. 验收样例：对 docs/examples/ma-suppression-strategy-card.md 逐条件试评，
   能自动的部分给出真实读数，不能的说明还缺什么（如压制状态机需逐 bar 历史，
   属于后续阶段，不硬做）。
3. 通过真实评审前不改策略卡样例的 automation 标注；评估器输出只作为升级依据
   提交给用户判断。
4. 工程约束同前：ruff / mypy strict / pytest 全绿；金额 Decimal；
   收盘确认、无未来函数纪律不变。

## 5. 进入后续阶段的条件（不预先建设）

- 压制状态机（ARMED/ENGAGED/CONFIRMED）逐 bar 评估：仅在用户确认当前读数
  有价值后，作为独立一步评审；
- 历史验证（任何形式的回测）：仅按 STRATEGY-DISTILLATION-RFC §11 的五项前提
  独立评审后进入，与本计划无关。

## 6. 观察记录

- 2026-08-13：分支使命改写。main 纠偏要点：Golden Scenario / ExperimentSpec /
  回测轨道取消为交付门槛；工程完成度不等于用户完成度。原 spike 资产判定：
  指标内核与口径测试保留（迁入 strategy/），其余下架。
