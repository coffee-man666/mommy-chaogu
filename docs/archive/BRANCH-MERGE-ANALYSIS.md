# 分支 Merge 分析报告

> `feature/agent-centric` vs `main`，从功能维度评估两个分支的差异、冲突点与 merge 策略。
>
> 生成时间：2026-07-03

---

## 1. 起点：共同祖先（`bef7af9`）已有的能力

两个分支都从一个**已经能跑的行情监控工具**出发：

| 模块 | 能力 |
|---|---|
| `market_data` | 实时报价 / K线 / 资金流 / 全市场快照（efinance + tencent fallback） |
| `cache` | 5 张表 + 节流 + 失败保留旧数据 |
| `watchlist` | 自选股分组 CRUD |
| `monitor` | snapshot / 持续轮询 |
| `signals` | 7 条内置告警规则（价格阈值 / 资金流 / 量价等） |
| `portfolio` | 持仓表 + 加权平均成本 |
| `push` | Server酱微信推送 + JSON 去重 |
| `semicon` | 半导体产业链 reference（106 只） |
| `flows` | 资金流拉新 + 排行 |
| `report_render` | HTML 报告渲染 |
| `web` | FastAPI + WebSocket |

在此基础上，两个分支往**完全不同的方向**扩展。

---

## 2. `feature/agent-centric`：往「智能」方向走

> 10 commits，+7724 行
>
> 核心理念：**从硬编码 if-else 规则转向 LLM agent 驱动的智能分析**。

### 2.1 AI Agent 对话系统（M7）

- **AgentService** — LLM + 18 个 function-calling 工具的循环引擎
- 支持 DeepSeek / OpenAI / Kimi 三个 provider（统一走 OpenAI SDK）
- Web 聊天页（`💬 问` Tab）+ WebSocket 流式回复
- **评估**：核心差异化能力。让妈妈能直接问「茅台今天怎么了」「帮我分析半导体板块」，而不是看固定页面。无 API key 时优雅降级不崩溃。

### 2.2 Agent 盘中扫描监控（M7 Phase 5）

- **AgentMonitor** — 低频 LLM 扫描循环（3 min 默认）
- 收集自选股报价 + 资金流 → 一次性塞给 LLM（不让 LLM 自己调工具，省 token）
- JSON response mode 强制结构化输出（alerts 列表）
- 复用 SignalNotifier 去重推送
- **评估**：实用。~0.05 元/天的成本很低。但判断质量取决于 prompt 调优和 LLM 的稳定性。

### 2.3 MCP Server（M8）

- stdio 协议，Claude Desktop / Cursor / 任意 MCP client 可直连 18 个工具
- **评估**：技术前瞻性很高，让 mommy-chaogu 变成可被其他 AI 工具调用的「行情数据服务」。当前使用场景偏开发者（团长自己）。

### 2.4 基本面 + 新闻 + 龙虎榜 API（M8）

- `fundamentals_api.py` — PE/PB/PS/ROE/利润率/行业
- `news_api.py` — 新闻搜索 / 公告 / 龙虎榜
- `sector_api.py` — 板块成分股查询
- **评估**：数据维度扩展，填补了「只有量价资金流、没有基本面和新闻」的空白。被包装成 agent 工具，也可独立调用。

### 2.5 组合分析（M8）

- **PortfolioAnalyzer** — 板块集中度 / 相关性矩阵 / 最大回撤 / Sharpe ratio
- **评估**：专业级组合风险分析，比券商 APP 做得深。目标用户偏团长，妈妈大概率看不懂 Sharpe ratio。

### 2.6 回测引擎（M8）

- **BacktestEngine** — 把信号规则回放到缓存的历史数据上
- **评估**：能验证「ratio 阈值设得合不合理」。实战价值取决于缓存里有多少历史数据。

### 2.7 ConversationMemory（M8）

- SQLite 持久化，agent 跨 session 记住对话
- **评估**：体验改善，让 agent 能记住上下文。不复杂但必要。

### 2.8 自定义告警（M8）

- **CustomAlertStore** — 用户自定义价格 / 涨跌幅告警
- CLI：`mommy-watchlist alert add/list/remove`
- **评估**：补了 7 条内置规则不能自定义的缺口。

### 2.9 统一 TOML 配置（M8）

- **AppConfig** — AgentConfig / PushConfig / CacheConfig / MonitorConfig
- `mommy-chaogu config init` 生成模板
- **评估**：工程基础设施，把散落的环境变量收拢。

---

## 3. `main`：往「数据深度 + 开源」方向走

> 7 commits，+7054 行
>
> 核心理念：**深挖业绩数据这条线 + 让代码可以开源给别人看**。

### 3.1 业绩前瞻数据库（earnings preview）

- schema + loader 脚本 + 按主题分组的 41 家公司入库
- 数据：H1 2026（2026 中报）业绩前瞻
- **评估**：**非常实战**。团长自己整理的券商研报前瞻数据，是市场上买不到的私有 alpha。直接回答「这些公司中报会怎样」。

### 3.2 业绩实际值模块（earnings actual）

- `EarningsActual` / `EarningsCalendar` / `EarningsScore` / `EarningsVerdict`
- 5 级 verdict：super_beat / beat / meet / miss / deep_miss
- Service API：pull_actual → score_one → summary
- **评估**：**核心业务逻辑**。actual vs predicted 的比对是这个项目的独特价值——市面上很少有工具能做「实际业绩 vs 研报前瞻」的自动比对打分。

### 3.3 东财业绩数据接入

- **EfinanceEarningsAdapter** — 从东方财富拉实际业绩数据
- **评估**：数据源补齐。没有这个，earnings 模块只有结构没有数据。

### 3.4 资金流 ratio 信号 + 监控 + 日报（flows）

- ratio = main_net / circulating_market_cap（消除大票小票偏差）
- 4 条 ratio-based 规则（5bp WARN / 10bp CRIT）
- FlowMonitor 持续轮询 + 断点续传
- FlowReport 收盘日报（板块汇总 + TOP 10 + 矛盾股清单）
- **评估**：**团长明确要求的**（「阈值不能用绝对值，要用比率」）。日报的「矛盾股」清单（今日流入但 30 日流出）实战价值很高。

### 3.5 业绩手册文档

- `EARNINGS-HANDBOOK.md` — 2026 中报窗口实战手册
- **评估**：团长自己的实战方法论沉淀，不是普通文档。

### 3.6 开源发布准备

- LICENSE / CONTRIBUTING / SECURITY / CHANGELOG / issue 模板 / PR 模板
- **评估**：工程治理，让项目从「私人脚本」变成「可以给别人看的项目」。

### 3.7 ruff format 全量格式化

- 统一代码风格
- **评估**：技术债清理。但这也是 merge 时文件级冲突的主要来源。

---

## 4. 两个方向的本质对比

| 维度 | agent-centric | main |
|---|---|---|
| **核心赌注** | LLM 是更好的分析引擎 | 业绩数据是核心 alpha |
| **用户价值** | 让工具「能对话、能思考」 | 让工具「能看到别人看不到的数据」 |
| **技术壁垒** | Agent 工具链 + MCP 协议 | 私有业绩前瞻数据库 + actual vs predicted 比对 |
| **外部依赖** | 需要 LLM API key | 数据自给自足（本地 DB） |
| **成熟度** | Agent 响应质量取决于 prompt / LLM 波动 | 数据 + 规则是确定性的 |
| **对妈妈的价值** | 间接（更好的分析报告） | 直接（知道持仓股中报会怎样） |
| **对团长的价值** | 高（MCP / agent 是开发乐趣） | 高（业绩 alpha 是投资收益） |

---

## 5. 功能互补性分析

两个分支**功能上完全不冲突**，而是互补的：

| 层 | 来源 | 内容 |
|---|---|---|
| 数据层 | main | 业绩前瞻 + actual vs predicted 比对 |
| 数据层 | main | flows ratio 信号 + 收盘日报 |
| 数据层 | agent-centric | 基本面 / 新闻 / 龙虎榜 API |
| 信号层 | main | ratio-based 确定性规则（4 条） |
| 信号层 | agent-centric | AgentMonitor LLM 软分析 |
| 信号层 | agent-centric | 自定义告警 |
| 分析层 | agent-centric | 18 工具 + AgentService + MCP Server |
| 分析层 | agent-centric | 组合分析（集中度 / 回撤 / Sharpe） |
| 工程层 | main | ruff format + 开源文件 |
| 工程层 | agent-centric | 统一 TOML 配置 + Dockerfile + 回测引擎 |

**结论：两个分支合在一起才是完整产品——main 的业绩数据 + flows ratio 信号 + agent-centric 的 AI 分析层。**

---

## 6. 信号体系的双轨制

两个分支各自引入了不同的信号来源，设计上可以共存：

| 信号来源 | 分支 | 定位 | 触发方式 |
|---|---|---|---|
| `flows/signals.py` ratio 规则 | main | 确定性硬告警 | 5min delta > 5bp/10bp |
| 7 条内置 signals 规则 | 祖先 | 硬告警（价格 / 量价） | 固定阈值 |
| `AgentMonitor` LLM 扫描 | agent-centric | 软分析告警 | LLM 判断 |
| `CustomAlertStore` | agent-centric | 用户自定义 | 用户设定阈值 |

**互补设计**：ratio 规则 + 内置规则跑确定性硬告警（涨停跌停 / 资金异动），AgentMonitor 跑软分析（趋势 / 情绪 / 板块联动），两者不重复。

---

## 7. Merge 冲突点与解决策略

### 7.1 文件级冲突清单

两边都改了 **8 个文件**：

| 文件 | main 改动 | agent-centric 改动 | 冲突风险 | 解决方式 |
|---|---|---|---|---|
| `pyproject.toml` | +3 行 | +10 行 | 🟢 低 | 合并两边的依赖和 entry points |
| `web/app.py` | +4 行 | +5 行 | 🟢 低 | 都是加 router，合并即可 |
| `web/deps.py` | +3 行 | +34 行 | 🟢 低 | 改动区域大概率不重叠 |
| `cache/store.py` | ruff format | +108 行 | 🟡 中 | main 格式化了，需确认 agent 侧接口兼容 |
| `cli.py` | +284 行 | +473 行 | 🔴 高 | 两边各加了大量子命令，手动拼接 |
| `.github/workflows/ci.yml` | +71 行 | +34 行 | 🟡 中 | 以 main 为准（更完整），补 agent 测试目录 |
| `README.md` | 大改 | 大改 | 🟡 中 | 文档手动合 |
| `docs/PROGRESS.md` | 大改 | 大改 | 🟡 中 | 文档手动合 |

### 7.2 新增文件零冲突

两个分支的**新增文件互不重叠**：

- agent-centric 独有：`agent/` 全部 + `backtest/` + `config.py` + `market_data/{news,fundamentals,sector}_api.py` + `portfolio/analysis.py` + `signals/custom_alerts.py` + `web/routes/agent.py` + 前端 agent 页 + `Dockerfile`
- main 独有：`earnings/` 全部 + 开源文件（LICENSE / CONTRIBUTING / SECURITY / CHANGELOG / issue 模板）+ `scripts/` + 各模块的测试文件

### 7.3 关键难点

**难点 1：`cli.py` 子命令合并**

main 新增的子命令：
- `mommy-earnings`（业绩管理）
- 可能有 flows 相关命令

agent-centric 新增的子命令：
- `mommy-agent`（chat / report / tools / scan / monitor）
- `mommy-mcp`（MCP Server）
- `mommy-flows backtest`（回测）
- `mommy-chaogu config init`（配置初始化）
- `mommy-watchlist alert`（自定义告警）

策略：两组子命令并存，手动拼接到同一个 argparse 主入口。

**难点 2：`cache/store.py` 接口兼容**

main 做了 ruff format 全量格式化，可能改了 import 路径或类接口。
agent-centric 的 `agent/tools.py` 直接 `from mommy_chaogu.cache.store import CacheStore`。

策略：merge 后跑 `mypy --strict` + `pytest`，确认 agent 侧调用链不断。

**难点 3：CI 配置**

main 的 ci.yml 更完整（71 行），agent-centric 的较短（34 行）。

策略：以 main 为准，补上 agent-centric 新增的测试目录路径。

---

## 8. 推荐 Merge 策略

### 方向：把 `feature/agent-centric` 合进 `main`

理由：
1. main 有 ruff format 全量格式化，作为基线更干净
2. main 有完整的开源基础设施（LICENSE / CI / 模板）
3. agent-centric 的新增文件全是独立模块，merge 进来不需要改 main 的已有代码

### 步骤

```
1. git checkout main
2. git merge feature/agent-centric
   → 预期 8 个文件冲突
3. 逐个解冲突：
   ├─ pyproject.toml: 合并依赖 + entry points
   ├─ cli.py: 两组子命令并存（最大工作量）
   ├─ cache/store.py: 确认接口兼容
   ├─ app.py / deps.py: 合并 router + 依赖注入
   ├─ ci.yml: 以 main 为准，补 agent 测试目录
   └─ README.md / PROGRESS.md: 文档手动合
4. uv run pytest + ruff check + mypy → 全绿
5. 手动验证：mommy-agent chat / mommy-mcp / mommy-earnings 各跑一次
```

### 验收标准

- [ ] 287+ 测试全通过（agent-centric 287 + main 的 earnings 测试）
- [ ] ruff check 0 errors
- [ ] mypy --strict 0 errors
- [ ] CLI 所有子命令可执行（mommy-agent / mommy-mcp / mommy-earnings / mommy-flows backtest）
- [ ] Web 服务启动正常（含 agent 聊天页）
- [ ] MCP Server 启动正常（stdio）

---

## 9. 风险评估

| 风险 | 概率 | 影响 | 缓解 |
|---|---|---|---|
| cache/store.py 接口不兼容 | 中 | agent 工具链全部失效 | merge 后立即跑 mypy + agent 相关测试 |
| cli.py 合并遗漏子命令 | 中 | 某个 CLI 入口缺失 | 合并后逐个 `--help` 验证 |
| 测试合并后数量不对 | 低 | 回归覆盖不足 | 对比两边测试数，确认无丢失 |
| ruff format 冲突扩散 | 低 | merge 产生大量无意义 diff | 以 main 的格式化为准 |
| agent 依赖的 openai SDK 版本与 main 冲突 | 低 | import 失败 | 检查 pyproject.toml 版本约束 |
