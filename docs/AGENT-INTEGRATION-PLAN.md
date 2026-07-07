# Agent 系统整合计划

> 目标：把记忆管道从 AgentService 内部逻辑提取为独立服务，让所有 agent 入口（Web/CLI、MCP Server）获得一致的记忆能力。

## 问题诊断

当前记忆系统的断裂：

```
AgentService.chat()         ← 记忆注入和提取写死在这里
  ├─ pipeline.build_prompt()
  ├─ LLM ↔ 工具循环
  ├─ memory.add()
  └─ pipeline.record_analysis()

MCP Server                  ← 只有工具分发，没有记忆管道
  └─ registry.call(name, args)

Coding Agent                ← 不走工具层，完全独立
```

## 解决方案

### Phase 1: MemoryService 抽象（基础）

**改动文件：**
- `src/mommy_chaogu/agent/memory_service.py`（新建）
- `src/mommy_chaogu/agent/service.py`（改为调 MemoryService）
- `src/mommy_chaogu/web/deps.py`（构造 MemoryService 单例）

**设计：**

```python
class MemoryService:
    """独立记忆服务，任何 agent 入口都可调用。"""
    
    def __init__(self, pipeline: MemoryPipeline | None, 
                 memory: ConversationMemory | None):
        self._pipeline = pipeline
        self._memory = memory
    
    def get_context(self, query: str | None = None) -> str:
        """获取记忆上下文（注入到 system prompt）。"""
        if self._pipeline:
            return self._pipeline.build_prompt(query)
        return SYSTEM_PROMPT
    
    def record_conversation(self, user_msg: str, assistant_response: str,
                          adapter: MarketDataAdapter | None = None) -> None:
        """对话后记录 + 提取。"""
        if self._memory:
            self._memory.add("user", user_msg)
            self._memory.add("assistant", assistant_response)
        if self._pipeline:
            self._pipeline.record_analysis(user_msg, assistant_response, adapter)
    
    def stats(self) -> dict:
        """记忆系统状态（可观测性）。"""
        ...
```

**AgentService 改为：**
```python
def __init__(self, ctx, memory_service: MemoryService | None = None, ...):
    self._memory_service = memory_service
    
def chat(self, user_message, ...):
    system_prompt = self._memory_service.get_context(user_message) if self._memory_service else SYSTEM_PROMPT
    # ... LLM 循环 ...
    if self._memory_service:
        self._memory_service.record_conversation(user_message, resp.text, adapter=self._ctx.adapter)
```

**关键原则：** MemoryService 可选（None 时用 SYSTEM_PROMPT + 不记录），向后兼容。

### Phase 2: MCP Server 记忆打通

**改动文件：**
- `src/mommy_chaogu/agent/tools.py`（加 `get_memory_context` 工具）
- `src/mommy_chaogu/agent/mcp_server.py`（构造 MemoryService 并注入 ToolContext）

**设计：**

在 ToolContext 加一个 `memory_service` 字段：
```python
@dataclass
class ToolContext:
    adapter: MarketDataAdapter
    watchlist_store: WatchlistStore
    portfolio_store: PortfolioStore
    db_path: Path
    memory_service: MemoryService | None = None  # 新增
```

加一个工具让外部 LLM 主动获取记忆上下文：
```python
ToolDef(
    name="get_memory_context",
    description=(
        "获取历史分析记忆。返回最近的 episodic events、predictions、semantic knowledge。"
        "在分析个股或板块前调用此工具，获取项目积累的历史判断和准确率。"
    ),
    parameters={
        "type": "object",
        "properties": {
            "query": {"type": "string", "description": "查询关键词（股票名/板块名）"},
        },
    },
)
```

这样 MCP 外部 LLM 可以：
1. 对话开始时调 `get_memory_context` 拿历史记忆
2. 用工具做分析（行情/资金流/主题）
3. 工具调用结果和历史上下文一起构成完整分析

### Phase 3: 统一数据服务层

**改动文件：**
- `src/mommy_chaogu/services/theme_service.py`（新建）
- `src/mommy_chaogu/agent/tools.py`（handler 改为调 ThemeService）
- `src/mommy_chaogu/web/routes/themes.py`（改为调 ThemeService）

**现在重复的代码：**

```python
# tools.py _handle_get_theme_stocks
for f in data_dir.glob("*.json"):
    data = json.loads(f.read_text())
    ...
    for stock in stocks_data:
        q = ctx.adapter.get_quote(code)
        ...

# routes/themes.py get_theme_quotes
for f in sorted(_DATA_DIR.glob("*.json")):
    data = _load_json(f)
    ...
    for stock in stocks[:limit]:
        q = adapter.get_quote(code)
        ...
```

**提取为 ThemeService：**
```python
class ThemeService:
    """主题/产业链数据服务。工具层和 API 层共用。"""
    
    def __init__(self, adapter: MarketDataAdapter):
        self._adapter = adapter
    
    def list_themes(self) -> list[dict]:
        """列出所有主题。"""
        ...
    
    def get_theme(self, theme_id: str) -> dict | None:
        """获取主题详情。"""
        ...
    
    def get_theme_quotes(self, theme_id: str, limit: int = 100) -> list[dict]:
        """获取主题成分股实时行情。"""
        ...
```

### Phase 4: 文档更新 + 端到端测试

- 更新 `docs/AGENT-INTERFACE-EVOLUTION.md`
- 更新 `docs/AGENT-INTERACTION-GUIDE.md`（24 个工具）
- 更新 `AGENTS.md`
- 全量测试 `uv run pytest -m "not network"` ≥ 893 passed
- 验证 MCP `uv run mommy-mcp` 启动正常

## 执行策略

Phase 1 是 Phase 2 的基础（MCP 需要 MemoryService）。Phase 3 独立。

```
Phase 1 (MemoryService) ──→ Phase 2 (MCP 记忆)
                      ╲
                       ╱ Phase 3 (ThemeService)  ← 并行
                      ╲
                       Phase 4 (文档 + 测试) ← 最后
```

## 依赖变更

无新增依赖。纯重构 + 新增模块。
