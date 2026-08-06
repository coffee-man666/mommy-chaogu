# 交易观点 → 可执行工作流

## 核心思路

把交易观点变成可执行工作流需要三层协作：

1. **交易积木（中层工具）**——把高频交易逻辑封装成确定性复合工具，不靠 LLM 做计算
2. **WorkflowSpec（可序列化工作流定义）**——用声明式 ArgSource 替代 Python Callable，使工作流可序列化为 JSON
3. **WorkflowCompiler（LLM 编译器）**——LLM 只负责理解意图、选择积木、决定顺序，不做任何数据计算

关键设计决策：**不改动现有 9 个内置工作流的任何代码**。新增一条「JSON spec → Workflow」的平行路径，最终汇入同一个 WorkflowRegistry。

---

## Phase 1：交易积木（中层复合工具）

### 1.1 新建 `src/mommy_chaogu/agent/tools/analysis.py`

遵循现有域模块模式（`DEFS: list[ToolDef]` + `HANDLERS: dict[str, ToolHandler]`），注册 3 个积木：

#### `screen_inflow_stocks` — 筛选主力资金异动股

```
输入：codes: list[str], threshold_bp: int = 50  (50bp = 0.5%)
逻辑：
  1. 调 ctx.adapter.get_today_money_flow(code) 批量获取（内部分批，每次≤10）
  2. 计算 ratio_bp = main_net / circulating_market_cap * 10000
     - circulating_market_cap 从 get_quote 获取（或用 main_net_ratio 字段如果有值）
  3. filter(ratio_bp >= threshold_bp)
  4. 按 ratio_bp 降序排列
输出：{"results": [{"code","name","main_net","ratio_bp","main_net_ratio"}], "count": N}
```

#### `check_earnings_catalyst` — 业绩催化检查

```
输入：codes: list[str]
逻辑：
  1. 对每只股票调 get_fundamentals
  2. 调 get_announcements(limit=3) 看是否有业绩相关公告
  3. 汇总成简洁结构
输出：{"results": [{"code","name","pe","roe","has_earnings_ann","ann_titles"}], "count": N}
```

#### `check_kline_signal` — K线信号检测

```
输入：codes: list[str], signal: str = "volume_breakout"
逻辑：
  1. 调 get_bars(interval="1d", limit=20) 获取近 20 日 K 线
  2. 根据 signal 类型计算：
     - volume_breakout: 今日成交量 > 5日均量 × 1.5 且 涨幅 > 2%
     - ma_golden_cross: 5日均线上穿20日均线
  3. 返回命中信号的股票
输出：{"results": [{"code","name","signal","close","volume_ratio","change_pct"}], "count": N}
```

### 1.2 注册到 `registry.py`

在 `_MODULES` 元组中添加 `analysis`：

```python
# registry.py:34
_MODULES = (quote, sector, flows, bars, holdings, intel, alerts, memory, themes, analysis)
```

import 时一致性校验自动生效。

### 1.3 测试

新建 `tests/test_tools/test_analysis.py`：
- `screen_inflow_stocks`：mock adapter，验证 ratio 计算 + 筛选 + 排序
- `check_earnings_catalyst`：mock adapter，验证公告聚合
- `check_kline_signal`：mock adapter，验证信号判定
- 空输入返回 `{"results": [], "count": 0}`（不报错——下游步骤自然流过空数据）

---

## Phase 2：WorkflowSpec + SpecRuntime

### 2.1 新建 `src/mommy_chaogu/workflow/spec.py` — 数据模型

```python
@dataclass(frozen=True)
class ArgSource:
    """声明式参数来源（替代 Python Callable 的 args_extractor）。"""
    kind: Literal["literal", "user_regex", "step_field", "param"]
    value: Any = None           # kind="literal" 时的静态值
    pattern: str = ""           # kind="user_regex" 时的正则
    step_index: int = 0         # kind="step_field" 时引用的前序步骤
    field: str = "codes"        # kind="step_field" 时取的字段名
    param_name: str = ""        # kind="param" 时引用的工作流参数

@dataclass(frozen=True)
class StepSpec:
    tool_name: str
    display_name: str
    inputs: dict[str, ArgSource] = field(default_factory=dict)  # 参数名 → 来源
    optional: bool = False

@dataclass(frozen=True)
class WorkflowSpec:
    id: str
    trigger_patterns: list[str]
    description: str
    steps: list[StepSpec]
    summary_template: str | None = None
    use_llm_summary: bool = True
    params: dict[str, Any] = field(default_factory=dict)  # 默认参数值

    def to_json(self) -> str: ...      # 序列化
    @classmethod
    def from_json(cls, s: str) -> WorkflowSpec: ...  # 反序列化
```

### 2.2 新建 `src/mommy_chaogu/workflow/spec_runtime.py` — Spec → Workflow 转换

```python
def spec_to_workflow(spec: WorkflowSpec) -> Workflow:
    """把声明式 WorkflowSpec 转成现有 Workflow 引擎可执行的 Workflow。"""
```

核心逻辑：为每个 `StepSpec` 生成一个闭包 `args_extractor`，内部根据 `ArgSource.kind` 解析值：
- `literal` → 直接返回 `value`
- `user_regex` → `re.search(pattern, user_input)` 取 group
- `step_field` → 从 `previous_results[step_index]["result"]` 中提取 `field` 字段
  - 支持列表提取（如 `results[*].code` → code 列表）
- `param` → 从 `spec.params[param_name]` 取值

对 `step_field` 的特殊处理：如果前序步骤返回 `{"results": [...], "count": N}` 格式，自动从每个 item 提取 `code` 字段组成 `codes` 列表。这是积木工具的标准输出格式，让步骤间的数据传递变简单。

### 2.3 新建 `src/mommy_chaogu/workflow/validator.py` — 校验器

```python
def validate_spec(spec: WorkflowSpec, tool_registry: ToolRegistry) -> list[str]:
    """校验 spec 合法性，返回错误信息列表（空 = 合法）。"""
```

检查项：
- 每个步骤的 `tool_name` 存在于 ToolRegistry
- `step_field` 引用的 `step_index` < 当前步骤索引（不能引用后面的步骤）
- `user_regex` 的 pattern 是合法正则
- `inputs` 的参数名与工具定义的 parameters 对齐（warn 级别，不报错——LLM 可能多给/少给参数，registry.call 会兜底）

### 2.4 测试

新建 `tests/test_workflow/test_spec.py`：
- WorkflowSpec 序列化/反序列化往返
- `spec_to_workflow`：4 种 ArgSource 各一个用例
- `step_field` 从积木标准输出提取 codes 列表
- `validate_spec`：合法 spec 通过、非法 tool_name 报错、非法 step_index 报错

---

## Phase 3：WorkflowCompiler（LLM 编译器）

### 3.1 新建 `src/mommy_chaogu/workflow/compiler.py`

```python
class WorkflowCompiler:
    def __init__(self, agent_service: AgentService, tool_registry: ToolRegistry):
        ...

    def compile(self, viewpoint: str, *, dry_run: bool = False) -> CompileResult:
        """把交易观点编译成 WorkflowSpec。"""
```

#### Compiler Prompt 结构

```
System:
你是一个 A 股交易工作流设计师。用户给你一段交易观点，你需要把它拆解成可执行的工作流。

## 可用工具
{tool_catalog}  ← 从 tool_registry.definitions() 格式化（name + description + parameters）

## 工作流格式
输出一个 JSON，schema 如下：
{WorkflowSpec JSON Schema}

## 规则
1. 每个步骤调用一个工具
2. 步骤间的数据传递用 ArgSource 声明
3. 不要做计算——用 screen_inflow_stocks / check_kline_signal 等积木工具
4. 步骤之间通常是线性的：上一步筛出的 codes 传给下一步
5. 可变参数（阈值/天数）放到 params 里

## 示例
{2-3 个 examples：观点 → spec JSON}

User:
{viewpoint}
```

#### Compiler 内部流程

1. 构建 system prompt（工具目录 + schema + 示例）
2. 调 `agent_service.chat_raw()` 获取 LLM 输出
3. 从 LLM 输出中提取 JSON（处理 markdown 代码块包裹）
4. `WorkflowSpec.from_json()` 解析
5. `validate_spec()` 校验——如果有错误，做一轮 retry（把错误信息拼进 prompt 再问一次）
6. 如果 dry_run，直接返回 spec；否则 `spec_to_workflow()` 转成可执行 Workflow

#### CompileResult

```python
@dataclass
class CompileResult:
    spec: WorkflowSpec
    workflow: Workflow | None   # dry_run=True 时为 None
    errors: list[str]           # 校验错误（编译失败时）
    raw_llm_output: str         # 原始 LLM 输出（调试用）
```

### 3.2 测试

新建 `tests/test_workflow/test_compiler.py`：
- Mock `AgentService.chat_raw()`，返回预制的 spec JSON
- 验证解析 + 校验 + spec_to_workflow 全流程
- 测试 retry 逻辑（第一次输出非法 JSON → 带错误重试 → 第二次合法）
- 测试 dry_run 不生成 Workflow

---

## Phase 4：持久化 + CLI + NLRouter 集成

### 4.1 新建 `src/mommy_chaogu/workflow/store.py` — 持久化

agent.db 新增表：

```sql
CREATE TABLE IF NOT EXISTS custom_workflows (
    id          TEXT PRIMARY KEY,
    spec_json   TEXT NOT NULL,
    source_text TEXT,
    created_at  TEXT NOT NULL,
    hit_count   INTEGER DEFAULT 0,
    last_used   TEXT
);
```

```python
class WorkflowStore:
    def __init__(self, db_path: Path): ...
    def save(self, spec: WorkflowSpec, source_text: str = "") -> None: ...
    def load(self, workflow_id: str) -> WorkflowSpec | None: ...
    def load_all(self) -> list[WorkflowSpec]: ...
    def delete(self, workflow_id: str) -> bool: ...
    def increment_hit(self, workflow_id: str) -> None: ...
```

### 4.2 CLI 子命令：`mommy workflow`

在 `cli.py` 中添加 `workflow` 子命令分支（在现有 `main_mommy` 的子命令检测之前）：

```bash
mommy workflow create "当自选股主力净流入超过流通市值0.5%时，看看业绩公告和K线"
mommy workflow create "..." --dry-run    # 只编译不注册
mommy workflow list                       # 列出所有工作流（内置 + 自定义）
mommy workflow delete user_flow_001       # 删除自定义工作流
```

实现：在 `main_mommy()` 的子命令检测段（`cli.py:486` 附近），添加 `workflow` 子命令分支，路由到新函数 `_handle_workflow_subcommand(args)`。

### 4.3 NLRouter 启动时加载自定义工作流

修改 `cli.py` 中构建 router 的部分（`cli.py:650` 附近）：

```python
# 现有代码
executor = WorkflowExecutor(tool_registry, llm_summarizer=llm_summarizer)
router = NLRouter(get_default_registry(), executor=executor)

# 改为：加载自定义工作流并合并
registry = get_default_registry()
# 创建一个新的 registry（包含内置 + 自定义），避免污染全局单例
from mommy_chaogu.workflow.spec_runtime import spec_to_workflow
from mommy_chaogu.workflow.store import WorkflowStore

store = WorkflowStore(AGENT_DB)
for spec in store.load_all():
    try:
        wf = spec_to_workflow(spec)
        if not registry.get(wf.id):  # 不覆盖内置工作流
            registry.register(wf)
    except Exception:
        pass  # 存储的 spec 损坏时跳过，不阻塞启动

router = NLRouter(registry, executor=executor)
```

### 4.4 测试

- `tests/test_workflow/test_store.py`：save / load / load_all / delete / increment_hit 的 CRUD
- `tests/test_workflow/test_cli_workflow.py`：集成测试——mock compiler 验证 CLI create/list/delete 全流程

---

## 文件清单

| 操作 | 文件 | 说明 |
|---|---|---|
| 新建 | `src/mommy_chaogu/agent/tools/analysis.py` | 3 个交易积木工具 |
| 修改 | `src/mommy_chaogu/agent/tools/registry.py` | `_MODULES` 加 `analysis` |
| 新建 | `src/mommy_chaogu/workflow/spec.py` | WorkflowSpec / StepSpec / ArgSource 数据模型 |
| 新建 | `src/mommy_chaogu/workflow/spec_runtime.py` | spec_to_workflow + step_field 提取逻辑 |
| 新建 | `src/mommy_chaogu/workflow/validator.py` | validate_spec |
| 新建 | `src/mommy_chaogu/workflow/compiler.py` | WorkflowCompiler（LLM 编译器） |
| 新建 | `src/mommy_chaogu/workflow/store.py` | WorkflowStore（agent.db CRUD） |
| 修改 | `src/mommy_chaogu/cli.py` | `workflow create/list/delete` 子命令 + 启动时加载自定义工作流 |
| 新建 | `tests/test_tools/test_analysis.py` | 积木工具测试 |
| 新建 | `tests/test_workflow/test_spec.py` | Spec 序列化 + spec_to_workflow 测试 |
| 新建 | `tests/test_workflow/test_compiler.py` | 编译器测试（mock LLM） |
| 新建 | `tests/test_workflow/test_store.py` | 持久化 CRUD 测试 |
| 新建 | `tests/test_workflow/test_cli_workflow.py` | CLI 集成测试 |

## 实现顺序

Phase 1 → Phase 2 → Phase 3 → Phase 4（严格顺序依赖）

每个 Phase 完成后跑 `uv run pytest tests/test_workflow/ tests/test_tools/test_analysis.py -m "not network"` 验证。

## 不改动的文件

- `workflow/engine.py` — Workflow / WorkflowStep / WorkflowExecutor / WorkflowRegistry 完全不动
- `workflow/definitions.py` — 9 个内置工作流不动
- `workflow/router.py` — NLRouter 不动（它只依赖 WorkflowRegistry 接口）
- `agent/tools/` 现有 9 个域模块 — 不动

---

# 评审意见（Deepseek-v4-flash 提供，2026-08-04）

整体评价：**架构方向对，风险控制好，但有三个实质遗漏**。

## 做得对的地方

1. **分层正确**——积木（确定性）+ Spec（可序列化）+ LLM（只做意图理解）。这个分工是整套计划的灵魂，别动摇。
2. **不破坏现有系统**——9 个内置工作流不动，新代码平行路径汇入同一个 Registry。这让功能可以渐进落地，风险可控。
3. **积木输出格式统一**（`{"results": [...], "count": N}`）——下游提取 codes 变简单，这个简化很聪明，省掉了复杂 DSL。

## 实质遗漏 1：trigger_patterns 冲突 / 路由劫持（最严重，计划里完全没提）

`WorkflowRegistry.match()` 是**按注册顺序返回第一个命中**的。用户自定义工作流如果 LLM 给了个宽泛的触发词（比如 `.*股票.*`），就会**劫持**内置工作流的意图，或者反过来互相打架。比如内置 `morning_brief` 有 `r"帮我看看"`，自定义工作流也有，谁先注册谁赢。

需要补：
- **注册顺序策略**：内置永远优先于自定义（注册自定义前先查重，冲突时拒绝或 warn）
- **validator 里加 trigger 冲突检测**：对 `re.search` 逐一对内置工作流的 pattern 做前缀/包含检查，命中就报错让 LLM 重试
- 或者更稳：自定义工作流优先**显式触发**（`mommy workflow run <id>`），模糊匹配作为 bonus

## 实质遗漏 2：积木实现细节有一个隐患

计划里 `screen_inflow_stocks` 写的是「circulating_market_cap 从 get_quote 获取」——这意味着 N 只股票要 **2N 次请求**（flow + quote），批量场景会被限流。但其实 `get_money_flow_today` 的 `_flow_to_dict` 已经返回了 `main_net_ratio` 字段——**建议先确认数据源里这个 ratio 的确切口径**（是不是主力净流入/流通市值），如果是，积木直接用现成字段，零额外请求。这一步值得在实现前花 10 分钟查一下 efinance 的数据结构。

另外积木内部怎么调数据也要定死：**统一走 adapter（带缓存），不复用其他工具 handler**——否则绕开 ToolRegistry 的 8KB 截断和错误处理，行为不一致。

## 实质遗漏 3：LLM 生成质量的保障不够

- **summary_template**：让 LLM 自由写模板质量不可控。建议给一批精选模板让 LLM 挑，或默认用「description + 通用模板」。
- **编译失败路径**：计划只有一轮 retry，没提失败后怎么办。实际中交易观点经常模糊（"看看有没有机会"），编译失败应该给出**交互式引导**（告诉用户缺什么信息），而不是干巴巴报错。
- **测试盲区**：`test_compiler.py` mock LLM 返回预制 JSON，测的是解析逻辑，**测不到 LLM 会不会输出合法 JSON**。至少补一个真实 LLM 的冒烟测试脚本（标 network，不进 CI 默认跑），或者一组 golden-file 样本人工过一遍。

## 可选的小建议

`mommy workflow list` 内置 + 自定义混在一起，用户建多了会乱。建议分组显示（`[内置]` / `[自定义]`），自定义的显示触发词和命中次数——`hit_count` 字段既然建了就让它有用。
