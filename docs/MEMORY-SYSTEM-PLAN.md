# 深层记忆系统实现计划

> 目标：让 Agent 拥有跨会话的多维度记忆——记住每次行情分析、板块叙事、信号触发和买卖决策，能通过前后信息比对总结市场脉络，形成"越用越懂"的投研智能体。

---

## 背景：当前记忆的局限

项目已有 `ConversationMemory`（SQLite 存对话记录），但这只是最浅层的**对话历史**——记住了"上次说了什么"，无法：

- 记住行情分析的结构化快照（"7/1 创新药涨了 5.1%，主力流入 19.47 亿"）
- 从多次分析中提炼板块叙事（"创新药处于政策底 + 估值底 + 出海兑现期"）
- 做前后比对（"上周你说半导体要调整，这周确实跌了"）
- 检测市场状态变化（"从科技独强切换到高低切"）

---

## 理论框架：四层记忆架构

参考 CoALA（Princeton, 2023）认知科学框架，映射到 A 股投研：

```
┌──────────────────────────────────────────────────────┐
│              工作记忆 (Working)                        │
│  当前会话 context window + 最近 N 轮对话               │
│  ← 已实现（ConversationMemory.recent()）               │
└──────────────────┬───────────────────────────────────┘
                   │ 检索
┌──────────────────┴───────────────────────────────────┐
│           情景记忆 (Episodic)                          │
│  按时间排序的"事件流" — 结构化的投研事件                │
│  ← Phase 1 新建                                       │
└──────────────────┬───────────────────────────────────┘
                   │ 提炼（LLM 离线任务）
┌──────────────────┴───────────────────────────────────┐
│           语义记忆 (Semantic)                          │
│  从情景记忆中提炼出的"知识"                            │
│  ← Phase 4 新建                                       │
└──────────────────┬───────────────────────────────────┘
                   │ 注入
┌──────────────────┴───────────────────────────────────┐
│           程序记忆 (Procedural)                        │
│  投资策略 + 分析流程 + 风险规则                        │
│  ← 部分已有（system prompt + signals 规则）            │
└──────────────────────────────────────────────────────┘
```

### 四种记忆类型的投研映射

| 记忆类型 | 回答什么 | 投研内容 | 存储 |
|---|---|---|---|
| **情景 (Episodic)** | "之前发生了什么？" | 每日行情快照、分析报告、信号触发、买卖决策 | SQLite（结构化事件表） |
| **语义 (Semantic)** | "什么是真的？" | 板块叙事、个股认知、规律观察、市场状态 | SQLite + embedding 检索 |
| **程序 (Procedural)** | "该怎么做？" | 分析流程、风险规则、策略偏好 | system prompt + 可更新策略库 |
| **工作 (Working)** | "现在在看什么？" | 当前会话上下文 | context window（已有） |

---

## Phase 1: 情景记忆 — 结构化事件流

> 记住"发生了什么"。核心是 4 张 SQLite 表 + 写入管道。

### 新增文件

**`src/mommy_chaogu/agent/episodic_memory.py`**

```python
@dataclass(frozen=True, slots=True)
class MarketEvent:
    """一条情景记忆事件"""
    id: int
    timestamp: datetime
    event_type: str          # market_snapshot / analysis_record / signal_event / trade_decision
    scope: str               # "market" / "sector:创新药" / "stock:600519" / "portfolio"
    data: dict[str, Any]     # 结构化内容（JSON）
    summary: str             # 一句话摘要
    tags: list[str]          # 可选标签 ["暴跌", "风格切换", "政策利好"]

class EpisodicMemory:
    """情景记忆存储。同一个 data/watchlist.db，新增 1 张表。"""

    def __init__(self, db_path: Path): ...

    def write(self, event_type: str, scope: str, data: dict, summary: str,
              tags: list[str] | None = None) -> int:
        """写入一条事件，返回 id。"""

    def query(
        self,
        scope: str | None = None,
        event_type: str | None = None,
        start_date: str | None = None,
        end_date: str | None = None,
        tags: list[str] | None = None,
        limit: int = 100,
    ) -> list[MarketEvent]:
        """按条件查询历史事件。支持 scope 前缀匹配（"sector:*" 匹配所有板块）。"""

    def recent(self, days: int = 7, scope: str | None = None) -> list[MarketEvent]:
        """最近 N 天的事件。"""

    def compare(
        self,
        scope: str,
        date1: str,
        date2: str,
    ) -> dict:
        """对比两个时间点的事件数据，返回差异。"""

    def summary(self) -> dict:
        """统计：各类型事件数、最早/最新记录、scope 分布。"""
```

### 4 种事件类型

| event_type | 触发时机 | scope | data 内容 |
|---|---|---|---|
| `market_snapshot` | 收盘 cron（15:30） | `market` | 大盘 6 指数涨跌、板块 TOP5、全市场涨跌统计 |
| `analysis_record` | 每次 `mommy-agent report` 或对话分析后 | `sector:创新药` / `stock:600519` | 分析的输入数据 + agent 输出的结论 |
| `signal_event` | AgentMonitor 扫描出 alert | `stock:600519` | 信号内容、触发条件、当时价格 |
| `trade_decision` | 用户手动记录买卖 | `portfolio` | 买卖的 code/price/shares/reason |

### 写入管道

| 触发点 | 改动 |
|---|---|
| `agent/reports.py` AgentReportService.generate_daily_report | 完成后自动 `episodic.write("analysis_record", ...)` |
| `agent/monitor.py` AgentMonitor.scan_once | 有 alert 时自动 `episodic.write("signal_event", ...)` |
| 新增 CLI: `mommy-agent remember --type trade --code 600519 --action buy --price 1680 --shares 100 --reason "妈妈长期持有"` | 手动写入 |
| 新增 cron: `mommy-agent snapshot` → 拉大盘数据写入 `market_snapshot` | 每日自动 |

### 验收标准
- 4 种事件类型都能写入 + 查询
- `query(scope="sector:创新药")` 能返回该板块所有历史事件
- `compare("market", "2026-07-01", "2026-07-02")` 能输出差异
- `pytest tests/test_agent/test_episodic.py` 通过（6-8 个测试）

---

## Phase 2: 记忆注入对话

> Agent 回答时自动加载历史上下文。

### 改动

**`src/mommy_chaogu/agent/service.py`** — `AgentService.__init__` 增加可选 `episodic: EpisodicMemory | None`：

```python
def chat(self, user_message, history=None):
    # 1. 如果有 episodic memory，注入相关历史
    memory_context = ""
    if self._episodic:
        recent_events = self._episodic.recent(days=7)
        if recent_events:
            memory_context = self._format_events(recent_events)

    # 2. 把记忆注入 system prompt
    system = SYSTEM_PROMPT
    if memory_context:
        system += f"\n\n## 近期记忆（过去7天的事件）\n{memory_context}"

    # 3. 正常对话
    ...
```

**`src/mommy_chaogu/web/deps.py`** — `get_agent_service()` 注入 EpisodicMemory。

### 效果

用户问"创新药现在怎么样"，agent 的 system prompt 里已经包含了：
```
## 近期记忆（过去 7 天的事件）
[2026-07-01] 板块分析：创新药 +5.1%，主力净流入 19.47 亿，三重底共振
[2026-07-02] 市场快照：科创50 -7.7%，全面杀跌，高低切继续
[2026-07-02] 信号：柯力传感 -1.09% 抗跌，量比 1.60
```

Agent 回答就有了历史纵深：不只是"今天涨了多少"，而是"上周我们分析过创新药的三重底逻辑，这周验证了"。

### 验收标准
- 对话时 system prompt 包含近期事件摘要
- 不影响无 API Key 的降级行为
- 现有测试不受影响

---

## Phase 3: 前后比对 — 市场脉络生成

> "总结市场脉络"能力。

### 新增文件

**`src/mommy_chaogu/agent/narrative.py`**

```python
class MarketNarrative:
    """基于情景记忆生成市场脉络分析。"""

    def __init__(self, episodic: EpisodicMemory, agent: AgentService): ...

    def generate_narrative(
        self,
        scope: str = "market",
        days: int = 30,
    ) -> str:
        """生成一段市场脉络叙述。

        流程：
        1. 拉过去 N 天的所有相关事件
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
        """检测最近 3 天 vs 之前 10 天的关键变化。

        比 generate_narrative 更聚焦——只输出"变了什么"。
        """
```

### CLI 集成

```bash
# 生成过去 30 天的市场脉络
mommy-agent narrative --days 30

# 只看板块
mommy-agent narrative --scope "sector:创新药" --days 14

# 检测最近变化
mommy-agent narrative --changes

# 推送到微信
mommy-agent narrative --days 7 --push
```

### 新增工具

在 `agent/tools.py` 加一个 `get_market_narrative` 工具，让 agent 在对话中可以自主决定"调出市场脉络"：

```
用户："帮我复盘一下最近的市场"
Agent → 调 get_market_narrative(days=30) → 返回叙述
```

### 验收标准
- `mommy-agent narrative --days 30` 能输出有逻辑的脉络叙述
- 叙述中引用具体日期和数字（来自情景记忆）
- `detect_changes` 能识别"风格切换"等转折

---

## Phase 4: 语义记忆 — 离线知识提炼

> 从一堆事件中归纳出"知识"。

### 新增文件

**`src/mommy_chaogu/agent/semantic_memory.py`**

```python
@dataclass(frozen=True, slots=True)
class KnowledgeEntry:
    """一条语义记忆（提炼出的知识）"""
    id: int
    knowledge_type: str    # sector_thesis / stock_insight / pattern_observed / market_regime
    scope: str             # "sector:创新药" / "stock:600519" / "market"
    content: str           # 知识内容
    confidence: float      # 0-1
    source_event_ids: list[int]  # 来源的事件 ID（溯源）
    created_at: datetime
    updated_at: datetime

class SemanticMemory:
    """语义记忆存储。data/watchlist.db，新增 1 张表。"""

    def __init__(self, db_path: Path): ...

    def upsert(self, knowledge_type: str, scope: str, content: str,
               confidence: float = 0.8, source_ids: list[int] | None = None) -> int:
        """写入或更新一条知识（同 type+scope 覆盖旧的）。"""

    def query(
        self,
        scope: str | None = None,
        knowledge_type: str | None = None,
    ) -> list[KnowledgeEntry]:
        """查询知识。"""

    def search(self, query_text: str, top_k: int = 5) -> list[KnowledgeEntry]:
        """语义搜索（Phase 5 接 embedding，Phase 4 用关键词匹配）。"""

    def supersede(self, entry_id: int, new_content: str, reason: str) -> int:
        """一条知识被新知识取代（保留历史）。"""
```

### 离线提炼任务

**`src/mommy_chaogu/agent/consolidator.py`**

```python
class MemoryConsolidator:
    """从情景记忆提炼语义记忆的离线任务。"""

    def __init__(self, episodic: EpisodicMemory, semantic: SemanticMemory,
                 agent: AgentService): ...

    def consolidate_all(self):
        """全量提炼（每周跑一次）。"""
        self._consolidate_sector_theses()
        self._consolidate_market_regime()
        self._consolidate_patterns()

    def _consolidate_sector_theses(self):
        """从过去 N 天的板块事件提炼板块叙事。

        输入：该板块的所有 analysis_record + market_snapshot + signal_event
        LLM 任务："基于以下事件，提炼出 {sector} 的核心叙事。
                  如果叙事与已有认知矛盾，标记为 supersede。"
        输出：写入 semantic_memory 表
        """

    def _consolidate_market_regime(self):
        """提炼当前市场状态。

        对比最近 5 天 vs 之前 20 天，
        LLM 判断："市场处于什么状态？（牛市/熊市/震荡/高低切/...）"
        """

    def _consolidate_patterns(self):
        """从重复出现的信号中归纳规律。

        示例：发现"量比 > 2 + 主力流入 > 5bp"后 3 天上涨概率 70%
        → 写入 pattern_observed
        """
```

### 4 种知识类型

| knowledge_type | 内容 | 提炼频率 | 示例 |
|---|---|---|---|
| `sector_thesis` | 板块核心叙事 | 每周 | "创新药处于政策底 + 估值底 + 出海兑现期" |
| `stock_insight` | 个股认知 | 每周 | "柯力传感是机器人力矩传感器龙头，每次大跌抗跌" |
| `market_regime` | 市场状态 | 每天 | "高低切进行中，科技调整 + 低位补涨" |
| `pattern_observed` | 规律观察 | 每周 | "对子顶信号后 1 天平均跌 8%" |

### CLI 集成

```bash
# 手动触发提炼
mommy-agent consolidate --all
mommy-agent consolidate --scope "sector:创新药"

# 查看已有知识
mommy-agent knowledge list
mommy-agent knowledge search "创新药"
```

### cron 集成

每周六 10:00 的周报 cron 里加入 `consolidate --all`。

### 验收标准
- `consolidate_all` 能从事件中提炼出有意义的知识
- `semantic.query(scope="sector:创新药")` 能返回板块叙事
- supersede 保留历史（旧的标记为 superseded，新的为 active）
- 知识溯源：每条知识能查到来源事件 ID

---

## Phase 5: 向量检索 — "找相似历史事件"

> "上次类似情况是什么时候，后来怎么走的"。

### 技术选型

用 **sqlite-vec**（SQLite 原生向量扩展）或 **ChromaDB**（轻量嵌入式向量库），不引入 Postgres / Milvus 等重量级依赖。

### 新增

```python
class EpisodicMemory:
    # Phase 5 扩展
    def write(self, ..., auto_embed: bool = True):
        """写入时自动生成 embedding 存入向量表。"""

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
        → 返回历史上类似的事件（可能找到 7/2 的大跌、
          以及更早的几次半导体调整记录）
        """
```

### Embedding 生成

用 DeepSeek/OpenAI 的 embedding API（`text-embedding-3-small` 或 DeepSeek embedding），每次写入事件时异步生成 embedding。

### 验收标准
- `search_similar("半导体暴跌")` 能返回相关的历史事件
- 向量检索 + scope 过滤同时工作
- 性能：< 100ms（90 天内 ~1000 条事件）

---

## 数据库 Schema 变更

### 新增表（同一个 data/watchlist.db）

```sql
-- Phase 1: 情景记忆
CREATE TABLE IF NOT EXISTS episodic_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    timestamp TEXT NOT NULL,           -- ISO 8601
    event_type TEXT NOT NULL,          -- market_snapshot / analysis_record / signal_event / trade_decision
    scope TEXT NOT NULL,               -- market / sector:创新药 / stock:600519 / portfolio
    data TEXT NOT NULL,                -- JSON
    summary TEXT NOT NULL,             -- 一句话摘要
    tags TEXT DEFAULT '[]',            -- JSON array
    created_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_episodic_scope ON episodic_events(scope);
CREATE INDEX IF NOT EXISTS idx_episodic_type ON episodic_events(event_type);
CREATE INDEX IF NOT EXISTS idx_episodic_ts ON episodic_events(timestamp);

-- Phase 4: 语义记忆
CREATE TABLE IF NOT EXISTS semantic_knowledge (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    knowledge_type TEXT NOT NULL,      -- sector_thesis / stock_insight / market_regime / pattern_observed
    scope TEXT NOT NULL,
    content TEXT NOT NULL,
    confidence REAL DEFAULT 0.8,
    source_event_ids TEXT DEFAULT '[]', -- JSON array of episodic event IDs
    status TEXT DEFAULT 'active',      -- active / superseded
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_semantic_scope ON semantic_knowledge(scope);
CREATE INDEX IF NOT EXISTS idx_semantic_status ON semantic_knowledge(status);

-- Phase 5: 向量索引
CREATE TABLE IF NOT EXISTS episodic_embeddings (
    event_id INTEGER PRIMARY KEY REFERENCES episodic_events(id),
    embedding BLOB,                    -- float32 vector
    model TEXT NOT NULL,               -- embedding 模型名
    created_at TEXT NOT NULL
);
```

---

## 文件变更总览

### 新增

```
src/mommy_chaogu/agent/
├── episodic_memory.py      # Phase 1: 情景记忆存储
├── semantic_memory.py      # Phase 4: 语义记忆存储
├── consolidator.py         # Phase 4: LLM 离线提炼
└── narrative.py            # Phase 3: 市场脉络生成

tests/test_agent/
├── test_episodic.py        # Phase 1: 6-8 个测试
├── test_narrative.py       # Phase 3: 3-4 个测试
├── test_semantic.py        # Phase 4: 5-6 个测试
└── test_consolidator.py    # Phase 4: 3-4 个测试
```

### 修改

```
src/mommy_chaogu/agent/service.py       # Phase 2: 注入 episodic 到对话
src/mommy_chaogu/agent/tools.py         # Phase 3: get_market_narrative 工具
src/mommy_chaogu/agent/reports.py       # Phase 1: 完成后写 episodic
src/mommy_chaogu/agent/monitor.py       # Phase 1: 信号写 episodic
src/mommy_chaogu/web/deps.py            # Phase 2: 注入 episodic 到 AgentService
src/mommy_chaogu/cli.py                 # Phase 1-4: remember / narrative / consolidate / knowledge 命令
```

---

## 执行顺序 & 预估

| Phase | 内容 | 预估 | 依赖 |
|---|---|---|---|
| **1** | 情景记忆（表 + CRUD + 写入管道） | 3-4 小时 | 无 |
| **2** | 记忆注入对话 | 1 小时 | Phase 1 |
| **3** | 市场脉络生成（narrative + CLI + 工具） | 2-3 小时 | Phase 1 |
| **4** | 语义记忆 + 离线提炼 | 3-4 小时 | Phase 1 |
| **5** | 向量检索（sqlite-vec / embedding） | 3-4 小时 | Phase 1 + 4 |

Phase 1-3 是核心路径，做完 agent 就有了"记住过去 + 讲出脉络"的能力。Phase 4 让它"越用越聪明"。Phase 5 让它能"找历史相似事件"。

---

## 成本估算

| 操作 | Token 消耗 | 频率 | 月成本 |
|---|---|---|---|
| 情景记忆写入 | 0（纯 SQLite） | 每次 report/scan | 0 |
| 记忆注入对话 | ~200 token（事件摘要） | 每次对话 | ~0.5 元 |
| 市场脉络生成 | ~2000 token（事件 + LLM 分析） | 每周 1-2 次 | ~0.1 元 |
| 语义提炼 | ~3000 token/板块 × 5 板块 | 每周 1 次 | ~0.1 元 |
| Embedding（Phase 5） | ~200 token/事件 × 50 事件/天 | 每天 | ~0.03 元 |
| **总计** | | | **~0.7 元/月** |

---

## 风险与回退

| 风险 | 应对 |
|---|---|
| 事件数据膨胀 | Phase 1 设 TTL（保留 90 天 raw 事件，更老的只保留 summary）|
| LLM 提炼出错误知识 | 每条 semantic entry 带 confidence + source_event_ids，可追溯和修正 |
| 提炼任务消耗 token | 设为离线 cron（非实时），且只跑有新事件的 scope |
| 向量检索太慢 | Phase 5 才需要，先跳过。Phase 1-4 用 SQLite 关键词检索足够 |

**回退策略**：每个 Phase 独立。EpisodicMemory 是 optional 的——传 None 时 AgentService 行为完全不变（向后兼容）。
