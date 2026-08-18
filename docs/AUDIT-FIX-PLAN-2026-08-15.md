# 审计修复执行计划（2026-08-15）

> 分支：`fix/audit-2026-08-15`（自 `8195869` 切出）
> 输入：两份外部评估（UX / 工程）+ 三路代码级验证（三入口装配、数据层 8 项断言、agent-first 现状）
> 原则：每项独立 commit；验收（定向测试 + ruff + mypy）通过才在台账勾选；修不了/不该修的写明理由延期，不装完成。

## 修复项总览

| 编号 | 主题 | 严重度 | 来源 |
|---|---|---|---|
| F1 | 批量 fallback 按 code 缺口续拉（在途修复收尾提交） | P0 | 工程评估 #1 |
| F2 | 时间戳统一 aware UTC（efinance/tencent/盘口 off-by-one/下游钳位语义） | P0 | 工程评估 #2-5 |
| F3 | 截断证据标 degraded（research_tools `_call`） | P0 | 工程评估 #6-7 |
| F4 | `build_nl_runtime()` 统一三入口装配（自定义工作流三端可见） | P1 | 工程评估 #4 |
| F5 | market-only 档增补 3 个确定性无隐私工具 | P1 | 我的补充发现 |
| F6 | `main_net_inflow` 悬空字段：接真实数据或诚实移除 | P1 | 工程评估 #8 |
| F7 | 发布一致性：wheel exclude / skill 计数 / repair 提示 / 绊网测试 | P0 | 我的补充发现 |
| F8 | 文档真相对齐：EVOLUTION 反向表述 / GUIDE 工具数 / dev 副本 / TUI audit 标记 | P1 | 双评估 |

## 各项明细

### F1 批量 fallback 缺口续拉（在途）

- **问题**：`fallback_adapter.py` 旧逻辑"非空即返回"，混合 A股+美股 批量请求中缺失的 A 股永不到达链上 Efinance（Massive/Yahoo 只认美股，`massive_adapter.py:331`、`yahoo_adapter.py:261`）。
- **修复**：工作区已有未提交实现 `_try_call_batch`（按 code 缺口在链上续拉合并），+4 测试。本项只做：验证 + 提交。
- **验收**：`tests/test_market_data/test_fallback_adapter.py` 全过；全量离线套件不回归。

### F2 时间戳统一 aware UTC

- **问题**（验证后的完整链条）：
  - efinance 全部时间戳是 naive 北京时间（`efinance_adapter.py:130-137` 及盘口/K线/Tick/资金流各处），兜底 `datetime.now()` 也是 naive；
  - tencent `_ts_from_str`（`tencent_adapter.py:82-90`）把北京墙时间 `replace(tzinfo=UTC)`，绝对时刻快 8 小时；
  - tencent `_parse_order_book`（`:294`）读 `fields[29]` 而行情用 `f(30)`，off-by-one 导致解析必失败、永远落到 naive now；
  - 下游统一假设 naive⇒UTC（`web/mappers.py:44`、`services/basket_service.py:223,239`），叠加后 **A 股 data_age 恒为 0、basket 15 分钟 stale 检测对 A 股永不触发**——"数据诚实"卖点在 A 股新鲜度上系统性失真。
- **修复**：adapter 层统一产出 aware UTC——efinance 按 `ZoneInfo("Asia/Shanghai")` 解释后转 UTC；tencent 去掉错误的 UTC 标注、修盘口 off-by-one；naive now 兜底改 aware。下游 naive 分支保留为防御。MCP/API 输出带时区后缀（`agent/tools/bars.py:83` 等 isoformat 处随 adapter 修复自然带 tz）。
- **验收**：新增跨 adapter 时间戳语义测试（所有解析路径产 aware UTC）；现有 market_data/cache/TUI 渲染测试不回归；缓存序列化往返无损。

### F3 截断证据标 degraded

- **问题**：`registry.py:69-84` 在 JSON 字符串层截断（有意设计，带标记）；但 `research_tools.py:353-361` `_call` 解析失败即 fallback 原始字符串且 `ok=True`——`research_stock days≥40` 必截断，宿主拿到"看似完整实则被裁"的证据。
- **修复**：registry 暴露截断判定（常量/`is_truncated()`）；`_Evidence` 增加 `truncated` 标志；证据包 JSON 与给宿主的指令同步（截断证据必须声明部分数据）。
- **验收**：新增测试断言截断结果 `ok=true, truncated=true` 且指令文本提及；正常结果 `truncated=false`。

### F4 `build_nl_runtime()` 统一三入口装配

- **问题**：CLI（`cli.py:636-713`）/ TUI（`tui/services/bootstrap.py:243-335`）/ Web（`web/routes/agent.py:76-111`）三处重复装配 ToolContext→Registry→AgentService→Summarizer→Executor→NLRouter；`_AgentSummarizer` 两处逐字复制；**用户自定义工作流（`mommy workflow add`）只在 CLI merge，TUI/Web 不可见**；无任何跨入口一致性测试。
- **修复**：新增共享装配工厂（建议 `workflow/assembly.py`：`build_nl_runtime()` 返回 router+agent+registry bundle，内置 WorkflowStore merge、共享 summarizer、hit recorder 钩子），三入口改用工厂，入口特有差异（TUI 的 ConversationMemory/取消回调、Web 的 lru_cache/reload、CLI 的 recorder/close）以参数注入。
- **验收**：新增测试：工厂 merge 自定义工作流；TUI bootstrap 与 Web router 装配后自定义工作流可路由；现有三入口测试全过。

### F5 market-only 档增补确定性行情工具

- **问题**：`check_kline_signal` / `screen_inflow_stocks` / `check_earnings_catalyst` 是纯确定性、不触及个人数据的行情/参考库工具，却被关在 personal 档（`research_tools.py:31-49` 白名单外），默认档用户用不上。
- **边界**：策略卡（strategy_*）是个人数据，**保持 personal-only 不动**——本项不越过隐私边界，只按"是否触及个人数据/是否写库"重新划线。
- **修复**：三个工具加入 `MARKET_ONLY_BASE_TOOLS`；同步 doctor 的 `privacy_boundary` 泄漏检查期望与相关测试。
- **验收**：market-only 下 tools-list 含此三工具且不含任何 personal 工具；泄漏检查测试更新后通过。

### F6 `main_net_inflow` 悬空字段

- **问题**：`theme_service.py:239` 读 `extra["main_net_inflow"]`，但全 market_data 无任何 adapter 写过此字段（git -S 只有读没有写）——Web 主题详情页主力净流入徽章永远不渲染、按主力净流入排序无效。
- **修复**（二选一，按调查结果定）：若存在单次批量资金流路径（如 flows service 批量接口）则接真实数据；否则诚实移除字段 + 前端徽章/排序 + 相应测试。**禁止**再挂一个永远为 None 的字段。
- **验收**：主题详情要么显示真实主力净流入（与个股详情页同源可对账），要么彻底无此 UI；测试覆盖所选路径。

### F7 发布一致性

- **问题**：
  1. `pyproject.toml:69-73` 把 `bundled_skills/market-watch-loop` 从 wheel exclude，而 `connect.py`/`base.py`（工作区在途）已把它捆为第 4 个 skill——wheel 安装后 `connect` 会在 `copytree` 直接 FileNotFoundError；
  2. `agent_managed.py:5-6,431` 与 `mommy-onboard/SKILL.md:9,94,116` 仍写"三个 Skills"；
  3. 存量连接升级（新增 skill）后 doctor `skill_integrity` 报 missing，但提示不可操作。
- **修复**：移除 market-watch-loop 的 wheel exclude（`market-monitoring-test` 保留排除）；计数改四处（含 onboard skill 文案）；missing-skill 失败信息附 `mommy agent repair --apply` 指引；新增绊网测试：pyproject exclude 集合不得包含任何 bundled skill 目录（显式实验目录除外，白名单声明）。
- **验收**：绊网测试过；`uv build` 产物含 4 个 skill 目录（或以等价文件清单断言）；lifecycle 测试更新后过。

### F8 文档真相对齐

- **问题**（均已验证）：
  1. `AGENT-INTERFACE-EVOLUTION.md:121-125` 明文"投研用户不应该走 coding agent 这条路"，与已上线的 agent-first 主路线正面矛盾；
  2. `AGENT-INTERACTION-GUIDE.md:50` "25 个工具" vs 实际 36，且前半篇是内置 AgentService 人格叙事、读者混淆；
  3. 仓库 dev 副本 `.kimi-code/skills/mommy-research/SKILL.md`（8/6 旧版）与捆绑版（8/11）教两种冲突的隐私流程；
  4. `TUI-AUDIT-2026-07-25.md` 12 个已修问题未标"已解决"；
  5. `workflow/definitions.py` 注释"9 个工作流"实际 10；`vector_search.py:9` 宣称 DeepSeek embedding 与 `llm.py`（`embedding_model: None`）矛盾。
- **修复**：逐条改写/同步/标注；TUI audit 只标**经代码验证确已修复**的项（逐项核对，不许整页批量勾选）。
- **验收**：文档内不再存在与代码相反的表述；dev 副本与捆绑版逐字节一致。

## 延期项（本轮不做，写明理由）

| 编号 | 主题 | 理由 |
|---|---|---|
| D1 | Agent→Web 深链桥（research_* 附 web URL） | 需要 URL scheme 与 web 端 evidence 参数设计，独立立项 |
| D2 | WeChat P4 收尾（去重合并/深链/通道健康） | 依赖 D1 深链地基；执行计划已挂账 |
| D3 | iOS 冻结/继续、Taro 出树 | 产品资源决策，需用户拍板，不宜由修复分支代决 |
| D4 | personal 档免重启热切换 | 涉及宿主 MCP 会话模型，需设计讨论 |
| D5 | 覆盖率 63.4%→70% | 持续性工作，不属本审计修复批次 |

## 执行台账

> 状态：☐ 待办 / ◐ 进行中 / ✅ 完成（附 commit + 验证）/ ⏸ 延期
> 执行方式：F1 主会话直接提交；F2–F8 由 5 路 swarm（文件集互不相交）并行实现，主会话逐 diff 复核后集成提交。

| 编号 | 状态 | Commit | 验证记录 |
|---|---|---|---|
| 基线 | ✅ | 8195869 | 改动前全量离线套件绿、ruff 全绿、mypy --strict 206 文件无错误 |
| F1 | ✅ | a72017f（fallback）/ 8363a1a（第 4 个 skill 捆绑） | test_fallback_adapter + test_connect + test_agent_managed_lifecycle 40 passed |
| F2 | ✅ | 2b1f278 | 新增 test_timestamp_semantics.py 11 用例（北京→UTC 绝对时刻断言 + 盘口 off-by-one 回归）；market_data/cache/basket_service 205 passed |
| F3 | ✅ | caa7187（含 F5） | 截断证据 ok=true+truncated=true+指令提及、正常证据 truncated=false、is_truncated_result 尾部锚定不误报；581 passed |
| F4 | ✅ | 327642a | test_assembly.py 5 用例（merge/坏 spec 跳过/无 key 降级/注入共享）+ TUI smoke 扩展自定义工作流路由；CLI/TUI/Web 相关 131 passed；净 -74 行装配代码 |
| F5 | ✅ | caa7187 | market-only 白名单含 3 个新工具且不含 strategy_*/record_*；doctor 泄漏检查派生测试通过 |
| F6 | ✅ | 88bca6c | 真实 Decimal 值 / 单只失败静默 None / 上限 10 只防 N+1，3 新用例；services+web 相邻 54 passed |
| F7 | ✅ | 6b2f24f | test_release_consistency.py 绊网（exclude 不含 bundled skill、_bundled_skill_dirs 落盘）；doctor missing-skill 附 repair 指引；11 passed |
| F8 | ✅ | 4385e3f | EVOLUTION/GUIDE/TUI audit/definitions/vector_search/agent_managed/skill 文案逐项对齐；dev 副本与捆绑版 diff 为空 |
| 集成 | ✅ | — | junitxml 权威计数：2114 tests / 0 failures / 0 errors（基线 2082 + 新增 32）；ruff check . 全绿；mypy --strict 207 文件无错误 |

## 验证方法备忘

全量离线套件在本机输出的 pytest 汇总行会被截断（基线即存在），故集成验证以
`--junitxml` 的机器可读计数为准（tests/failures/errors/skipped），不依赖终端摘要。

## 执行纪律

1. 每项一个独立 commit（Conventional Commits），commit message 注明编号。
2. 修复项完成后必须跑：定向测试 + `uv run ruff check .` + `uv run mypy --strict`（改动文件）。
3. 台账在每次 commit 后同步更新（本文件即台账，随代码同仓提交）。
4. 并行修复使用 subagent swarm：按"文件集互不相交"分组，agent 只改自己的文件、只跑定向测试、不 commit；集成验证与提交由主会话统一做。

---

# 第二批修复（2026-08-18，接续设计评审）

> 输入：2026-08-18 全库设计/实现评审（数据层 / Agent 子系统 / 入口层三路深评 + 主会话抽查验证）。
> 第一批 F1–F8 已覆盖评审的 P0 项；本批收尾评审中剩余的 P1/P2 代码级问题。
> 纪律同上：每项独立 commit、定向测试 + ruff + mypy 通过才勾选。

## 修复项总览

| 编号 | 主题 | 严重度 | 来源 |
|---|---|---|---|
| F9 | get_bars 缓存路径：start/end 透传 + 拉新后当次可见 + 北京日历 trade_date | P1 | 数据层评审 |
| F10 | get_prediction_history：code 过滤下推 SQL（冷门股查空 bug） | P2 | Agent 评审 |
| F11 | strategy store LIKE 通配符转义 | P2 | Agent 评审 |
| F12 | 批量 get_quotes 拉新失败 stale 标注（cache → stale_cache） | P2 | 数据层评审 |
| F13 | tencent 死节流字段移除 | P3 | 数据层评审 |
| F14 | coding_agents 四份 inspect_status 骨架上移 base | P2 | Agent 评审 |
| F15 | 东财直连三 API（fundamentals/sector/news）金额 Decimal 化 | P1-P2 | 数据层评审 |
| F16 | main_mommy 拆分 + CLI 入口补测试 | P1 | 入口层评审 |
| F17 | web create_app 对 deps 的 monkeypatch 参数化（评估后定） | P2 | 入口层评审 |

## 各项明细

### F9 get_bars 缓存路径（三项合一，同一代码路径）

- **问题**：
  1. 缓存读取不透传 start/end（`cache/adapter.py` 旧 `store.get_bars(code, interval, adj)` 三参调用），带区间的调用走缓存时返回全量历史再 `[-limit:]`，违反 Protocol"闭区间过滤"契约；
  2. 节流到期拉新成功后仍用拉新前读到的 `cached_bars` 构造返回值——当次调用永远看不到刚拉的新 K 线，盘中增量每次延迟一轮；
  3. F2 把时间戳统一 aware UTC 后，`bar.timestamp.strftime("%Y-%m-%d")` 把北京午夜（UTC 前一天 16:00）落到错误日期，缓存 trade_date 系统性差一天（efinance 内部已按北京日历，`efinance_adapter.py:370`，缓存层漏改）。
- **修复**：区间参数透传到 store；拉新成功后重读缓存再构造返回值；trade_date 按 `Asia/Shanghai` 取；无缓存分支补节流检查（防止失败风暴打上游）；成功拉新 last_source 从"cache"改标"network"。
- **验收**：新增 3 用例（区间过滤 / 拉新当次可见 / 北京日历落库）+ 既有 limit 用例不回归。

### F10 get_prediction_history code 过滤下推

- **问题**：`agent/tools/memory.py` 旧逻辑 `tracker.all(limit=N)` 后在 Python 层按 code 过滤——先截断后过滤，冷门股票的记录若不在最近 N 条内会查空。
- **修复**：`PredictionTracker` 查询支持 code 过滤（SQL WHERE + 截断），工具层去掉 Python 过滤。
- **验收**：新增用例：同一 code 记录多于 limit 条时，按 code 查询仍返回该 code 最近的记录。

### F11 strategy store LIKE 通配符转义

- **问题**：`strategy/store.py` 搜索用 `LIKE :query`，`%`/`_` 未转义——搜索含 `%` 的关键词会误匹配任意串。
- **修复**：ESCAPE 子句 + 参数化转义。
- **验收**：新增用例：搜索字面 `%` 只匹配标题真含 `%` 的卡。

### F12 批量 get_quotes stale 标注

- **问题**：批量路径拉新失败后用旧缓存，last_source 标 "cache" 而非 "stale_cache"（单股路径是 stale_cache），下游无法区分"刚缓存"与"拉新失败翻出的旧数据"。
- **修复**：批量路径区分 network / cache / stale_cache（任一 code 来自拉新失败的旧缓存即标 stale_cache）。
- **验收**：新增用例断言批量失败路径 last_source == "stale_cache"。

### F13 tencent 死节流字段移除

- **问题**：`tencent_adapter.py` `_last_call_ts` 注释承诺"简单节流"但全仓库无使用点——死代码 + 虚假承诺。
- **修复**：删除字段；节流实际由缓存层节流窗口承担（注释说明）。
- **验收**：现有 tencent 测试不回归。

### F14 coding_agents inspect_status 骨架上移

- **问题**：claude/kimi/cline/codex 四份 `inspect_status` 几乎逐字相同（仅 target 字符串不同），约 110 行 × 4 复制。
- **修复**：base 提供模板实现（读 spec → 存在性/一致性判断 → skill 目录状态），子类只提供差异点；`agent_home`/`skill_dir` 的 if-chain 收敛为 adapter 属性。
- **验收**：`tests/test_coding_agent_adapters.py` 参数化四家用例全过。

### F15 东财直连三 API Decimal 化

- **问题**：`fundamentals_api.py`（总市值/流通市值）、`sector_api.py`（price/amount/main_net/total_market_cap）、`news_api.py`（net_buy_amount）全用 float——绕过 adapter 体系也绕过了项目"金额一律 Decimal"约定。
- **修复**：金额/估值字段改 Decimal（安全转换函数），边界序列化处 str()；非金额的纯比率字段（PE/PB/ROE/涨跌幅）随源语义保留 float 或一并 Decimal，以调用方序列化需求为准。
- **验收**：各 API 现有测试更新后通过；类型断言 Decimal。

### F16 main_mommy 拆分 + CLI 入口测试

- **问题**：`cli.py` 旧 `main_mommy` 305 行巨型函数（env 加载 + dispatch + argparse + onboarding + 80 行装配 + 单发/REPL 双模式混杂）；CLI 入口仅 4 个测试（覆盖率 19.3%）。
- **修复**：拆出 `_resolve_command` / `_run_single_query` / 装配（F4 工厂已收走大半）等私有函数；为 dispatch 表、`--raw` 透传、单次查询模式补集成测试。
- **验收**：新增 CLI 入口测试 ≥ 5 个；`main_mommy` 主体降至 ~100 行以内。

### F17 web create_app monkeypatch（评估后定）

- **问题**：`web/app.py` create_app 用 `deps.get_db_path = _custom_db_path` 自改模块属性模拟测试框架行为，并发多 app 会互相踩。
- **修复**（若可行）：改为显式参数/依赖注入。若改动面过大（牵连 deps 全部入口）则记录设计结论延期。

## 新增延期项

| 编号 | 主题 | 理由 |
|---|---|---|
| D6 | 跨进程拉新节流 | freshness 窗口本身以 DB `fetched_at` 为准（别的进程拉过即视为新鲜），`_last_fetch_attempt` 只防同进程失败风暴；改 DB 级节流引入写放大与锁竞争，收益不成比例 |
| D7 | Massive Basic-tier close-only 报价 degraded 标记 | change/change_pct 恒 0 无标记的问题需先定下游展示策略（extra 字段如何呈现），属产品决策 |
| D8 | cache health_check 语义 / signal_events 库归属 | 前者是语义之争（缓存有数据≠源健康），后者涉及 DB 迁移，均不在本轮批准范围 |

## 执行台账（第二批）

| 编号 | 状态 | Commit | 验证记录 |
|---|---|---|---|
| 计划 | ✅ | （本 commit） | 第二批计划入台账 |
| F9 | ✅ | f70509e | test_cache 44 passed（新增 3 用例：区间过滤/拉新当次可见/北京日历落库）；market_data+agent 离线 701 passed |
| F10 | ✅ | a3a3143 | test_tools+verify_engine+eval_followup 82 passed（新增冷门股下推用例） |
| F11 | ✅ | 074cffd | test_strategy_tools 15 passed（新增字面 % 搜索用例） |
| F12 | ✅ | 52afb50 | test_cache 46 passed（新增 stale 标注 2 用例）；TUI/services 49 passed |
| F13 | ✅ | aceeb27 | tencent+timestamp 28 passed |
| F14 | ✅ | 9d5527d | coding_agents 全家 45 passed；净 -27 行 |
| F15 | ✅ | 729761f | test_agent 全套 542 passed / 0 failures；ruff+mypy（8 文件）无错 |
| F16 | ✅ | c8fabbd | test_cli_repl 12 新用例全过；main_mommy 258→109 行；ruff+mypy 无错 |
| F17 | ✅ | （本 commit） | 评估中升级为真 bug：--db 只替换 get_db_path 属性，store 重建仍读默认路径。改为 deps.set_portfolio_db_override 走解析链 + 重建单例；test_web 369 passed（新增 2 用例） |
