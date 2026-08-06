# 交易观点 → 可执行工作流（V2）

> V2 相对 V1（`CUSTOM-WORKFLOW-PLAN.md`）的变化：架构不变，修正了评审发现的
> 设计缺陷，并按「零 LLM 依赖优先验证」重排了实现顺序。变化对照表见文末。

## 实施状态（2026-08-04）

V2 已完成：Phase 0 的数据口径确认、Phase 1 交易积木、Phase 2
`WorkflowSpec` 运行时与校验器、Phase 3 SQLite 存储与显式 CLI、Phase 4
编译器及 `create/update` 命令、Phase 5 网络冒烟脚本均已落地。离线测试覆盖
契约、提取规则、参数覆盖、信号判定、CRUD、命中计数、CLI 全链路和编译器重试。

Phase 5 的真实网络冒烟需要本机配置有效的 LLM key 和模型名，运行：

```bash
uv run python scripts/smoke_workflow.py
```

配置错误时脚本返回退出码 `2` 并打印 provider/model 检查指引，不会留下 traceback。

## 设计哲学（三条，不动摇）

1. **LLM 只做意图理解，不做计算**——一切数值逻辑沉淀在积木里，确定性、可复现
2. **积木输出契约是整个系统的基石**——先定契约，再写代码
3. **编译器是最后一块，不是第一块**——它依赖的所有东西（积木、spec、执行、存储）
   都必须能在没有 LLM 的情况下先验证完毕

---

## 数据契约（先于一切实现）

### 积木输出契约

所有积木工具（以及未来沉淀的新积木）必须返回统一结构：

```json
{
  "results": [{"code": "600519", "name": "...", ...}],
  "count": 20,
  "total": 47
}
```

- `results` 每项必含 `code` 字段——下游 `step_field` 提取的唯一约定
- `count` = 本次返回条数（**积木内部预裁剪，≤ 20 条**，防止撞 ToolRegistry 8KB 截断线）
- `total` = 裁剪前命中总数（让 LLM 总结时能说「共命中 47 只，列出前 20」）
- 空结果返回 `{"results": [], "count": 0, "total": 0}`，**不报错**——下游自然流过空数据

### 已知工具的 codes 提取规则表

`spec_runtime` 内置一张表，解决「原子工具输出形状不统一」问题（V1 的静默空 codes 陷阱）：

```python
# spec_runtime.py
KNOWN_CODE_EXTRACTORS: dict[str, Callable[[Any], list[str]]] = {
    "get_watchlist": _extract_watchlist_codes,   # {"groups":[{"stocks":[...]}]} 嵌套两层
    "get_portfolio": _extract_portfolio_codes,   # {"positions":[...]}
    # 所有积木走默认 _extract_from_results（契约格式）
}
```

查找顺序：`KNOWN_CODE_EXTRACTORS.get(tool_name, 默认契约提取)`。
**两种都找不到时显式报错，绝不静默返回空列表**——「步骤成功但啥也没干」比报错更难排查。

提取逻辑直接搬 `definitions.py` 里现成的 `_extract_codes_from_watchlist` /
`_extract_codes_from_portfolio`，不重新发明。

---

## Phase 0：数据口径确认（半天，不写产品代码）

开工前先回答两个问题，答错后面全歪：

1. **`main_net_ratio` 的确切口径**——用真实 efinance adapter 拉几只股票，
   手算 `main_net / circulating_market_cap` 对比该字段。若口径一致，
   `screen_inflow_stocks` 直接用现成字段，**零额外请求**（否则 N 只股票 2N 次请求）
2. **摸清 5 个高频工具的输出形状**（get_watchlist / get_portfolio /
   get_money_flow_today / get_quote / get_bars），确认提取规则表的内容

产出：一段手算记录，写进本文件评论区或 commit message。

### Phase 0 实际确认记录

`MoneyFlow.main_net_ratio` 在 `market_data/types.py` 中明确标注为百分比（`%`），
因此字段存在时按 `ratio_bp = main_net_ratio(%) × 100` 换算：例如 `2.5% = 250bp`。
2026-08-04 用真实 efinance 拉取 `600519` 时，源返回的资金流列没有
“主力净流入占比”，适配后的字段为 `None`；同一时点主力净流入为
`-769,324,349`、流通市值为 `1,634,856,717,788`，手算
`main_net / circulating_market_cap × 100 = -0.0470656%`。因此积木现在采用
明确 fallback：字段缺失时额外读取报价的流通市值并按上述公式计算，再换算 bp；
这只在源字段缺失时发生，避免把实时数据静默过滤掉。当前五个工具的输出形状也已
对照实现确认：`get_watchlist` 当前返回股票数组（运行时同时兼容计划中的
`groups[].stocks[]` 嵌套形状），`get_portfolio` 返回 `positions`，三个行情积木
统一返回 `results/count/total` 契约。

---

## Phase 1：交易积木

### 新建 `src/mommy_chaogu/agent/tools/analysis.py`

三个积木，全部遵守输出契约、直接调 `ctx.adapter`（走缓存）、**不复用其他工具 handler**
（避免绕开 registry 的截断和错误处理，行为不一致）：

#### `screen_inflow_stocks` — 主力资金异动筛选

```
输入：codes: list[str], threshold_bp: int = 50（50bp = 0.5%）
逻辑：批量调 adapter.get_today_money_flow（分批 ≤10 只/次）→ 用 main_net_ratio
     （Phase 0 确认口径后）换算 bp → filter(≥ threshold_bp) → 按 ratio_bp 降序
     → 预裁剪 top 20
输出：契约格式，每项含 code/name/main_net/ratio_bp
```

#### `check_earnings_catalyst` — 业绩催化检查

```
输入：codes: list[str]
逻辑：逐只调 adapter 的 fundamentals + announcements(limit=3)，汇总
输出：契约格式，每项含 code/name/pe/roe/has_earnings_ann/ann_titles
```

#### `check_kline_signal` — K线信号检测

```
输入：codes: list[str], signal: str = "volume_breakout"
逻辑：调 get_bars(1d, 20) → 计算信号：
  - volume_breakout：最新一根**已完成**日 K 的成交量 > 前 5 根均量 × 1.5 且涨幅 > 2%
    ⚠️ 文档明确标注：这是收盘后信号。盘中跑时最新一根是残缺 bar，
    实现上跳过当日未完成 bar，用上一根完整 bar 判定
  - ma_golden_cross：5 日均线上穿 20 日均线（最近 2 根内发生交叉）
输出：契约格式，每项含 code/name/signal/close/volume_ratio/change_pct
```

### 注册 + 测试

- `registry.py` 的 `_MODULES` 末尾加 `analysis`（import 时一致性校验自动生效）
- `tests/test_tools/test_analysis.py`：mock adapter 验证 ratio 计算、筛选、排序、
  信号判定、空输入契约、**超 20 条预裁剪**

### Phase 1 出口标准

**用真实 adapter 手动跑一遍三个积木**（不写自动化，打印出来人眼看）：
输出形状符合契约、数值口径和手算一致。积木行为是 compiler prompt 里要宣称的事实，
积木错了，LLM 生成的所有 spec 继承错误且极难定位——这一步不能省。

### Phase 1 实际核验记录

已用真实 `EfinanceAdapter` 对 `600519` 手动运行三个积木。资金流积木在
`threshold_bp=-100` 下返回 1 条，实测 `main_net=-766051346.0`、
`ratio_bp=-4.677942...`，与 `main_net / circulating_market_cap × 100 × 100`
一致；业绩积木返回 3 条公告标题并保持契约；K 线积木在当前没有信号时返回
`results=[]/count=0/total=0`。这同时验证了真实 efinance 当前缺少占比字段时的
流通市值 fallback，以及所有分支的统一输出形状。

---

## Phase 2：WorkflowSpec + Runtime + Validator

### `workflow/spec.py` — 数据模型

```python
SPEC_VERSION = 1   # 随 spec 存入 DB，工具签名漂移时据此标记 stale

@dataclass(frozen=True)
class ArgSource:
    kind: Literal["literal", "user_regex", "step_field", "param"]
    value: Any = None
    pattern: str = ""           # user_regex
    step_index: int = 0         # step_field
    field: str = "codes"        # step_field
    param_name: str = ""        # param

@dataclass(frozen=True)
class StepSpec:
    tool_name: str
    display_name: str
    inputs: dict[str, ArgSource] = field(default_factory=dict)
    optional: bool = False

@dataclass(frozen=True)
class WorkflowSpec:
    id: str                              # 自定义工作流必须以 user_ 开头（validator 强制）
    trigger_patterns: list[str]
    description: str
    steps: list[StepSpec]
    summary_template: str | None = None  # None 时用通用模板 + description 拼
    use_llm_summary: bool = True
    params: dict[str, Any] = field(default_factory=dict)
    spec_version: int = SPEC_VERSION
    # to_json / from_json
```

### `workflow/spec_runtime.py` — Spec → Workflow

```python
def spec_to_workflow(
    spec: WorkflowSpec,
    param_overrides: dict[str, Any] | None = None,
) -> Workflow:
```

- 为每个 StepSpec 生成闭包 `args_extractor`，按 ArgSource.kind 解析
- `step_field` 走**已知提取规则表**（见数据契约节），找不到显式报错
- `param` 从 `{**spec.params, **(param_overrides or {})}` 取值——
  **运行时覆盖在闭包里 bake 进去，engine 一行不用改**：
  `workflow run user_x --set threshold_bp=100` → load spec → overrides → spec_to_workflow → executor

### `workflow/validator.py`

```python
def validate_spec(spec, tool_registry, *, existing_workflows=None) -> list[str]:
```

检查项：
1. 每个 `tool_name` 在 ToolRegistry 中存在
2. `step_field` 引用的 `step_index` < 当前步骤索引
3. `user_regex` 是合法正则
4. **trigger 冲突检测**：逐一对内置工作流的 pattern 做包含关系检查，
   命中即报错（编译器据此 retry）；自定义之间重复 id 报错
5. `id` 必须以 `user_` 开头
6. 参数名与工具 parameters 对齐（warn 级，不阻断）

### 测试

`tests/test_workflow/test_spec.py` + `test_validator.py`：
序列化往返、4 种 ArgSource、提取规则表（含 get_watchlist 嵌套形状）、
未知形状显式报错、param override 生效、trigger 冲突检出、id 前缀强制。

---

## Phase 3：Store + 显式 CLI（零 LLM，全链路可测）

**把编译器推迟到存储和运行链路全部打通之后**——这一版最重要的结构调整。
手写一份 spec JSON 文件就能测试完整链路：注册 → 匹配 → 执行 → 持久化 → 命中计数。

### `workflow/store.py`

agent.db 新表：

```sql
CREATE TABLE IF NOT EXISTS custom_workflows (
    id           TEXT PRIMARY KEY,
    spec_json    TEXT NOT NULL,
    source_text  TEXT,
    created_at   TEXT NOT NULL,
    updated_at   TEXT NOT NULL,
    hit_count    INTEGER DEFAULT 0,
    last_used    TEXT
);
```

```python
class WorkflowStore:
    def save(self, spec, source_text="") -> None      # insert or replace，更新时保留 hit_count
    def load(self, workflow_id) -> WorkflowSpec | None
    def load_all(self) -> list[tuple[WorkflowSpec, dict]]   # (spec, meta) 含 hit_count/last_used
    def delete(self, workflow_id) -> bool
    def increment_hit(self, workflow_id) -> None
```

### CLI（cli.py 新增 `workflow` 子命令族）

```bash
mommy workflow add <file.json>            # 手写 spec 注册（本阶段测试编译器之前的主路径）
mommy workflow run <id> [--set key=val]   # 显式执行，--set 覆盖 params
mommy workflow list                       # 分组显示：[内置] / [自定义]（含触发词、命中次数、stale 标记）
mommy workflow delete <id>
```

启动时构建 merged registry（**新建实例，不污染全局单例**）：

```python
merged = WorkflowRegistry()
for wf in get_default_registry().all_workflows():   # 内置先注册，天然优先
    merged.register(wf)
store = WorkflowStore(AGENT_DB)
for spec, _meta in store.load_all():
    try:
        wf = spec_to_workflow(spec)
        if merged.get(wf.id) is None:
            merged.register(wf)
    except Exception:
        continue   # 损坏 spec 跳过，不阻塞启动；list 时标 stale
router = NLRouter(merged, executor=executor)
```

- **内置优先由注册顺序保证**（match 按序返回第一个命中）+ validator 冲突检测，双保险
- 执行成功后，CLI 层对 `user_` 开头的 id 调 `store.increment_hit`
- **stale 检测**：`list` 时对每个已存 spec 跑一遍 validate（工具签名漂移 → 标 stale，提示 update）

### 测试

`tests/test_workflow/test_store.py`：CRUD、hit_count 递增、update 保留 hit_count。
`tests/test_workflow/test_cli_workflow.py`：add → run → list → delete 全链路（mock adapter）。

---

## Phase 4：Compiler + create/update 命令

此时积木、spec、执行、存储都已验证完毕，编译器只是「spec 的自动作者」。

### `workflow/compiler.py`

```python
class WorkflowCompiler:
    def compile(self, viewpoint: str, *,
                current_spec: WorkflowSpec | None = None) -> CompileResult:
```

**双模式输出**（编译失败路径设计进来，不是事后补丁）：
prompt 要求 LLM 输出两种 JSON 之一——
- `{"kind": "spec", ...}`：观点足够具体，给出 spec
- `{"kind": "questions", "questions": [...]}`：观点模糊，给出需要用户澄清的问题
  （如「要分析的股票范围：自选股/持仓/指定代码？」「阈值多少？」）

CLI 收到 questions 时打印引导，不硬报错。

**update 时带上下文**：`workflow update <id> "新描述"` 把**旧 spec JSON 一并放进 prompt**
（「这是当前版本，用户想改成这样」），比空白重编收敛快得多，且保留 id/hit_count/created_at。

**内部流程**：构建 prompt（工具目录 + 契约 + 2-3 个示例 + 可选旧 spec）→
`chat_raw()` → 提取 JSON → 分支：
- spec → from_json → validate → 有错则**带错误信息 retry 一次** → 仍错返回 errors + guidance
- questions → 直接返回

**summary_template 不让 LLM 自由发挥**：默认 None（运行时拼通用模板 + description），
LLM 可选提供；curated 模板库是 P2。

### CLI 增补

```bash
mommy workflow create "当自选股主力净流入超过0.5%时，看看业绩和K线" [--dry-run]
mommy workflow update <id> "改成阈值1%，只看业绩"
```

### 测试

`tests/test_workflow/test_compiler.py`：mock `chat_raw` 分别返回 spec / questions /
非法 JSON（验证 retry）/ 二次仍非法（验证 errors + guidance）；
update 模式验证旧 spec 注入 prompt。

---

## Phase 5：端到端冒烟（脚本，不进 CI）

`scripts/smoke_workflow.py`（标 network）：
真实 adapter + 真实 LLM 跑 3 条固定观点 → 编译 → dry-run 打印 spec → 人眼检查。
另备 3-5 组 golden 样本（观点 → 期望 spec 骨架），用于人工回归。

本机实测：配置中的旧 z.ai 模型名会被服务端返回 `Unknown Model`，脚本能完整遍历
3 条样本并以退出码 `2` 给出修复指引；临时指定 provider 默认的 `glm-4.7` 后，
单条真实编译成功生成可运行的 `user_` spec。完整三条请求受远端响应超时影响时，
脚本会逐条继续并保留每条结果，不把外部服务问题误报为代码通过。

---

## CLI 命令全集（最终态）

| 命令 | 说明 | 所属 Phase |
|---|---|---|
| `workflow add <file.json>` | 手写 spec 注册 | 3 |
| `workflow run <id> [--set k=v]` | 显式执行（**主触发路径**） | 3 |
| `workflow list` | 分组显示，含命中次数/stale | 3 |
| `workflow delete <id>` | 删除 | 3 |
| `workflow create "观点" [--dry-run]` | LLM 编译注册 | 4 |
| `workflow update <id> "新描述"` | 带上下文重编，保留 id/命中数 | 4 |

自然语言模糊触发（NLRouter regex 匹配）作为 bonus 路径存在，但**显式 run 才是被保证的路径**——这从根本上化解了路由劫持风险：即便模糊匹配失灵，用户永远有确定性的入口。

## 工作流生命周期

```
create（编译）→ run（反复使用，hit_count 增长）→ update（修正，保留历史）
                                                    │
                                      高频使用 + 用户满意 → 人工沉淀为新积木
                                      （开发者把组合逻辑固化进 analysis.py）
```

`hit_count` 是沉淀决策的数据依据：哪些自定义工作流值得升级成积木，看数说话。

## 文件清单

| 操作 | 文件 | Phase |
|---|---|---|
| 新建 | `src/mommy_chaogu/agent/tools/analysis.py` | 1 |
| 修改 | `src/mommy_chaogu/agent/tools/registry.py`（`_MODULES` 加 analysis） | 1 |
| 新建 | `src/mommy_chaogu/workflow/spec.py` | 2 |
| 新建 | `src/mommy_chaogu/workflow/spec_runtime.py`（含提取规则表） | 2 |
| 新建 | `src/mommy_chaogu/workflow/validator.py`（含 trigger 冲突检测） | 2 |
| 新建 | `src/mommy_chaogu/workflow/store.py` | 3 |
| 修改 | `src/mommy_chaogu/cli.py`（workflow 子命令 + merged registry） | 3、4 |
| 新建 | `src/mommy_chaogu/workflow/compiler.py` | 4 |
| 新建 | `scripts/smoke_workflow.py` | 5 |
| 测试 | `tests/test_tools/test_analysis.py` | 1 |
| 测试 | `tests/test_workflow/test_spec.py` + `test_validator.py` | 2 |
| 测试 | `tests/test_workflow/test_store.py` + `test_cli_workflow.py` | 3 |
| 测试 | `tests/test_workflow/test_compiler.py` | 4 |

**不改动**：`workflow/engine.py`、`workflow/definitions.py`、`workflow/router.py`、
`agent/tools/` 现有 9 个域模块。

## V2 相对 V1 的关键变化

| # | 变化 | 来源 |
|---|---|---|
| 1 | 新增 Phase 0：先确认 `main_net_ratio` 口径再写积木 | DS 评审 #2 |
| 2 | 积木输出契约提前为独立章节，加预裁剪 ≤20 条（防 8KB 截断） | K3 评审：截断陷阱 |
| 3 | 内置「已知工具提取规则表」，未知形状显式报错不静默 | K3 评审 #2 |
| 4 | `spec_version` + stale 检测，应对工具签名漂移 | K3 评审 #3 |
| 5 | params 支持运行时 `--set` 覆盖（闭包 bake，不动 engine） | K3 评审 #4 |
| 6 | validator 增加 trigger 冲突检测 + `user_` 前缀强制 | DS 评审 #1 |
| 7 | 显式 `workflow run` 为主路径，模糊匹配降级为 bonus | DS 评审 #1 |
| 8 | 新增 `workflow update`（带旧 spec 上下文重编，保留命中数） | K3 评审 #1 |
| 9 | 编译器双模式输出（spec 或 clarifying questions） | DS 评审 #3 |
| 10 | volume_breakout 明确为收盘后信号，跳过残缺 bar | K3 评审：语义坑 |
| 11 | 顺序重排：Store/CLI（Phase 3）先于 Compiler（Phase 4），LLM 出现前全链路零 LLM 可测 | K3：风险驱动排序 |
| 12 | Phase 1 出口标准含真实数据人工验证 | K3：实现顺序调整 |
