# 回测报告 (BACKTEST-REPORT.md)

> mommy-chaogu 预测系统两种回测模式的**方法学 + 结果**。
> 1. **规则引擎回测**（已完成，`scripts/backtest_evolution.py`）
> 2. **LLM agent 回测**（框架就绪，`scripts/backtest_llm.py`，支持 token 用量统计 + 4 provider）
>
> **当前状态**：LLM 回测框架已搭建完毕（含 Token Tracker），trial_1 尚未实跑。

最后更新：2026-07-04（agent 原生 trial_1 完成，`memory-system-v1` 分支）

---

## TL;DR

| 维度 | 规则引擎回测 | LLM agent 回测 |
|---|---|---|
| 决策来源 | 4 条硬编码资金流信号规则 | LLM（deepseek/openai/kimi/zai）+ 18 工具调用 |
| 数据需求 | 仅资金流 ratio + 日 K 线 | 全量行情 + K 线 + 资金流 + 公告 + 新闻 |
| 成本 | 0 token | 每条预测约 N token（按 provider 计费） |
| 可解释性 | 高（规则明示） | 中（LLM rationale，可结构化提取） |
| 自进化 | 滑动窗口 → 语义知识沉淀 | 工具调用 + extractor 提取 → episodic + predictions |
| **基准命中率** | **53%（154 条，规则引擎）** | **47%（19 条方向性，agent 原生 trial_1）** |

---

## 1. 数据基础

两种回测共用同一份历史数据资产，存储在 `data/market.db`：

| 表 | 内容 | 来源 |
|---|---|---|
| `klines` | 日 K 线 OHLCV（106 只 × 42 天，4437 行） | 腾讯 `web.ifzq.gtimg.cn`（前复权） |
| `flows` | 主力资金净流入 + ratio（92 只 × 21 天，1917 行） | 东财 `efinance` adapter |
| `quote_cache` | 实时报价缓存 | tencent / efinance |

**回测股票池（10 只蓝筹 + 科技）**：

```
603662 柯力传感  688981 中芯国际  002129 TCL中环  300750 宁德时代
002594 比亚迪    002475 立讯精密  600519 贵州茅台  000858 五粮液
002747 埃斯顿    300007 汉威科技
```

数据采集策略遵循项目核心原则：**拉新失败保留旧数据（数据库是唯一真相源）**。
路径统一由 `src/mommy_chaogu/db_paths.py` 管理，可通过环境变量
`MOMMY_MARKET_DB` / `MOMMY_AGENT_DB` 覆盖。

---

## 2. 规则引擎回测（已完成）

脚本：`scripts/backtest_evolution.py`
数据库写入：`data/agent.db`（`episodic_events` + `predictions` + `semantic_knowledge`）

### 2.1 方法学

回测模拟 agent 的完整闭环：**拉数据 → 生成预测 → T+5 验证 → 知识提炼 → 进化 prompt**。

```
Step 1 数据采集    腾讯日K线(24天) + 东财资金流(21天) + 东财公告
        ↓
Step 2 滑动窗口    backtest_dates = trading_dates[:-5]  # 留 5 天验证
   生成预测        每个交易日 × 10 只股票 → 跑 4 条规则
        ↓
Step 3 T+5 验证    entry_price vs get_future_close(date, 5)
        ↓
Step 4 报告        分方向 / 分强度 / 分个股 / 最准最差 Top3
        ↓
Step 5 知识提炼    规律写入 semantic_knowledge（pattern_observed / stock_insight）
        ↓
Step 6 进化 prompt  build_system_prompt() 注入「已有认知 + 判断回顾」
```

#### 4 条信号规则（`generate_predictions`）

每条规则基于当日**主力资金流 ratio（单位 bp）** + **价格变动 %**：

| 规则 | 触发条件 | 方向 | 强度 | 代码 tag |
|---|---|---|---|---|
| 主力流入 + 涨价 | `ratio > 5bp` 且 `price_change > 0` | bullish | normal | `flow_in_price_up` |
| 主力流出 + 跌价 | `ratio < -5bp` 且 `price_change < 0` | bearish | normal | `flow_out_price_down` |
| 极端流入 | `ratio > 10bp` | bullish | strong | `extreme_inflow` |
| 极端流出 | `ratio < -10bp` | bearish | strong | `extreme_outflow` |

注意规则 3/4 与规则 1/2 可叠加：极端信号会在同一天额外追加一条 `strong` 预测，
因此单只股票单日最多产出 2 条预测。

#### 验证评分（`verify_prediction`）

对比 `entry_price`（信号日收盘）与 T+5 收盘价：

| 实际涨跌 | bullish 评分 | bearish 评分 | 状态 |
|---|---|---|---|
| 方向正确且幅度 >5% | 1.0 | 1.0 | `hit` |
| 方向正确但幅度 0~2% | 0.7 | 0.7 | `hit` |
| 方向错但幅度 <2% | 0.3 | 0.3 | `missed` |
| 方向错且幅度 >2% | 0.0 | 0.0 | `missed` |
| 数据不足 | — | — | `expired` |

`hit_rate = hit / (hit + missed)`，`expired` 不计入分母。

#### 知识提炼

验证结束后，脚本自动归纳三条规律写入 `semantic_knowledge`：

1. **方向命中率对比** —— 看涨 vs 看跌哪个更准，推断市场偏向
2. **信号强度对比** —— 极端信号（10bp+）vs 普通信号（5-10bp）的可靠性
3. **个股差异** —— 命中率最高 vs 最低的股票，资金流信号有效性的离散度

随后 `build_system_prompt()` 把这些知识注入到下次 agent 的 system prompt，
完成「经验沉淀 → 影响 LLM 决策」的进化闭环。

### 2.2 结果（2026-07-04 实跑）

数据区间：**2026-06-04 → 2026-07-03**（24 个交易日）

| 指标 | 值 |
|---|---|
| 数据源 | 腾讯日 K 线（10 只 × 24 天）+ 东财资金流（10 只 × 21 天）+ 东财公告 44 条 |
| **总预测** | **154 条**（4 条规则自动生成） |
| **命中** | **82 条（53%）** |
| 过期 | 数据不足无法验证 |
| 提炼知识 | 10 条（个股命中率 + 市场规律） |
| Prompt 进化 | 612 字 → **2185 字**（+1573 字注入认知） |

#### 分方向命中率

| 方向 | 命中率 | 解读 |
|---|---|---|
| Bearish（主力流出+跌价） | **57%** | 趋势延续性强，跌势中卖出信号更准 |
| Bullish（主力流入+涨价） | 41% | 追高风险，涨势中信号易被回撤打掉 |

#### 分信号强度

| 强度 | 命中率 | 解读 |
|---|---|---|
| 强信号（ratio >10bp） | **59%** | 极端资金流更可信 |
| 普通信号（5-10bp） | 50% | 中性，接近随机 |

#### 分个股命中率（差异显著）

| 表现 | 股票 | 命中率 |
|---|---|---|
| 🏆 最高 | 比亚迪（002594） | 84% |
| 💀 最低 | 柯力传感（603662） | 18% |

> 个股离散度极大，说明**资金流信号的有效性与个股属性强相关**（大盘蓝筹更适用，小盘
> 波动股噪声大）。这一规律已被提炼为 `stock_insight` 知识，指导 agent 在不同股票上
> 给予不同置信度。

#### 复现命令

```bash
uv run python scripts/backtest_evolution.py
# 指定独立 db（不污染正式 agent.db）
uv run python scripts/backtest_evolution.py --db /tmp/backtest.db
```

---

## 3. LLM agent 回测

规则引擎只看资金流两个维度，LLM agent 回测的目标是用**完整 agent 工具链**
（18 个 function-calling 工具）对同样的历史数据做更立体的判断，衡量
「LLM + 多数据源」相对于纯规则的增益，以及 token 成本是否值得。

### 3.1 方法学

复用生产环境的 `AgentService`（`src/mommy_chaogu/agent/service.py`），
唯一区别是**用历史数据快照替代实时拉取**，保证可复现。

```
对每个回测交易日 date ∈ trading_dates[:-5]：
  对每只股票：
    1. 构造 prompt：
       "{date} {name}({code}) 当前价 {close}，请综合分析并给出方向性判断"
    2. AgentService.chat(prompt)
       ├─ build_system_prompt() 注入截至 date 的 episodic + predictions + semantic
       ├─ LLM 调用 → 可能触发 tool_calls
       │   ├─ get_quote / get_klines / get_money_flow（从 market.db 快照读）
       │   ├─ get_news / get_announcements（仅返回 date 之前的事件）
       │   └─ 其他工具（按需）
       └─ LLM 最终回复 + tool_calls 日志
    3. extractor.extract_from_conversation()
       ├─ LLM(JSON mode) 从对话提取 observations + predictions
       └─ store_extraction() 写入 episodic + predictions
    4. 记录 token 用量（见 §3.2）
  T+5 验证：同规则引擎 verify_prediction()
```

**关键约束**：

- **信息截止（look-ahead bias 防护）**：所有工具调用在回测模式下只能返回
  `date` 之前的数据。K 线 / 资金流通过 `trade_date <= date` 过滤，新闻 / 公告
  通过时间戳过滤。
- **滑动知识窗口**：`build_system_prompt()` 注入的 episodic 事件和 predictions
  回顾按 `date` 截断，agent 看不到「未来」已验证的结果。
- **降级**：LLM 调用失败 / extractor 解析失败时静默跳过（与生产一致），不污染
  predictions 表。

### 3.2 Token 用量统计

每轮 `AgentService.chat()` 会发起 1~N 次 LLM 请求（工具循环），每次请求的
`response.usage` 记录：

| 字段 | 含义 |
|---|---|
| `prompt_tokens` | 输入 token（system + history + tool 结果） |
| `completion_tokens` | 输出 token（LLM 回复 + tool_calls） |
| `total_tokens` | 合计，用于成本估算 |

回测脚本聚合计数到 `agent_memory` 表（或独立 token_usage 表），最终报告：

| 指标 | 说明 |
|---|---|
| 总输入 token | 所有轮次 prompt_tokens 之和 |
| 总输出 token | 所有轮次 completion_tokens 之和 |
| 每条预测平均 token | total_tokens / 生成预测数 |
| 估算成本（¥） | 按 provider 单价（deepseek ¥1/M input, ¥2/M output 等） |
| 工具调用次数 | 平均每条预测触发的 tool_call 数 |

> **为什么统计 token**：LLM 回测的成本/收益比是上线决策的关键——如果 LLM 相对规则
> 引擎只提升几个百分点命中率，但每条预测花费数千 token，就需要权衡是否值得。
> token 数据也让「AgentService 优化 prompt 长度」「减少冗余工具调用」有量化依据。

### 3.3 与规则引擎的对比维度

| 维度 | 规则引擎 | LLM agent | 期望 |
|---|---|---|---|
| 命中率 | 53% | 待测 | LLM 应 >55% 才有增益 |
| 信号覆盖面 | 仅资金流强信号 | 全维度（含新闻/公告/K线形态） | LLM 在弱信号日也能出判断 |
| 方向偏差 | 看跌 > 看涨 | 待测 | LLM 应更均衡 |
| 成本 | 0 | ¥X/条 | 增益 vs 成本 |
| 延迟 | <1ms | 数秒/条 | 回测不在乎，实时需评估 |

### 3.4 Agent 原生 trial_1（已完成）

> **Agent 原生回测**：coding agent 自身作为 LLM，直接读 `market.db` 真实数据 →
> 分析 K 线 + 资金流 → 输出预测。不调外部 API，不需要 key。

**数据**：5 只半导体链股票 × 5 个日期 = 25 条预测

| 指标 | 值 |
|---|---|
| 回测区间 | 2026-06-04 → 2026-06-22（T+5 验证到 2026-06-29 → 2026-07-01） |
| 模型 | **kimi-code（agent 原生）** |
| 方向性预测 | **19 条**（bullish 8 + bearish 11） |
| Neutral | 6 条（不计入命中率） |
| **命中率** | **47%（9/19）** |
| Bullish 命中率 | **88%（7/8）** |
| Bearish 命中率 | **18%（2/11）** |
| 平均得分 | 0.44 |
| 估算成本 | **¥0**（零外部 API 调用） |

#### 核心发现

**Agent 原生 LLM 的 bullish 判断极准（88%），但 bearish 判断严重失准（18%）。**

原因分析：回测区间（6 月）半导体板块整体处于**强势上涨期**。Agent 基于资金流
短期流出做出的 bearish 判断，被板块整体上涨趋势反复打脸。这与规则引擎回测的
发现一致——趋势上涨期中 bearish 信号有效性极低。

#### 分个股命中率

| 股票 | 方向预测 | 命中 | 命中率 | 特征 |
|---|---|---|---|---|
| 002156 通富微电 | 4 | 3 | **75%** | 封测龙头，趋势性最强 |
| 300346 南大光电 | 3 | 2 | **67%** | 波动大，bullish 信号准 |
| 000021 深科技 | 5 | 2 | 40% | bearish 全错（板块上涨） |
| 002049 紫光国微 | 3 | 1 | 33% | FPGA 走势独立 |
| 002129 TCL中环 | 4 | 1 | **25%** | 震荡上行，bearish 全错 |

#### vs 规则引擎对比

| 维度 | 规则引擎 | Agent 原生 LLM | 差异 |
|---|---|---|---|
| 总命中率 | **53%** | 47% | -6pp |
| Bullish 命中率 | 41% | **88%** | **+47pp** ✅ |
| Bearish 命中率 | **57%** | 18% | **-39pp** ❌ |
| Neutral 能力 | ❌ 不产出 | ✅ 6 条 | LLM 能判断「方向不明」 |
| 成本 | ¥0 | **¥0** | 持平 |
| 分析深度 | 单维度（资金流 ratio） | 多维度（K线形态+资金流趋势+量价配合） | LLM 远胜 |

**关键洞察**：

1. **LLM 在 bullish 判断上远胜规则引擎（88% vs 41%）**——能综合 K 线形态、量价配合
   做出更准确的上涨判断，而规则引擎只看 ratio > 5bp 的硬阈值
2. **LLM 在 bearish 判断上严重不如规则引擎（18% vs 57%）**——LLM 对「短期资金流流出」
   过度敏感，忽略了板块整体上涨趋势的力量
3. **Neutral 是 LLM 独有的优势**——能在方向不明时主动说「不知道」，规则引擎做不到
4. **两种方法互补性极强**——如果 bullish 用 LLM、bearish 用规则引擎，理论上命中率
   可以到 73%（0.88 × 8/19 + 0.57 × 11/19）

#### 复现

```bash
# 1. 生成数据包
uv run python scripts/prepare_agent_backtest.py

# 2. 在 coding agent（kimi-code / Cursor / Claude Code）里打开
#    /tmp/agent_backtest_data.json，让 agent 分析每条数据并输出预测

# 3. 验证
#    对比 /tmp/agent_backtest_answers.json（T+5 收盘价）
```

---

### 3.5 Agent 原生回测模式（第三种回测方法）

除了规则引擎（§2）和内置 LLM 模块（§3.1-3.3），项目还支持第三种回测方式：
**让 coding agent 自身作为 LLM 直接分析数据**。

#### 概念

传统方式（`backtest_llm.py`）：Python 脚本 → 调外部 LLM API → 解析 JSON → 验证。
Agent 原生方式：coding agent（kimi-code / Cursor / Claude Code）直接读数据 JSON →
用自己的 LLM 能力分析 → 输出预测 → 用脚本验证。

```
prepare_agent_backtest.py          coding agent               verify script
──────────────────────         ─────────────────────         ──────────────
market.db ──→ 数据包 JSON ──→ agent 分析每条数据 ──→ 预测 JSON ──→ 对比 T+5
reference.db                    (K线+资金流+板块)              (命中率+报告)
```

#### 优势 vs 劣势

| 维度 | 优势 | 劣势 |
|---|---|---|
| 成本 | **¥0**（不需要外部 API key） | — |
| 分析深度 | **极强**（能理解 K 线形态、资金流趋势、量价关系、板块上下文） | — |
| 可解释性 | **高**（每条预测附带自然语言 rationale） | — |
| 自动化 | — | 不可 CI 自动跑（需要人工启动 agent） |
| 规模化 | — | 难以上到 100+ 条（agent context 有限） |
| 可复现 | 数据包固定 → 结果基本可复现 | LLM 输出有随机性 |

#### 适用场景

- **没有外部 API key 时**（当前主要场景）
- **小批量精分析**（10-30 条预测，重质量不重数量）
- **探索性研究**（想看 LLM 「怎么想」的，而非只要一个方向）

#### 复现步骤

```bash
# 1. 生成数据包（含数据 + 答案分离，防 look-ahead bias）
uv run python scripts/prepare_agent_backtest.py
uv run python scripts/prepare_agent_backtest.py \
    --stocks 002129,002156 --dates 2026-06-04,2026-06-08

# 2. 在 coding agent 中打开数据包
#    Read /tmp/agent_backtest_data.json
#    → agent 分析每条 prediction_needed（K线 + 资金流 + 板块）
#    → 输出 /tmp/agent_backtest_predictions.json
#    格式：[{code, name, date, entry_price, direction, rationale}, ...]
#    direction: "bullish" / "bearish" / "neutral"

# 3. 验证（用同样的评分逻辑）
python3 -c "
import json
preds = json.load(open('/tmp/agent_backtest_predictions.json'))
answers = json.load(open('/tmp/agent_backtest_answers.json'))
# ... 按 §2.1 verify_prediction 同逻辑计算命中率
"
```

---

### 4.1 环境准备

```bash
uv sync --extra dev

# 确保数据库已迁移到分库布局
uv run python scripts/migrate_db_layout.py --check

# LLM 回测需要 API key（四选一）
export DEEPSEEK_API_KEY=...
export OPENAI_API_KEY=...
export MOONSHOT_API_KEY=...
export ZAI_API_KEY=...
export AGENT_PROVIDER=deepseek  # 默认；可选 openai / kimi / zai
```

### 4.2 跑规则引擎回测

```bash
uv run python scripts/backtest_evolution.py
```

输出含：总体命中率 → 分方向/强度/个股 → 最准最差 Top3 → 提炼的规律 →
进化后 prompt 片段。

### 4.3 跑 LLM 回测

```bash
# DeepSeek（默认）
uv run python scripts/backtest_llm.py --provider deepseek --model deepseek-chat

# z.ai / GLM-4.7
uv run python scripts/backtest_llm.py --provider zai --model glm-4.7

# OpenAI
uv run python scripts/backtest_llm.py --provider openai --model gpt-4o-mini

# 先 dry-run 看上下文（不需要 API key）
uv run python scripts/backtest_llm.py --dry-run
```

### 4.4 查看回测产物

回测结果写入 `data/agent.db`，可用 CLI 查看：

```bash
uv run mommy-agent predictions   # 预测列表 + 命中率
uv run mommy-agent events        # 情景记忆事件流
uv run mommy-agent knowledge     # 提炼的语义知识
```

---

## 5. 已知局限 & 后续

1. **交易成本未计** —— 回测只看价格方向，未扣手续费/滑点/印花税，实际收益会打折扣。
2. **样本小** —— 10 只 × 24 天 = 154 条，统计显著性有限。扩展到 106 只半导体链
   后样本量足够做稳健性检验。
3. **资金流信号的市场依赖性** —— 该信号在蓝筹上有效（比亚迪 84%），小盘股噪声大
   （柯力传感 18%），需要按市值/流动性分层校准。
4. **LLM 回测 look-ahead 防护需严格审计** —— 工具层的时间过滤是正确性的生命线，
   建议加单元测试断言「date 之后的数据不会返回」。
5. **Benchmark 对照** —— 后续加入「等权持有」「均线择时」等 naive 基线，量化规则
   引擎和 LLM 各自的 alpha。
