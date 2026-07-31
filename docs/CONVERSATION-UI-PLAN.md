# 对话即界面（Conversation as Interface）实施台账

> 创建：2026-07-24。状态：Phase 0–2 已完成，Phase 3 发布门禁已完成（待 v1.2.0 tag）。
> 本文档跟踪「对话即界面」重构的阶段划分、已完成工作与接下来的实施方案。
> 完成后归档到 `docs/archive/`。
> 2026-07-31 更新：本文继续记录已完成实现；Web 首页与导航的下一阶段产品方向以
> [`PRODUCT-UX-EXECUTION-PLAN.md`](PRODUCT-UX-EXECUTION-PLAN.md) 为准。

## 目标与设计原则

把产品中心从「数据看板 + 附加的 AI」翻转为「AI 对话 + 内联的数据证据」：

- **TUI**：投研版 Coding Agent CLI（Claude Code / Kimi Code 体感）。单屏对话流，全键盘，无模式切换、无鼠标、无交易所式看板。
- **Web**：移动优先，首页即对话。数据页面收敛为对话的上下文，不再是 9 个并列页面。

三条原则：**agent 是产品，数据是它的论据；任何系统状态都必须可见（反静默）；错误不是空态。**

## 阶段总览

| 阶段 | 内容 | 状态 | 交付物 |
|---|---|---|---|
| Phase 0 | 后端评估修复（EVALUATION-2026-07-18 全部 17 项） | ✅ 已合并 main | PR #23 + `fix/eval-backlog`（`812c647`，merge `ef434fe`） |
| Phase 1 | TUI 单屏重写 + 后端配套 + Web 错误约定 + 文档同步 | ✅ 已合并 | PR #27 → `feat/conversation-ui` |
| Phase 2 | Web 对话为主轴重构 | ✅ 已完成 | 根路由对话 + 上下文栏 + 搜股/详情/持仓闭环 |
| Phase 3 | 截图 / 发版 / 文档收尾 | 🟡 门禁完成 | v1.2.0、3 张截图、全量门禁；待 tag |

---

## 1. Phase 0 — 后端评估修复 ✅

EVALUATION-2026-07-18（`docs/archive/EVALUATION-2026-07-18-backend.md`）的 17 个主问题 + 次要项 + 行动清单 #1-#12 全部闭环。两轮独立终审 + 二次复核无遗漏。1475 测试全绿。

关键交付：`agent/llm.py`（provider 单一真相源 + embedding 模型分离）、流式单次调用重构（消除双重计费）、对话后提取后台化（`flush()`）、TokenTracker 接线、ToolContext 三库拆分、registry 8KB 截断、装配冒烟测试套件。详见 commit `812c647`。

---

## 2. Phase 1 — TUI 重写 + 配套 ✅（PR #27 已合并）

### 2.1 任务清单

| 任务 | 状态 | Commit |
|---|---|---|
| 后端：`on_status` 重试回调 + Esc 穿透重试等待（`cancel_event.wait`） | ✅ | `d810344` |
| TUI：单屏对话重写（删看板/ContentSwitcher/Tab） | ✅ | `782bb91` |
| TUI：13 个 slash 命令 + 对话内富卡片 + `@` 股票联想 | ✅ | `782bb91` |
| TUI：状态可见性（TopBar AI 状态点、重试进度、记忆回执、截断标注） | ✅ | `782bb91` |
| Web 先行块：错误状态约定（ErrorState≠EmptyState、401 横幅、stores 保留旧数据） | ✅ | `cd44e7e` |
| `mommy` 主入口补 `load_dotenv()`（实测复现的高优 bug） | ✅ | `cd44e7e` |
| 文档：CHANGELOG Unreleased、README/AGENTS/docs 数字同步 | ✅ | `cd44e7e` |
| 验证：1518 pytest + ruff + mypy strict + web vitest 35 + build/typecheck | ✅ | — |
| 界面验收（Pilot 冒烟 + SVG 渲染检查） | ✅ | — |

### 2.2 已完成的设计细节（留档）

**单屏布局**：`TopBar（指数快照 + AI🟢/⚪ + 时钟）+ ChatView（对话流）+ WorkingIndicator + 输入框 + Footer`。启动焦点在输入框（Pilot 测试断言）。看板三文件（dashboard/main/stock_detail）删除，「看板键盘全死」bug 随架构消失。

**slash 命令 → 卡片**（全部对话流内渲染，不跳屏）：

| 命令 | 卡片 | 数据源 |
|---|---|---|
| `/today` | 今日总览（三指数 + 自选红绿 + 信号数 + 待验证预测数） | DataService.watchlist_quotes / memory_db |
| `/watch` | 自选股表格（名称/现价/涨跌/量比） | watchlist_quotes |
| `/portfolio` | 持仓（代码/成本/现价/浮盈亏） | portfolio_snapshot |
| `/flows [code]` | 资金流（无参=自选主力净流入榜） | _fetch_flow_safe |
| `/quote <code>` | 报价卡（输 6 位代码也直接触发） | adapter.get_quote |
| `/predictions` | 预测跟踪（命中率 + 倒计时） | PredictionTracker |
| `/signals` | 信号（中文严重度徽章） | SignalStore |
| `/memory` | 记忆统计 + token 用量与估算成本 | memory_db + TokenTracker |
| `/status` | AI/数据源/缓存命中/4 个 DB 路径 | bootstrap |
| `/help` `/clear` `/theme` `/quit` | — | — |

**`@` 联想**：代码前缀 + 名称子串匹配（自选股 + 半导体库 + quote_cache，实测 133 只）；HintBar 候选 + ↑↓ 循环 + Tab 插入；Enter 在联想态先接受候选。

**工具结果渲染**（`services/renderers.py`）：get_quote→报价卡、get_money_flow_today→资金流卡（单/多）、get_bars→≤10 行迷你表、get_prediction_history→预测卡、其余→文本 digest。结果含 `[truncated` 时工具行追加「（结果过大已截断）」。

**状态可见性**：重试时工作行「⏳ 网络较慢，正在重试 (1/3)…」（接 `on_status`）；后台提取完成后追加淡色「✎ 已记住本轮要点」（`AgentBridge.watch_background`：watcher join `_bg_threads` 后 call_from_thread 上屏）；错误三条路径（chat/workflow/卡片 worker）统一走 `friendly_error()`（401→"API key 无效，请检查 .env"等）。

**键盘**：Enter 发送；busy 排队（「已排队 N 条」+ 轮次结束自动发）；Esc 中断（保留已流部分标注「（已中断）」）；↑↓ 候选/历史；PgUp/PgDn 滚动；Ctrl+C 双击退出；Ctrl+P 命令面板（12 条目映射 slash）。

**Web 错误约定（先行完成）**：`ApiError{status, friendly, raw}`（401→需要访问令牌 / 5xx→服务暂时不可用 / 网络→网络连接失败）；stores 统一 `error` 字段且失败保留旧数据；`ErrorState.vue`（图标+人话+重试）与 EmptyState 严格区分；401 全站横幅跳设置页；6 页面（portfolio/dashboard/detail/themes/market/themes-detail）三态分离落地。

---

## 3. Phase 2 — Web 对话为主轴重构 ✅

> 目标：首页即对话；预测/信号/主题融入对话场景；动线打通（搜股、加自选、问 AI）；移动端持仓卡片化。

### 3.1 信息架构（9 页 → 4 tab + 对话内抽屉）

```
移动端底部 tab：  对话 │ 行情 │ 持仓 │ 我的
桌面端（≥768px）：左栏对话（主，flex-1） + 右栏上下文（w-80：自选摘要/近期预测/信号），
                  <1280px 右栏折叠为对话页内抽屉（Sheet 组件）
```

**路由重排**（`web/src/router/index.ts`）：

| 路径 | 页面 | 说明 |
|---|---|---|
| `/` | 对话页（新首页） | 原 `/agent` 内容重写；`/agent` redirect → `/` |
| `/market` | 行情 | 保留（指数 + 涨跌榜 + 板块） |
| `/portfolio` | 持仓 | 保留，移动端改卡片式 |
| `/my` | 我的 | 原 settings 改名搬家（AI 状态卡、令牌、自选股管理、缓存、主题） |
| `/predictions` `/signals` | 保留路由可深链 | 从导航移除，入口在对话页抽屉 |
| `/detail/:code` `/themes` `/themes/:id` | 二级页保留 | 详情页加动线按钮（§3.4） |
| `*` | 新增 404 页 | catch-all（现状空白主区） |

**导航**（`App.vue` 重写）：移动端 4 tab（对话/行情/持仓/我的，图标+双字标签）；桌面端左侧窄栏同样 4 项（w-16 图标 + title，或 w-40 图标+文字——取 w-40，K3 报告指出纯图标对新用户不友好）；移除「更多」弹层（预测/信号入口进对话页抽屉，「齿轮图标装非设置内容」问题随之消失）。

### 3.2 对话页重写（`pages/agent/index.vue` → `pages/chat/index.vue`）

**布局**：

```
┌ 页顶：AI🟢 glm-4.7（或 ⚪ 未配置横幅） · 🗋 上下文抽屉 · ＋新对话 ┐
│ 欢迎卡（无历史时）：今日概览（指数/自选红绿/信号数）              │
│   + 快捷问题药丸 ×6 + 🎤 语音 + 「近期预测」卡片入口               │
│   + 一句卖点：我会记住自己的判断并挨打验证                         │
│ 消息流：用户气泡 / AI 气泡（流式 markdown）                       │
│   工具调用行（🔧 name ✓ Ns，折叠）                                │
│   AI 气泡下挂「🎯 查看预测跟踪」（回答涉及预测时）                 │
├ 输入区：多行 textarea（自适应）· 🎤 · 发送                        │
│  busy 时可打字，Enter 排队；■ 停止按钮                            │
└──────────────────────────────────────────────┘
```

**WS 状态机修复**（`api/agent.ts` 重写核心逻辑）：
- `onDone(text, toolsUsed, rounds)`：无 chunk 时用 `done.text` 兜底渲染（修「降级空气泡」——后端降级 done 已带 text，前端此前丢弃）。
- 中途断连：不再静默重试一次后卡死——`onclose` 且存在未完成回合时，直接 `onError('连接中断，请重试')` + `loading=false` + 输入框解锁 + 停止按钮复位。
- `closedByClient` 语义保留；重试仅用于初始连接失败（现状逻辑保留）。

**AI 状态**：页顶状态点（进入页面时 `GET /api/agent/chat` OPTIONS 不行——用现有 `/api/health` + 首次交互兜底；更简单：复用错误约定，首次 401/降级时切 ⚪ 并显示常驻横幅「AI 未配置：回答不可用，行情页可正常浏览」）。

**记忆露出**：加载时 `GET /api/agent/history?session_id=`（端点已有 `routes/agent.py:178`）恢复会话；欢迎卡含「近期预测」卡片（`GET /api/agent/predictions?limit=3`，点击开抽屉）；回答涉及预测时气泡下挂抽屉链接（后端 done 消息带 `predictions_made: N` 则更精确——若没有该字段，前端以「查看预测跟踪」常驻欢迎卡入口代替，不猜）。

**输入区**：单行 Input → 自适应 textarea（Shift+Enter 换行、Enter 发送、busy 可打字排队）；🎤 语音按钮复用 `useSpeechRecognition`（持仓页已有，对话页此前反而没有）；「＋新对话」按钮（清 sessionStorage + 新 session id + 清空消息流）。

### 3.3 右侧上下文栏 / 抽屉（`components/ContextPanel.vue`）

三个 section（数据源均为现有端点）：
- **自选股摘要**：`GET /api/watchlist/quotes`，行可点 → `/detail/:code`
- **近期预测**：`GET /api/agent/predictions?limit=5`（命中率徽章 + 状态点）
- **信号**：`GET /api/signals/recent?limit=5`（中文严重度徽章）

移动端为对话页内 Sheet 抽屉（页顶 🗋 按钮触发）；桌面 ≥1280px 常驻右栏。

### 3.4 动线

- **名称搜股**：新端点 `GET /api/stocks/search?q=`（`web/routes/market.py` 新增——自选股 + semicon_stocks + quote_cache 模糊匹配：名称子串 / 代码前缀，限 10 条；配套单测）。前端 `components/StockSearch.vue`（输入联想下拉），用于：「我的」加自选、行情页搜索框、对话页 @。
- **详情页**报价卡加「⭐ 加自选」「🤖 问问 AI」（跳 `/?q=分析一下{code}`，对话页 onMount 读 query 自动发送）。
- 自选股/持仓/榜单/上下文栏中的代码全部 `<RouterLink>` 进 `/detail/:code`。

### 3.5 持仓页移动端卡片化

≤767px：表格 → 卡片列表（每票一卡：名称/代码 + 现价 + 浮盈亏大字 + 成本/占比小字 + 展开按钮显示调仓表单）；≥768px 保留表格。「操作列在屏外」「7 列横滚」问题消失。

### 3.6 打磨项（随重构顺手）

- K 线深色模式：网格/tooltip 颜色从 CSS 变量取（`detail/index.vue:154-169` 硬编码 `#eee/#333` → `getComputedStyle` 读 `--border/--foreground`，主题切换时 setStyles）。
- 成交量 `fmtWan` + 「万手」单位；信号徽章 CRIT/WARN/INFO → 紧急/注意/提示。
- 工作流徽章英文 slug → 中文名映射（morning_brief→早安简报等，前端常量表）。
- 术语 Glossary tooltip（主力净流入/量比/换手/PE，挂 info 图标）。
- 行情页标题「盘面」与导航统一为「行情」；emoji 与仪表盘错开。

### 3.7 实施步骤（文件级）

1. **后端**：`routes/market.py` 加 `/api/stocks/search` + 单测（`tests/test_web*` 对应文件）。
2. **错误约定衔接**：Phase 1 已完成的部分（client/stores/ErrorState/401 横幅）不动；新页面一律用该约定。
3. **router + App.vue**：4 tab + 路由重排 + 404 catch-all + `/agent`→`/` redirect。
4. **对话页重写**：`pages/chat/index.vue`（新）+ `api/agent.ts` WS 状态机修复 + 多行输入 + 语音 + 新对话；旧 `pages/agent/index.vue` 删除。
5. **ContextPanel + StockSearch 组件** + 抽屉接线。
6. **详情页动线按钮** + 代码链接化（market/portfolio/watchlist 各页）。
7. **持仓移动卡片化** + 打磨项（深色 K 线/术语/徽章/单位/标题）。
8. **测试**：vitest 新增（WS 状态机：done.text 兜底/断连解锁；search 端点；StockSearch 组件）；playwright e2e 更新关键路径（对话→抽屉→详情→问 AI；移动端 4 tab 导航；401 横幅）；`npm run build` + `vue-tsc` 零错误。

### 3.8 验证标准

- 手机尺寸（375px）完成：对话发问 → 预测抽屉 → 点代码进详情 → 「问 AI」回对话（带预填）→ 加自选。
- 断网测试：对话中途断连 → 输入框解锁 + 错误提示（不卡死）；行情页显示 ErrorState 而非空态。
- vitest 全绿 + build + typecheck；pytest/ruff/mypy 不回归。

---

## 4. Phase 3 — 截图与发版收尾 🟡

- [x] README 补 3 张新界面截图（TUI 对话流、Web 对话页、上下文抽屉），放 `docs/images/`。
- [x] 版本号 v1.2.0（version.py + CHANGELOG [1.2.0] + README 徽章）。
- [x] RELEASE-CHECKLIST 本地门禁（1,555 pytest + ruff + mypy + 40 vitest + build + 3 e2e + audit + migration）。
- [x] PR #28 合入，GitHub CI / Docker release gate 全绿（run `30420741759`）。
- [ ] 打 `v1.2.0` tag 并创建 GitHub release。
- [ ] GitHub release 完成后将本台账归档到 `docs/archive/CONVERSATION-UI-PLAN-2026-07.md`。

## 5. 关键设计决策（已定论，不再回头）

1. **删除 TUI 看板**（不做可选模式）：盯盘需求由欢迎卡 + `/today` + TopBar 承接。双模式是焦点 bug 与心智成本的根因。
2. **预测/信号从 Web 主导航降级为对话抽屉**：记忆系统的证据放在对话发生的场景里，比孤立页面更能传达卖点；路由保留可深链。
3. **错误约定先行**（Phase 1 已落地）：ErrorState≠EmptyState + stores 保留旧数据，是 Web 所有页面的底层约定，新页面必须遵守。
4. **后端架构不动**：Phase 2 只加一个搜索端点；WS 协议不加字段（除非预测计数有现成字段）。
5. **不做**：多用户、TUI K 线全图 sparkline、Web 语音播报、桌面端宽侧边栏以外的导航变体。

## 6. 风险与缓解

| 风险 | 缓解 |
|---|---|
| TUI 大改后真实终端 CJK 渲染差异（SVG 导出验收有伪影） | 用户亲测 `mommy-tui` 后再合并 Phase 1 |
| Web 对话页重写给 e2e 带来大面积选择器失效 | 重写时同步更新 e2e（步骤 3.7-8 内含） |
| `@`/搜股联想数据源覆盖不全（非半导体非自选股） | 联想仅作快捷方式，手输 6 位代码永远可用；后续可加行情快照全表 |
| 老用户找不到看板/预测页 | 欢迎卡与 `/help` 引导；Web `/predictions` `/signals` 路由保留深链 |
