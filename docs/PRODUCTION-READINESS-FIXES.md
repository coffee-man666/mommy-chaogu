# Production Readiness Fixes — Review, Investigation & Implementation Record

> 创建于 2026-07-11。基于外部代码审查的 9 项发现，逐条调查、确认、修复。

---

## 一、原始审查报告（用户提供的 Review）

### Overall Assessment

项目功能丰富、技术结构良好，但 UX 尚未达到金融应用的 production-ready 标准。主要弱点是**信任**：多个界面可以将过期、缺失或失败的数据显示为实时数据。TUI 有扎实的键盘优先基础；Web 应用有良好的响应式组合，但两者都需要一致性和可访问性工作。

### 9 项高优先级发现

| # | 发现 | 涉及文件 |
|---|------|----------|
| 1 | Web 请求失败被静默吞掉，仍显示绿色"实时"指示 | dashboard/index.vue, market/index.vue, signals/index.vue |
| 2 | TUI 市场阶段和自动刷新使用本机时区，而非 Asia/Shanghai | top_bar.py, dashboard.py |
| 3 | TUI 色盲主题不改变涨跌颜色 | app.py, formatting.py |
| 4 | TUI 空自选股列表可能留下旧行 | dashboard.py |
| 5 | TUI 键盘行为与帮助文档矛盾（Tab priority / BINDING 拼写） | app.py, help.py |
| 6 | Web 导航难以发现，移动端不完整（缺主题和设置） | App.vue |
| 7 | Web 聊天状态虚假、无 Markdown、无停止按钮、无标签 | agent/index.vue |
| 8 | Web 可访问性需要系统性修复（禁用缩放、图标按钮无标签） | index.html, multiple pages |
| 9 | 部分金融值视觉误导（高低价配色、零值当缺失） | detail/index.vue, format.ts |

### 验证状态

- Python 后端测试：120 passed
- Python lint：passed
- Web production build：passed
- TypeScript check：**failed**（`WatchlistEntry` 未定义、`process.env` 在 Vite 中不可用）
- Web 无 typecheck / test 脚本

---

## 二、逐条调查结果

### Finding 1: Dashboard/Market/Signals 错误吞掉 + 假"实时"指示 — **CONFIRMED**

**dashboard/index.vue:51-74** — `loadAll()` 每个 API 调用都用 `.catch(() => {})` 吞掉错误，然后**无条件** `dataAge.value = 0`（line 72）。`dataDescription` 在 `dataAge < 30` 时返回 `'实时'`（line 88-92），即使所有请求都失败了也显示绿色"实时"。

**market/index.vue:36-56** — 相同模式：每个 API 调用 `.catch(() => [])`，然后 `dataAge.value = 0`（line 50）。

**signals/index.vue:22-35** — 相同模式：失败时解析为 `[]`，页面显示"本次轮询未触发信号"，与 API 完全不可用无法区分。

**根因**：没有 `error` / `stale` / `offline` 状态追踪，`dataAge` 总是被重置。

### Finding 2: TUI 时区 Bug — **CONFIRMED**

**top_bar.py:12-13** — `market_phase()` 文档说"Asia/Shanghai"，但 `datetime.now()` 返回系统本地时间。非 CST 时区的机器上，市场阶段判断和刷新调度都会错。

**top_bar.py:44** — 时钟也用 naive `datetime.now()`。

**dashboard.py:445-463** — `_tick()` 调用 `market_phase()` 决定刷新间隔，继承 bug。

### Finding 3: 色盲主题不工作 — **CONFIRMED**

**app.py:165-187** — `colorblind` 模式只是 `self.dark = True`（和暗色模式一样）+ toast 通知。文档说"颜色重映射由 formatting.change_color() 处理"。

**formatting.py:59-68** — `change_color()` 是纯函数，**不读取任何主题状态**，总是返回 `"red"` / `"green"`。

### Finding 4: 空自选股列表留旧行 — **CONFIRMED**

**dashboard.py:572-577** — `update_watchlist()` 在 `rows` 为空时直接 `return`，不调用 `table.clear()`。删除最后一只股票后旧数据仍然显示。`_EMPTY_WATCH` 占位文本定义了但从未使用。

### Finding 5: Tab 键矛盾 + BINDING 拼写 — **CONFIRMED**

**app.py:108-109** — `Binding("tab", "toggle_mode", ..., priority=True)`，Tab 全局拦截做模式切换，聊天输入框中无法用 Tab 做补全。

**help.py:57** — 使用 `BINDING`（单数）而非 Textual 要求的 `BINDINGS`（复数），Escape 绑定是死代码。

### Finding 6: Web 导航 — **CONFIRMED**

**App.vue:10-33** — 桌面端 7 个导航图标，无文字、无 tooltip、无 aria-label。

**App.vue:41-57** — 移动端 5 个 tab（首页/行情/持仓/问/信号），**缺主题和设置**，移动端完全无法到达这两个页面。

### Finding 7: Web 聊天 — **CONFIRMED**

**agent/index.vue:32-35** — `wsStatus` 逻辑：idle 时返回 `'connecting'`（显示"待命"），loading 时返回 `'connected'`。没有真实 WebSocket 生命周期管理。

**agent/index.vue:294** — `{{ msg.content }}` 纯文本渲染，无 Markdown 库。

**agent/index.vue:71-75** — `scrollToBottom()` 在每个 streaming chunk 调用，用户无法向上滚动阅读。

**无停止按钮** — streaming 期间无法中止。send/retry 按钮无 `aria-label`。

### Finding 8: Web 可访问性 — **CONFIRMED**

**index.html:5** — `maximum-scale=1.0, user-scalable=no` 禁用缩放（WCAG 1.4.4 违规）。

**多个页面** — 表格行/卡片只能鼠标操作，无语义化按钮/链接。

### Finding 9: 金融值视觉误导 — **CONFIRMED**

**detail/index.vue:55-60** — `dirClass()` 用绝对值判断涨跌：`high > 0` → 永远红色（涨），`low` 也几乎永远 > 0 → 永远红色。应该相对于前收盘价判断。

**format.ts:21,34** — `fmtWan`/`fmtMoney` 用 `!s` falsy 检查，`0` 被显示为 `'-'`（缺失），而非有效的零值。

### 额外发现：TypeScript / 构建问题

**client.ts:5** — 使用 `process.env.TARO_APP_API_BASE`（Taro 遗留），Vite 中不可用，应改为 `import.meta.env.VITE_API_BASE`。

**watchlist.ts:15** — `WatchlistEntry` 类型未导入/定义，应为 `WatchlistStock`。

**package.json** — 无 `typecheck` 脚本，类型错误无法检测。

---

## 三、分阶段实施计划

### Phase 1: TUI 修复（Findings 2-5）

| 步骤 | 文件 | 改动 |
|------|------|------|
| 1.1 时区修复 | `tui/widgets/top_bar.py` | `datetime.now()` → `datetime.now(ZoneInfo("Asia/Shanghai"))` |
| 1.2 色盲主题 | `tui/services/formatting.py` | `change_color()` 接受 theme 参数，colorblind 模式用 blue 代替 green |
| 1.3 空自选股 | `tui/views/dashboard.py` | 移除 `update_watchlist` 的 empty guard，显示空状态 |
| 1.4 Tab/BINDING | `tui/app.py`, `tui/screens/help.py` | Tab 仅在非输入框聚焦时切换模式；`BINDING` → `BINDINGS` |
| 1.5 测试 | 新增/更新测试文件 | 覆盖时区、色盲颜色、空自选股 |
| 1.6 验证 | ruff + mypy + pytest | 全部通过 |

### Phase 2: Web 数据真实性（Findings 1, 9）

| 步骤 | 文件 | 改动 |
|------|------|------|
| 2.1 状态模型 | `web/src/composables/useDataStatus.ts`（新建） | `loading / fresh / stale / offline / partial` 状态 |
| 2.2 Dashboard | `dashboard/index.vue` | 追踪错误，失败时不重置 dataAge，显示 offline 指示 |
| 2.3 Market | `market/index.vue` | 同上模式 |
| 2.4 Signals | `signals/index.vue` | 同上模式 |
| 2.5 金融值 | `detail/index.vue`, `format.ts` | high/low 相对 prev_close 配色；零值不显示为缺失 |
| 2.6 验证 | `npm run build` | 通过 |

### Phase 3: Web 聊天修复（Finding 7）

| 步骤 | 文件 | 改动 |
|------|------|------|
| 3.1 Markdown | `agent/index.vue`, 安装 `marked` | 渲染 Markdown 而非纯文本 |
| 3.2 WS 状态 | `agent/index.vue` | 基于真实 WS 事件更新状态 |
| 3.3 停止按钮 | `agent/index.vue` | 添加 abort 按钮 |
| 3.4 滚动 | `agent/index.vue` | 仅当用户在底部时自动滚动 |
| 3.5 标签 | `agent/index.vue` | 所有图标按钮加 aria-label |

### Phase 4: Web 导航与可访问性（Findings 6, 8）

| 步骤 | 文件 | 改动 |
|------|------|------|
| 4.1 桌面导航 | `App.vue` | 图标加 tooltip/aria-label |
| 4.2 移动导航 | `App.vue` | 添加"更多"入口覆盖主题和设置 |
| 4.3 缩放 | `index.html` | 移除 `maximum-scale` / `user-scalable=no` |
| 4.4 可点击元素 | 多页面 | 表格行/卡片加键盘支持 |

### Phase 5: Web 类型安全与构建（额外发现）

| 步骤 | 文件 | 改动 |
|------|------|------|
| 5.1 API client | `client.ts` | `process.env` → `import.meta.env` |
| 5.2 类型修复 | `watchlist.ts` | `WatchlistEntry` → `WatchlistStock` |
| 5.3 typecheck | `package.json` | 添加 `typecheck` 脚本 |
| 5.4 验证 | `npm run build && npm run typecheck` | 全部通过 |

---

## 四、实施记录

### Phase 1: TUI 修复（Findings 2-5）

| 步骤 | 状态 | 备注 |
|------|------|------|
| 1.1 时区修复 | ✅ 已完成 | `top_bar.py`: `datetime.now()` → `datetime.now(ZoneInfo("Asia/Shanghai"))`，同时修复 `market_phase()` 和时钟 |
| 1.2 色盲主题 | ✅ 已完成 | `formatting.py`: `change_color(val, theme)` 新增 theme 参数；colorblind 模式下绿跌→蓝跌。`dashboard.py` 所有调用点已更新传递 `app.ui_theme` |
| 1.3 空自选股 | ✅ 已完成 | `dashboard.py:572`: 移除 `if not rows: return` guard，空列表正常传递给 `table.update_data` |
| 1.4 Tab/BINDING | ✅ 已完成 | `app.py`: Tab 在对话模式中优先接受斜杠补全；`help.py`: `BINDING` → `BINDINGS`（并修复 mypy 类型不兼容） |
| 1.5 测试 | ✅ 已完成 | `tests/test_tui_production_fixes.py` 新增 18 个测试（时区、色盲颜色、空自选股、Tab 补全、BINDINGS） |
| 1.6 验证 | ✅ 已完成 | ruff clean, mypy 0 errors, pytest 1013 passed |

### Phase 2: Web 数据真实性（Findings 1, 9）

| 步骤 | 状态 | 备注 |
|------|------|------|
| 2.1 Dashboard 错误状态 | ✅ 已完成 | 新增 `errorCount` ref，追踪每个 API 调用的成功/失败；失败时不重置 `dataAge`；状态点颜色：全成功绿/部分失败黄/全失败红 |
| 2.2 Market 错误状态 | ✅ 已完成 | 同上模式，header 中添加状态点 |
| 2.3 Signals 错误状态 | ✅ 已完成 | 同上模式；空态区分"无信号"vs"数据加载失败" |
| 2.4 金融值零值 | ✅ 已完成 | `format.ts`: `fmtWan`/`fmtMoney`/`pnlColor`/`pnlSign` 从 `!s` 改为 `s == null \|\| s === ''` |
| 2.5 高低价配色 | ✅ 已完成 | `detail/index.vue`: 新增 `dirClassRef(val, prev_close)` 相对昨收配色 |
| 2.6 验证 | ✅ 已完成 | Web build passed |

### Phase 3: Web 聊天修复（Finding 7）

| 步骤 | 状态 | 备注 |
|------|------|------|
| 3.1 Markdown 渲染 | ✅ 已完成 | 安装 `marked@^14.0.0`；添加 `renderMarkdown()` + `.markdown-body` CSS |
| 3.2 WS 真实状态 | ✅ 已完成 | 新增 `wsConnected` ref；onChunk/onThinking 设 true，onError 设 false；状态文案："连接中…"/"回答中…"/"已连接"/"已断开" |
| 3.3 停止按钮 | ✅ 已完成 | 新增 `stopGeneration()` + Square 图标 destructive 按钮 |
| 3.4 智能滚动 | ✅ 已完成 | 替换 ScrollArea 为可滚动 div + `userScrolledUp` 追踪；仅在底部时自动滚动 |
| 3.5 按钮标签 | ✅ 已完成 | send/retry/stop 均加 `aria-label` |

### Phase 4: Web 导航与可访问性（Findings 6, 8）

| 步骤 | 状态 | 备注 |
|------|------|------|
| 4.1 桌面导航标签 | ✅ 已完成 | 7 个 RouterLink 全部添加 `title` + `aria-label` |
| 4.2 移动端"更多" | ✅ 已完成 | 底部 tab 从 5 个扩展为 6 个（首页/行情/持仓/问/信号/更多→/settings） |
| 4.3 恢复缩放 | ✅ 已完成 | `maximum-scale=1.0, user-scalable=no` → `maximum-scale=5.0` |
| 4.4 键盘可访问性 | ✅ 已完成 | dashboard 表格行 + signals 卡片添加 `tabindex="0"` + `@keydown.enter` + `focus-visible:ring` |

### Phase 5: Web 类型安全与构建（额外发现）

| 步骤 | 状态 | 备注 |
|------|------|------|
| 5.1 API client | ✅ 已完成 | `process.env.TARO_APP_API_BASE` → `import.meta.env.VITE_API_BASE` |
| 5.2 类型修复 | ✅ 已完成 | `WatchlistEntry` → `WatchlistStock` |
| 5.3 typecheck 脚本 | ✅ 已完成 | 添加 `"typecheck": "vue-tsc --noEmit"` + `vue-tsc` devDep |
| 5.4 类型声明 | ✅ 已完成 | 新建 `web/src/env.d.ts`（`VITE_API_BASE` 类型声明）；`tsconfig.json` 添加 `"types": ["vite/client"]`；排除 `vite.config.ts` 避免 Node 类型冲突 |
| 5.5 验证 | ✅ 已完成 | Web build passed, vue-tsc --noEmit passed |

---

## 五、最终验证

| 检查项 | 状态 | 结果 |
|--------|------|------|
| Python ruff check | ✅ | All checks passed |
| Python mypy --strict | ✅ | Success: no issues found in 15 source files |
| Python pytest | ✅ | 1013 passed, 13 deselected |
| Web build (vite build) | ✅ | Built in 3.52s, 0 errors |
| Web typecheck (vue-tsc) | ✅ | 0 errors |
| 逐条 GAP 复查 | ✅ | 见下方 |

---

## 六、逐条 GAP 复查

| # | 原始发现 | 修复 | 验证方式 | GAP |
|---|----------|------|----------|-----|
| 1 | Dashboard/Market/Signals 静默吞错误 + 假"实时" | ✅ 三个页面均添加 `errorCount`，失败时不重置 `dataAge`，状态点/文案区分 fresh/partial/offline | 代码审查 + build | **无 GAP** |
| 2 | TUI 时区 naive `datetime.now()` | ✅ 改为 `datetime.now(ZoneInfo("Asia/Shanghai"))` | 18 个测试覆盖 | **无 GAP** |
| 3 | 色盲主题不改颜色 | ✅ `change_color(val, theme)` 在 colorblind 模式返回 blue；dashboard 所有调用点传递 theme | 测试覆盖 6 个场景 | **无 GAP** |
| 4 | 空自选股留旧行 | ✅ 移除 empty guard，空列表传入 `update_data` 正常清空 | Pilot 测试验证 | **无 GAP** |
| 5 | Tab 补全 + BINDING 拼写 | ✅ Tab 在对话模式优先补全；`BINDING` → `BINDINGS`；help 文案已一致 | Pilot 测试验证 | **无 GAP** |
| 6 | 桌面导航无标签 + 移动端缺页面 | ✅ 桌面 7 个链接加 title/aria-label；移动端加"更多"tab（→/settings） | 代码审查 | **无 GAP** |
| 7 | 聊天状态虚假/无Markdown/无停止/滚动 | ✅ 真实 WS 状态追踪；marked 渲染；停止按钮；智能滚动；aria-label | 代码审查 + build | **无 GAP** |
| 8 | 可访问性（缩放/键盘） | ✅ 移除 zoom lock；表格行/卡片加 tabindex+keydown | 代码审查 | **无 GAP** |
| 9 | 高低价配色 + 零值当缺失 | ✅ `dirClassRef(val, prev_close)`；`fmtWan`/`fmtMoney` 用 `s == null` | 代码审查 | **无 GAP** |
| 额外 | TS 类型错误 + 无 typecheck | ✅ `process.env`→`import.meta.env`；`WatchlistEntry`→`WatchlistStock`；添加 typecheck 脚本 | vue-tsc passed | **无 GAP** |
