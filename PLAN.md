# Mommy Research：Coding Agent 默认个人记忆接入主计划

> 状态：**实施中（Phase 1–6 核心链路已落地，Phase 7 收尾）**
> 创建日期：2026-08-06  
> 适用范围：Claude Code、Kimi Code、Cline，以及后续 Codex 接入  
> 历史计划：统一存放于 `docs/archive/`

## 1. 背景

mommy-chaogu 的产品特点不只是提供行情工具，而是让外部 Coding Agent 能使用用户本地的完整投研上下文：持仓、自选、告警、历史事件、预测记录和语义知识，并把新的研究结论继续沉淀到同一套记忆系统中。

当前实现已经具备 MCP、`mommy-research` Skill、个人数据工具和记忆数据库，但生产接线仍有以下缺口：

- 新连接默认使用 `market-only`，个人持仓和记忆工具不会发布。
- Coding Agent 不会像内置 Agent 一样自动积累每轮分析；结论只能显式写回。
- 无 embedding 模型时，`get_memory_context(query)` 基本不按查询筛选。
- 股票代码的关键词降级检索可能匹配到其他股票摘要里的数字。
- 预测验证和知识提炼依赖额外维护任务，用户无法直观看到闭环是否运行。
- 当前一键连接器只支持 Claude Code、Kimi Code 和 Cline，尚未覆盖 Codex。

本计划的目标是让用户连接并开始使用 Mommy Research 后，默认获得完整、准确、可持续积累的个人投研能力。

## 2. 产品契约

### 2.1 默认行为

新用户执行以下命令时，默认连接为 `personal`：

```bash
mommy connect claude
mommy connect kimi
mommy connect cline
# 后续支持
mommy connect codex
```

默认启用：

- 持仓、自选股和个人告警；
- 历史事件、预测和语义知识；
- 与当前股票、板块或组合相关的个人上下文；
- 研究事件自动记录；
- 实质分析结论自动写回；
- 符合条件的预测进入验证闭环。

### 2.2 数据最小化

`personal` 表示完整能力默认可用，不表示每次请求都发送全部个人数据。

- 个股研究只附带该股票相关的持仓、自选、告警和历史记忆。
- 板块研究只附带相关持仓暴露和板块记忆。
- 组合研究才读取完整持仓。
- 普通市场问题不应无差别注入完整个人组合。

### 2.3 用户控制

- 用户可以通过 `--profile market-only` 关闭所有个人能力。
- 用户可以在单轮中要求“不要使用个人数据”或“不要记录这次分析”。
- 已明确选择 `market-only` 的存量用户不静默升级；在下次连接或升级时提示切换。
- 连接时明确说明：被调用的个人数据会进入当前 Coding Agent 的模型上下文。

### 2.4 写入标准

- 报价查询、失败响应、无数据回答和闲聊不保存为研究结论。
- 成功的高层研究调用至少记录一条事实型研究事件。
- 实质分析完成后保存结论；用户明确退出时跳过。
- 只有同时具备方向、时间范围和依据的判断才创建预测。
- 所有自动写入必须幂等，重试不能产生重复事件或预测。

## 3. 目标架构

```text
Coding Agent + mommy-research Skill
        │
        ├─ 会话开始：检查 personal / memory health
        │
        ├─ 研究前：调用 research_* 高层工具
        │              │
        │              ├─ 获取行情与基本面证据
        │              ├─ 获取任务相关的持仓/自选/告警
        │              ├─ 精确检索历史事件/预测/知识
        │              └─ 服务端自动记录 research session
        │
        ├─ Coding Agent 基于证据完成分析
        │
        └─ 研究后：record_research_conclusion
                       │
                       ├─ 幂等写入结论
                       ├─ 可选创建预测
                       └─ 关联 research_session_id

后台维护
  ├─ 到期预测验证（不依赖 LLM）
  ├─ 事件索引/向量补全（可降级）
  └─ 语义知识提炼（有 LLM 时运行）
```

Skill 只能指导 Agent 行为，不能保证所有 Agent 都执行最后的结论写回。因此“使用即产生记忆”的最低保证必须放在 MCP 服务端：高层 `research_*` 工具成功返回时自动记录事实型研究事件。最终分析结论再由 Skill 驱动写回。

## 4. 分阶段实施

### Phase 0：冻结产品契约

预计：0.5 天

- [ ] 评审并确认本计划第 2 节中的默认、退出、数据最小化和自动写入规则。
- [ ] 确认新用户默认 `personal`，存量明确选择 `market-only` 的用户不静默升级。
- [ ] 确认“研究事实服务端保证写入，模型结论由 Skill 写回”的责任边界。
- [ ] 确认个人数据提示文案和 consent 版本策略。

验收标准：产品、工程和测试使用同一份行为定义，不再同时存在“默认 market-only”和“默认个人记忆”两套口径。

### Phase 1：连接器默认 personal

预计：1–2 天

主要文件：

- `src/mommy_chaogu/cli_commands/connect.py`
- `src/mommy_chaogu/agent/mcp_server.py`
- `src/mommy_chaogu/agent/research_tools.py`
- `tests/test_connect.py`
- `tests/test_agent/test_assembly_smoke.py`

任务：

- [x] 建立唯一常量 `DEFAULT_MCP_PROFILE = "personal"`，连接器和 MCP Server 共同引用。
- [x] 无参数连接和直接运行 `mommy-mcp` 时默认使用 `personal`。
- [x] 保留显式 `--profile market-only`。
- [x] 在 `connections.json` 中记录 `privacy_consent_version`、连接时间和个人能力状态。
- [x] `mommy connect status` 显示 profile、记忆读取、个人数据和写回能力状态。
- [x] `mommy connect test` 除了列工具，还验证以下工具存在：
  - `get_memory_context`
  - `get_portfolio`
  - `research_portfolio`
  - `record_research_conclusion`
- [x] 为旧连接增加“可升级到完整个人研究能力”的状态提示。

验收标准：全新连接默认发布个人和记忆工具；显式 `market-only` 仍严格隐藏所有个人工具。

### Phase 2：结构化个人研究上下文

预计：2–3 天

主要文件：

- `src/mommy_chaogu/agent/memory_service.py`
- `src/mommy_chaogu/agent/prompt_builder.py`
- `src/mommy_chaogu/agent/tools/memory.py`
- `src/mommy_chaogu/agent/research_tools.py`
- 新增 `src/mommy_chaogu/agent/research_context.py`

任务：

- [x] 新增 `ResearchContextService`，返回结构化个人研究上下文，而不是完整 system prompt 字符串。
- [x] 定义稳定、可版本化的返回 schema：

```json
{
  "schema_version": 1,
  "subject": {"type": "stock", "code": "600519"},
  "position": {},
  "watchlist": {},
  "alerts": [],
  "recent_events": [],
  "predictions": [],
  "semantic_knowledge": [],
  "retrieval_mode": "exact+keyword",
  "freshness": {}
}
```

- [x] 检索优先级改为：股票代码/`scope` 精确匹配 → 名称/别名 → 关键词 → 可选向量扩展。
- [x] 没有本地 LLM Key 或 embedding 模型时仍能完整使用基础记忆。
- [x] 股票代码禁止使用两字符数字滑窗模糊匹配。
- [x] 每条记忆返回来源、时间、置信度和验证状态。
- [x] 修复 MCP `semantic_count` 被默认 limit 截断的问题。
- [x] 让 `research_stock`、`research_sector`、`research_money_flow`、`research_market_brief` 和 `research_portfolio` 自动附带任务相关个人上下文。
- [x] 保留旧 `get_memory_context` 的兼容层，内部改用新服务。

验收标准：无 embedding 模型时，查询 `600519` 只返回贵州茅台相关记录；不同查询返回不同且相关的上下文。

### Phase 3：服务端保证的自动记忆

预计：2–3 天

主要文件：

- `src/mommy_chaogu/agent/research_tools.py`
- `src/mommy_chaogu/agent/episodic_memory.py`
- `src/mommy_chaogu/agent/prediction_tracker.py`
- `tests/test_agent/test_research_tools.py`

任务：

- [x] 每个成功的高层 `research_*` 调用创建 `research_session_id`。
- [x] 服务端自动写入 `external_research_session` 事实事件，记录研究对象、证据源、数据时间和覆盖情况。
- [x] 扩展 `record_research_conclusion`，接受：
  - `research_session_id`
  - `idempotency_key`
  - `analysis_type`
  - `evidence_as_of`
  - `data_coverage`
- [x] 使用现有 `content_hash` 或等价机制实现幂等写入。
- [x] 结论事件关联事实研究事件；预测通过 `source_event_id` 关联结论事件。
- [x] 返回明确回执：是否保存、事件 ID、预测 ID、是否因幂等而复用。
- [x] 普通报价、失败研究和空证据不得自动保存为研究结论。
- [x] 用户单轮退出时，允许 `save_conclusion=false`，但研究工具自身的访问审计与事实记录策略按 Phase 0 决议执行。

验收标准：一次实质研究至少产生一个可追踪研究事件；同一写回请求执行两次不产生重复数据。

### Phase 4：升级 Mommy Research Skill

预计：1–2 天

主要文件：

- `src/mommy_chaogu/bundled_skills/mommy-research/SKILL.md`
- `src/mommy_chaogu/bundled_skills/mommy-research/references/analysis-method.md`

任务：

- [x] 会话首次使用时调用能力/健康检查，确认当前为 `personal` 且记忆数据库可用。
- [x] 优先调用带个人上下文的高层 `research_*` 工具。
- [ ] 将工具事实、历史记忆和模型推断明确分层。
- [x] 实质分析完成后默认调用 `record_research_conclusion`。
- [x] 只有满足预测标准时附带 direction、timeframe 和 rationale。
- [x] 用户说“不要记录”时跳过结论写回。
- [ ] 对成功写入显示简短回执，例如“已记入研究记忆”。
- [ ] 如果连接仍为 `market-only`，停止个人研究流程并提示重新连接为 personal。
- [x] 修正文档中“外部 Agent 每轮全自动记忆”的旧描述，说明服务端记录与 Skill 写回的真实边界。

验收标准：Claude、Kimi、Cline 使用相同研究问题时遵循同一套读取、分析、写回顺序。

### Phase 5：预测验证与知识沉淀闭环

预计：2–3 天

主要文件：

- `src/mommy_chaogu/agent/memory_pipeline.py`
- `src/mommy_chaogu/cli_commands/memory.py`
- `src/mommy_chaogu/cli_commands/agent.py`
- `scripts/cron_verify.py`
- `scripts/cron_consolidate.sh`

任务：

- [x] 新增统一入口 `mommy memory maintain`。
- [x] 维护入口执行到期预测验证、索引补全和知识提炼状态检查。
- [ ] MCP 每个自然日首次研究时异步检查一次到期预测，并通过维护状态防止重复运行。
- [ ] 预测验证必须不依赖 LLM。
- [ ] 有本地 LLM 时运行语义知识提炼；无 LLM 时显式报告“事件和预测正常，知识提炼待运行”。
- [x] 新增 `get_memory_health`，至少返回：
  - 最近读取时间
  - 最近写入时间
  - 最近预测验证时间
  - 最近知识提炼时间
  - 当前检索模式
  - 当前降级原因
- [x] 维护失败不得阻塞研究，但必须可见，不能只写 debug 日志。

验收标准：创建一个短期预测后，维护流程能把它从 `pending` 更新到最终状态，并在健康检查中显示最近执行结果。

### Phase 6：Coding Agent 适配器与 Codex

预计：2–3 天

主要文件：

- `src/mommy_chaogu/cli_commands/connect.py`
- 新增 `src/mommy_chaogu/coding_agents/`
- `tests/test_connect.py`

任务：

- [ ] 抽象 `CodingAgentAdapter`：

```python
class CodingAgentAdapter(Protocol):
    def register_mcp(self, spec: ConnectionSpec) -> None: ...
    def install_skill(self, source: Path) -> Path: ...
    def inspect_status(self) -> ConnectionStatus: ...
    def disconnect(self) -> None: ...
```

- [ ] 将 Claude、Kimi、Cline 的配置逻辑迁移到独立适配器。
- [x] 在实施前用最新官方文档验证 Codex 的 MCP、Skill 和持久化配置位置。
- [x] 增加 Codex 适配器和 `mommy connect codex`。
- [ ] 所有 Agent 共用 profile、隐私提示、健康检查和断开语义。
- [ ] 不允许 Agent 适配器自行绕过 `market-only` 隔离。

验收标准：四种 Coding Agent 都能完成同一条“连接 → 读取相关持仓/记忆 → 研究 → 写回 → 再次召回”的端到端用例。

### Phase 7：测试、迁移与发布

预计：2–3 天

必须新增的自动化覆盖：

- [x] 新连接默认 `personal`。
- [x] 显式 `market-only` 完全隔离个人工具。
- [x] 无 LLM Key、无 embedding 的生产装配路径。
- [x] 股票代码和 scope 精确召回。
- [x] 持仓只按当前研究对象进入上下文。
- [x] 高层研究工具自动记录事实事件。
- [x] 结论写回和重试幂等。
- [ ] 预测创建、事件关联和到期验证。
- [ ] MCP stdio 真实进程测试，而不只测试内存组件。
- [x] Claude、Kimi、Cline、Codex 配置生成与状态检查。
- [ ] 存量连接迁移和明确选择保护。
- [x] `ruff check`、`mypy --strict src` 和全部非网络测试通过。

发布顺序：

1. 新安装用户默认 personal。
2. 内部试用，审计个人上下文范围和数据库写入质量。
3. 存量用户显示升级提示，并提供一条命令完成重连。
4. 观察一个发布周期后，再决定是否迁移从未明确选择 profile 的旧连接。

## 5. 建议的 PR 拆分

1. **PR 1：默认 personal 与连接状态**  
   Phase 0–1；只处理产品契约、默认 profile、状态和基础测试。
2. **PR 2：ResearchContextService**  
   Phase 2；修复精确召回和无 embedding 降级。
3. **PR 3：自动研究事件与幂等写回**  
   Phase 3；建立可保证的服务端记忆写入。
4. **PR 4：Mommy Research Skill 行为升级**  
   Phase 4；让各 Coding Agent 使用一致工作流。
5. **PR 5：记忆维护与健康检查**  
   Phase 5；打通预测验证、提炼状态和可观测性。
6. **PR 6：Agent 适配器、Codex 与发布测试**  
   Phase 6–7；扩展支持矩阵并完成端到端验证。

每个 PR 必须能独立回滚，不应把 profile 默认切换、检索重构和数据库写入变更合并成一个不可拆分的大提交。

## 6. 风险与控制

### 6.1 个人数据进入模型上下文

控制：连接时明确提示；按任务最小化上下文；保留 `market-only` 和单轮退出。

### 6.2 自动记忆积累低质量内容

控制：区分事实事件和模型结论；普通查询不保存结论；记录数据覆盖和来源；预测必须可验证。

### 6.3 Agent 未执行结论写回

控制：MCP 高层研究工具服务端保证记录事实型研究事件；Skill 写回作为第二层增强，并通过回执与健康检查暴露缺失。

### 6.4 工具重试造成重复记录

控制：`research_session_id`、`idempotency_key` 和 `content_hash` 三层去重；增加重复调用测试。

### 6.5 无 embedding 时召回失真

控制：精确 code/scope 检索永远优先；关键词检索是基础能力；向量检索只能扩展排序，不能成为正确性的前置条件。

### 6.6 存量用户隐私预期变化

控制：新用户默认 personal；明确选择过 market-only 的用户只提示、不静默升级；状态命令清楚显示实际能力。

## 7. Definition of Done

本计划完成必须同时满足：

- [ ] 新用户无需理解 profile，连接后默认获得完整个人投研能力。
- [ ] 第一次个股研究就能读取准确的相关持仓、自选、告警和历史判断。
- [ ] 不配置额外 LLM Key 也能使用基础个人记忆和精确检索。
- [ ] 每次成功的实质研究都产生可追踪的本地研究事件。
- [ ] Coding Agent 的结论可写回，并能在下一次相关研究中召回。
- [ ] 预测能够创建、到期验证并反馈到历史判断中。
- [ ] 健康检查能区分正常、降级、未启用和维护失败。
- [ ] `market-only` 仍是严格、可测试的退出选项。
- [ ] 不再出现股票代码跨标的误召回。
- [ ] Claude Code、Kimi Code、Cline 和 Codex 的端到端测试通过。
- [ ] 用户文档、Skill 指令和实际生产行为保持一致。

## 8. 计划维护规则

- 本文件是根目录唯一的活跃主计划。
- 实施者完成任务后直接勾选对应复选框，并在相关 PR 中引用 Phase 编号。
- 产品契约或阶段顺序发生变化时，先更新本文件再实现。
- 本计划全部完成或被替代后，移动到 `docs/archive/`，并在根目录建立新的 `PLAN.md`。
- 其他阶段性分析、评估和历史计划不得长期留在根目录。
