# TUI 真机验收记录（Kimi Code 级交互升级）

> 日期: 2026-08-27（验收执行于 2026-08-26 晚间）
> 范围: 真实 Terminal.app 中运行 `uv run mommy-tui`，走通「启动自动恢复 → 提问流式
> 回答 → 思考折叠展开 → 工具轨迹展开 → 写操作确认(y/n) → /resume /new」整条链路
> 方法: 本地 OpenAI 兼容 mock 网关（仅标准库 SSE）+ AppleScript TTY 注入 + Terminal
> `contents of tab` 屏显文本读取（验收时屏幕处于锁定状态，无法截屏，全部证据取自
> 真实终端渲染文本本身）
> 提交基线: 82be99b → ffec167 → f1dec84 → 0cf3cfb（验收后）
> 测试基线: 2,219 → 2,222 passed (offline) / mypy --strict 215 文件 / ruff clean

---

## TL;DR

真机全链一次走通，其中工具调用打的是**真实行情数据源**（真实现价 1291.01，
非脚本数据）、写操作确认后策略卡**真实落库**（strategy_cards + revisions 两行
验证）。链路中发现 1 个键盘可用性缺口（Tab 被优先绑定吞掉，键盘用户无法展开
思考块/工具轨迹），已按 TDD 修复并回归锁定（`0cf3cfb`）。

## 验收环境与方法

- **隔离**：`MOMMY_DATA_DIR=/tmp/mommy_demo_data`（种子 4 条历史），未触碰真实数据。
- **LLM 通路**：本机无 API Key，起本地 mock 网关 `127.0.0.1:8399`（OpenAI 兼容
  SSE：reason_content delta → tool_calls → content delta → usage 尾块；非流式
  回退路径也实现）。为此在 `llm.py` 新增 `{PROVIDER}_BASE_URL` 环境覆盖。
  **模型输出是脚本回放，其余全真**（真实终端 / 真实 App / 真实网络栈 / 真实
  行情数据源 / 真实 SQLite）。
- **驱动与取证**：macOS 授权（辅助功能 + 屏幕录制）已授，但验收时屏幕锁定且
  Terminal 窗口不在当前 Space，键鼠注入被 window_offscreen 拒绝。改用两条
  不依赖屏幕的通道：
  - 输入：`osascript` `do script … in window id N`（文本注入运行中 TUI 的 TTY）；
  - 取证：`get contents of tab 1 of window id N`（终端可见区全文）。
- 无头预验证：先以真 `AgentService` + mock adapter 打 mock 网关跑通
  reasoning/tool_calls/usage，再上真机（`tests/test_agent` 同款 mock 模式）。

## 链路步骤 × 证据（终端屏显文本摘录）

| # | 步骤 | 实际发生（屏显摘录） |
|---|---|---|
| 1 | 启动自动恢复 | `AI🟢 deepseek`；`↩ 已恢复会话 default · 4 条（/new 开新对话 · /resume 切换）`，种子问答重放。**重启 3 次均恢复**，含前一轮新增内容（跨重启） |
| 2 | 提问流式回答 | 「帮我看下贵州茅台最新行情…」→ 逐字流式：结论 + bullet + Markdown 表格 + ```python 代码块；收尾 `✻ 3.5s · ↓ 3.6k tokens` |
| 3 | 工具真实执行 | `⏺ 查行情(code=600519)` → `⎿ 贵州茅台 1291.01 -0.90% · 3.8s`——**真实行情数据源**（脚本答案里的 1680 是回放文本，工具数据是真实市价），报价卡渲染真实 OHLC/换手 0.18%/量比 0.80 |
| 4 | 顶栏会话用量 | `指数 — · AI🟢 deepseek · ∑ 3.6k tok · 14:43:56`（每轮累加常驻） |
| 5 | 思考折叠展开 | `✻ 思考完成 · 23 字（Enter 展开查看）` → Tab×2 聚焦 + Enter → 展开全文「先查最新报价和资金面，再结合位置给可操作结论。」 |
| 6 | 工具轨迹展开 | 焦点 + Enter → 详情展开完整真实结果 JSON（`pe: 18.13`、`total_market_cap: 1.61e12`、真实 ISO 时间戳） |
| 7a | 确认 **n** 拒绝 | 确认条出现（`⏸ 等待确认 · y 允许 · n 拒绝 · a 本会话不再询问`）→ `n` → 审计行 `⏸ 保存策略卡(user_confirmed=True) ✗ 已拒绝` + 黄圈 `⎿ 已拒绝（用户）`；工具未执行，LLM 收到拒绝 JSON 后转为向用户说明 |
| 7b | 确认 **y** 放行 | 再次提问 → `y` → 审计行 `✓ 已允许`（含 confirmation_note 参数）→ 工具真实执行 `⎿ {"saved":true,"strategy_id":"strategy_896db08…" · 5ms` → **DB 验证**：`strategy_cards` + `strategy_card_revisions` 各一行落库 |
| 8 | /resume | 列表卡 `📜 历史会话 1. default · 14 条 · 08-27 06:55 · 把这条观察存成策略卡…`（条数与最近话题预览正确） |
| 9 | /new | `⚠ 已开新会话 tui-20260826-235544-92b3（旧会话保留在 /resume 列表）` |

## 发现并修复的问题（0cf3cfb）

1. **Tab 被优先绑定吞掉（键盘可用性缺口）**：`ChatView` 的
   `Binding("tab", "accept_completion", priority=True)` 在无补全候选时仍消费
   按键，键盘用户永远无法聚焦思考块/工具轨迹（只能靠鼠标）。修复：无候选时
   `action_focus_next()` 把焦点让给对话流（先落 `#chat-log` 滚动容器，再一次
   Tab 进入具体 widget——浏览器式容器导航）。回归测试
   `tests/test_tui_thinking.py::TestKeyboardFocusCycle`。
2. **新增 `{PROVIDER}_BASE_URL` 环境覆盖**（`agent/llm.py`）：自建网关 / 本地
   代理 / OpenAI 兼容网关场景标准能力；默认仍取 provider 配置表，空串视为未
   设置。回归测试 `tests/test_agent/test_service.py::TestBaseUrlOverride`。

## 验收方法学记录（下次真机验收可复用）

- 屏幕锁定 / 窗口不在当前 Space 时，CUA 键鼠注入全部 fail-closed
  （`window_offscreen`）；`do script` + `contents of tab` 是不依赖屏幕的
  完整替代通道，`caffeinate -u` 只能唤醒显示器不能解锁会话。
- **焦点漂移**：TTI 注入前必须确认 TUI 内焦点在输入框——焦点停在
  ToolIndicator/ThinkingBlock 时，注入的文本会被 widget 吞掉（仅 y/n/a/Enter
  有绑定）。`Shift+Tab`(0x19) 可回退焦点但圈长不定；**重启 TUI 是确定性的
  焦点复位手段**（启动焦点必在输入框），且顺带多验证一次自动恢复。
- mock 网关脚本化场景判定：`messages` 含 `role=="tool"` → answer；末条 user
  含「策略/存」→ save；否则 → quote。注意后台记忆提取（`已记住本轮要点`）
  也会发无 `on_chunk` 的非流式请求，属正常噪声。

## 验收中发现、未在本次处理的观察项（诚实清单）

| 观察 | 判断 | 处置建议 |
|---|---|---|
| TopBar `指数 —` + 日志 `fetch indexes failed: Expecting value` | 本机当前无外网/接口返回非 JSON，降级显示正常（未崩溃） | 已有降级路径；外网恢复即自愈，无需处理 |
| `extractor WARNING: LLM 返回无效 JSON` | 后台记忆提取对 mock 的非 JSON 回答优雅降级，仅警告 | 真实模型下应少发；可观察，不改 |
| 键盘展开需两次 Tab（先落 chat-log 容器） | 容器导航惯例，与浏览器一致 | 保持；如嫌多可后续支持 Ctrl+G 直达 |
| 策略卡首次 `y` 后报 `title：Field required` | mock 脚本卡片缺必填字段，StrategyStore 真实校验如实拒绝并回传 LLM——**这是校验生效的正确行为** | 已补全 mock 卡片字段后重验通过 |
| 屏幕锁定期间无截图证据 | 证据以终端 `contents` 屏显文本为准（渲染管线真实） | 用户解锁后可按本文步骤亲手复跑 |

## 关联

- 功能与架构说明：`docs/TUI.md`
- 上一次 TUI 体检：`docs/TUI-AUDIT-2026-07-25.md`（12 项修复已全部复查通过）
- 本轮提交：`82be99b`（agent 契约：on_confirm + reasoning 流解析）、
  `ffec167`（TUI 交互全套）、`f1dec84`（文档）、`0cf3cfb`（真机反馈修正）
