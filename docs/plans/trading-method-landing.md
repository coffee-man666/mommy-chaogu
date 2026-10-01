# 交易心法落地方案

> 状态：草案 v1.3 终审定稿（2026-09-30；v1.1 按 7 条评审意见、v1.2 按 2 条二审意见、v1.3 按终审读者 15 条反馈修订，处理记录见附录 B/C/D，均无拒绝项）
> 依据：四份侦察报告（下称①板块数据 / ②日内数据 / ③监控告警 / ④积木测绘）+ 心法作者本人确认的四层结构原文 + 两轮对关键锚点的抽查验证。
> 遵守 `AGENTS.md`「产品定位」与「产品交付原则」：最小纵向闭环优先；每个技术任务说明它解锁哪个用户步骤；能力边界诚实；不可自动化的标「需人工判断」；未确认数据语义前不称「真实回测」。

## 0. 引用约定与已验证事实

- 〔①/②/③/④ evidence〕= 对应侦察报告的 evidence 原文；`path:line` 为其中给出的锚点。
- 「本次验证」= 本轮起草时亲自运行过的检查，共 9 项：
  1. `sed -n '1,40p' src/mommy_chaogu/agent/tools/bars.py` — get_bars code pattern `^(\^[A-Z]{1,6}|[A-Z]{1,6}|\d{6})$`（bars.py:16）确实无法匹配 `BK1036` 这类字母+数字代码；interval enum 含 `5m/15m/30m/60m`。
  2. `sed -n '18,32p' src/mommy_chaogu/cache/schema.py` — bar_cache 主键 `(code, interval, adj_type, trade_date)`，注释「K 线（每天一条，永久保留）」。
  3. `sed -n '38,48p' src/mommy_chaogu/signals/custom_alerts.py` — VALID_CONDITIONS 仅 4 种静态阈值条件。
  4. `grep -rn "\.evaluate(" src/mommy_chaogu` — 生产代码中 `.evaluate(` 调用仅：`monitor/poller.py:259`、`web/background.py:152`、`cli_commands/monitor.py:46`（均为 `alerter.evaluate`，内置 7 条规则）及 `signals/alerter.py:67`、`earnings/signals.py:242`（规则内部）。**`CustomAlertStore.evaluate` 生产零调用**，与〔③ evidence〕一致。
  5. `sed -n '64,90p' src/mommy_chaogu/agent/tools/analysis.py` — check_kline_signal 的 signal enum 仅 `volume_breakout / ma_golden_cross`。
  6. `grep -c "Workflow(" src/mommy_chaogu/workflow/definitions.py` — 10 个工作流。
  7. `sed -n '52,58p' src/mommy_chaogu/strategy/models.py` — MonitorCondition 仅 4 枚举。
  8. `sed -n '85,125p' src/mommy_chaogu/backtest/regime_analysis.py` — classify_market_regime 判定规则（MA20/60 + 波动率 + 回撤）与〔④ evidence〕一致。
  9. `grep -n "server_chan" src/mommy_chaogu/push/*.py` — 无命中，Server酱确已从 push 管道移除（与 git status 删除记录一致）。
- 心法结构与侦察材料的**出处及可查证性（v1.3 补充）**：①四份侦察报告是本工作流中侦察 agent 产出的 JSON 报告，经任务派发直接传入本文起草上下文，**未作为文件存入仓库**——读者无法在仓库内查看其原文本；本文对其结论的引用均带 evidence 转述与 `path:line` 锚点，凡引用落到代码行的均可独立复核（如验证 16 的「以代码为准」裁决给出了完整命令与文件行号，不依赖对报告的信任）。②四层结构在仓库内 grep 无原文（仅 `docs/EARNINGS-HANDBOOK.md:383` 的业绩窗口「决策心法 7 条」与 `docs/archive/LEDGER.md:1211` 的「5 大心法」，与本文四层不是同一套）；其定义经起草 agent 向工作流主控**升级提问**（多 agent 工作流中子代理向主控提出阻塞问题并获答复的机制）由心法作者确认。**这是本方案唯一不可在仓库内核对的地基**：如四层定义与心法原文有出入，§1 映射表与各阶段的「忠于心法」表述需随之修订；建议后续将心法原文与四份侦察报告一并归档入仓库以便查证。
- 网络前提：①②均报告当前机器对 `push2his.eastmoney.com` TLS 后空响应（21 次请求全失败）、`push2.eastmoney.com` 502。**所有依赖东财实拉的验收步骤，须先在可访问东财的网络环境跑通网络探针**（见 §5 风险 R1 与 §6 Q2）。
- **状态判据（v1.3 明确，回答「同样是零调用，为何一个是 available 一个是 bug」）**：四档状态衡量的是「相对心法用途的交付前提」——available = 代码存在且其设计用途可按需达成；buildable = 数据/算法前提已验证、需组装；degraded = 已承诺的行为无法发生；unavailable = 无实现且无替代。**「零调用」本身不是判据，判据是零调用是否使既有产品承诺失效**：`classify_market_regime` 是分析库，按需调用即达设计用途，无人调用只说明 L1 用户路径未建（阶段四建），不违背任何已作出的承诺 → available；`CustomAlertStore.evaluate` 的存在意义是兑现策略卡 activate_monitor「启用后自动检查并提醒」的承诺，生产零调用 = 承诺失效 → degraded（断裂）。
- 评审回合补充验证（v1.1，逐条复核评审意见引用的事实，均亲自运行）：
  10. `sed -n '100,155p' src/mommy_chaogu/web/background.py` — `_tick` 开头 `codes = self.watchlist.get_all_codes(); if not codes: return`（自选股为空时评估循环不进入）；评估循环仅此处的 `alerter.evaluate` 调用。
  11. `grep -rn "notifier|Notifier|alerter|Alerter" src/mommy_chaogu/tui/` — 无命中，TUI 无任何 notifier 接入。
  12. `sed -n '110,175p' src/mommy_chaogu/monitor/poller.py` — `snapshot_now` 的 codes 完全来自 `_index_entries()`（自选股 entry），`SnapshotRow` 按该 codes 拼装；不在自选股的代码不进 Snapshot。
  13. `sed -n '170,180p' src/mommy_chaogu/cli_commands/monitor.py` — `mommy monitor run` 为前台持续轮询命令（「持续轮询 (Ctrl+C 退出)」，默认 30s）。
  14. `sed -n '505,570p' src/mommy_chaogu/agent/tools/strategies.py` — `_handle_activate_monitor` 接受任意 `code` 直接 `CustomAlertStore.add`，不要求先加自选股。
  15. `sed -n '18,30p' src/mommy_chaogu/market_data/rankings.py` + `sed -n '13,24p' src/mommy_chaogu/agent/tools/bars.py` — A 股指数真相源是 secid `'1.000001'` / 代码 `'sh000001'`（INDEX_LIST），两者均不匹配 get_bars 的 pattern；`'000001'`（平安银行）匹配 `\d{6}`——误传会静默拉到个股日 K。
  16. `sed -n '91,140p' src/mommy_chaogu/market_data/rankings.py` — `fetch_sector_ranking` 固定 `pn=1` 单页、`pz=limit*2`、凑满 limit 即两处 break：是截断的当日涨幅榜，**不是全量板块枚举**（侦察报告①「当日返回全部行业+概念代码，可作板块池来源」的 evidence 与代码不符，本文以代码为准）；`grep -n "pn" src/mommy_chaogu/market_data/sector_api.py` 显示 `fetch_sector_stocks` 有 `for pn in (1, 2)` 翻页先例。
  17. `grep -rn "update_status" src/mommy_chaogu --include="*.py"` — 调用方仅 verify_engine（:317/:335/:351）与 docstring；`grep agent/tools/` 无任何 prediction 写入工具。`sed -n '212,230p' src/mommy_chaogu/agent/tools/memory.py` — get_prediction_history 输出字段硬编码且**无 stage**；`tui/services/renderers.py:49-50` → `tui/widgets/cards.py:377-381` 按当前状态列表渲染，非变化轨迹。
  18. `sed -n '218,226p' src/mommy_chaogu/cli.py` — `doctor` 透传 `agent_managed.main_doctor`（agent_managed.py:662），是安装诊断，**不展示告警评估计数**。
  19. `sed -n '244,270p' src/mommy_chaogu/agent/tools/analysis.py` — check_kline_signal 仅在命中时 append 结果记录，未命中时 results 为空、**不含 20 日高点/收盘等依据数值**。
- 二审回合补充验证（v1.2，均亲自运行）：
  20. `sed -n '38,60p' src/mommy_chaogu/cli_commands/monitor.py` — `cmd_monitor_snapshot` 内 `if args.with_signals: signals = alerter.evaluate(snap)` 是**独立的第三处** `alerter.evaluate` 调用（:44-46）：`mommy monitor snapshot --with-signals` 短命命令走的是这里，不经 web/background._tick 也不经 monitor/poller.py:259 的 run 循环。
  21. `sed -n '25,50p' src/mommy_chaogu/agent/prediction_tracker.py` — predictions 表时间字段仅 `created_at`（:29）与 `verified_at`（:44），**无确认类时间戳**；stage=confirmed 的回写时刻无字段可存。
- 终审回合补充验证（v1.3，均亲自运行）：
  22. `sed -n '52,80p' src/mommy_chaogu/agent/prediction_tracker.py` — `verify_after` 由 `_compute_verify_after(timeframe)` 按 `_TIMEFRAME_DAYS` 日历日映射计算：1d→1、3d→3、5d→5、10d→10、20d→20、60d→60（:64-73）。即「等 1 个 verify_after 周期」是天级（timeframe 天数），非小时级；叠加 verify_engine 的一个 timeframe 宽限窗口（verify_engine.py:52-66〔④〕），终态最长约 2×timeframe 天必然出现。
  23. `grep -n "trigger_patterns" src/mommy_chaogu/workflow/definitions.py` + `sed -n '220,245p'` — 每个工作流带正则列表（如 `r"美股.*(怎么样|如何|行情|走势)"`）；`grep -n "fallback" workflow/router.py` — router 正则匹配优先，未命中 fallback 到 AgentService（router.py:3）。

---

## 1. 心法四层结构与项目积木整体映射

### 1.1 心法结构（作者确认原文）

四个层次 + 一条贯穿机制：

| 层 | 名称 | 一句话含义 |
|---|---|---|
| 1 | **市场环境** | 先看市场而不是先看股票：大盘 / 科创 / 半导体及热门板块各自状态、风险偏好（资金扩散 / 集中 / 退潮）；判断对象是**以往的路径**而非今天的截面（超跌→缩量企稳→龙头先涨→板块扩散→成交额放大） |
| 2 | **板块轮动** | 板块之间的相对变化：指数横盘但半导体强于软件 = 资金在迁移；回答「钱现在在哪里？钱下一步可能往哪里走？」 |
| 3 | **个股状态（个股闭环）** | 技术面在前：价格/量/趋势/相对强弱/突破回踩看是否有「形」→ 新闻与信息解释「市场为何这样交易它」→ 基本面判断持续性 → 回到技术面决定执行 |
| 4 | **多周期交易判断** | 三档分离：**超短期（日内）**看当日资金如何交易它（开盘强弱、VWAP、量能、盘中承接、突破失败、尾盘行为）；**短期（未来几日）**看能否形成 swing（突破关键位、连续资金流入、板块配合、催化剂发酵）；**中期（未来几周）**看趋势本身（盈利预期、行业景气、资金配置持续性、价格结构） |
| 横切 | **左侧发现 → 右侧确认** | 左侧高频信号（资金流、量能异常、相对强弱、盘中结构）早但噪声大；右侧低频信号（趋势形成、突破确认、板块共振、基本面兑现）准但晚。左侧生成 candidate，右侧决定 conviction 和仓位；左侧小仓试错、右侧逐步确认加仓、**右侧迟迟不确认则退出** |

### 1.2 映射总表

状态沿用侦察口径：available（已可用）/ buildable（数据或算法前提成立，需组装）/ degraded（有明确缺口或断裂）/ unavailable（不可用）。

| 心法概念 | 现有积木 | 状态 | 关键缺口 |
|---|---|---|---|
| **L1 市场环境·状态判定** | `backtest/regime_analysis.py:88` classify_market_regime（bull/bear/sideways，MA20/60+波动率+回撤；合成 K 线实测通过〔④〕，本次验证判定规则） | available（作为库） | 输出单值截面，无逐日序列/持续天数/状态转移；全仓库无实盘调用方〔④ evidence〕 |
| **L1 市场环境·路径（非截面）** | 板块历史 K 线：EfinanceAdapter.get_bars 透传 BK 代码（efinance_adapter.py:343-423 无前缀校验，mock 注入验证〔①〕） | buildable | agent 工具层 code pattern 拒绝 BK（本次验证）；「路径」需在 regime 之上加序列化封装（_regime_at 已有逐日定位，regime_analysis.py:131-148〔④〕）。**A 股指数 K 线无 agent 工具通路**：get_bars pattern 只认美股指数（`^GSPC` 类）与 6 位个股码，A 股指数真相源是 secid `'1.000001'`/`'sh000001'`（rankings.py:24 INDEX_LIST，v1.1 验证 15），两者均不匹配；误传 `'000001'` 会静默拉到平安银行——需新增指数通路并在输出标注判定标的（阶段四任务 1） |
| **L1 市场环境·叙事** | get_market_narrative（agent/tools/memory.py:70 + agent/narrative.py:73） | degraded | 数据源是 agent 自己的 episodic 事件而非行情，质量取决于记录密度；scope 参数 narrative 层支持但工具层未暴露（memory.py:248 固定 market）；LLM 生成路径未实测〔④〕 |
| **L2 板块轮动·当日截面** | fetch_sector_ranking（market_data/rankings.py:91，行业+概念合并当日涨跌幅）+ get_sector_ranking 工具（agent/tools/sector.py:20） | available | 仅当日，clist 接口无历史参数〔①〕 |
| **L2 板块轮动·多日相对强弱** | 板块日 K 全量（BK1036 dktotal=6480 根，接口语义经外部网络验证〔①〕）+ bar_cache TEXT 主键零 schema 变更（cache/schema.py:22，本次验证） | buildable | 需新建服务：板块池→逐板块日 K→回算 N 日涨幅排名序列；批量节流（约 90 行业+400 概念）〔① anchor〕 |
| **L2 板块轮动·资金迁移** | EfinanceAdapter.get_history_money_flow 透传 BK（efinance_adapter.py:547，mock 验证〔①〕）；120 交易日滚动窗口（上游硬限制） | degraded | cache/adapter.py:511-518 首次拉取后不再增量，滚动累积需调度层每日触发〔①〕 |
| **L2 板块↔个股** | 正向：fetch_sector_stocks（sector_api.py:28）；反向：无——Quote 类型无 sector/industry 字段〔③ evidence〕 | degraded（反向） | 个股→板块归属需 LLM 对齐或人工指定 |
| **L3 个股闭环·技术面发现** | check_kline_signal（analysis.py:221，volume_breakout/ma_golden_cross，本次验证枚举）；get_bars 日 K ≤120 根（bars.py:13-39） | available | 现有两信号已是右侧性质（放量/金叉确认）〔④〕；左侧形态枚举未建 |
| **L3 个股闭环·信息面解释** | check_earnings_catalyst（analysis.py:160：fundamentals + 近 3 条公告聚合，标题关键词匹配） | available | 是证据聚合器，解释本身留给上游 Agent〔④〕 |
| **L3 个股闭环·基本面持续性** | get_fundamentals（name/pe/roe） | available | 深度有限，「持续性判断」的解释归 Agent/人工 |
| **L3 个股闭环·技术面执行** | 无（也**不应有**：本产品不是券商/自动下单系统，AGENTS.md 产品定位红线） | — | 执行仅到「提示与记录」为止 |
| **L4 超短期（日内）·分钟 K** | 类型层 BarInterval 5 档分钟级（types.py:47-57）+ _KLT_MAP（efinance_adapter.py:115）齐备〔②〕 | degraded | 仓库内 A 股唯一实现 efinance 本网络全挂；腾讯 ifzq mkline 本网络可用但未接线（tencent_adapter.py:362 返回 []）；bar_cache 同日分钟 K 坍缩为最后一根（确定性 bug，离线探针复现〔②〕） |
| **L4 超短期（日内）·盘口** | get_order_book 双实现（efinance_adapter.py:295 / tencent_adapter.py:351，2026-09-30 盘后实测拉通〔②〕） | available | 时点快照、无历史留存，收盘后返回当日冻结盘口〔②〕 |
| **L4 超短期（日内）·日内指标** | VWAP/开盘半小时/尾盘行为：腾讯 m5 全天 48 根实算通过（VWAP 1251.52、开盘半小时 +0.19% 量占 14.1%、尾盘 -0.09% 量占 15.0%〔②〕） | buildable | 需新建计算积木；腾讯无成交额→VWAP 只能典型价近似；腾讯周期末 vs efinance 周期初时间标签需统一〔②〕 |
| **L4 短期（未来几日）·突破确认** | 数据层：日 K 120 根 available〔③〕 | buildable | 信号层缺 high_20_breakout / price_above_ma20 枚举（analysis.py:80，本次验证仅两枚举）；复权/时点语义未核验〔③ notVerified〕 |
| **L4 短期·板块共振** | get_quote + get_sector_ranking/get_sector_stocks 可组合近似〔③〕 | degraded | 个股→板块无字段、监控无板块维度、CustomAlert 单条件表达不了组合→建成前**需人工判断**〔③〕 |
| **L4 短期/中期·业绩兑现** | earnings 模块完整：pull/score/verdict 五档 + 4 条信号规则（earnings/service.py:55-204、signals.py:226-233） | available（计算） | 自动提醒断裂：evaluate_all 生产零调用（本次验证仅 signals.py:242 内部 rule.evaluate），CLI 手动触发〔③〕 |
| **L4 中期·盈利预期/景气** | earnings 前瞻 vs 实际 + fundamentals | available | 行业景气等更广面数据不在本次侦察范围 |
| **横切·左侧候选生成** | screen_inflow_stocks（analysis.py:25/119，池内当日主力净流入占比过滤） | available | 只做给定池过滤、无全市场扫描、仅当日无多日持续性〔④〕 |
| **横切·prediction 记录** | PredictionTracker + verify_engine 闭环实测通过（创建/到期发现/三重保险报价/回填/统计，〔④ evidence 全链〕） | available | 状态机无「左侧候选→右侧已确认」阶段标记；验证触发是 cron/CLI 驱动〔④〕 |
| **横切·右侧常驻监控** | 内置 7 条规则（rules.py:423-433，Snapshot 仅实时报价无历史窗口）+ CustomAlert 4 静态条件 | degraded | **CustomAlertStore.evaluate 生产零调用（本次验证）**：策略卡启用的告警存了但没人查，不会自动响〔③〕 |
| **横切·推送** | Bark + SignalNotifier（严重度过滤 + Deduper 一码一规一天，push/base.py:38-111）+ 微信（web/app.py:138-156） | available（代码链路；**端到端从未实跑**，见 §4.2） | available 的口径：管道代码存在且在内置规则链路被生产调用（background._tick → SignalNotifier）；实际推送（含 device key/扫码）从未端到端验证——两处口径以此衔接〔③ notVerified〕；custom_alerts 与 earnings 不在链路〔③〕；Server酱已删（v1.0 验证 9） |
| **横切·策略卡承接** | 三层齐备：models/store/工具（source 溯源、fingerprint 幂等、乐观锁、prepare/activate 双确认，实测通过〔④〕） | available | monitor_rule 仅 4 种价格/涨跌幅阈值——K 线形态/资金流占比/多日相对强弱只能标 manual〔④〕 |

### 1.3 三时间尺度的落点差异（为什么超短期放最后）

- **短期（未来几日）**：数据前提最硬（日 K available），只差信号枚举 → 进入阶段一。
- **中期（未来几周）**：earnings 比对 + fundamentals available，缺口在自动提醒（阶段五修）。
- **超短期（日内）**：双重 degraded（网络出口 + bar_cache 坍缩 bug），且需接腾讯备源 → 阶段六，前置两项工程修复，不阻塞前五个阶段。

---

## 2. 分阶段落地方案

排序原则：先做数据前提已验证、改动最小、用户最先能亲手走通的闭环；把「修复断裂链路」和「重建受限数据层」放后面。每阶段独立可验收、可独立回滚（见 §5）。

### 阶段一：个股闭环按需检查（L3 + 短期右侧确认）——最小纵向闭环

**解锁的用户步骤**：用户对一只自选股说「按个股闭环看看它」，得到四段式回答——技术面有没有「形」→ 信息面市场为何这样交易它 → 基本面能否持续 → 技术面执行建议；其中右侧确认信号有明确命中/未命中与依据。

**做什么**：
1. `agent/tools/analysis.py` 的 check_kline_signal 扩 2 个 signal 枚举：`high_20_breakout`（收盘价突破前 20 日完成 K 线的最高高点）与 `price_above_ma20`（收盘价站上 MA20）。复用既有 `_ma`（analysis.py:216）与 `_completed_daily_bars`（analysis.py:185-194——15:05 剔除当日未完成 K，天然收盘后右侧语义〔④〕）。DEFS 与 HANDLERS 双侧各加一项，registry 自动聚合（AGENTS.md 开发规范）。
2. **同步扩展返回契约（v1.1，评审意见 7）**：现有 handler 仅命中时 append 记录（analysis.py:244-266，v1.1 验证 19），未命中时 results 为空、无依据数值——不满足下方验收「未突破也要给出 20 日高点 = X、今日收盘 Y」。改为未命中也输出每只代码的依据字段（`hit: false` + `high_20` / `ma20` / `close` + 依据根数），命中记录沿用现字段并加 `hit: true`。契约变更需同步 `results/count/total` 的消费方语义（count 保持命中数，依据明细放独立字段，避免破坏现有 top20 截断契约〔④〕）。
3. `workflow/definitions.py` WORKFLOWS 列表加一个 `stock_closed_loop` 工作流：get_quote → check_kline_signal(high_20_breakout) → check_kline_signal(price_above_ma20) → check_earnings_catalyst → 汇总模板按「技术面发现→信息面解释→基本面持续性→技术面执行」四段渲染。步间传参复用 `_extract_*` 模式（definitions.py:42-56 先例〔④〕）；注册零成本（:533-535 循环〔④〕）。**触发方式（v1.3 补充）**：工作流靠 `trigger_patterns` 正则列表路由（每个 Workflow 必带，如现有 `r"美股.*(怎么样|如何|行情|走势)"`，v1.3 验证 23）——本工作流需配「个股闭环」「按闭环看看」类正则，验收语句须落在正则覆盖内；正则未命中时 NLRouter fallback 到 AgentService（router.py:3），agent 经工具组合（get_quote + check_kline_signal + check_earnings_catalyst）同样能完成检查——工作流是固化路径而非唯一通路，两条路都通向同一验收。

**积木清单**：
- 修改：`agent/tools/analysis.py`（枚举 + 2 个判定分支 + 未命中依据字段的契约扩展）
- 新增：`workflow/definitions.py` 一项工作流
- 复用：get_bars（日 K）、check_earnings_catalyst、get_fundamentals、get_quote、NLRouter 正则路由

**验收方式**（用户可感知）：正常网络下 `uv run mommy 按个股闭环看看 603662`，回答含四段结构，且每段标注数据时间与依据（如「20 日高点 = X 元，今日收盘 Y，未突破」）。断网/东财不可达时，回答明确说数据拉不到，**不产出假信号**。

**边界**：high_20_breakout 的复权/时点语义在验收前必须核对一次（〔③ notVerified〕get_bars 日 K 复权语义未核验；板块侧已验证 fqt=0/1 等价〔①〕但个股未验证）——核对方式：选 1-2 只有除权记录的个股，对比东财前台前复权数值；未核对前输出标注「未复权口径」。

### 阶段二：左侧→右侧纪律闭环（横切机制：记录、验证、退出）

**解锁的用户步骤**：用户说「把今天主力资金占比前几的记为左侧候选」→ 系统创建带阶段的预测记录；数天后用户问「上次记的候选后来怎么样了」→ 看到右侧是否确认、未确认的已自动退出归档。

**做什么**：
1. `agent/prediction_tracker.py` predictions 表加 `stage` 列（默认 `candidate`，可迁移到 `confirmed` / `retired`）**与 `confirmed_at` 可空时间列（v1.2，二审意见 2）**——现有时间字段仅 created_at（:29）/ verified_at（:44），不加则 stage=confirmed 的回写时刻无处可存，验收的「确认时间戳」做不到（v1.2 验证 21）。均用 SQLite 加可空列 + 默认值，向后兼容旧数据。〔④ evidence：状态机只有 pending→hit/missed/expired/unverifiable，无阶段语义——这是心法左右侧分层所需的唯一 schema 变更（v1.2 起为 stage + confirmed_at 两列，同一张表一次迁移）。〕
2. 左侧候选入口：不新建筛选器，复用 screen_inflow_stocks（analysis.py:119，池由上游喂入，如 `_extract_codes_from_watchlist` definitions.py:59-78〔④〕），把其输出接 PredictionTracker.create（direction/timeframe=短期档/entry_price/rationale/source_event_id/idempotency_key 全字段〔④〕）。**承接方式（v1.3 明确，不写专用胶水代码）**：用户自然语言 → NLRouter 未命中 → fallback AgentService → agent 调用 screen_inflow_stocks → 结果进入对话上下文（资金依据成为预测理由）→ extractor.py:383-405 从 agent 输出自动抽取创建（entry_price 自动填〔④〕）→ create 走 schema 默认 stage=candidate。即「接」是数据流承接（screen 输出 → rationale），不是新组件；MCP 入口（research_tools.py:763-794，幂等 key）同样不改。
3. **stage 与 status 的正交关系（v1.3 新增定义，两套状态机各管一件事）**：
   - `status`（既有列，verify_engine 写入）：验证**结局**——pending → hit / missed / expired / unverifiable，衡量「价格方向对不对」。
   - `stage`（新增列，右侧确认驱动）：心法**阶段**——candidate → confirmed / retired，衡量「右侧确认信号出现没有」。
   - 叠加规则：(a) verify 判 hit 但右侧信号（high_20_breakout 等）从未出现 → `status=hit` 且 `stage` 仍为 candidate——按心法口径「价格对了 ≠ 右侧确认」，展示为「方向对但未经确认」，不自动升 confirmed；(b) `confirmed` 只能由右侧确认依据写入（agent 按需检查命中后经 update_prediction_stage 工具回写，或用户人工判定后回写），**verify_engine 永不写 confirmed**；(c) `retired` 写入条件二选一：用户经工具显式放弃，或 verify 回填终态（missed/expired）时 stage 仍为 candidate 则一并标 retired——即「右侧迟迟不确认则退出」的落库面；(d) 展示层以 stage 为主键视角、status 为终态注记（/predictions 卡行同时展示两列）。
4. 右侧确认命中时（阶段一的按需检查发现 high_20_breakout / price_above_ma20）回写 stage=confirmed 并记录确认依据；右侧迟迟不确认由既有 verify_engine 兜底（见 §3 第四段与上方任务 3 叠加规则）。**回写的写入端是新增积木（v1.1，评审意见 5a）**：agent 工具层目前没有任何 prediction 写入工具（v1.1 验证 17：`update_status` 仅被 verify_engine 内部调用），需新增一个 agent 工具（如 `update_prediction_stage`，挂 `agent/tools/memory.py` 域，DEFS/HANDLERS 各一项），或扩展 MCP 研究结论入口（research_tools.py）携带 stage——二选一，默认前者（对话内闭环更短）。
5. **展示端同步改（v1.1，评审意见 5b）**：get_prediction_history 输出字段硬编码且无 stage（memory.py:212-227，v1.1 验证 17），TUI 卡片按该输出渲染当前状态列表而非变化轨迹（tui/services/renderers.py:49-50 → tui/widgets/cards.py:377-381）。需在工具输出加 `stage` 与 `confirmed_at` 字段（v1.2：确认时间戳也要出得来），并在预测卡行内展示 stage（候选/已确认/已退出）；「变化轨迹」的验收口径放宽为「当前 stage + 创建/确认/验证三个时间戳（confirmed_at 取任务 1 新增列）」，不新建轨迹视图。

**积木清单**：
- 修改：`agent/prediction_tracker.py`（stage + confirmed_at 列 + 状态迁移方法）、`agent/tools/memory.py`（get_prediction_history 输出加 stage/confirmed_at + 新增 update_prediction_stage 工具）
- 修改：`tui/widgets/cards.py` 预测卡（展示 stage 与 status 两列；renderers.py 分发已存在，无需改）
- 复用：screen_inflow_stocks、**extractor.py:383-405 对话自动抽取（左侧入口承接，v1.3 明确，无需新胶水）**、PredictionTracker.create、verify_engine.verify_pending（verify_engine.py:274-408）、scripts/cron_verify.py / `mommy agent run-verify`（cli_commands/agent.py:105-127）、TUI `/predictions` 预测卡

**验收方式**：创建一条真实左侧候选（当日资金流数据，正常网络）——建议用 `timeframe=1d` 或 `3d` 档做快速回路（v1.3 验证 22：verify_after = timeframe 的日历天数，1d→1 天、3d→3 天；叠加一个 timeframe 宽限窗口，终态最长约 2×timeframe 天必然出现——「等 1 个 verify_after 周期」是天级不是小时级）；到期后 `uv run mommy agent run-verify --json` 回填；`uv run mommy-tui` 内 `/predictions` 能看到该记录的 stage/status 及创建/确认/验证时间戳（candidate→confirmed，或 candidate→missed/expired 且 stage 同步 retired，见任务 3 叠加规则）。命中率统计（stats hit_rate，〔④实测 update_status 后 =1.0 正确〕）可查。

**边界**：stage/conviction 是**记录与提醒层面**的纪律执行，不产生任何自动交易动作；多日持续性资金流筛选不在本阶段（板块侧 120 日窗口见 §4）。

### 阶段三：板块轮动多日相对强弱（L2）

**解锁的用户步骤**：用户问「过去 20 日哪些板块最强？半导体排第几？钱在往哪走？」→ 得到**路径式**排名序列（N 日涨幅 + 排名变化），而非当日截面。

**做什么**：
1. `agent/tools/sector.py` 新增 `get_sector_bars` 工具（DEFS/HANDLERS 各一项）：直接透传 BK 代码给 EfinanceAdapter.get_bars（efinance_adapter.py:343-423 无前缀校验，mock 注入验证 adapter 路径通〔①〕）。不改 `agent/tools/bars.py:16` 的个股 pattern（避免个股工具误收板块代码，本次验证该 pattern 确实拒 BK）。
2. 新建板块相对强弱服务（建议 `src/mommy_chaogu/services/sector_momentum.py`，对齐现有 basket_service 模式〔②anchor 提及 services/ 模式〕）：板块池 → 逐板块经 CachedAdapter 拉日 K（落 bar_cache，TEXT 主键零 schema 变更〔①〕，二次计算零网络）→ 回算 N 日收益序列 → 排名。**板块池是新增工作而非复用（v1.1，评审意见 4）**：侦察报告①称 fetch_sector_ranking「当日返回全部行业+概念代码」与代码不符——它是固定 `pn=1` 单页、`pz=limit*2`、凑满 limit 即两处 break 的截断涨幅榜（rankings.py:91-136，v1.1 验证 16），拿不到全量池。需新建 clist 全量翻页拉取（翻页有先例：`sector_api.py:56` `for pn in (1, 2)`），或基于东财板块列表接口另建枚举函数。**必须节流**：全量约 90 行业+400 概念，每板块一次 push2his K 线请求〔①〕+ 列表翻页请求（pz 放大后数页）——限速 + 失败保留旧缓存（R4 已按此更新）。
3. 顺手修正两处过时注释：`sector_api.py:36` 与 `agent/tools/sector.py:57` 写「BK0475（半导体）」，但东财当前 BK0475=银行Ⅱ、半导体=BK1036（searchapi 实测〔①〕）。板块代码一律动态查询（search_sector，sector_api.py:110），不得硬编码。

**积木清单**：
- 新增：`services/sector_momentum.py`（含板块池全量翻页枚举函数）、`agent/tools/sector.py` 的 get_sector_bars
- 修改：两处注释
- 复用：EfinanceAdapter.get_bars（BK 透传）、CachedAdapter、bar_cache、clist 接口翻页模式（sector_api.py fetch_sector_stocks 先例）、search_sector
- 不复用：fetch_sector_ranking 作板块池（截断涨幅榜，仅可作为当日截面参考，v1.1 验证 16）

**验收方式**（需可访问东财的网络）：`uv run mommy 过去20日板块强度排名` 输出排名表（板块名/N 日涨幅/排名 vs 上一窗口）；二次执行明显变快（缓存命中）；拉取失败时返回旧缓存数据并标注数据截止日（开发规范：拉新失败保留旧数据）。

**边界**：首次全量拉取约 490 次请求，耗时与被限流风险见 §5 R4；板块资金流滚动累积（120 日窗口突破）不在本阶段（§4 degraded 项）。

### 阶段四：市场环境路径式状态与变化（L1）

**解锁的用户步骤**：用户问「现在市场什么状态？跟上周比有什么变化？」→ 得到指数三态序列（近 N 日逐日 bull/bear/sideways + 状态持续天数/切换点）+ 结构化变化清单，而不再是单值截面。

**做什么**：
1. **先补 A 股指数 K 线通路（v1.1，评审意见 3）**：get_bars pattern 只认美股指数（`^GSPC` 类）与 6 位个股码，A 股指数真相源 secid `'1.000001'` / 代码 `'sh000001'`（rankings.py:24 INDEX_LIST）均不匹配；误传 `'000001'` 会静默拉到平安银行日 K，regime 算在个股上且输出不暴露标的（v1.1 验证 15）。设计三选一（推荐 a）：(a) 新增 `get_index_bars` 工具（挂 `agent/tools/` 对应域），以 INDEX_LIST 为代码表，指数代码直通 EfinanceAdapter.get_bars（adapter 层 :343 起无前缀校验可透传；**指数实拉语义本轮未验证**——网络不可达，验收前须网络探针确认）；(b) 扩 get_bars pattern 接纳 `sh000001` 形式；(c) secid 直通。无论哪种，**输出必须标注判定标的**（如「上证指数 sh000001」）防静默错源。
2. 在 `backtest/regime_analysis.py` 之上加序列化封装：复用 `_regime_at`（:131-148，已实现按日期二分定位任意历史日〔④〕）生成逐日状态序列 + 状态转移摘要。挂成 agent 工具（如 `market_regime_series`，放 `agent/tools/` 对应域模块），数据入口用任务 1 的指数通路。
3. `agent/tools/memory.py:248` 把 narrative 的 scope 参数暴露到工具层（narrative.py:81 已支持 'market'/'sector:X'/'stock:Y'〔④〕）；将 detect_changes（narrative.py:112-159，最近 3 天 vs 之前 10 天的维度变化）挂成工具。

**积木清单**：
- 新增：A 股指数 K 线通路（get_index_bars 工具或等价）、regime 序列封装 + 对应工具；detect_changes 工具
- 修改：`agent/tools/memory.py`（scope 参数）
- 复用：classify_market_regime、_regime_at、INDEX_LIST（rankings.py:24）、episodic 事件源
- 不复用：get_bars 现有 pattern 拉 A 股指数（不通，v1.1 验证 15）

**验收方式**：`uv run mommy 现在市场什么状态，跟上周边比` 返回：**判定标的标注** + 三态序列摘要（如「上证指数：近 20 日 bull×12 → sideways×8，3 日前切换」）+ detect_changes 清单。验收含一道防错源检查：随机抽序列中一日，人工核对当日指数收盘价与东财前台一致（确认不是个股数据）。输出**标注「探索性状态评估」**——vol 阈值 2%/2.5% 未在真实指数数据上校准（〔④ notVerified〕仅合成 K 线验证），不构成择时建议。

**边界**：叙事（get_market_narrative）质量取决于 agent episodic 事件记录密度，数据源是 agent 自己的事件而非行情〔④〕——本阶段不改造叙事数据源，只暴露既有能力；LLM 生成路径未实测（§4）。

### 阶段五：右侧确认常驻化（修复断裂链路 + 推送覆盖）

**解锁的用户步骤**：用户经策略卡二次确认启用一条监控后，**告警会响**——在某个常驻进程运行期间，价格越过阈值时收到 Bark/微信推送，而不是存进数据库无人问津（常驻前提的产品口径见任务 3，v1.1 修订）。

**做什么**：
1. 接入 CustomAlert 常驻评估，共**三处** `alerter.evaluate` 调用点全部旁挂 `CustomAlertStore.evaluate`（v1.2，二审意见 1 补全第三处）：(a) `web/background.py:152` 的 `_tick`（默认 5s〔③〕）；(b) `monitor/poller.py:259`（覆盖 `mommy monitor run` 前台命令，CLI 30s〔③〕）；(c) `cli_commands/monitor.py:44-46` 的 `cmd_monitor_snapshot` 内 `if args.with_signals` 分支（覆盖 `mommy monitor snapshot --with-signals` 短命命令，v1.2 验证 20——v1.0 验证 4 已列出该调用但 v1.1 任务清单漏接，导致任务 3(b) 推荐的 cron 方案照单实现后仍不评估 CustomAlert）。接入 `CustomAlertStore.evaluate`（纯静态方法，接收实时 Quote 列表与固定 Decimal 阈值比较，custom_alerts.py:205-226，v1.0 已验证其生产零调用）。命中转成 Signal 对象进既有 SignalNotifier 管道（push/base.py:38-111：严重度过滤 ≥warning + Deduper 一码一规一天）与微信 sender（web/app.py:138-156）——推送限流天然继承，不需新机制。三处接入建议抽一个共用评估函数（输入 Quote 集 + 告警库），避免三份拷贝。
2. **告警代码集并入轮询范围（v1.1，评审意见 2）**：「评估输入复用 Snapshot 内 quotes」不成立——Snapshot 的代码集有两条隐性门槛：`background._tick` 开头 `codes = watchlist.get_all_codes(); if not codes: return`（自选股为空则评估循环不进，v1.1 验证 10）；`Monitor.snapshot_now` 以自选股 entry 为骨架拼 SnapshotRow（poller.py:118 起，codes 完全来自 `_index_entries()`，v1.1 验证 12）。而 custom_alerts 是独立表、code 任意——策略卡 `_handle_activate_monitor` 接受任意 code 写入，不要求先加自选股（strategies.py:516/559-564，v1.1 验证 14）。不处理则「不在自选股的告警永不评估」——恰是本阶段要修的 bug 的变体。修法：评估循环的取数代码集改为 `watchlist.get_all_codes() ∪ enabled custom_alerts 的 codes`；CustomAlert 评估分支直接对告警代码取 Quote（`CustomAlertStore.evaluate` 本就吃 Quote，无需构造 SnapshotRow），避开 SnapshotRow 依赖自选股 entry 的结构约束；`_tick` 的空判同理改为并集判空。
3. **明确常驻部署前提并写入产品口径（v1.1，评审意见 1；v1.2 修正推荐方案）**：评估循环只随进程存在——常驻的 `mommy-web`（`_tick`）、前台的 `mommy monitor run`，以及短命的 `mommy monitor snapshot --with-signals`（v1.2 验证 13/20）；TUI 无任何 notifier 接入（v1.1 验证 11）。产品的日常入口是一次性 CLI/TUI 对话，用户不常开 web 服务时告警不会响。本阶段据此**如实定口径**：「自定义告警仅在上述命令运行期间评估与推送」，并落到三处：(a) 策略卡 activate_monitor 的返回 message 与文档写明此前提；(b) 部署文档给出常驻方案选项——cron 定时 `mommy monitor snapshot --with-signals` 短命命令（**该路径经任务 1 第 (c) 处接入点评估 CustomAlert，v1.2 已闭环**；注意 `--with-signals` 是开关，不传则只打印快照不评估）或 launchd/systemd 常驻 `mommy-web`；(c) 不在本阶段新建 daemon 守护进程（超出最小必要工程，AGENTS.md 交付原则 4）。
4. earnings 自动提醒：将 `EarningsService` + `evaluate_all`（earnings/signals.py:236-243，生产零调用〔③〕，v1.0 已验证仅内部 rule.evaluate 有调用）接入 background 的日频调度（收盘后 pull+score+evaluate），信号走同一 SignalNotifier。

**积木清单**：
- 修改：`web/background.py`、`monitor/poller.py`、`cli_commands/monitor.py`（cmd_monitor_snapshot 分支；v1.2：三处评估点 + 代码集并集 + 共用评估函数）、earnings 调度接入、策略卡 activate_monitor 返回文案
- 新增：部署文档的常驻方案章节（cron/launchd 二选一指引）
- 复用：CustomAlertStore、SignalNotifier/Deduper、Bark/微信通道、策略卡 activate_monitor 双确认（strategies.py:495-595，不改其授权语义）

**验收方式**：
- **核心链路（v1.3 补可操作细节）**：启用一条 `price_above` 告警，**告警代码故意不加自选股**（v1.1：直接验证代码集并集修复）；**确定性制造触发**——阈值贴着现价设（如现价 +0.5%~+1%），盘中波动大概率在数个轮询周期内自然越过；若当日未越过，改设 `price_below` 现价 -0.5% 或直接把阈值调到现价下方即可下一 tick 必然满足。满足后在 `mommy-web` 运行期间收到推送（Bark 需用户自备 device key、微信需扫码——〔③ notVerified〕实际推送未实跑，验收即首次真实验证）。
- **Deduper 当天限流的验证方法（v1.3 补）**：触发一次后，让条件持续满足（价格停留在阈值上方）观察后续多个 tick / 手动再跑一次 `mommy monitor snapshot --with-signals`，确认同一条告警当天不再推；次日（或换告警 code）再验证可再次触发。
- **空自选股不失效**：清空自选股（或用独立测试库）重启 web，确认告警评估循环仍进入（v1.1：防 `_tick` 空判 return）。
- **评估可观测**：评估与命中计数写入日志（与 `poller tick` 同级 INFO；v1.1，评审意见 6：`mommy doctor` 是 agent 安装诊断透传（cli.py:222 → agent_managed.py:662），**不会**展示评估计数，验收入口改为日志 + 既有 manage_alert 查询确认告警在库状态）。
- **常驻前提如实呈现**：停掉 web 与 monitor run、不跑 snapshot 后，确认 activate_monitor 返回文案/文档明示「仅在评估命令运行期间评估」，不产生「已启用即常驻生效」的误导。
- 加开关（环境变量）可一键停用新评估分支（回滚用，§5 R3）。

**边界**：组合条件（板块共振、多日相对强弱阈值）仍**不可自动监控**——MonitorCondition 仅 4 枚举（strategy/models.py:52-56，v1.0 验证），扩枚举牵动策略卡校验器与 signals 两侧，不在本阶段；这些条件在策略卡中标 `manual`（「需人工判断」）。**告警非常开进程不响是产品口径而非缺陷**（任务 3），不在本阶段承诺后台守护。

### 阶段六：超短期（日内）层——前置修复 + 备源重建（受限环境阶段）

**解锁的用户步骤**：盘中（或盘后复盘）问「今天资金怎么交易 600519 的？」→ 得到开盘半小时强弱、VWAP 相对位置、尾盘行为卡片。

**做什么**（两项前置修复，顺序固定）：
1. **修复 bar_cache 分钟坍缩**：现状是确定性 bug——同日 4 根 5m K 落库仅 1 行（最后一根胜出），且缓存命中路径用坍缩缓存覆盖 fresh 返回值（cache/adapter.py:382-386；离线探针复现〔②〕）；生产全入口都包 CachedMarketDataAdapter（web/deps.py:105-108、cli.py:281、cli_commands/agent.py:62、cli_commands/monitor.py:30、tui/services/bootstrap.py:195〔②〕）。**两个候选方向的取舍（v1.3 展开依据，方向出自〔②anchor〕）**：(A)「分钟周期按日打包整日序列为单行 JSON」——不改主键、不改日线路径，只动分钟行，而存量分钟行本来就是坍缩的错误数据、无可破坏；(B)「主键加入 bar 时间戳」——bar_cache 主键 `(code, interval, adj_type, trade_date)`（cache/schema.py:22，v1.0 验证 2）要动结构，意味着全表现有行（含全部正确日线缓存）迁移、`set_bar` 的 ON CONFLICT 语义（store.py:233）与按日 fresh 判断全部重写，波及面覆盖日线。**选 A**：影响面小且失败爆炸半径不触及日线缓存；同时补 backfill 分钟周期（store.py:344-349 现硬编码 D1〔②〕）。
2. **接腾讯分钟 K 备源**：`tencent_adapter.py:362` 的 get_bars（现返回 []〔②〕）接 `ifzq.gtimg.cn/appstock/app/kline/mkline`——本网络实测可用：m5 单请求约 800 根 ≈17 交易日、start 锚点可翻页、存档约 2026-07 起；m1 ≈3-4 交易日〔②〕。时间标签从周期末转换为与 efinance 一致的周期初（混源统一约定〔②〕）。
3. 日内计算积木：新建 `services/intraday_service.py`（或 agent/tools/ intraday 域）：开盘半小时（10:00 价相对昨收 + 量占比）、VWAP（**公式：Σ(典型价×成交量)/Σ(成交量)，典型价 = (H+L+C)/3**——腾讯 mkline 无每根成交额，只能以成交量加权的典型价近似精确 VWAP，实算口径〔②〕）、尾盘 14:30-15:00 段行为。三个口径均已经腾讯 m5 真实数据实算验证〔②〕。

**积木清单**：
- 修改：`cache/schema.py`/`cache/store.py`/`cache/adapter.py`（分钟按日打包）、`tencent_adapter.py`（get_bars 分钟实现）
- 新增：`services/intraday_service.py` + intraday 工具
- 复用：get_order_book（五档，双源已实测拉通〔②〕；不缓存直通，cache/adapter.py:286）、BarInterval、_KLT_MAP

**验收方式**：离线单测（Fake 分钟源）验证同日多根分钟 K 落库后完整读回（坍缩修复的直接复现用例）；正常网络下 `uv run mommy 今天600519资金怎么交易它的` 输出三指标卡片并标注「VWAP 为典型价近似」。

**边界**：efinance 分钟 K 真实深度未知（本网络不可达〔② notVerified〕）；腾讯 m1 仅 3-4 交易日、m5 存档约 2026-07 起〔②〕——日内指标只承诺「当日 + 近期」，不做长期日内统计；盘口无历史留存，不能回看〔②〕。

---

## 3. 「左侧发现 → 右侧确认」机制：四段串联

心法横切机制在系统里的完整链路（阶段一、二建成后即成形，阶段五补常驻化）：

```
[左侧·高频·早而噪]                [右侧·低频·晚而准]                [纪律]
screen_inflow_stocks ──┐
（当日资金占比，池内）   │
板块相对强弱序列 ───────┼──> PredictionTracker.create ──> 按需检查（阶段一）──> stage=confirmed
（阶段三，多日路径）     │    stage=candidate              常驻告警（阶段五）        │
                       │    timeframe/target/entry         │                      │
                       │    idempotency_key 防重复          ├─ 确认 → conviction↑ 提示（不自动下单）
                       └──────────────────────────────────  └─ 未确认 → verify_engine 到期回填
                                                              missed/expired = 「右侧迟迟不确认则退出」
```

**第一段·候选生成（左侧）**：入口是 screen_inflow_stocks（给定池内当日主力净流入占比 ≥ 阈值，默认 50bp，降序 top20，analysis.py:119-157〔④〕）与阶段三的板块相对强弱序列。产出是 candidate 列表 + 每条的 rationale（资金依据）。诚实点：当前左侧信号只有**当日截面**（无多日持续性过滤）——板块侧 120 日资金流窗口可得但受缓存定格限制（§4），个股多日资金流持续性不在本次侦察证据内，不承诺。

**第二段·prediction 记录**：每个 candidate 落一条 PredictionTracker 记录（prediction_tracker.py:165-227：direction / timeframe（1d~60d 六档）/ target_price / entry_price / stop_loss / rationale / data_coverage / source_event_id / idempotency_key〔④〕）。两条既有入口：内置 agent 对话自动抽取（extractor.py:383-405，自动填 entry_price）与 MCP 外部研究结论（research_tools.py:763-794，幂等 key 防重复）。stage 初始为 `candidate`（阶段二新增）。

**第三段·监控确认（右侧）**：两条并行路径——
- **按需检查**（阶段一起可用，数日尺度低频）：agent 用 check_kline_signal 的 `high_20_breakout` / `price_above_ma20` 收盘后判定（_completed_daily_bars 保证只用完成 K 线，天然右侧〔④〕）；命中即回写 stage=confirmed 并附确认依据。
- **常驻监控**（阶段五后）：可自动化的条件（仅 4 种静态价格/涨跌幅阈值，models.py:52-56）经策略卡 activate_monitor 双重独立确认（prepare 只出候选、activate 强制 user_confirmed + confirmation_note，strategies.py:467-595〔④〕）后接入评估循环，命中经 Deduper 限流推送。
- **无法自动化的右侧条件**（板块共振、多日相对强弱阈值、K 线形态组合）：策略卡中标 `manual`，由 agent 在对话中按需检查并提示用户——**需人工判断**，不得偷换成相似的可实现规则（AGENTS.md 产品定位明令）。

**第四段·未确认退出**：verify_engine.verify_pending 到期自动回填（verify_engine.py:274-408：验证窗口 = verify_after + 一个 timeframe 宽限；报价三重保险 adapter→stale_cache；3 次 data_unavailable→expired；有目标价走距离分档、无目标价走 ±2% 死区方向判定〔④〕，实测通过）。timeframe 窗口耗尽时 stage 仍为 candidate → 终态 missed/expired，即心法「右侧迟迟不确认则退出」的记录面。用户在 TUI `/predictions` 或 CLI 看到全轨迹与 stats hit_rate；回填同时写 episodic 事件并回填源事件 prediction_id（verify_engine.py:339-397〔④〕），供 L1 叙事与后续复盘引用。

调度现实（v1.1 补齐两处部署前提）：① 验证触发是 cron/CLI 驱动（scripts/cron_verify.py、`mommy agent run-verify`、memory_pipeline.py:178-192〔④〕），无常驻高频调度——部署文档需写明 cron 配置属用户环境责任（〔④ notVerified〕用户 crontab 是否配置无法从仓库确认）。② 第三段「常驻监控」路径的评估随进程存在：`mommy-web` 进程、`mommy monitor run` 前台命令、`mommy monitor snapshot --with-signals` 短命命令三处（v1.1 验证 10/13、v1.2 验证 20，TUI 无 notifier 接入，验证 11）——**用户不运行这些命令则右侧确认不会自动提醒**，产品口径与部署选项见阶段五任务 3。

---

## 4. 诚实边界

### 4.1 unavailable——当前不可用，方案内不承诺

| 项 | 证据 | 处置 |
|---|---|---|
| 其他适配器（tencent/massive/yahoo）的板块支持 | tencent_adapter.py:111 明示不支持板块；massive_adapter.py:98/443-444 同；yahoo 仅美股〔①〕 | 板块能力全部锚定 EfinanceAdapter，按「东财单源 + 本地缓存续命」假设设计〔①anchor〕 |
| 自动下单 / 券商执行 | AGENTS.md 产品定位红线（非券商、非自动下单系统） | 执行层只到提示与记录 |

### 4.2 degraded——降级运行或需先修复

| 项 | 缺口 | 方案内处置 |
|---|---|---|
| 东财 push2his 本机出口被拒（TLS 后空响应，21 请求全失败；push2 502） | 环境性〔①② notVerified 声明为出口问题〕 | 板块 K 线/资金流/分钟 K 的端到端验收**必须在可访问东财的网络跑**；接口语义已外部验证但本机未实拉〔①〕 |
| CustomAlert 常驻触发链路断裂（evaluate 生产零调用，本次验证） | 告警存了没人查〔③〕 | 阶段五修复；修复前策略卡监控启用的实际效果是「可查询状态」而非「会自动提醒」，须向用户如实说明 |
| 评估仅随进程存在（mommy-web / monitor run 前台 / monitor snapshot --with-signals 短命命令三处），TUI 无 notifier 接入（v1.1 验证 10/11/13、v1.2 验证 20） | 用户不运行这些命令则告警不响 | 阶段五任务 1 三处接入点 + 任务 3 定产品口径与部署文档常驻方案；不新建 daemon（AGENTS.md 交付原则 4） |
| 告警代码不在自选股则不进 Snapshot；自选股为空 `_tick` 直接 return（v1.1 验证 10/12） | 「存了没人查」bug 的变体 | 阶段五任务 2：代码集取并集、CustomAlert 分支直接吃 Quote |
| earnings 披露后自动提醒缺失（evaluate_all 生产零调用〔③〕） | 只能手动 pull+score | 阶段五接入；此前标「需人工定期运行」 |
| 板块资金流 120 交易日滚动窗口 + 缓存定格（cache/adapter.py:511-518 首次拉多少定格多少〔①〕） | 上游硬限制 + 缓存不增量 | 不在本方案范围；若未来做，需调度层每日收盘增量落库〔①anchor〕 |
| 个股→板块反向归属无字段 | Quote 无 sector/industry〔③〕 | 共振确认与板块归属**需人工判断**/LLM 对齐 |
| 板块共振（个股与板块同日同向）作为监控条件 | 监控无板块维度、CustomAlert 单条件〔③〕 | 建成前标 manual；agent 可用 get_quote+get_sector_ranking 组合**近似**判断，输出须带「近似」标注 |
| 分钟 K：efinance 本网络不可达 + 腾讯备源未接线 + bar_cache 同日坍缩 | 确定性 bug 离线复现〔②〕 | 阶段六两项前置修复；修复前**任何分钟级功能不可信**（缓存命中路径退化为每日最后一根〔②〕） |
| 腾讯 mkline 无成交额 → VWAP 只能典型价近似；时间标签周期末 vs efinance 周期初 | 实测〔②〕 | 输出标注近似口径；统一标签约定后再混源 |
| MarketNarrative 数据源是 agent 事件非行情 | 质量取决于记录密度〔④〕；LLM 生成路径未实测 | 阶段四只暴露 scope/detect_changes，不改造数据源 |
| 推送只覆盖内置规则链路 | custom_alerts/earnings 不在链路〔③〕 | 阶段五统一；Bark/微信实际推送未实跑过〔③ notVerified〕，阶段五验收即首次真实验证 |
| monitor_rule 仅 4 种静态条件 | models.py:52-56（本次验证） | K 线形态/资金流占比/多日相对强弱一律标 manual |
| Server酱通道已删除 | git status + push/*.py 无引用（本次验证） | 推送通道 = Bark + 微信，无第三方备选承诺 |
| A 股指数无 agent 工具 K 线通路（get_bars pattern 拒 `sh000001`/`1.000001`，`000001` 会静默匹配平安银行） | v1.1 验证 15 | 阶段四任务 1 新增指数通路并标注判定标的 |

### 4.3 未验证项——对应阶段验收前必须补的检查

1. 板块 K 线/资金流在本机（及用户常用网络）的真实实拉：正常网络下先跑 `uv run pytest tests/test_market_data/test_efinance_adapter.py -m network`（本环境该探针 FAILED，health_check=False，属出口问题〔① notVerified〕）。
2. get_bars 日 K 复权/时点语义（影响 high_20_breakout 准确性〔③ notVerified〕）：阶段一验收前对比东财前台前复权数值。
3. 板块 1/5/15/30 分钟线未逐周期实测（仅 60m 验证，其余参数同构推断〔① notVerified〕）。
4. 腾讯 m1/m15 最深存档边界（仅实测 m5 至约 2026-07〔② notVerified〕）。
5. classify_market_regime 阈值未在真实指数校准〔④ notVerified〕：输出标「探索性状态评估」。
6. Snapshot 的 volume_ratio/turnover_rate 在腾讯 fallback 源下可得性未验证〔③ notVerified〕：影响 volume_surge/turnover_surge 触发率。
7. 用户 crontab（cron_verify）实际部署状态无法从仓库确认〔④ notVerified〕：部署文档明示。

### 4.4 产品红线（高于自动化率）

- **不称「真实回测」**：本方案所有历史序列计算（regime 序列、板块相对强弱、日内指标回看）均为「探索性观察 / 当前状态评估」；未确认复权/样本/信号定义/评价方法前不进入回测叙事（AGENTS.md 交付原则 6）。
- **不偷换指标**：不能精确实现的心法条件标「需人工判断」或「当前不可用」，不得换成相似指标或代理规则（AGENTS.md 产品定位）。
- **三次独立授权不放松**：策略卡确认含义、保存、启用监控保持三次独立授权（〔④ evidence：prepare/activate 双确认实测〕）；阶段五只接通「启用后真的会响」，不改授权语义。

---

## 5. 风险与回滚

| # | 风险 | 影响 | 缓解 | 回滚 |
|---|---|---|---|---|
| R1 | 东财单源、用户网络不可达（本机已复现 push2his 拒连） | 阶段三/六验收阻塞；板块功能整体失效 | 验收前置网络探针；设计按「东财 + 本地缓存续命」〔①〕；拉新失败保留旧数据并标注截止日（开发规范：数据库唯一真相源） | 数据库缓存仍在，功能降级为「只读缓存 + 明示数据过期」，无破坏性 |
| R2 | schema 变更（predictions 加 stage + confirmed_at 列；bar_cache 分钟按日打包） | 旧数据兼容 | stage 列可空 + 默认值（SQLite ALTER TABLE，向后兼容）；分钟打包不动 PK、日线路径零影响。**对用户旧数据的直白答复（v1.3）**：已有 predictions 记录一条不丢——新列自动取默认（stage=candidate、confirmed_at 为空），旧字段与旧查询完全不受影响；已有 bar_cache 日线行原样保留，按日打包只写分钟行（且存量分钟行本就是坍缩错误数据） | stage 列弃用即可（查询忽略）；分钟打包行可按 interval 识别清理，日线缓存不受影响 |
| R3 | CustomAlert/earnings 接入评估循环后的推送打扰 | 用户被噪声淹没 | 命中转 Signal 走既有 Deduper（一码一规一天）+ 严重度过滤〔③〕，不新造限流 | 新评估分支加环境变量开关，一键摘除回到仅内置规则 |
| R4 | 板块批量拉取被限流/耗时过长：全量枚举翻页请求（pz 放大后数页）+ 约 90 行业+400 概念各一次 K 线请求（v1.1 评审意见 4 重新核对：侦察报告①「fetch_sector_ranking 可作全量池」与代码不符，全量枚举是新增翻页拉取） | 阶段三首次执行慢或部分失败 | 请求间限速 + 失败重试退避 + 已落库板块跳过（bar_cache 二次零网络〔①〕）；首期可先只做行业板块（约 90 个）再扩概念。**量级（v1.3，算术估计非实测）**：约 490 次串行请求 × 限速间隔 0.5~1s ≈ 首次 5~10 分钟量级，实际取决于限速参数与网络；被限流/封禁的概率无数据、未验证——属「未验证项」，首次运行即真实测量点 | 板块池可配置缩减；失败板块显示「数据缺失」不阻塞整体 |
| R10 | A 股指数误走个股码（`000001`=平安银行）致 regime 算在个股上，输出貌似合理实则错源（v1.1 验证 15） | 阶段四产出错误的市场状态 | 阶段四任务 1 专用指数通路 + 输出强制标注判定标的 + 验收抽日对价 | 指数通路独立工具，摘除即回退现状 |
| R5 | 板块代码映射漂移（BK0475 注释已证实过时〔①〕） | 硬编码代码指向错误板块 | 一律 search_sector 动态查询；顺手修正两处注释（阶段三任务 3） | 无需回滚（纯注释 + 查询路径） |
| R6 | 复权语义未核验导致 high_20_breakout 误判 | 假突破/漏突破信号 | 阶段一验收前语义核对（§4.3-2）；未核对前输出「未复权口径」标注 | 信号枚举可独立摘除（enum 收回即回到两信号现状） |
| R7 | 阶段六 bar_cache 改造伤及现有日线缓存 | 现有日 K 功能回归 | 方案选「按日打包」不动 PK；离线单测覆盖「同日多根分钟 K 完整读回」+ 现有日线用例全量跑（`uv run pytest -m "not network"`，2,082 用例基线） | 打包行按 interval 识别清理；最坏情况 bar_cache 重建（缓存可再生，非用户数据） |
| R8 | 腾讯分钟备源变更/限流 | 阶段六日内指标失效 | 备源仅承担分钟 K；efinance 通道在正常网络下仍是主源（其分钟 K 含成交额，可做精确 VWAP〔②〕） | tencent get_bars 分钟实现独立成方法，摘除即回退 [] 现状 |
| R9 | 产品来源倒置（围绕自动化率优化而偏离心法原意） | 策略卡失真 | 策略卡忠于原意优先于技术可执行率（AGENTS.md）；§3 第三段明列 manual 条目清单 | 每阶段验收先问「用户多了什么能力」再查工程（交付原则 5/评审顺序） |

**阶段依赖与独立回滚（v1.3 重写以澄清依赖关系）**：
- 一 → 二 有依赖：阶段一的右侧确认信号枚举是阶段二 stage=confirmed 的判定来源（先有一才有二的确认回写；但二只做记录与验证闭环时，不依赖一也能跑——确认回写功能空缺而已）。
- 三、四相互独立，各自只依赖既有数据层，不依赖一/二。
- 五不依赖一~四的任何产出：它只接通告警链路（评估点 + 推送），可与任一阶段并行开发。
- 六完全独立（两项前置修复自成闭环，不触及一~五的任何改动）。
- 任一阶段回滚不影响其余阶段的既有功能。

**工作量口径（v1.3 明确）**：本方案**不含工期估计**——四份侦察报告未做工作量测量，任何天数都是编造；可用的粗序是各阶段「积木清单」里的修改/新增文件数与 schema/缓存/网络触碰面：阶段一最小（1 个工具扩展 + 1 个工作流项，不动 schema、不动缓存、不依赖新网络通路），是建议的起点与第一个可走通闭环；其余按编号顺序推进即可，每阶段独立可验收意味着可以做完一段停一段。

---

## 6. 使用者须知（v1.3 新增，回答「读完最可能接着问的」）

**Q1 先做哪个？多久能走通第一个闭环？**
阶段一（理由与粗序见 §5「工作量口径」）。本方案不提供天数估计——没有工作量测量依据，编数字违反本方案的诚实原则；第一个闭环的规模感：改 1 个工具文件的枚举与返回契约、加 1 个工作流定义，不动 schema、不动缓存、不依赖新网络通路。

**Q2 我的机器连不上东财（§0 说的 push2his 拒连）怎么办？**
验收前先跑网络探针确认环境：`uv run pytest tests/test_market_data/test_efinance_adapter.py -m network`（本方案起草机器上该探针 FAILED，属出口问题〔① notVerified〕）。可达网络指大陆常规家宽/办公出口（②实测本机疑似境外出口被东财拒绝）。**代理方案未验证、不做承诺**——本文没有任何证据支持「配代理可绕过」。网络不可达期间功能不是坏了：降级读本地缓存并标注数据截止日（R1，开发规范「拉新失败保留旧数据」）。

**Q3 我平时只用 TUI / 一次性 CLI，告警是不是必须常开 mommy-web 或配 cron？频率多少？**
是——阶段五的产品口径就是「告警仅在评估命令运行期间评估」（任务 3），这是如实陈述而非缺陷遮掩。最低成本姿势：cron 定时 `mommy monitor snapshot --with-signals`（经任务 1 第 (c) 处接入点评估 CustomAlert）。**频率建议值（非验证值）**：交易时段每 1~5 分钟一次——参照系是 web 内置 5s / monitor run 默认 30s，而 4 种可自动化的告警条件都是静态阈值、非秒级语义，分钟级足够；收盘后再跑一次做当日兜底。愿意常驻就开 `mommy-web` 或 launchd/systemd（部署文档给两个选项）。

**Q4 我已有的 predictions / bar_cache 数据会怎样？**
见 R2 的直白答复：predictions 旧记录一条不丢（新列取默认值，旧查询不受影响）；bar_cache 日线行原样保留（按日打包只写分钟行，且存量分钟行本就是坍缩错误数据）。

**Q5 标「需人工判断」的条件（板块共振等）是永远人工吗？**
不是设计上永远，但**本方案不承诺解锁时间**。可监控化的技术前提（v1.3 盘点，均出自③④证据）：MonitorCondition 扩枚举（strategy/models.py:52-56）+ signals 侧板块数据源与 Snapshot 扩展 + **个股→板块反向归属字段（当前 Quote 无此字段〔③〕，数据前提缺失）**——工程面横跨策略卡校验器、signals、monitor 三层且关键数据前提不在手里，故未排期。§4.2「建成前需人工判断」的「建成」即指这些前提全部落地；在那之前把这类条件改写成「方便实现的相似规则」是被 AGENTS.md 明令禁止的偷换。

**Q6 板块全量拉取首次要跑多久？封 IP 概率多大？**
时长量级与假设见 R4（约 490 次请求 ≈ 5~10 分钟量级，算术估计非实测）；封禁概率无数据、未验证，首次运行即真实测量点，缓解是限速 + 退避 + 分批（先行业约 90 个再扩概念）。

---

## 附录 A：与既有计划的关系

- 本方案不改动 `PLAN.md` 当前主线（Strategy Distillation 产品合同与「按这套方法看 X」路径）；阶段二/五的 prediction stage 与告警接通是对该合同「可靠支持的条件接到二次确认的本地监控」承诺的兑现补全，授权语义不变。
- `AGENTS.md` 项目结构中 workflow 数量写 9、实际 10（〔④ evidence：definitions.py 10 个，本次 grep 确认〕）；阶段一新增后为 11，建议顺手更新该行文档（属文档勘误，不属本方案工程范围）。

---

## 附录 B：v1.1 评审意见处理记录（7 条全部接受，无拒绝项）

每条意见引用的事实均经本轮亲自运行命令复核（命令与输出见 §0「评审回合补充验证」10-19），全部成立后落入正文：

| # | severity | 意见摘要 | 核验结果 | 落点 |
|---|---|---|---|---|
| 1 | high | 「告警真的会响」漏常驻进程前提：评估循环仅在 mommy-web `_tick` 与前台 `monitor run`，TUI 无 notifier | 成立（验证 10/11/13） | 阶段五任务 3（产品口径 + 部署文档，不新建 daemon）、验收增「常驻前提如实呈现」项、§3 末段补第 ② 点、§4.2 增行 |
| 2 | high | 「复用 Snapshot 内 quotes」覆盖不了非自选股告警代码；自选股为空 `_tick` 直接 return | 成立（验证 10/12/14） | 阶段五任务 2（代码集并集 + CustomAlert 分支直接吃 Quote，避开 SnapshotRow 依赖 entry）、验收增两项针对性用例、§4.2 增行 |
| 3 | medium | 「复用：指数日 K（get_bars）」对 A 股指数不通，`000001` 静默拉到平安银行 | 成立（验证 15） | §1.2 L1 行改写、阶段四任务 1（新增指数通路三选一设计 + 标注判定标的 + 验收抽日对价）、§4.2 增行、§5 新增 R10 |
| 4 | medium | 「板块池 = fetch_sector_ranking 全量」与代码不符：单页截断涨幅榜，全量需新建翻页拉取 | 成立（验证 16；侦察报告①该条 evidence 与代码不符，以代码为准） | 阶段三任务 2 改写、积木清单「不复用」项、R4 重新核对请求量 |
| 5 | medium | stage 写入端（无 agent prediction 写入工具）与展示端（get_prediction_history 无 stage、卡片非轨迹）都没落点 | 成立（验证 17） | 阶段二任务 3/4（新增 update_prediction_stage 工具、输出加 stage、卡片改展示 stage + 三时间戳；验收口径放宽为非轨迹视图）、积木清单补两项 |
| 6 | low | `mommy doctor` 是安装诊断，不展示评估计数，验收入口不存在 | 成立（验证 18） | 阶段五验收「评估可观测」项改为日志 + 既有 manage_alert 查询，不扩 doctor |
| 7 | low | 验收要求未命中也给依据数值，但 check_kline_signal 仅命中时返回记录 | 成立（验证 19） | 阶段一新增任务 2（契约扩展：未命中输出 hit:false + high_20/ma20/close 依据字段，count 语义不变）、积木清单同步 |

## 附录 C：v1.2 二审意见处理记录（2 条全部接受，无拒绝项）

意见引用的事实均经本轮亲自运行命令复核（命令与输出见 §0「二审回合补充验证」20-21）：

| # | severity | 意见摘要 | 核验结果 | 落点 |
|---|---|---|---|---|
| 1 | medium | 任务 3(b) 推荐的 cron 方案（`mommy monitor snapshot --with-signals`）的评估点是第三处独立 `alerter.evaluate`（cmd_monitor_snapshot 内），不在任务 1 接入点清单里——照单实现后 cron 方案不评估 CustomAlert | 成立（验证 20；v1.0 验证 4 自己列过该调用但 v1.1 任务清单漏接，属本方案自相矛盾） | 阶段五任务 1 改为三处接入点（补 cli_commands/monitor.py:44-46，建议抽共用评估函数）；任务 3(b) 的 cron 方案明确经第 (c) 处接入点闭环、删开放性「需确认」提示；积木清单、§3 末段、§4.2 同步 |
| 2 | low | 「确认时间戳」无存储落点：predictions 表时间字段仅 created_at/verified_at，stage 变更不含确认时刻字段 | 成立（验证 21） | 阶段二任务 1 schema 变更扩为 stage + confirmed_at 两列（同一张表一次迁移）；任务 4 工具输出与卡片展示加 confirmed_at；积木清单同步 |

## 附录 D：v1.3 终审反馈处理记录（15 条全部处理，无拒绝项）

终审读者以「第一次读、未来照着用」视角通读全文（仅读文本、未核对代码）。15 条归并为三类处理；其中 2 条需补仓库事实，已亲自运行命令核验（§0「终审回合补充验证」22-23）：

| 类 | 条目 | 处理 | 落点 |
|---|---|---|---|
| 一1 | §5 阶段依赖病句 | 重写为逐条依赖清单（一→二、三/四独立、五不依赖一~四、六独立） | §5「阶段依赖与独立回滚」 |
| 一2 | stage 与 status 两套状态机关系未定义 | 新增正交定义与叠加规则（hit≠confirmed、retired 写入条件、verify_engine 永不写 confirmed、展示双列） | 阶段二任务 3、验收、§3 落库面表述 |
| 一3 | 阶段二用户入口无承接组件 | 明确数据流承接：NLRouter fallback → agent 调 screen_inflow_stocks → extractor 自动抽取创建，无专用胶水 | 阶段二任务 2、积木清单补 extractor 复用 |
| 一4/二1 | 证据材料只有代号无出处；「作者确认」不可查证 | §0 新增「出处及可查证性」：侦察报告未入仓库、升级提问机制解释、不可查证的地基如实声明并建议归档；代码行号锚点可独立复核 | §0 |
| 一5 | 新工作流如何被触发未说明 | 补 trigger_patterns 正则路由 + 未命中 fallback AgentService 双通路说明（核验 23） | 阶段一任务 3 |
| 二2 | available/degraded 判据不一致（同为零调用） | §0 新增状态判据定义：零调用不是判据，「是否使既有产品承诺失效」才是 | §0「状态判据」 |
| 二3 | 推送 available 与「未实跑」矛盾 | §1.2 状态改为「available（代码链路；端到端从未实跑）」并与 §4.2 衔接 | §1.2 推送行 |
| 二4 | 「等 1 个 verify_after 周期」无时长量级 | 核验 22：verify_after=timeframe 日历天数（1d→1…60d→60）+ 一个 timeframe 宽限；验收建议 1d/3d 档 | 阶段二验收 |
| 二5 | 告警验收缺确定性触发与 Deduper 验证方法 | 补：阈值贴现价 ±0.5%~1% 制造必然触发；条件持续满足 + 手动重跑 snapshot 验证当天不重复推 | 阶段五验收 |
| 二6 | 按日打包取舍无文本内依据；VWAP 加权权未说明 | 补两方向对比（B 动主键波及日线缓存 vs A 只动分钟行）与选择理由；VWAP 公式 Σ(典型价×成交量)/Σ(成交量) 明示 | 阶段六任务 1/3 |
| 三1 | 工期与优先级 | 不编天数（无测量依据），给定性排序与阶段一规模感 | §5「工作量口径」、§6 Q1 |
| 三2 | 本机网络不可达的操作路径 | 探针命令、可达网络定义、代理未验证不承诺、降级行为 | §6 Q2 |
| 三3 | 告警日常使用姿势与 cron 频率 | cron snapshot --with-signals 最低成本姿势；频率建议值（1~5 分钟，标注非验证值）与参照系 | §6 Q3 |
| 三4 | 旧数据安全要一句直白话 | 「predictions 旧记录一条不丢、bar_cache 日线行原样保留」 | R2、§6 Q4 |
| 三5 | manual 条件是永远人工还是未来可监控 | 盘点可监控化前提（含反向归属数据缺口），不承诺时间 | §6 Q5 |
| 三6 | 板块全量拉取代价量级 | 5~10 分钟量级（算术估计非实测）、封禁概率未验证 | R4、§6 Q6 |
