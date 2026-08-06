# 更新日志 (Changelog)

> mommy-chaogu 的所有重要变更记录。
> 格式基于 [Keep a Changelog](https://keepachangelog.com/)。

---

## [Unreleased]

### 改进

- **REPL 欢迎页 logo**——块体字母 M 加紫→青水平渐变，下方配红绿迷你 K 线和琥珀色
  趋势箭头；欢迎面板边框提亮，深色终端下更清晰。

## [1.3.0] - 2026-08-04

> 本节汇总自 1.2.0（2026-07-28）以来主分支已完成、但尚未单独发布版本的变更。

### 新增

- **一行安装**——macOS / Linux 可通过 GitHub `install.sh` 安装；脚本自动准备隔离的
  Python 3.12 + uv 工具环境，支持重复运行更新，并在结束前验证 `mommy` 入口。
- **安装包内置 Web 前端与数据资产**——Vue 生产构建及业绩、产业链参考数据随 Python
  wheel 发布；通过 `uv tool install` 安装后运行 `mommy web` 不再退化为仅 API。
- **外部 Coding Agent 接入**——`mommy connect claude|kimi` 自动注册本地 stdio MCP、
  安装 `mommy-research` Skill 并执行连通性测试；新增 `status` / `test` / `disconnect`，
  同时保留用户已有的第三方 MCP 配置和被修改过的 Skill。
- **确定性的 MCP 投研工具**——新增市场、个股、板块、资金流、持仓和结论写回等高层
  工具；支持 MCP 2.0 连接，外部 Agent 负责最终推理，不再嵌套调用项目内 LLM。
- **Web 引导式配置**——新增 `/setup` 流程，逐步完成 Provider 选择、Key 验证和可选
  微信扫码，降低首次使用门槛。
- **个股决策上下文**——在一个视图聚合行情、资金流、业绩和预测信息，并支持从上下文
  直接进入 AI 对话或加入自选。
- **预测证据与个股回测**——预测卡片增加触发时的行情证据链；新增单只股票的历史预测
  回测流程和 Web API，用于评估预测表现。
- **共享用户偏好**——主题、风险偏好等设置由服务端统一保存，可在不同设备和入口之间
  保持一致。

### 改进

- **投研工作台导航**——统一 baskets 与 today 的决策摘要，完善首页、主题、个股详情、
  预测和设置页面之间的联动，减少重复查看和上下文切换。
- **CLI 助手体验**——升级默认自然语言入口、交互式 REPL 和提示辅助；补充品牌标识，
  并同步 CLI、TUI 与 Web 的使用引导。
- **发布与回归验证**——增加安装脚本、静态资源、MCP 接入、配置向导、WebSocket、偏好、
  篮子、预测证据和回测等单元、API 及端到端测试；CI 校验前端源码与安装包内静态资源
  保持一致。

### 变更

- **移除 Nova Bridge provider**——该 provider 已废弃，不再出现在配置向导和支持列表中。

### 修复

- **CLI 首字符吞输**——修复首次显示提示时光标位置异常导致输入的第一个字符被删除。
- **预测附件与偏好迁移**——强化预测证据的持久化写入，修正偏好 schema 迁移的边界情况。
- **主题与行情缓存**——主题页报价改为批量获取，限制缓存 K 线条目数量，避免重复请求和
  缓存无界增长。
- **安装与发布产物**——收敛安装脚本输出；修复前端源码构建结果与已提交静态资源不同步
  的问题。

### 安全

- **MCP 默认最小权限**——默认启用 `market-only`，不暴露持仓、自选、告警和历史记忆；
  只有用户显式选择 `--profile personal` 才开放个人数据及写回工具，并在 MCP annotations
  中标注读写性质。
- **依赖安全更新**——将 `cryptography` 升至 50.0.0，修复 PYSEC-2026-3552。

## [1.2.0] - 2026-07-28

### 新增

- **微信本地频道（Beta）**——参考腾讯 `openclaw-weixin` 的 iLink 协议，支持终端二维码登录、仅扫码者私聊、长轮询收信和 Agent 文本回复；授权以 `0600` 权限仅保存在当前设备，不需要开放公网端口。扫码后自动启动后台网关，并提供 `start` / `stop` / `status` 生命周期命令。
- **统一首次配置向导**——`mommy setup` 和首次启动统一完成 Provider、模型、隐藏 Key 输入、真实连通性验证及可选微信扫码；配置以 `0600` 保存到用户目录，CLI / TUI / Web / MCP / 微信共享模型选择。
- **Web 对话即界面**——根路由即投研对话，导航收敛为「对话 / 行情 / 持仓 / 我的」；桌面常驻上下文栏，移动端抽屉聚合自选、预测和信号。
- **移动端 Coding Agent 对话体验**——加入状态栏、slash 命令面板、工作指示和实时工具调用开始/完成事件；旧 `/agent` 页面能力迁移到统一 `/chat` 页面。
- **股票名称联想**——新增 `/api/stocks/search`，聚合自选、半导体参考库和报价缓存；行情页、「我的」加自选与对话 `@` 统一复用可键盘操作的搜索组件。
- **移动端投研闭环**——持仓卡片、详情页「加自选 / 问问 AI」、对话历史恢复、新对话、语音输入与忙时消息排队。
- **MiniMax provider**——第 6 个 LLM provider，使用开放平台普通按量 API 的 OpenAI 兼容 `/v1` 接口，默认模型 `MiniMax-M3`（非 Coding Plan）。
- **`manage_watchlist` 工具**（第 25 个）——agent 可直接增删自选股，`add_watchlist` 工作流从空壳变为真功能。
- **装配冒烟测试**（`tests/test_agent/test_assembly_smoke.py`）——TUI bootstrap / MCP stdio 真实入口回归。

### 改进

- **本地 Web 零口令启动**——loopback 地址默认不再要求 Bearer token；公网监听仍默认强制认证，并保留 `--require-auth` 显式开启本机认证。
- **TUI 单屏重写**——删除看板模式，slash 命令、工具结果、重试/记忆回执全部回到对话流；补齐 `@` 联想、排队、Esc 中断和三主题。
- **Web 细节打磨**——移动持仓卡片化，K 线跟随深浅主题，成交量单位与信号/工作流徽章中文化，关键术语增加解释。
- **发布验证**——搜索端点、WebSocket 降级/断连、股票联想组件与桌面/移动关键路径均有自动化回归。

### 修复

- **微信配置热重载**：重新运行 `mommy setup` 修改 Provider、模型或 API Key 后，在线微信网关会等待旧进程退出并自动重启，避免继续使用进程内的旧配置。
- **WebSocket 对话**：非流式降级的 `done.text` 不再被前端丢弃；生成中途断连立即解锁输入并提示重试，仅首次建连失败允许一次自动重试。
- **记忆系统**：`mommy-agent verify/consolidate` 启动崩溃；预测验证窗口为零导致从未真正验证（现在宽限期 = verify_after + 一个 timeframe）；方向验证改用相对 entry_price 的窗口涨跌幅、neutral 不再灌水命中率；`store_extraction` 补写 `trade_date`（存量 137 行已回填，`scripts/backfill_trade_date.py`）；对话后提取改后台线程不再阻塞响应。
- **LLM 连接层**：流式空串覆盖完整答案；流式双重调用消除（单次 stream 带 tools，不再双倍计费）；显式 120s 超时 + 关 SDK 内置重试 + 读 Retry-After；TokenTracker 接线进调用链并补全在产 provider 定价；TUI 密钥探测链与 AGENT_PROVIDER 对齐；提取调用 temperature=0 且计入 token 统计。
- **工具与工作流**：`ctx.db_path` 一物三用拆为 agent_db/market_db/portfolio_db（agent 设的告警监控进程读得到了）；工作流错误不再被当成功（`flow_check`/`add_watchlist`/`stock_analysis` 三处定义 bug 修复）；`ctx.client` 接线（向量检索、LLM 叙事从死代码变为可用，无 embedding 接口的 provider 显式降级）；工具结果 8KB 统一截断 + `get_bars` 上限 120 + JSON Schema 参数校验 + handler 层数值钳制；MCP 调用不再阻塞 event loop。
- **其他**：中断对话不再写入记忆；provider 配置收敛为 `agent/llm.py` 单一真相源；predictions 价格字段走 Decimal；向量孤儿随 cleanup 清理；`mommy` 主入口补加载 `.env`（只配 .env 的用户不再被误报未配置）。

---

## [1.1.0] - 2026-07-19

### 新增

- **dexter 风格 TUI 对话体验** — ToolIndicator（⏺ 工具调用指示 + ⎿ 摘要 + 耗时）、WorkingIndicator（spinner + 思考动词 + 计时）、HintBar（上下文提示 + slash 命令候选）；统一符号 ❯/⏺/✻/⎿；`AgentService` 新增 `on_tool_result` 回调驱动指示器。
- **slash 命令 ↑↓ 循环选择** — slash 模式下 ↑↓ 切换候选，HintBar 高亮，Tab + ghost text 跟随，命令名后空格退出选择。

### 改进

- **agent 工具按域拆分重构** — 单文件 `tools.py` 拆为 `tools/` 包 9 个域模块（quote/sector/flows/bars/holdings/intel/alerts/memory/themes）+ base + registry；全部通过 `mypy --strict`，移除 `agent.tools` 的豁免并记入 `docs/TECH-DEBT.md`。
- **工具编写指南** — `docs/AGENT-INTERACTION-GUIDE.md` 的 add-a-tool 改为指向域模块的 `DEFS`/`HANDLERS`（registry 自动聚合，无需改注册表）。
- **SQLite WAL sidecar 文件**（`*.db-shm`/`*.db-wal`）取消跟踪并加入 `.gitignore`。
- 主题切换修复（textual 8.x `self.dark` → `app.theme`）；HelpScreen 改 Markdown 渲染；看板空状态接通。

### 修复

- `/api/agent/predictions` 调用不存在的 `list_recent` 导致永远返回空（改用 `PredictionTracker.all()` 并加 limit 边界）。
- `/api/earnings/scores/{code}` 访问不存在的 `.score` 属性导致永远返回空（改用真实 `EarningsScore` 字段）。
- `WSSignalMessage` schema 的 `signals`（复数列表）与实际推送格式不匹配。

---

## [1.0.0] - 2026-07-16

### 新增

- Kimi K2.6 和 Nova Bridge provider，并校验 provider 配置。
- 单用户 Bearer 鉴权、短期 WebSocket ticket、受限 CORS、安全监听默认值和 agent 并发上限。
- 浏览器会话级对话隔离、非活跃会话清理、Vitest 和 Playwright 行为测试。
- Docker、迁移、依赖审计、覆盖率和定时数据源探针等发布门禁。

### 改进

- Docker 可复现构建 Vue/Python 产物并以非 root 用户运行。
- SQLite owner 统一显式生命周期、WAL、外键和 busy timeout。
- CLI 拆分为有边界的命令族模块，入口保持兼容。
- Workflow registry/router 改为进程级缓存和显式依赖。
- CI 覆盖 Python 3.12/3.13、前端、Docker、依赖审计和 65% 分支覆盖率。
- 移动端体验与 AI 对话韧性（连接状态指示、失败重试）。

### 修复

- Quote/signal WebSocket 订阅注册和清理。
- 持仓调整后的成本基础重复计算。
- 报告解析中 `万亿` 被较短的 `亿` 后缀抢先匹配。
- Docker 镜像直接服务打包后的前端产物。
- Railway 部署：运行时约束适配、数据持久化安全、健康检查版本化。
- 移除不支持的 Docker volume 指令。
- 发布门禁检查加固。

### 文档

- docs/ 收敛：25 份一次性计划 / 评估 / 实施记录归档至 `docs/archive/`，索引重写。
- 新增 `docs/TECH-DEBT.md`：mypy 豁免清单与已知告警如实台账化。
- README / AGENTS.md 数字与实测对齐（1,103 测试、10 个透传子命令等）。

详见 [基线评估](docs/archive/EVALUATION-2026-07-14.md) 和已完成的
[增强计划](docs/archive/ENHANCEMENT-PLAN-2026-07-14.md)。

---

## [未发布] - 2026-07-02

### 新增 ⭐

- **earnings 模块（业绩前瞻 + actual 比对）** — `src/mommy_chaogu/earnings/`
  - `types.py` — 4 dataclass + 2 StrEnum（EarningsActual / Calendar / Score / Verdict）
  - `schema.py` — 3 表 + 9 索引 + v_recent_disclosures 视图
  - `store.py` — EarningsStore（Decimal TEXT 精度安全）
  - `adapter.py` — EarningsAdapter Protocol + MockEarningsAdapter
  - `efinance_adapter.py` — EfinanceEarningsAdapter（真实东财数据）
  - `service.py` — EarningsService（pull / score / watch / summary）
  - `signals.py` — 4 条规则（beat / meet / miss / approaching）
  - `cli.py` — `mommy-earnings` 命令行
- **业绩前瞻数据资产** — `data/earnings_preview.db`（41 家公司中信证券 H1 2026）
- **实战手册** — `docs/EARNINGS-HANDBOOK.md`（12 章节 / 407 行）
- **主题分组** — 13 个 watchlist 主题组（半导体 6 子类 / AI算力 / PCB / 面板 / LED / 传感器 / 机器人 / 消费电子）
- **mommy-earnings CLI** — 4 子命令（pull / score / watch / summary）
- **EfinanceEarningsAdapter** — 真实东财业绩拉取（实测 H1 2025 数据完整）

### 改进

- **质量门**：ruff ✅ / mypy --strict ✅ / pytest 270 通过（196 原有 + 51 earnings + 23 efinance_adapter）
- **CLI 默认 adapter**：`mommy-earnings` 默认用 EfinanceEarningsAdapter（真实数据），可加 `--adapter mock` 切换
- **README 大改**：10KB / 389 行，含架构图、CLI 速查、财报窗口实战、开发指南

---

## [0.6.x] - 2026-07-01

### 新增

- **supply_chains 数据资产** — 3 个 JSON
  - `humanoid_robot.json` — 25 只人形机器人
  - `semiconductor.json` — 106 只半导体（中游-存储/MCU/处理器/...）
  - `materials.json` — 41 只材料（化工/钢铁/煤炭/...）
- **mommy-hub 联动** — 三个产业链页面（机器人/半导体/材料）
- **cron 修复** — 4 个 jobs（M6.1-M6.2）
- **reports 结构化** — 实战产物目录 `.gitignore` + `README.md`
- **Web UI 完整化（M5.4）** — 后端 web + 前端 Vue + money flow API

### 实战验证

- 妈妈已能用 Web + 资金流 ratio 监控跑通
- 7/1 多次板块扫描稳定（机器人 / 半导体 / 材料 / 光模块 / 证券）

---

## [0.5.x] - 2026-06-29

### 新增

- **半导体产业链参考库** — `src/mommy_chaogu/semicon/`（106 只）
- **资金流 ratio 监控 + 收盘日报** — `flows/signals.py`（4 条 ratio-based 默认规则）
- **FlowMonitor** — 持续轮询 + 状态持久化 + 失败告警
- **FlowReport** — 收盘日报 markdown（板块汇总 + TOP 流入/流出 + 矛盾股）
- **mommy-semicon / mommy-flows / mommy-report CLI**
- **OpenClaw cron 4 jobs 自动化**（M6.1-M6.4）
  - 8:30 盘前预热 / 9:30 盘中监控 / 15:30 收盘日报 / 周六 10:00 周报

---

## [0.4.x] - 2026-06-28

### 新增

- **持仓管理** — `portfolio/` 模块（Position + PositionAdjustment 表 / 6 API 端点 / 加权平均成本）
- **语音录入** — `useSpeechRecognition` composable（webkitSpeechRecognition）
- **资金流图表** — 5 维累计卡片 + 日内分时 SVG + 历史柱状图
- **盘面扫描** — 大盘 6 指数 / 涨幅榜 / 跌幅榜 / 板块榜
- **持仓快览** — 首页持仓条 + 盘面页联动

---

## [0.3.x] - 2026-06-27

### 新增

- **Web UI（M3.0）** — Vite + Vue 3 + FastAPI + WebSocket（妈妈手机可用）
  - 首页（5 自选 + 主力合计 + WebSocket）
  - 详情（klinecharts K线 + MA 均线 + VOL）
  - 信号（触发历史）
  - 设置（服务状态 + 自选股 CRUD）
- **Server酱 微信推送（M3.1）** — 阈值过滤 + JSON 去重

---

## [0.2.x] - 2026-06-26

### 新增

- **数据层**（M0 - M2.5）
  - M0 — 通用行情数据层 + efinance 适配器
  - M1 — 自选池 + 实时监控
  - M1.5 — 7 条内置告警规则 + Alerter
  - M2 — 时间戳驱动缓存 + 装饰器
  - M2.5 — TencentAdapter + FallbackAdapter（凌晨实战）
- **CLI** — `mommy-watchlist` / `mommy-monitor` / `mommy-cache` 4 子应用
- **设计文档** — `docs/DESIGN.md` / `docs/archive/LEDGER.md` / `docs/archive/PROGRESS.md`

---

## [0.1.0] - 2026-06-25

### 新增

- 项目初始化
- 数据契约 + MarketDataAdapter Protocol
- efinance 适配器（11 路数据）
- 端到端冒烟脚本（`scripts/smoke_market_data.py`）
- 24 测试（13 离线 + 11 实时网络）

---

## 版本说明

- **0.1.x** — 数据层（行情 / 自选 / 信号 / 缓存）
- **0.2.x** — 实战验证 + 凌晨 fallback 修复
- **0.3.x** — Web UI + 推送
- **0.4.x** — 持仓 + 语音录入
- **0.5.x** — 资金流 ratio + 自动化
- **0.6.x** — 产业链数据 + hub 联动
- **0.7.x** — 财报窗口 + 实战手册
- **1.0.0** — 首个稳定版（生产加固 + TUI/Web 重写 + 安全边界）
- **1.1.0** — 体验对齐 dexter（工具指示 + slash 选择）+ agent 工具按域拆分 + web API 修复

---

## 贡献者

- **coffee-man666** — 主要开发者 + 项目维护者

---

**License**: [MIT](LICENSE)
