# Mommy Chaogu TUI

> 单屏对话即界面的投研 Agent 终端。`uv run mommy-tui` 启动。

这套 TUI 的目标是对齐 Claude Code / Kimi Code 的交互品质，同时保留 A 股投研
工具箱的特色（红涨绿跌、资金流、策略卡）。本文档是它的功能地图、按键速查、
架构职责与已知边界。

## 功能地图

| 能力 | 说明 | 入口 |
|---|---|---|
| 流式回答 | `stream=True` 逐 delta 渲染，50ms 节流，Markdown 表格/代码块高亮 | 默认 |
| 思考折叠 | 推理模型（deepseek-reasoner 等）思考流式展示，正文到达自动收起为「✻ 思考完成 · N 字」，Enter/点击展开全文 | 自动 |
| 工具轨迹 | 呼吸圈 → 语义摘要行（如「贵州茅台 1680.0 -0.52% · 842ms」）；点击/Enter 展开参数与结果预览 | 自动 |
| 写操作确认 | 保存/归档策略卡、启用监控、告警与自选股增删前内联弹确认条 | 自动 |
| 富卡片 | 报价/资金流/K线/预测/信号等 10 种卡片，工具结果自动渲染 | 自动 |
| 会话恢复 | 启动自动回到上次对话；`/resume` 列表切换、`/new` 开新会话 | 自动 + 命令 |
| 用量可见 | 顶栏常驻会话累计 token（∑ 1.8k tok）；工作行显示轮内实时 token 与耗时 | 自动 |
| 首启引导 | 未配置 Key 时渲染三步引导卡；`uv run mommy setup` 一分钟配好 | 自动 |
| slash 命令 | /today /watch /portfolio /flows /quote /predictions /signals /memory /status /resume /new /help /clear /theme /quit | 手动 |
| @ 联想 | 自选股+产业链+行情缓存模糊匹配，Tab 插入代码 | 手动 |

## 按键速查

- `Enter` 发送（busy 时排队，轮次结束自动发出）
- `Esc` 中断当前轮（保留已流部分）；确认条聚焦时等价「拒绝」
- `↑/↓` 历史 / 候选循环；`Tab` 接受补全；`PgUp/PgDn` 滚动
- `y / n / a` 写操作确认（允许 / 拒绝 / 本会话不再问）
- 点击或 `Enter`：展开工具轨迹详情、思考全文
- `Ctrl+P` 命令面板；`Ctrl+T` 主题选择器（↑↓ 实时预览 / Enter 确认 / Esc 还原；`/theme 名称` 可直接选中）；`Ctrl+C` 双击退出

## 架构（谁负责什么）

```
tui/
├── app.py                  # 轮次生命周期：回调转发、确认等待、自动恢复、用量累加
├── views/chat.py           # 对话流渲染原语（append_*/replay_entries/确认条挂载）
├── services/
│   ├── bootstrap.py        # Services 容器；AgentBridge（含 bind_conversation_memory）
│   ├── session_journal.py  # 会话恢复：agent_memory 只读派生，无指针无新表
│   ├── renderers.py        # 工具结果 → 富卡片分发
│   └── errors.py           # 错误文案友好映射
└── widgets/
    ├── tool_indicator.py   # 工具轨迹：呼吸圈→语义摘要→可展开详情
    ├── thinking.py         # 思考折叠块（活动→完成→展开）
    ├── confirm_bar.py      # 写操作内联确认（y/n/a，决定后定格为审计行）
    ├── working_indicator.py# 轮内 spinner + 实时 token/耗时/重试
    └── top_bar.py          # 指数 · AI 状态 · ∑ 会话 token · 时钟
```

数据契约（跨层）：

- `AgentService.chat(on_chunk/on_thinking/on_tool_call/on_tool_result/on_confirm/on_status)`
  ——UI 是纯订阅者；文本持久化的唯一写入点在 agent 层 `memory.add`，TUI 对
  `agent_memory` 严格只读（会话恢复靠换绑 `SessionMemory` 视图实现续聊）。
- 思考文本（`delta.reason_content`）只进 UI 与 `AgentResponse.reasoning`，
  绝不回流对话历史。
- 确认决定经 `threading.Event` 从主线程回传 worker，等待期间 UI 不阻塞；
  拒绝以 `{"error": "用户拒绝了该操作"}` 回传 LLM，由它向用户解释。

## 已知边界（诚实清单）

- 工具轨迹、富卡片、工作流轮次不持久化——会话恢复重放的是纯文字骨架。
- 被 Esc 中断的轮次双方都不入库（agent 层防污染语义），恢复后会有话题断层。
- 所有 TUI 历史默认在 `default` 会话里；`/new` 之后才按 `tui-<时间戳>` 分段。
- 思考折叠依赖 provider 返回 `reason_content`；普通模型整轮不出现该块。
- 确认条覆盖的写操作白名单见 `agent/service.py` 的
  `CONFIRM_ALWAYS` / `CONFIRM_BY_ACTION`；MCP 宿主不受影响（不传 on_confirm
  即为旧行为）。

## 验收方式

```bash
uv run pytest -m "not network"   # 全量离线用例（TUI 相关见 tests/test_tui_*.py）
uv run mommy-tui                 # 亲手跑一轮：提问 → 轨迹 → 确认 → 恢复
```

最近一次真机验收记录（含逐步骤证据与遗留观察项）：
`docs/TUI-ACCEPTANCE-2026-08-27.md`；更早的体检见
`docs/TUI-AUDIT-2026-07-25.md`。
