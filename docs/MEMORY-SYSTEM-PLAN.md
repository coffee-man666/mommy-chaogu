# 自进化记忆系统设计

> 让 agent 从「每次从零开始」变成「越用越懂」的投研智能体——记住过去、讲出脉络、验证判断、沉淀经验。
>
> 状态：设计稿 v2（合并版，2026-07-03）
>
> 前置依赖：`docs/BRANCH-MERGE-ANALYSIS.md`（merge 完成）、`src/mommy_chaogu/agent/memory.py`（现有朴素记忆）

---

## 1. 现状与目标

当前记忆系统（`agent/memory.py`）是一个**聊天记录本**：存原文、取最近 20 条拼 prompt。

**无法做到：**

- 记住行情分析的结构化快照（"7/1 创新药涨了 5.1%，主力流入 19.47 亿"）
- 从多次分析中提炼板块叙事（"创新药处于政策底 + 估值底 + 出海兑现期"）
- 做前后比对（"上周你说半导体要调整，这周确实跌了"）
- 验证自己的判断（"推荐了柯力传感底部反转，5 天后涨了 8% — 印证了"）

**目标**：四层记忆架构 + 预测验证闭环，数据缺失场景下不误判。

---

## 2. 核心约束：数据不完整是常态

设计必须把「数据缺失」作为一等公民。

### 2.1 数据可用性矩阵（实测）

| 数据类型 | 主源 | 备源 | 缓存兜底 | 失败行为 |
|---|---|---|---|---|
| 实时报价 | efinance ✅ | tencent ✅ | stale cache ✅ | 三重保险，几乎不会丢 |
| 资金流（日内） | efinance | ❌ 腾讯无此接口 | stale cache | 东财挂 = 只有旧数据 |
| 资金流（历史） | efinance | ❌ | 永久缓存 | 拉过的不会丢，没拉过就没有 |
| K线 | efinance | ❌ | 永久缓存（按日期） | 同上 |
| 大盘指数 / 板块榜 | 东财直连 | ❌ | ❌ 无缓存 | 挂了就是空列表，且无历史 |
| 基本面 / 新闻 / 龙虎榜 | 东财直连 | ❌ | ❌ | 挂了返回空，且无历史 |
| 盘口 / Tick | efinance | ❌ | ❌ passthrough | 挂了就是空 |

### 2.2 设计原则

1. **预测验证必须容忍数据缺失** — 不能因为"今天东财挂了"就标记为 missed
2. **验证可延迟** — 今天拿不到数据，明天/后天再试，超时才标 expired
3. **记录数据可用性** — 每条 event / prediction 都带 `data_coverage` 字段
4. **降级验证** — 资金流数据拿不到时，退化为「价格验证」（报价有三重保险）
5. **从不伪造验证结果** — 数据不可用时标 `unverifiable`，不猜

---

## 3. 架构总览

四层记忆（CoALA 框架）+ 预测验证闭环，映射到 A 股投研：

```
┌──────────────────────────────────────────────────────────┐
│  Layer 4: 程序记忆 (Procedural) — 策略与规则              │
│  ├─ system prompt 中的分析原则（ratio bp、量价关系）      │
│  ├─ 动态注入的经验摘要（命中率反馈）       ← self-review  │
│  └─ 可更新策略库（从语义记忆中沉淀）                      │
├──────────────────────────────────────────────────────────┤
│  Layer 3: 语义记忆 (Semantic) — 提炼出的知识             │
│  ├─ 板块叙事（sector_thesis）                             │
│  ├─ 个股认知（stock_insight）                             │
│  ├─ 市场状态（market_regime）                             │
│  └─ 规律观察（pattern_observed）— 置信度由命中率校准      │
├──────────────────────────────────────────────────────────┤
│  Layer 2: 情景记忆 + 预测追踪 (Episodic + Prediction)    │
│  ├─ 按时间排序的结构化事件流（market_snapshot /           │
│  │   analysis_record / signal_event / trade_decision）   │
│  ├─ 预测追踪状态机（pending → hit / missed / expired）   │
│  └─ 降级验证引擎（报价优先，资金流可选，数据缺失不误判）  │
├──────────────────────────────────────────────────────────┤
│  Layer 1: 工作记忆 (Working) — 当前会话                   │
│  ├─ context window + 最近 N 轮对话原文                    │
│  └─ ConversationMemory.recent()（已有，保留）             │
└──────────────────────────────────────────────────────────┘
```

### 四层映射到投研场景

| 记忆类型 | 回答什么 | 投研内容 | 实现 |
|---|---|---|---|
| **工作** | "现在在看什么？" | 当前会话上下文 | context window（已有） |
| **情景** | "之前发生了什么？" | 每日快照、分析记录、信号触发、买卖决策 | `episodic_events` 表 |
| **语义** | "什么是真的？" | 板块叙事、个股认知、规律观察 | `semantic_knowledge` 表 |
| **程序** | "该怎么做？" | 分析流程、经验反馈、策略偏好 | system prompt 动态注入 |

**闭环关系**：情景记忆 →（LLM 离线提炼）→ 语义记忆 →（注入）→ 程序记忆 →（指导分析）→ 情景记忆

**预测验证闭环**：情景记忆中记录预测 → 降级验证引擎定时检查 → 命中率反馈 → 校准语义记忆的置信度 → 注入程序记忆

---

## 4. 数据库 Schema（同一份 `data/watchlist.db`）

### 4.1 `episodic_events` — 情景记忆（事实层）

```sql
CREATE TABLE IF NOT EXISTS episodic_events (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp     TEXT NOT NULL,               -- ISO 8601 UTC
    trade_date    TEXT,                        -- YYYY-MM-DD（交易日，可空）
    event_type    TEXT NOT NULL,               -- market_snapshot / analysis_record / signal_event / trade_decision
    scope         TEXT NOT NULL,               -- "market" / "sector:创新药" / "stock:600519" / "portfolio"
    code          TEXT,                        -- 股票代码（可空，market_snapshot 无）
    name          TEXT,                        -- 股票名称

    data          TEXT NOT NULL,               -- JSON: 结构化内容
    summary       TEXT NOT NULL,               -- 一句话摘要
    tags          TEXT DEFAULT '[]',           -- JSON array: ["暴跌", "风格切换", "政策利好"]

    -- 数据可用性标记（核心约束）
    data_coverage TEXT NOT NULL DEFAULT '{}',  -- JSON: {"quote": true, "flow_today": true, "flow_5d": false, "news": false}

    source        TEXT NOT NULL DEFAULT 'agent', -- "user" / "agent" / "cron_report" / "earnings" / "signal"
    confidence    REAL DEFAULT 0.5,             -- 0.0~1.0

    -- 关联（可选）
    prediction_id INTEGER,                      -- 如果关联一条预测

    created_at    TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS ix_episodic_scope ON episodic_events(scope);
CREATE INDEX IF NOT EXISTS ix_episodic_type ON episodic_events(event_type);
CREATE INDEX IF NOT EXISTS ix_episodic_ts ON episodic_events(timestamp);
CREATE INDEX IF NOT EXISTS ix_episodic_code_date ON episodic_events(code, trade_date);
```

### 4.2 `predictions` — 预测追踪

```sql
CREATE TABLE IF NOT EXISTS predictions (
    id                    INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at            TEXT NOT NULL,         -- ISO8601 UTC
    code                  TEXT NOT NULL,
    name                  TEXT,

    prediction            TEXT NOT NULL,         -- 自然语言："底部反转初期信号"
    direction             TEXT NOT NULL,         -- "bullish" / "bearish" / "neutral"
    rationale             TEXT,                  -- 推理依据

    -- 可量化目标（可选）
    target_price          REAL,                  -- 目标价
    entry_price           REAL,                  -- 提出时的价格
    stop_loss             REAL,                  -- 止损价
    change_pct_at_creation REAL,                 -- 提出时当日涨跌幅

    -- 时间窗口
    timeframe             TEXT NOT NULL,         -- "1d" / "5d" / "20d" / "60d"
    verify_after          TEXT NOT NULL,         -- 最早验证时间

    -- 状态机
    status                TEXT NOT NULL DEFAULT 'pending',
                                               -- pending / hit / missed / expired / unverifiable
    verified_at           TEXT,
    actual_price          REAL,
    actual_change_pct     REAL,
    accuracy_score        REAL,                  -- 0.0~1.0

    -- 验证过程记录
    verify_attempts       INTEGER DEFAULT 0,
    verify_log            TEXT,                  -- JSON: [{"attempt": 1, "time": "...", "result": "data_unavailable"}]

    -- 数据覆盖
    data_coverage_at_creation TEXT,
    data_coverage_at_verify   TEXT,

    -- 溯源
    source_event_id       INTEGER,               -- 关联的 episodic_events.id
    insight_event_id      INTEGER                -- 验证结果写回的 episodic_events.id
);

CREATE INDEX IF NOT EXISTS ix_pred_status ON predictions(status);
CREATE INDEX IF NOT EXISTS ix_pred_code ON predictions(code);
CREATE INDEX IF NOT EXISTS ix_pred_verify_after ON predictions(verify_after);
```

### 4.3 `semantic_knowledge` — 语义记忆（知识层）

```sql
CREATE TABLE IF NOT EXISTS semantic_knowledge (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    knowledge_type    TEXT NOT NULL,             -- sector_thesis / stock_insight / market_regime / pattern_observed
    scope             TEXT NOT NULL,             -- "sector:创新药" / "stock:600519" / "market"
    content           TEXT NOT NULL,             -- 知识内容
    confidence        REAL DEFAULT 0.8,          -- 0-1（由命中率校准）
    source_event_ids  TEXT DEFAULT '[]',         -- JSON array of episodic event IDs
    status            TEXT DEFAULT 'active',     -- active / superseded
    hit_count         INTEGER DEFAULT 0,         -- 基于该知识的预测命中次数
    miss_count        INTEGER DEFAULT 0,         -- 基于该知识的预测失误次数
    created_at        TEXT NOT NULL,
    updated_at        TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS ix_semantic_scope ON semantic_knowledge(scope);
CREATE INDEX IF NOT EXISTS ix_semantic_type ON semantic_knowledge(knowledge_type);
CREATE INDEX IF NOT EXISTS ix_semantic_status ON semantic_knowledge(status);
```

### 4.4 `insight_summary` — 周期复盘

```sql
CREATE TABLE IF NOT EXISTS insight_summary (
    id                  INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at          TEXT NOT NULL,
    period              TEXT NOT NULL,           -- "daily" / "weekly" / "monthly"
    period_start        TEXT NOT NULL,
    period_end          TEXT NOT NULL,

    -- 预测统计
    total_predictions   INTEGER,
    hit_count           INTEGER,
    missed_count        INTEGER,
    expired_count       INTEGER,
    unverifiable_count  INTEGER,
    hit_rate            REAL,                    -- hit / (hit + missed)，排除 unverifiable

    -- 事件统计
    total_events        INTEGER,
    data_coverage_avg   REAL,                    -- 平均数据覆盖率

    -- LLM 生成内容
    best_calls          TEXT,                    -- JSON: 本期最准的预测
    worst_calls         TEXT,                    -- JSON: 本期最差的预测
    key_lessons         TEXT,                    -- 自然语言经验摘要
    narrative           TEXT,                    -- 市场脉络叙述
    regime              TEXT,                    -- 市场状态判断

    -- 注入 prompt 的精简版（≤200 字）
    prompt_snippet      TEXT NOT NULL
);
```

### 4.5 `episodic_embeddings` — 向量索引（Phase 5）

```sql
CREATE TABLE IF NOT EXISTS episodic_embeddings (
    event_id    INTEGER PRIMARY KEY REFERENCES episodic_events(id),
    embedding   BLOB,                            -- float32 vector
    model       TEXT NOT NULL,
    created_at  TEXT NOT NULL
);
```

---

## 5. 事件类型与写入管道

### 5.1 四种事件类型

| event_type | 触发时机 | scope | data 内容 |
|---|---|---|---|
| `market_snapshot` | 收盘 cron（15:30） | `market` | 大盘 6 指数涨跌、板块 TOP5、全市场涨跌统计 |
| `analysis_record` | 每次 agent 对话或 report 后 | `sector:创新药` / `stock:600519` | 分析输入 + agent 结论 |
| `signal_event` | AgentMonitor 扫描出 alert | `stock:600519` | 信号内容、触发条件、当时价格 |
| `trade_decision` | 用户手动记录买卖 | `portfolio` | code/price/shares/reason |

### 5.2 写入管道

| 触发点 | 改动 |
|---|---|
| `AgentService.chat()` 返回后 | 后置 hook：LLM 提取 observations + predictions → 写 episodic + predictions |
| `AgentReportService.generate()` | 完成后写 `analysis_record` |
| `AgentMonitor.scan_once()` | 有 alert 时写 `signal_event` |
| 新增 CLI: `mommy-agent remember --type trade --code 600519 --action buy --price 80 --shares 100 --reason "底部反转"` | 手动写入 |
| 收盘 cron 15:30 | 拉大盘数据写 `market_snapshot` |

### 5.3 对话后事实抽取

```
用户对话 → AgentService.chat() 返回 → 后置 hook
    ├─ LLM structured output 提取 observations + predictions
    ├─ 写入 episodic_events
    ├─ 有方向性判断 → 写入 predictions
    └─ data_coverage 由提取 prompt 判断
```

提取 prompt（JSON response mode）：

```
从以下对话中提取结构化信息。如果没有可提取的投资观察或预测，返回空数组。

对话:
  user: {user_message}
  assistant: {assistant_response}

提取格式:
{
  "observations": [
    {
      "event_type": "analysis_record",
      "scope": "stock:603662",
      "code": "603662",
      "name": "柯力传感",
      "summary": "6/30 和 7/2 两次放量流入，底部反转初期信号",
      "data": {"flow_5d": 179000000, "direction": "inflow"},
      "data_coverage": {"quote": true, "flow_today": true, "flow_5d": false, "news": false},
      "confidence": 0.7,
      "tags": ["底部反转", "放量"]
    }
  ],
  "predictions": [
    {
      "code": "603662",
      "prediction": "底部反转初期，短期看涨",
      "direction": "bullish",
      "timeframe": "5d",
      "target_price": 84.49,
      "rationale": "业绩催化 +188%~217% + 放量流入"
    }
  ]
}
```

---

## 6. 预测验证引擎（降级策略）

### 6.1 状态机

```
                     创建
                      ↓
                  pending ←──────────┐
                      │              │
            到 verify_after          │
                      │              │
                      ↓              │
              ┌────验证─────┐        │
              │              │       │
         数据可用          数据不可用  │
              │              │       │
         ┌────┴────┐    attempts++   │
         │         │         │       │
       hit     missed    attempts<3──┘
         │         │
         └────┬────┘
              ↓
         写回 episodic_events
         (验证结果 observation)

     attempts >= 3 → expired
```

### 6.2 验证降级策略

```python
def verify_one(pred: Prediction, adapter) -> VerifyResult:
    """验证优先级：报价（三重保险）→ 资金流（可选）→ 不可用"""

    # 第一优先：报价验证（几乎不会失败）
    quote = adapter.get_latest_quote(pred.code)
    if quote is None:
        cache = cache_store.get_quote(pred.code)
        if cache is None:
            return VerifyResult(DATA_UNAVAILABLE, "报价数据完全不可用")
        quote = cache  # 用缓存中的旧报价

    # 报价验证逻辑
    if pred.direction == "bullish":
        if pred.target_price and quote.price >= pred.target_price:
            return VerifyResult(HIT, price=quote.price, score=1.0)
        elif quote.change_pct > 2:
            return VerifyResult(HIT, price=quote.price, score=0.7)
        elif quote.change_pct < -3:
            return VerifyResult(MISSED, price=quote.price, score=0.0)
    # bearish 镜像...

    # 资金流类预测：额外尝试资金流二次确认（可能失败，不 block）
    if "flow" in (pred.data_coverage_at_creation or ""):
        flow = adapter.get_today_money_flow(pred.code)
        if flow:
            # 资金流方向二次确认（加成）
            ...
        # 资金流不可用 = 只用报价验证结果，不 block

    # 超过窗口还没 hit/missed
    if now() > pred.created_at + parse_timeframe(pred.timeframe):
        return VerifyResult(EXPIRED)

    return VerifyResult(STILL_PENDING)
```

### 6.3 评分规则

**方向预测**：

| direction | actual change_pct | status | score |
|---|---|---|---|
| bullish | > +2% | hit | 1.0 |
| bullish | 0 ~ +2% | hit | 0.7 |
| bullish | -2 ~ 0 | missed | 0.3 |
| bullish | < -2% | missed | 0.0 |

**目标价预测**：

| |actual - target| / target | status | score |
|---|---|---|---|
| < 2% | hit | 1.0 |
| 2-5% | hit | 0.8 |
| 方向对但没到目标 | hit | 0.5 |
| 方向错 | missed | 0.2 |

---

## 7. 市场脉络生成（narrative）

```python
class MarketNarrative:
    """基于情景记忆生成市场脉络分析。"""

    def generate_narrative(
        self,
        scope: str = "market",
        days: int = 30,
    ) -> str:
        """生成一段市场脉络叙述。

        流程：
        1. 拉过去 N 天的所有相关 episodic_events
        2. LLM 分析：关键转折点 → 因果链 → 当前状态 → 与之前的变化
        3. 返回结构化的叙述文本

        示例输出：
        "过去30天的主线是'科技股高低切'。
         6月中旬半导体见顶（7/1出现对子顶信号），
         资金开始向低位板块转移——创新药（7/1 +5.1%）、
         化工、养殖业逆势走强。
         当前状态：风格切换进行中，科技板块仍在调整，
         低位板块刚开始补涨。"
        """

    def detect_changes(self, scope: str = "market") -> str:
        """检测最近 3 天 vs 之前 10 天的关键变化。只输出'变了什么'。"""

    def compare_periods(
        self,
        scope: str,
        date1: str,
        date2: str,
    ) -> dict:
        """对比两个时间点的事件数据，返回差异。"""
```

**Agent 工具**：在 `tools.py` 加 `get_market_narrative` 工具，让 agent 在对话中可以自主调出市场脉络。

**CLI**：
```bash
mommy-agent narrative --days 30          # 生成 30 天市场脉络
mommy-agent narrative --scope "sector:创新药" --days 14
mommy-agent narrative --changes           # 检测最近变化
mommy-agent narrative --days 7 --push     # + 微信推送
```

---

## 8. 语义记忆提炼（consolidator）

### 8.1 四种知识类型

| knowledge_type | 内容 | 提炼频率 | 示例 |
|---|---|---|---|
| `sector_thesis` | 板块核心叙事 | 每周 | "创新药处于政策底 + 估值底 + 出海兑现期" |
| `stock_insight` | 个股认知 | 每周 | "柯力传感是机器人力矩传感器龙头，每次大跌抗跌" |
| `market_regime` | 市场状态 | 每天 | "高低切进行中，科技调整 + 低位补涨" |
| `pattern_observed` | 规律观察 | 每周 | "对子顶信号后 1 天平均跌 8%" |

### 8.2 提炼流程

```python
class MemoryConsolidator:
    """从情景记忆提炼语义记忆的离线任务。"""

    def consolidate_all(self):
        self._consolidate_sector_theses()    # 板块叙事
        self._consolidate_market_regime()    # 市场状态
        self._consolidate_patterns()         # 规律归纳

    def _consolidate_sector_theses(self):
        """从过去 N 天的板块事件提炼板块叙事。

        输入：该板块的所有 analysis_record + market_snapshot + signal_event
        LLM 任务："基于以下事件，提炼出 {sector} 的核心叙事。
                  如果叙事与已有认知矛盾，标记为 supersede。"
        输出：写入 semantic_knowledge 表
        """

    def _consolidate_patterns(self):
        """从 predictions 表中归纳规律。

        示例：发现"量比 > 2 + 主力流入 > 5bp"后 3 天上涨概率 70%
        → 写入 pattern_observed
        → confidence = 0.7（由命中率校准，不是 agent 主观评估）
        """
```

### 8.3 置信度校准

语义记忆的 `confidence` 不只是 LLM 主观评估，还由**预测命中率**动态校准：

```python
def recalibrate_confidence(db):
    """每周复盘后，根据 predictions 命中率校准知识置信度。"""
    for knowledge in db.get_active_knowledge():
        related_preds = db.get_predictions_by_knowledge(knowledge.id)
        if len(related_preds) >= 3:  # 至少 3 次预测才校准
            hit_rate = count_hits(related_preds) / len(related_preds)
            # 命中率与原始 confidence 加权平均
            knowledge.confidence = 0.5 * knowledge.confidence + 0.5 * hit_rate
            knowledge.hit_count = count_hits(related_preds)
            knowledge.miss_count = count_misses(related_preds)
```

### 8.4 supersede 机制

当新知识与旧知识矛盾时：
- 旧的标记为 `status = 'superseded'`（保留历史，可溯源）
- 新的写入 `status = 'active'`
- 记录 supersede 原因

---

## 9. 注入 system prompt

```python
def build_system_prompt(db) -> str:
    base = SYSTEM_PROMPT  # 现有的 ratio bp 分析原则

    # 1. 注入最近经验摘要（≤3 条，≤200 字/条）
    recent_insights = db.get_recent_insights(limit=3)
    if recent_insights:
        insight_text = "\n".join(f"- {i.prompt_snippet}" for i in recent_insights)
        base += f"\n\n## 历史经验（最近复盘）\n{insight_text}\n"

    # 2. 注入最近验证的预测（≤5 条）
    recent_verified = db.get_recently_verified(limit=5)
    if recent_verified:
        calls_text = "\n".join(
            f"- {v.prediction} → {'✅ 印证' if v.status == 'hit' else '❌ 失误'}"
            for v in recent_verified
        )
        base += f"\n## 最近判断回顾\n{calls_text}\n"

    # 3. 注入活跃的语义知识（板块叙事 + 市场状态）
    active_knowledge = db.get_active_knowledge(limit=10)
    if active_knowledge:
        knowledge_text = "\n".join(
            f"- {k.scope}: {k.content}（置信度 {k.confidence:.0%}）"
            for k in active_knowledge
        )
        base += f"\n## 已有认知\n{knowledge_text}\n"

    # 4. 注入近期事件摘要（最近 7 天关键事件）
    recent_events = db.get_recent_episodic(days=7, limit=10)
    if recent_events:
        event_text = "\n".join(f"- [{e.timestamp[:10]}] {e.summary}" for e in recent_events)
        base += f"\n## 近期事件\n{event_text}\n"

    return base
```

---

## 10. 数据缺失场景处理

### 场景 A：东财完全挂了（凌晨维护 / 美国网络）

| 环节 | 处理 |
|---|---|
| 事实抽取 | 正常执行（从对话内容提取，不依赖实时数据） |
| 事件写入 | `market_snapshot` 可能拿不到大盘数据 → 写入 `data_coverage: {indexes: false}`，部分快照 |
| 预测创建 | `entry_price` 填缓存中的旧报价，`data_coverage` 标 `quote: stale` |
| 预测验证 | `verify_attempts += 1`，标 `data_unavailable`，留到明天 |
| 语义提炼 | 跳过本周，等数据恢复后补跑 |
| 周报复盘 | `unverifiable_count` 增加，命中率排除 unverifiable |

### 场景 B：资金流数据缺失（东财挂 / 腾讯没有）

| 环节 | 处理 |
|---|---|
| 观察记录 | `data_coverage.flow_today = false`，observation 仍记录 |
| 资金流类预测 | 降级为**纯报价验证** |
| 验证逻辑 | 资金流不可用 → 跳过二次确认，只用价格判断 hit/missed |
| 周报 | 标注"本周资金流数据覆盖 3/5 天，验证置信度降低" |
| pattern 提炼 | 资金流 pattern 跳过（数据不足） |

### 场景 C：某只股票完全没有数据（新股 / 停牌）

| 环节 | 处理 |
|---|---|
| 预测创建 | 正常创建，`entry_price = null` |
| 验证 | 连续 3 次 `data_unavailable` → 标 `expired`（不算 hit 也不算 missed） |
| 统计 | `expired` 单独统计，不拉低命中率 |

### 场景 D：收盘后数据空窗（15:00-15:30）

验证 cron 设置在 16:00（收盘后 1 小时），避开空窗。如果 16:00 仍拿不到，按场景 A 处理。

---

## 11. 向量检索（Phase 5）

用 **sqlite-vec**（SQLite 原生向量扩展）或 **ChromaDB**，不引入重量级依赖。

```python
def search_similar(
    self,
    query_text: str,
    scope: str | None = None,
    top_k: int = 5,
    days_back: int = 90,
) -> list[MarketEvent]:
    """语义搜索：找与当前情况相似的历史事件。

    示例：
    >>> memory.search_similar("半导体暴跌，主力大幅流出")
    → 返回历史上类似的事件（7/2 的大跌、更早的几次半导体调整记录）
    """
```

Embedding 用 DeepSeek/OpenAI 的 embedding API，写入事件时异步生成。

---

## 12. 与现有系统的集成

### 12.1 不改的部分

| 模块 | 改动 |
|---|---|
| `market_data/` adapter 层 | **不改** |
| `cache/` 缓存层 | **不改** |
| `flows/` 资金流模块 | **不改** |
| `signals/` 信号规则 | **不改** |
| `ConversationMemory` | **保留**（Layer 1 工作记忆仍然有价值） |

### 12.2 新增文件

```
src/mommy_chaogu/agent/
├── memory.py                  # 现有（不动）
├── episodic_memory.py         # Phase 1: 情景记忆存储 + CRUD
├── prediction_tracker.py      # Phase 2: 预测追踪 + 状态机
├── verify_engine.py           # Phase 2: 降级验证逻辑
├── narrative.py               # Phase 3: 市场脉络生成
├── semantic_memory.py         # Phase 4: 语义记忆存储
├── consolidator.py            # Phase 4: LLM 离线提炼 + 置信度校准
├── prompt_builder.py          # Phase 1-4: 动态 system prompt 构建
├── service.py                 # 改：chat() 后加 extractor hook
├── tools.py                   # 改：加 get_market_narrative 工具
├── reports.py                 # 改：完成后写 episodic
├── monitor.py                 # 改：信号写 episodic
└── prompt.py                  # 改：从静态变动态

tests/test_agent/
├── test_episodic.py
├── test_prediction_tracker.py
├── test_verify_engine.py
├── test_narrative.py
├── test_semantic.py
└── test_consolidator.py
```

### 12.3 AgentService.chat() 改动

```python
def chat(self, user_message, memory=None, episodic=None):
    # 动态构建 system prompt（注入历史经验 + 知识 + 事件）
    system = build_system_prompt(episodic) if episodic else SYSTEM_PROMPT

    # ... 正常 LLM 循环 ...

    resp = self._run_loop(messages)

    if memory is not None:
        memory.add("user", user_message)
        memory.add("assistant", resp.text)

    # 后置 hook：事实抽取
    if episodic is not None:
        self._extract_and_store(user_message, resp, episodic)

    return resp
```

### 12.4 CLI

```bash
# 手动写入事件
mommy-agent remember --type trade --code 603662 --action buy --price 80 --shares 100

# 预测管理
mommy-agent verify               # 验证所有到期预测
mommy-agent predictions          # 查看所有预测 + 状态
mommy-agent predictions --pending  # 只看待验证

# 市场脉络
mommy-agent narrative --days 30  # 30 天市场脉络
mommy-agent narrative --changes  # 最近变化

# 知识管理
mommy-agent consolidate --all    # 手动触发知识提炼
mommy-agent knowledge list       # 查看已有知识
mommy-agent knowledge search "创新药"

# 事件查询
mommy-agent events --scope "sector:创新药" --days 14
mommy-agent events --type signal_event
```

### 12.5 Cron 集成

| 时间 | 任务 | 说明 |
|---|---|---|
| 15:30 周一~五 | `mommy-agent snapshot` | 拉大盘数据写 market_snapshot |
| 16:00 周一~五 | `mommy-agent verify` | 验证到期预测（收盘后 1h） |
| 周日 10:00 | `mommy-agent consolidate --all` | 知识提炼 + 置信度校准 |
| 周日 10:00 | `mommy-agent review` | 生成周报 + 经验摘要 + 脉络叙述 |

---

## 13. 执行计划

### Phase 1 — 情景记忆 + 事实抽取（3-4 天）

- `episodic_events` 表 + `EpisodicMemory` CRUD（write / query / recent / compare / summary）
- 4 种事件类型写入管道
- 对话后事实抽取 hook（LLM structured output）
- `data_coverage` 字段标记
- 注入近期事件到 system prompt
- CLI: `mommy-agent remember` / `mommy-agent events`

### Phase 2 — 预测追踪 + 降级验证（2-3 天）

- `predictions` 表 + 状态机
- `verify_engine.py`：降级验证逻辑（报价优先 → 资金流可选 → unverifiable）
- 评分规则（方向 + 目标价）
- 注入最近验证结果到 system prompt
- CLI: `mommy-agent verify` / `mommy-agent predictions`
- Cron: 16:00 自动验证

### Phase 3 — 市场脉络（2-3 天）

- `narrative.py`：`generate_narrative()` / `detect_changes()` / `compare_periods()`
- Agent 工具：`get_market_narrative`
- CLI: `mommy-agent narrative`
- 周报中加入脉络叙述

### Phase 4 — 语义记忆 + 知识提炼（3-4 天）

- `semantic_knowledge` 表 + `SemanticMemory` CRUD（upsert / query / search / supersede）
- `consolidator.py`：4 种知识类型提炼
- 置信度校准（由 predictions 命中率动态调整）
- 注入活跃知识到 system prompt
- CLI: `mommy-agent consolidate` / `mommy-agent knowledge`
- Cron: 周日 10:00 自动提炼

### Phase 5 — 向量检索（2-3 天）

- sqlite-vec 或 ChromDB 集成
- `episodic_embeddings` 表
- 写入时异步生成 embedding
- `search_similar()` 语义搜索
- Agent 工具：`search_similar_events`

### Phase 6 — Web 可视化（2-3 天）

- 预测追踪面板（命中率 / 状态分布 / 时间线）
- 事件时间线页面
- 知识库页面（板块叙事 / 个股认知 / 规律）

**总计：Phase 1-4 核心路径约 2 周，Phase 5-6 后续 1 周。**

---

## 14. 成本估算

| 操作 | Token 消耗 | 频率 | 月成本 |
|---|---|---|---|
| 情景记忆写入 | 0（纯 SQLite） | 每次 report/scan/对话 | 0 |
| 事实抽取（对话后） | ~500 token（structured output） | 每次对话 | ~0.5 元 |
| 预测验证 | 0（纯规则计算） | 每天 | 0 |
| 市场脉络生成 | ~2000 token | 每周 1-2 次 | ~0.1 元 |
| 语义提炼 | ~3000 token/板块 × 5 | 每周 1 次 | ~0.1 元 |
| Embedding | ~200 token/事件 × 50/天 | 每天 | ~0.03 元 |
| system prompt 注入 | ~400 token（经验+知识+事件） | 每次对话 | ~0.3 元 |
| **总计** | | | **~1.0 元/月** |

---

## 15. 风险与缓解

| 风险 | 缓解 |
|---|---|
| LLM 提取的事实不准确 | 置信度 < 0.5 的不生成 prediction |
| 验证逻辑过于宽松（什么都算 hit） | 分级评分（1.0 / 0.7 / 0.3），命中率按 >0.5 阈值 |
| 数据缺失导致大量 unverifiable | 周报单独统计，命中率 = hit / (hit + missed) |
| 经验摘要注入 prompt 太长 | `prompt_snippet` 限制 200 字，只取最近 3 条 |
| 预测太少（agent 不经常做判断） | 扫描报告 / 日报也自动生成 prediction |
| 事件数据膨胀 | Phase 1 设 TTL（90 天 raw 事件，更老只保留 summary） |
| LLM 提炼出错误知识 | 每条知识带 confidence + source_event_ids，可追溯修正 |
| 知识与实际矛盾 | supersede 机制 + 命中率校准 |
| 隐私（妈妈持仓信息） | 本地 SQLite，不上传，不推送 |

**回退策略**：每个 Phase 独立。EpisodicMemory / PredictionTracker / SemanticMemory 都是 optional 的——传 None 时 AgentService 行为完全不变（向后兼容）。
