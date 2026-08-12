# Strategy Distillation 纠偏与交付计划

> 状态：Implemented / 自动化与发行物验证通过，待真实用户产品验收
>
> 评审对象：Agent-managed worktree `c9985b1`
> 决策：不把 Golden Scenario 回测当作 Strategy Distillation；先交付用户能直接感受到的最小闭环。

## 1. 产品定义

Strategy Distillation 不是“把观点编译成一个可回测的通用策略”。第一版只承诺：

> 用户把文章、研报、自然语言观点或自己的方法交给 Agent；Agent 保留来源，提炼成一张用户
> 看得懂、改得动、能保存、以后能再次调用的策略卡，并明确哪些条件现在可自动检查、哪些需要
> 人工判断、哪些受当前数据能力限制。用户确认后，Agent 可以结合当前证据应用这张策略卡；只有
> 已被现有能力可靠支持的条件，才允许进一步生成监控候选。

用户完成事件不是 schema、runtime 或回测通过，而是：

1. 用户看到一张忠于原意的策略卡；
2. 用户可以用自然语言修正并确认它；
3. 之后能说“按这套方法看看 X”，并得到结合当前证据的回答；
4. 用户愿意时可以保存，支持条件足够时可以创建监控候选。

## 2. 第一版明确不做

- 不做通用 `ExperimentSpec`、策略 DSL、因子编译器或参数搜索。
- 不把历史计算、收益统计或 deterministic hash 当作 Strategy Distillation 的完成条件。
- 不承诺真实回测；当前数据复权、时间语义、组合构造和验证方法未达到该承诺所需条件。
- 不做 Walk-forward、Regime、Sharpe、组合收益等包装性指标。
- 不先建设 `mommy-experiment` Skill、Web 策略编辑器或新的前端页面。
- 不为尚未出现的多应用场景重构通用平台；只补本闭环必需的接口和存储。

历史验证以后可以成为某些策略卡的可选动作，但必须作为独立能力做资源与方法评审，不能成为
策略沉淀入口的前置条件。

## 3. 本次执行评审结论

### 可以保留的产品方向

- MCP server-level instructions：给未正确加载 Skill 的 Agent 最低行为边界。
- `mommy-onboard` Skill 的分层思路：生命周期指导与日常研究指导分开。
- 机器可读的基础诊断和 JSON research 调用：可作为外部 Agent 的 bootstrap。
- 默认 `market-only`、外部 Agent 不要求第二套 LLM key、写入和监控需明确授权。

这些内容需要按真实用户路径收缩，不代表现有实现应整批合并。

### 合并前必须修正

- 启动文档安装 `mommy-chaogu[mcp]==1.4.0`，但现有 `v1.4.0` tag 不包含新管理命令；本地
  wheel checksum 也没有绑定实际安装来源。
- `doctor` 目前可把“配置存在”报告为 MCP initialize/tools 正常，并未执行相应探针；状态必须
  改为诚实的 `not_checked`，或执行真实的最小探针。
- capability `--timeout` 目前只是上下文字段，没有限制执行时间；删除该承诺或真正实现。
- onboarding 会因后台 capability metadata 写回而完成，但用户可能只看到一次固定的
  `research_us_market` 调用，未得到与自己目标相关、被 Agent 解释过的结果。
- `agent-start` 应先让 Agent 展示将修改的内容和权限范围，并询问用户想研究的股票或观点；不能
  用固定市场摘要替代第一次价值体验。

### 不应进入当前合并范围

- `docs/golden-scenario-spike/`、Golden Gate verifier、clarification schema、独立 hash reproduction
  和 2.1 MB 行情快照。
- 基于临时 SMA20 规则的 spike 及其指标。它既不代表用户的
  `ma_suppression_monitor` 方法，也不构成有效组合回测。
- 为此 spike 规划的 experiment capabilities 和未来 `mommy-experiment` Skill。
- 在策略沉淀纵向闭环出现前，对 Web/TUI/MCP/CLI 做统一 typed runtime 迁移、完整 extras/release
  matrix、repair/upgrade 平台化等扩展。若 Agent-managed bootstrap 确有需要，可逐项最小化引入。

## 4. 缺失的用户能力

| 能力 | 用户能感受到什么 | 第一版最小实现 |
|---|---|---|
| 来源接收与溯源 | 知道策略来自哪篇文章/哪段原话 | Host Agent 读取文本、文件或 URL；保存来源标识、摘要和关键摘录 |
| 策略提炼 | 看到自己的方法被整理清楚 | 新建 `mommy-strategy` Skill，输出固定的策略卡模板 |
| 澄清与确认 | 能纠正 Agent，而不是批准一份技术 spec | 只对影响含义的问题做一次成组澄清；自然语言修改后显式确认 |
| 能力边界标注 | 知道哪些能自动检查、哪些不能 | 每项条件标记 `supported / manual / unavailable` 及原因 |
| 本地保存与找回 | 以后能再次使用这套方法 | 最小 `save/list/get/archive`，保存策略卡和来源，不保存未经确认的草稿 |
| 应用到今天 | 说“按这套方法看 X”即可使用 | Agent 读取策略卡，调用现有 research tools，逐项给出当前证据和缺口 |
| 监控交接 | 支持的规则可以持续观察 | 只把现有告警/监控能表达的条件生成 candidate；用户二次确认后启用 |

第一版策略卡建议包含：标题、来源、用户原始意图、方法摘要、适用对象、观察条件、失效条件、
假设/未决问题、每项条件的自动化状态、用户修订记录和确认状态。它是用户文档，不是通用执行 DSL。

## 5. 交付阶段与 checklist

### Phase 0 — 收口产品边界

用户产物：一页可评审的真实用户旅程和一张策略卡样例。

- [x] 将 Agent-first RFC 中“回测是必经步骤”改为可选的未来验证能力。
- [x] 明确 `DESIGN.md`、Strategy Distillation 与 Agent-managed onboarding 的关系。
- [x] 把 Golden spike 从当前交付线移除；不再等待 Golden Gate 才做策略沉淀。
- [x] 用 `ma-suppression-monitor` 原始说明制作一张人工审核的策略卡样例。
- [ ] 由用户回答：样例是否忠于原方法、是否愿意保存并再次使用。

Gate：用户认可策略卡的内容和语言。未通过时只改体验，不写新 runtime。

### Phase 1 — 无新后端的可体验原型

用户产物：用户把一段方法发给 Agent，当场得到可修改的策略卡。

- [x] 新建边界清晰的 `mommy-strategy` Skill。
- [x] 支持直接文本、本地文件和 Agent 已能访问的 URL；不另建抓取平台。
- [x] 输出来源摘录、事实/解释区分、条件清单、失效条件和能力状态。
- [x] 最多进行一次成组澄清；不问技术实现细节。
- [x] 准备 3 个验收样例：技术方法、基本面框架、包含主观判断的方法。
- [ ] 邀请用户亲自完成一次“输入 → 修正 → 确认”。

Gate：首次策略卡在一次对话内产生，用户无需理解 JSON、MCP、回测或指标框架。

### Phase 2 — 最小本地保存

用户产物：用户能保存、列出并重新打开已经确认的策略卡。

- [x] 先确认现有 memory/agent DB 是否能安全承载；能复用就不建新数据库。
- [x] 实现最小 `strategy_save/list/get/archive` 能力。
- [x] 保存原始来源引用、策略卡、用户修订和确认时间。
- [x] 未经确认不保存；相同策略重复保存可识别并提示。
- [x] 通过现有 Agent tool/MCP 注册路径暴露，不为此重构所有适配器。

Gate：新会话中能找回策略，并准确回答“这条规则来自哪里、我改过什么”。

### Phase 3 — 应用到当前研究

用户产物：用户说“按策略 A 看 X”，得到逐条件、有证据的当前判断。

- [x] 由 Agent 将策略卡条件映射到现有 `research_*` / 行情能力。
- [x] `supported` 条件给证据和时间戳；`manual` 条件给人工检查提示；`unavailable` 明确缺口。
- [x] 不为覆盖率而猜规则，不自动把自然语言编译成任意代码。
- [x] 评审 `ma-suppression-monitor` 输入口径；在可靠接通前诚实标为 `manual/unavailable`，不造替代读数。
- [x] 输出“满足 / 不满足 / 无法判断”，以及最重要的下一步。

Gate：结果能帮助用户今天做一次观察或判断；不以历史收益指标验收。

### Phase 4 — 可选监控闭环

用户产物：用户可把已支持条件转成监控，并知道哪些条件仍需人工判断。

- [x] 只映射现有监控系统能够可靠表达的条件。
- [x] 先展示 monitor candidate、数据依赖和触发文案。
- [x] 用户二次确认后才启用；不支持的条件不伪装成自动化。
- [x] 告警回链到策略卡、版本、条件和来源。

Gate：一次真实或 fixture 触发能让用户理解“为什么提醒我”，且可关闭/归档。

### Phase 5 — Agent-managed 超级入口

用户产物：把一段话发给现有 Agent；Agent 先展示计划和权限，再连接、真实诊断，并围绕用户自己
选择的问题完成第一次研究。

- [x] 根目录提供 `agent-start.md`，README 第一入口改为“把这句话发给 Agent”。
- [x] 提供精简的 `agent detect/plan/connect/doctor/repair --json`，不引入通用 capability runtime。
- [x] plan 列出配置目标、MCP 命令、三个 Skills 和隐私范围；执行前要求用户确认。
- [x] MCP 绑定当前 `mommy` 的 Python 环境，避免新计划误连旧版全局 server。
- [x] 安装 `mommy-onboard` / `mommy-research` / `mommy-strategy` 三层 Skill，并保护用户修改。
- [x] 新连接默认 `market-only`；个人上下文、研究写回、策略保存和监控逐层授权。
- [x] doctor 真实执行 MCP initialize/tools-list；失败时不推断 privacy 正常，`--timeout` 真正生效。
- [x] MCP discovery 延迟数据库/数据源初始化，诊断探针不靠创建个人数据证明成功。
- [x] onboarding 不再由状态写回完成；必须询问用户目标并解释一次真实 `research_*` 结果。

Gate：安装/连接状态永远不能单独宣称成功体验；至少一条用户指定研究的事实、推断、时间戳和数据
缺口被自然语言解释后，才允许给出 onboarding 完成回执。

## 6. 资源门禁与停止规则

任何新阶段开始前只检查与该阶段直接相关的资源：

- 数据是否真的存在，复权、频率、新鲜度和时间语义是否适合该用途；
- 现有算法是否表达用户原方法，而不是一个方便实现的替代品；
- 结果是否能通过当前 Agent 入口呈现给用户；
- 保存、监控和维护成本是否在当前项目能力内。

遇到以下情况立即缩小范围：需要新数据平台、需要通用策略编译器、需要先解决完整回测方法论、
或者一项工程工作不能解释它改善了哪一步用户体验。此时记录缺口并标为 `manual/unavailable`，
不把它转成新的基础设施阶段。

## 7. 第一版成功指标

- 用户从提供材料到看到第一张策略卡不超过 3 分钟。
- 最多一次成组澄清，用户可以全程用自然语言修改。
- 用户能指出策略卡是否忠于原意，并完成确认/保存。
- 新会话中可以找回策略并应用到至少一个当前研究对象。
- 每项条件均说明 `supported / manual / unavailable`，不制造能力幻觉。
- 外部 Agent 模式不要求第二套 LLM key；保存和监控仍需明确授权。
- 回测、通用 runtime、release matrix 和前端页面均不是第一版成功条件。

## 8. 2026-08-11 实施验证记录

- `ruff check .`：通过。
- `mypy --strict src`：206 个源码文件通过。
- `pytest -m "not network"`：2,082 个离线测试通过；14 个网络探针按 marker 排除。
- `mommy-onboard` / `mommy-research` / `mommy-strategy`：官方 Skill validator 全部通过。
- 从源码分发包重建 wheel 成功；wheel 只包含三个正式 Skills。
- wheel 内 MCP 真实完成 initialize/tools-list，`market-only` 发现 20 个公共工具且 discovery 未创建数据库。
- 源码包和 wheel 均排除本地 `output/` 与实验性 `market-monitoring-test` Skill，避免脏工作树泄露。

这些结果证明实现和发行物可以进入产品验收，不替代 Phase 0/1 中仍未勾选的真实用户判断。
