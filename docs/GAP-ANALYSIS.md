# GAP 分析：当前实现 vs 需求文档

> 审计日期: 2026-07-11
> 基于分支: `tui-overhaul`
> 参考文档: `mommy_ux_review.md` (19 条用户建议) + `tui-design.md` (TUI 设计规格)

---

## 一、UX Review GAP（19 条）

| # | 建议 | 状态 | 说明 |
|---|------|------|------|
| 1 | Docker 一键启动 | ✅ | docker-compose.yml + Dockerfile 多阶段 |
| 2 | .env 交互式引导 | ✅ | mommy --setup + TUI 启动前检测 |
| 3 | README Docker 优先 | ✅ | Docker 放首，uv 折叠 |
| 4 | 统一入口 mommy | ✅ | mommy watchlist list 直接可用 |
| 5 | NLRouter 命中反馈 | ✅ | [匹配: ...] / [转交 AI 助手] |
| 6 | --help 使用示例 | ✅ | 所有 parser 有 EXAMPLES epilog |
| 7 | 工具调用可视化 | ✅ | CLI 🔧 调用 + --verbose |
| 8 | mommy memory | ✅ | stats/events/predictions/knowledge/history |
| 9 | WS 连接状态指示器 | ✅ | Web agent 页 🟢🟡🔴 |
| 10 | 移动端底部 Tab | ✅ | 首页/行情/持仓/AI/信号 |
| 11 | WS 断线重连 | ✅ | 初始连接失败重试 1 次 |
| 12 | TUI 文档 | ✅ | README + 场景指南 |
| 13 | TUI 启动前配置 | ✅ | check_and_run_setup() |
| 14 | 数据来源标注 | ✅ | format_source_label() |
| 15 | LLM 错误分类 | ✅ | rate limit/quota/auth 分别提示 |
| 16 | 多推送渠道 | ⚠️ 部分 | Protocol 就绪，仅 Server酱实现 |
| 17 | README 精简 | ✅ | 206 行 |
| 18 | Issue 模板 + Discussions | ✅ | .yml 模板 + Discussions 链接 |
| 19 | GIF/截图演示 | ❌ 未做 | 无演示 GIF |

---

## 二、TUI Design Doc GAP（28 项检查点）

### §3 信息架构 (3 项)
| # | 需求 | 状态 |
|---|------|------|
| 1 | TopBar (品牌+连接点+来源+阶段+时钟) | ✅ |
| 2 | ContentSwitcher 双视图不销毁 | ✅ |
| 3 | Footer 按键提示 | ✅ |

### §4 交互 (3 项)
| # | 需求 | 状态 | GAP |
|---|------|------|-----|
| 4 | Tab priority binding | ✅ | |
| 5 | r/?/^p/^q 全局键 | ✅ | |
| 6 | 对话交互 (Enter/↑↓/1-7/^L/Esc) | ✅ | |
| 7 | 看板交互 (1-4/o/a/x/s/Enter) | ⚠️ | j/k/g/G vim 键未实现 |

### §5 数据流 (4 项)
| # | 需求 | 状态 |
|---|------|------|
| 8 | 零 HTTP 进程内直连 | ✅ |
| 9 | Thread workers | ✅ |
| 10 | 自适应轮询 | ✅ |
| 11 | AgentBridge | ✅ |

### §6 视图 (5 项)
| # | 需求 | 状态 | GAP |
|---|------|------|-----|
| 12 | ChatView 五种消息组件 | ⚠️ | ToolPanel 不是 Collapsible；AssistantMsg 用 Static 不是 Markdown |
| 13 | WatchTable cell 级更新 | ❌ | 每次 clear()+add_row() 全量重建 |
| 14 | SummaryCards 三联 | ⚠️ | 当日/累计盈亏用了同一个值 |
| 15 | StockDetailScreen 懒加载 | ✅ | |
| — | StockDetailScreen 三栏布局 | ❌ | 实际纵向堆叠 |

### §8 视觉 (2 项)
| # | 需求 | 状态 | GAP |
|---|------|------|-----|
| 16 | 设计 token + 双重编码 | ⚠️ | TCSS 无 $up/$down 变量 |
| 17 | TCSS 布局规则 | ⚠️ | ToolPanel border 指向错误 |

### §9 错误处理 (2 项)
| # | 需求 | 状态 |
|---|------|------|
| 18 | 无 key HintCard | ✅ |
| 19 | 数据源失败 🟡 降级 | ✅ |

### §11 可测试性 (3 项)
| # | 需求 | 状态 |
|---|------|------|
| 20 | FakeServices 注入 | ✅ |
| 21 | Pilot 冒烟测试 | ✅ |
| 22 | 格式化测试 | ✅ |

### 专项缺失 (6 项)
| 特性 | 状态 |
|------|------|
| MOMMY_TUI_REFRESH 环境变量 | ❌ |
| Markdown widget 渲染 Agent 回复 | ❌ |
| ToolPanel 可折叠 | ❌ |
| WatchTable cell diff | ❌ |
| StockDetailScreen 三栏布局 | ❌ |
| light/colorblind 主题 | ❌ |

---

## 三、修复优先级

| 优先级 | GAP | 工作量 |
|--------|-----|--------|
| P0 | Markdown widget 渲染 Agent 回复 | 小 |
| P0 | WatchTable cell 级更新（防闪烁） | 中 |
| P0 | j/k/g/G vim 键 | 小 |
| P1 | ToolPanel Collapsible | 小 |
| P1 | SummaryCards 当日 vs 累计盈亏 | 小 |
| P1 | MOMMY_TUI_REFRESH 环境变量 | 小 |
| P1 | TCSS design token 变量 | 小 |
| P2 | StockDetailScreen 三栏布局 | 中 |
| P2 | 多推送渠道 (Bark) | 中 |
| P2 | light/colorblind 主题 | 中 |
| P3 | GIF/截图演示 | 外部资源 |
