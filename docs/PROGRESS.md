# 进度总结 (PROGRESS.md)

> mommy-chaogu 当前在哪个位置？**做完什么**、**还差什么**、**接下来做什么**。

最后更新：2026-07-04（memory-system-v1 — 记忆系统 + 回测 + 数据库重组 + 多模型 LLM 回测）

---

## TL;DR

| 维度 | 状态 |
|---|---|
| 项目阶段 | **记忆系统 Phase 1-5 + 30 天回测 + 数据库分库 + 多模型 LLM 回测** |
| 代码量 | **~36,000+ 行**（Python src ~23,000 + tests ~9,000 + web ~4,000） |
| 测试 | **518 个通过**（含 +36 token tracker 测试） |
| **AI Agent** | **✅ LLM agent 层**（deepseek/openai/kimi/zai，**18 function-calling 工具**，Web 聊天 + 流式推送 + **MCP Server**） |
| **自进化记忆** | **✅ 5 层记忆系统**（工作/情景/预测验证/语义知识/向量检索，**8 个 CLI 子命令**） |
| **30 天回测** | **✅ 154 条预测验证（真实数据），命中率 53%，提炼 10 条知识** |
| **LLM 回测** | **✅ 5 模型横向对比完成**（glm-4.7/5/5-turbo/5.1/5.2，70 条 × 5 = 350 条预测，最佳 glm-5 50% 命中率）|
| **数据库** | **✅ 分库重组**（market/portfolio/agent/reference 4 库，含迁移脚本） |
| 供应链数据资产 | **3 个 JSON**（机器人 25 / 半导体 106 / 材料 41， 总计 172 只） |
| **回测数据** | **market.db: 106 只 × 42 天 K 线(4437 行) + 92 只 × 21 天资金流(1917 行)** |
| 数据报告 | 10+ 条实战推送（hub SQLite 留底） |
| 代码质量 | ruff ✅ / mypy strict ✅ 0 errors / **CI ✅** |
| 文档 | DESIGN / PROJECT-LOG / LEDGER / PROGRESS / KLINE-SPEC / DISCUSSION-NOTES / EARNINGS-HANDBOOK / MEMORY-SYSTEM-PLAN / BRANCH-MERGE-ANALYSIS / BACKTEST-REPORT / **AGENTS.md** **11 份齐** |
| 自动化 | **4 个 OpenClaw cron jobs**（盘前/盘中/收盘/周报） |
| **实战验证** | ✅ 记忆系统闭环 + 30 天回测 + 数据库迁移 + 5 模型 LLM 回测对比 |

---

## 当前架构总览

```
              📱 妈妈手机                📱 妈妈微信（Server酱³）
              Web 主动看 + 💬 Agent 聊天        ↑ 被动收
                    ↑                          │
                    │ HTTP/WS                  │ POST https://sctapi.ftqq.com/{key}.send
                    │                          │
        ┌─────────────────────────────┐        │
        │  Vite-built 静态文件         │        │
        │  ├─ 行情/持仓/盘面 Tab       │        │
        │  └─ 💬 Agent 聊天页          │        │
        └────────────┬────────────────┘        │
                     ↓                          │
        ┌─────────────────────────────┐        │
        │  FastAPI (uvicorn :8000)    │        │
        │  ├─ /api/* REST (20+ 端点)  │        │
        │  ├─ /api/agent/chat (LLM)   │        │
        │  ├─ /ws/* WebSocket          │        │
        │  │   └─ /ws/agent (流式)     │        │
        │  └─ 后台轮询（5s）+ WS 广播  │        │
        └────────────┬────────────────┘        │
                     ↓                          │
        ┌─────────────────────────────┐        │
        │  BackgroundService          │────────┘
        │  ├─ snapshot + signals      │
        │  ├─ SignalNotifier          │ ← 推送：阈值过滤 + JSON 去重 + 微信
        │  └─ AgentReportService      │ ← agent 驱动的盘后报告（可选）
        └────────────┬────────────────┘
                     ↓
        ┌──────────────────────────────────────────┐
        │  AgentService (LLM + tools loop)          │ ← M7
        │  ├─ deepseek-chat (默认，~0.001元/1k tok) │
        │  ├─ 18 function-calling 工具             │ ← M8 扩展（+7）
        │  ├─ MCP Server (stdio protocol)           │ ← NEW M8
        │  ├─ ConversationMemory (SQLite)           │ ← NEW M8
        │  └─ system prompt（ratio bp 分析原则）    │
        └────────────┬─────────────────────────────┘
                     ↓
        ┌─────────────────────────────┐
        │  CachedMarketDataAdapter    │
        │  ↓                           │
        │  FallbackAdapter            │
        │  ├─ EfinanceAdapter (主)     │
        │  └─ TencentAdapter  (备)     │
        └─────────────────────────────┘
                     + 东方财富 push2.eastmoney.com 直连
                       （大盘指数 / 板块排行 / 板块成分股 / 龙虎榜）
```

---

### ✅ 30 天回测验证 + 数据库重组（`memory-system-v1` 分支，2026-07-04）

#### 30 天真实数据回测

用 10 只股票 × 24 天真实行情数据（腾讯日 K 线 + 东财资金流）跑完整闭环：

| 指标 | 值 |
|---|---|
| 数据源 | 腾讯日 K 线（10 只 × 24 天）+ 东财资金流（10 只 × 21 天）+ 东财公告（44 条） |
| 总预测 | 154 条（规则引擎自动生成，4 条信号规则） |
| 命中 | 82（53%） |
| 提炼知识 | 10 条（含个股命中率 + 市场规律） |
| Prompt 进化 | 612 字 → 2185 字 |

**关键发现**：
- 看跌比看涨准（57% vs 41%）——趋势延续性强
- 极端信号更可信（10bp+ 59% vs 5-10bp 50%）
- 个股差异巨大：比亚迪 84% vs 柯力传感 18%
- 脚本：`scripts/backtest_evolution.py`

#### 半导体链 106 只数据采集

| 数据 | 成功 | 总行数 | 存储 |
|---|---|---|---|
| K 线 | 106/106 | 4437 行（5/6 → 7/3） | data/market.db |
| 资金流 | 92/106 | 1917 行（6/4 → 7/3） | data/market.db |
| 股票列表 | 106 | — | data/reference.db |

14 只资金流不可用（模拟芯片类：圣邦/思瑞浦/纳芯微等，东财接口不覆盖）。

#### 数据库分库重组

从 1 个 `watchlist.db`（所有表混在一起）→ 4 个按职责分离的数据库：

| 数据库 | 用途 | 关键表 |
|---|---|---|
| `data/market.db` | 行情数据 | quote_cache, bar_cache, klines, flows |
| `data/portfolio.db` | 用户数据 | groups, stock_entries, positions |
| `data/agent.db` | 记忆系统 | agent_memory, episodic_events, predictions, semantic_knowledge |
| `data/reference.db` | 参考库 | semicon_stocks, earnings_* |

新增文件：
- `src/mommy_chaogu/db_paths.py` — 统一路径管理（环境变量可覆盖）
- `scripts/migrate_db_layout.py` — 自动迁移脚本（ATTACH + INSERT）
- `scripts/fetch_semicon_data.py` — 批量抓取半导体链数据
- `AGENTS.md` — agent / 开发者项目指南

向后兼容：环境变量覆盖、`--db` 参数、测试用 tmp_path 不受影响。

---

### ✅ Memory System v1: 自进化记忆系统 Phase 1-5（`memory-system-v1` 分支）

> **核心能力**：让 agent 从「每次从零开始」变成「越用越懂」——记住过去、验证判断、沉淀经验、找相似事件。
>
> 设计文档：`docs/MEMORY-SYSTEM-PLAN.md`（四层记忆架构 + 预测验证闭环 + 数据缺失降级策略）

#### Phase 1 — 情景记忆 + 预测追踪 + 降级验证

| 文件 | 内容 |
|---|---|
| `agent/episodic_memory.py` | 结构化事件存储（episodic_events 表，4 种事件类型 + data_coverage 追踪） |
| `agent/prediction_tracker.py` | 预测生命周期（predictions 表，pending → hit/missed/expired/unverifiable） |
| `agent/verify_engine.py` | 降级验证引擎（报价优先 → 资金流可选 → 不伪造结果，评分 1.0/0.7/0.3/0.0） |
| `agent/extractor.py` | 对话后 LLM 事实抽取（JSON response mode，失败不 block 主流程） |
| `agent/prompt_builder.py` | 动态 system prompt（注入知识 + 事件 + 判断回顾） |

#### Phase 3 — 市场脉络生成

| 文件 | 内容 |
|---|---|
| `agent/narrative.py` | 市场脉络叙述（30 天主线 + 转折点 + 因果链 + 变化检测 + 时段对比） |

#### Phase 4 — 语义记忆 + 知识提炼

| 文件 | 内容 |
|---|---|
| `agent/semantic_memory.py` | 语义知识库（semantic_knowledge 表，4 种知识 + supersede + 置信度校准） |
| `agent/consolidator.py` | LLM 离线知识提炼（板块叙事 / 市场状态 / 规律归纳 + 命中率校准 confidence） |

#### Phase 5 — 向量检索

| 文件 | 内容 |
|---|---|
| `agent/vector_search.py` | 语义搜索（sqlite-vec + embedding API，"找相似历史事件"） |

#### 8 个 CLI 子命令

```
mommy-agent verify          # 验证到期预测
mommy-agent predictions     # 查看预测 + 命中率
mommy-agent events          # 查看情景记忆
mommy-agent remember        # 手动记录事件
mommy-agent narrative       # 市场脉络叙述
mommy-agent consolidate     # 知识提炼
mommy-agent knowledge       # 查看知识库
mommy-agent search          # 语义搜索相似事件
```

#### 新增表（5 张，同一份 data/watchlist.db）

| 表 | 用途 |
|---|---|
| `episodic_events` | 情景记忆（结构化事件流） |
| `predictions` | 预测追踪（pending → hit/missed/expired） |
| `semantic_knowledge` | 语义知识（active / superseded + hit_count/miss_count） |
| `episodic_embeddings` | embedding 元数据 |
| `episodic_vec` | sqlite-vec 虚拟表（float[1536]） |

#### 测试（+121 个）

| 测试文件 | 数量 | 覆盖 |
|---|---|---|
| test_episodic.py | 16 | CRUD / query / prefix-scope / persistence |
| test_prediction_tracker.py | 20 | CRUD / status / attempts / stats |
| test_verify_engine.py | 23 | scoring / quote / target / degraded / expired / batch |
| test_prompt_builder.py | 7 | empty / events / predictions / full |
| test_extractor.py | 8 | extraction / store / entry_price / data_coverage |
| test_narrative.py | 7 | generate / detect_changes / compare / failure |
| test_semantic.py | 21 | CRUD / upsert-supersede / recalibrate / persistence |
| test_consolidator.py | 9 | sector_theses / market_regime / patterns / failure |
| test_vector_search.py | 10 | pack/unpack / store / embed / search / stats |

#### 实战验证

- ✅ 验证降级策略：hit / missed / data_unavailable → expired 全路径
- ✅ 置信度校准：0.8 → 命中率 30% → 0.55 → 命中率 70% → 0.62
- ✅ 向量检索：embed_pending 100% 覆盖，search_similar 正确返回相似事件
- ✅ prompt 注入：知识 + 事件 + 判断回顾 三部分正确注入
- ✅ 向后兼容：无 episodic/tracker 时 AgentService 行为不变

---

### ✅ M7.x — 中报前瞻 + Thematic groups + Earnings actual 模块（2026-07-02）
| commit | 标题 | 内容 |
|---|---|---|
| `5326b1e` | feat(data): H1 2026 业绩前瞻数据库 schema + loader 脚本 | 新增 `data/earnings_preview.db`（41 家公司中信证券 7/2 报告，45KB）|
| `4d96d83` | feat(watchlist): 按主题分组 + 41 家公司入库 | 13 个主题 group + 3 个持仓 group 不动，总计 47 条记录 |
| `018b276` | docs(EARNINGS-HANDBOOK): 2026 中报窗口实战手册 v1.0 | 12 章节 / 407 行 / 含柯力 603662 三情景推演 |
| (待提交) | feat(earnings): earnings_actual 模块 + adapter + signals | 7 文件 / 1263 行 / 51 测试 / mommy-earnings CLI |

## 已完成的里程碑

### ✅ M8: Infra Upgrade（P0-P3，`feature/infra-upgrade` 分支，commits `cd1efea` `05a8a71` `f0dd602`）

> **核心升级**：补齐基础设施短板 — 统一配置、MCP 协议支持、持久记忆、回测引擎、基本面/新闻/龙虎榜数据源、组合分析、自定义告警。
>
> Agent 工具从 11 → **18**，CLI 子命令 21 → **25+**，新增 `mommy-mcp` 独立入口。

#### 新增模块

| 文件 | 内容 |
|---|---|
| `src/mommy_chaogu/market_data/news_api.py` | **东方财富新闻/公告/龙虎榜 API** — `search_news()` / `get_announcements()` / `get_longhuban()` |
| `src/mommy_chaogu/market_data/fundamentals_api.py` | **基本面数据 API** — `get_fundamentals()`（PE/PB/PS/ROE/利润率/行业） |
| `src/mommy_chaogu/market_data/sector_api.py` | 板块成分股（M7 已建，M8 增强） |
| `src/mommy_chaogu/agent/mcp_server.py` | **MCP Server**（stdio 协议，任意 MCP client 可连接） |
| `src/mommy_chaogu/agent/memory.py` | **ConversationMemory**（SQLite 持久化，跨 session 记忆） |
| `src/mommy_chaogu/config.py` | **统一 TOML 配置** — `AppConfig`（AgentConfig / PushConfig / CacheConfig / MonitorConfig） |
| `src/mommy_chaogu/portfolio/analysis.py` | **PortfolioAnalyzer**（板块集中度 / 相关性矩阵 / 最大回撤 / Sharpe ratio） |
| `src/mommy_chaogu/signals/custom_alerts.py` | **CustomAlertStore**（用户自定义价格/涨跌幅告警） |
| `src/mommy_chaogu/backtest/engine.py` | **BacktestEngine**（回放信号规则到缓存历史数据） |
| `.github/workflows/ci.yml` | **CI**（ruff + mypy + pytest） |
| `Dockerfile` | **Docker 部署** |

#### 新增 CLI

| 命令 | 内容 |
|---|---|
| `mommy-mcp` | MCP Server 独立入口（stdio 协议） |
| `mommy-watchlist alert` | 自定义告警管理（增删改查） |
| `mommy-flows backtest` | 回测引擎（信号规则历史回放） |
| `mommy-chaogu config init` | 生成默认 TOML 配置文件 |

#### 新增 7 个 Agent 工具（11 → 18）

`search_news` / `get_announcements` / `get_longhuban` / `get_fundamentals` / `backfill_history` / `manage_alert` / `get_portfolio_analysis`

#### 完整 18 工具列表

get_quote, get_quotes, get_market_indexes, get_sector_ranking, search_sector, get_sector_stocks, get_money_flow_today, get_money_flow_history, get_bars, get_watchlist, get_portfolio, **search_news, get_announcements, get_longhuban, get_fundamentals, backfill_history, manage_alert, get_portfolio_analysis**

#### 测试

- **+53 个测试**（news_api / fundamentals_api / mcp_server / memory / config / analysis / custom_alerts / backtest）
- 总测试数：**287 通过**

---

### ✅ M7: Agent-Centric 重构（Phase 1-5，`feature/agent-centric` 分支，commit `d002ee5`）

> **核心架构转变**：从硬编码 if-else 规则转向 LLM agent 驱动的智能分析。
>
> - **OLD**：Data → 7 if-else rules → push「主力净流入 1.2亿」
> - **NEW**：Data → LLM agent（理解上下文、叙事、市场情绪）→ push 分析报告
>
> Agent 与现有系统并存，`signals/` 里的 7 条规则保留为 fallback，**未删除**。

#### 新增模块

| 文件 | 内容 |
|---|---|
| `src/mommy_chaogu/agent/tools.py` | **11 个 function-calling 工具**，封装现有数据接口（get_quote, get_quotes, get_market_indexes, get_sector_ranking, search_sector, get_sector_stocks, get_money_flow_today, get_money_flow_history, get_bars, get_watchlist, get_portfolio） |
| `src/mommy_chaogu/agent/service.py` | **AgentService** — LLM + tools 循环，支持 deepseek/openai/kimi（统一走 OpenAI SDK） |
| `src/mommy_chaogu/agent/prompt.py` | system prompt — ratio-based bp 分析原则（不是硬 if-else） |
| `src/mommy_chaogu/agent/reports.py` | **AgentReportService** — agent 驱动的盘后报告生成 |
| `src/mommy_chaogu/market_data/sector_api.py` | **东方财富板块成分股 API** — `fetch_sector_stocks()` + `search_sector()` |

#### 新增 CLI / Web / 前端

| 类型 | 文件 | 内容 |
|---|---|---|
| CLI | `pyproject.toml` + `cli.py` | **`mommy-agent`** 入口 — chat / report / tools 子命令（~130 行） |
| Web 后端 | `src/mommy_chaogu/web/routes/agent.py` | `POST /api/agent/chat` + `WS /ws/agent`（流式） |
| Web 依赖 | `web/deps.py` | `get_agent_service()` 单例（懒加载，无 API key 时返回 None） |
| 前端 | `web/src/pages/agent/index.vue` | 聊天 UI 页 — 快捷问题 + WebSocket 流式 |
| 前端 | `web/src/api/agent.ts` | agent API client |

#### 改造文件

| 文件 | 改动 |
|---|---|
| `pyproject.toml` | +`openai` 依赖，+`mommy-agent` entry point |
| `cli.py` | +agent 子命令（~130 行） |
| `web/app.py` | +agent router |
| `web/src/router/index.ts` | +`/agent` 路由 |
| `web/src/App.vue` | +💬 问 tab |

#### 测试

- **+38 个 agent 测试**（工具封装 / service 循环 / prompt / sector_api / monitor 扫描循环）
- 总测试数：**234 通过**（含 M4-M5 补充）

#### 成本

- 默认 LLM：`deepseek-chat`，成本 ~0.001 元 / 1k tokens

---

### ✅ M7 Phase 5: Agent 盘中扫描监控（commit `d002ee5`）

> **核心能力**：低频 LLM 扫描循环（3 min 默认），盘中自动分析自选股 + 板块异动，有告警才推送。

#### 新增模块

| 文件 | 内容 |
|---|---|
| `src/mommy_chaogu/agent/monitor.py` | **AgentMonitor** — `scan_once` / `run` / `run_async`，低频 LLM 扫描循环 |
| `src/mommy_chaogu/agent/scan_prompt.py` | scan 专用 prompt（JSON response mode，强制结构化输出） |
| `tests/test_agent/test_monitor.py` | **17 个测试** — scan_once / run / dedup / 无告警零成本 / 异步 |

#### 改造文件

| 文件 | 改动 |
|---|---|
| `cli.py` | +`scan` 和 `monitor` 子命令到 `mommy-agent` |

#### 设计要点

- **低频扫描（3 min 默认）**：收集自选股报价 + 资金流 → 一次性塞给 LLM（不让 LLM 自己调工具，省 token）
- **JSON response mode**：强制 LLM 返回结构化 JSON（alerts 列表）
- **复用 SignalNotifier 去重**：`code + "agent_scan" + date` — 一天只推一次
- **无告警零成本**：LLM 返回空 alerts 时只打印 summary，不推送
- **硬告警（涨停跌停）**：继续走 BackgroundService 的 7 条 if-else，AgentMonitor 不重复
- **成本**：~0.05 元/天（80 scans × 600 tokens × 0.001 元/1k）

#### CLI

```bash
uv run mommy-agent scan              # 单次扫描
uv run mommy-agent monitor --interval 180 --max-seconds 19800  # 持续监控
uv run mommy-agent monitor --push    # + 微信推送
```

---

### ✅ 数据层（M0–M2.5，5 个 milestone）
| ID | commit | 标题 | 行数 |
|---|---|---|---|
| M0 | `dc8fd33` | 通用行情数据层 + efinance 适配器 | ~800 |
| M1 | `dac4f8d` | 自选池 + 实时监控 | ~800 |
| M1.5 | `2a44ed8` | 7 条内置告警规则 + Alerter | ~900 |
| M2 | `30fad29` | 时间戳驱动缓存 + 装饰器 | ~1900 |
| M2.5 | `1910bc1` | TencentAdapter + FallbackAdapter（凌晨实战） | ~850 |

### ✅ Web UI（M3.0，4 个 commit）
| commit | 标题 | 内容 |
|---|---|---|
| `ee4170b` | FastAPI 后端 + WebSocket | 14 REST 端点 + 2 WS + 后台轮询 + 依赖注入 |
| `eb23fe5` | Vite + Vue 3 切换 + 4 页通过实测 | 切换到 Vite，15 分钟跑通 K 线 + 盘口 |
| `22f4e8b` | UI 优化 for 妈妈 | 5档盘口修色 + 大字号 + 骨架屏 + 信号跳转 |

### ✅ 推送（M3.1）
| commit | 标题 |
|---|---|
| `3402e19` | Server酱 微信推送 + JSON 文件去重 |

### ✅ 持仓管理 + 语音录入 + 资金流图表 + 盘面扫描（M4, 2026-06-28）
| 主题 | 内容 |
|---|---|
| **持仓管理** | Position + PositionAdjustment 表 / PortfolioStore / 6 个 API 端点 / 加权平均成本 / 实时盈亏计算 |
| **语音录入** | useSpeechRecognition composable（webkitSpeechRecognition）/ 自然语言解析（"茅台买入价1680 100股"）/ 弹窗录入 |
| **资金流图表** | 5 维累计卡片 + 日内分时 SVG 折线 + 历史柱状 SVG（零线居中）/ 7/30/90 天切换 |
| **盘面扫描** | 大盘 6 指数 / 涨幅榜 TOP20 / 跌幅榜 TOP20 / 板块榜 TOP20 / 30 秒轮询 |
| **持仓快览** | 首页持仓条 + 盘面页持仓条联动 |
| **删除盘口** | 详情页盘口信息隐藏（聚焦资金流） |
| **K线 bug 修复** | createIndicator 不判重导致切换周期叠加多张副图 → 用 isFirstInit 标志 |
| **文档** | KLINE-SPEC.md / DISCUSSION-NOTES.md |

---

## 当前功能矩阵（M4）

| 能力 | 数据源 | 缓存 | Web UI | 信号 | 推送 |
|---|---|---|---|---|---|
| 实时报价 | ✅ efin+tencent | ✅ | ✅ 盘面页 + 详情 | ✅ | ✅ ⚠️→🚨 |
| 5 档盘口 | ✅ efin+tencent | ✅ | ❌ 已隐藏 | ❌ | — |
| K 线（日/周/月 + 5/15/30/60 分） | ✅ efinance | ✅ | ✅ klinecharts + MA 均线 + VOL（修 bug 后稳定） | ❌ | — |
| 资金流（日内 + 历史） | ✅ efinance | ✅ | ✅ 累计卡片 + 折线图 + 柱状图 | ✅ | ✅ |
| 全市场快照 | ✅ efinance | ✅ | ✅ 涨幅榜/跌幅榜 | ❌ | — |
| 大盘指数（沪深300等6个） | ✅ 东财 push2 | ❌ | ✅ 指数卡片网格 | ❌ | — |
| 板块涨跌幅榜 | ✅ 东财 push2 | ❌ | ✅ 板块榜 TOP20 | ❌ | — |
| 自选股分组管理 | — | ✅ | ✅ 设置页 CRUD | ❌ | — |
| **持仓管理** | — | ✅ | ✅ 持仓页 + 总览 + 盈亏 | — | — |
| **语音录入持仓** | 浏览器 SpeechRecognition | — | ✅ 语音弹窗 | — | — |
| 信号告警（7 条规则） | — | — | ✅ 信号中心 | ✅ 实时 | ✅ JSON 去重 |
| **AI Agent 聊天** | ✅ 全量接口（11 工具） | ✅ | ✅ 💬 问 Tab（流式） | ✅ ratio 分析 | ✅ AgentReportService |
| 数据新鲜度报告 | — | ✅ | ✅ 设置页 | ❌ | — |
| 微信推送（Server酱³） | — | — | ⚠️ 设置页未集成入口 | ✅ 阈值过滤 | ✅ Markdown + 链接 |

🟢 妈妈能用 · 🟡 数据可达未深度集成 · ❌ 未实现

---

## M4 已交付细节

### 后端（~1500 行新增）

#### 持仓管理模块
- `src/mommy_chaogu/portfolio/models.py` — Position + PositionAdjustment 两表
- `src/mommy_chaogu/portfolio/store.py` — PortfolioStore（CRUD + 加权平均成本 + summary）
- `src/mommy_chaogu/web/routes/portfolio.py` — 6 个端点
- 6 个 Pydantic schemas + mappers

#### 资金流增强
- `routes/quotes.py` 改 `money_flow/today` 为 dict（含 cumulative）
- 新增 `money_flow/history?days=N` 端点
- 修复缓存层 `store.get_money_flow_history` bug（dict/list 类型混淆）

#### 盘面排行模块
- `src/mommy_chaogu/market_data/rankings.py` — 直连东财 push2
  - `fetch_indexes()` — 6 个大盘指数
  - `fetch_sector_ranking()` — 行业+概念板块合并去重
- `src/mommy_chaogu/web/routes/market.py` — 4 个端点
  - `GET /api/market/indexes`
  - `GET /api/market/sectors?limit=30`
  - `GET /api/market/gainers?limit=20`
  - `GET /api/market/losers?limit=20`

### 前端

#### 新增文件
- `web/src/composables/useSpeechRecognition.ts` — 语音识别 composable
- `web/src/api/market.ts` — 盘面 API client
- `web/src/api/portfolio.ts` — 持仓 API client
- `web/src/pages/market/index.vue` — 盘面 Tab（**新的首页**）
- `web/src/pages/portfolio/index.vue` — 持仓 Tab

#### 改造文件
- `web/src/router/index.ts` — 路由：index.vue → market/index.vue
- `web/src/App.vue` — 底部 Tab 加「💰 持仓」
- `web/src/pages/index/index.vue` → 删除（被 market 取代）
- `web/src/pages/detail/index.vue`
  - 删除盘口信息
  - 资金流改 SVG 图表（折线 + 柱状）
  - 用 computed 替代 function（修复响应式 bug）
- `web/src/api/types.ts` — 加 IndexQuote / SectorQuote / RankingQuote / Position / MoneyFlow

---

## 测试覆盖

```
src/mommy_chaogu/market_data/    13 dataclass + 11 efinance + 17 tencent (含 4 fallback 场景)
src/mommy_chaogu/watchlist/       17 CRUD
src/mommy_chaogu/monitor/         10 轮询（Mock adapter）
src/mommy_chaogu/signals/         31 规则（每条 3-5 case）
src/mommy_chaogu/cache/           26 命中/拉新/失败/节流/历史/Manager
src/mommy_chaogu/push/            29 server_chan + deduper + notifier
src/mommy_chaogu/agent/           38 + MCP/memory/scan 测试  ← M7+M8
src/mommy_chaogu/portfolio/       analysis + store 测试     ← M8
src/mommy_chaogu/backtest/        engine 单测               ← NEW M8
src/mommy_chaogu/signals/         31 规则 + custom_alerts   ← M8 扩展
                              ───
                              287 total（离线 + agent + infra-upgrade）
```

- `ruff`: All checks passed
- `mypy --strict`: 0 errors

---

## 已修复的 bug

1. **Decimal vs Money 误判**（mappers.py × 3）
2. **5档盘口颜色反了** → 已隐藏盘口
3. **Taro 4 H5 加载器错位** → 切换到 Vite + Vue 3
4. **FastAPI StaticFiles 抢路由** → 移到最后注册
5. **Naive datetime vs aware** → mappers 自动转 UTC
6. **Server酱 emoji 在标题里 markdown 化** → desp 用 `\n\n` 分段
7. **JSON Decimal 序列化 NaN** → Money/Decimal 一律转 str
8. **today 资金流累计用 sum 而非最后一条**（efinance 返回的是累计值）→ 取 items[-1]
9. **money_flow_cache 缓存层 JSON 反序列化类型错误** → 用 wrapper 存 trade_date
10. **K线 createIndicator 不判重**（切换周期叠加多张 VOL）→ 用 isFirstInit 标志
11. **Vue function 模板调用不响应式**（资金流 SVG NaN）→ 改 computed

---

## 已知限制

| 限制 | 影响 | 何时修 |
|---|---|---|
| Mac mini 内网 IP，妈妈出门不能访问 | 只能在 WiFi 下用 | Cloudflare Tunnel / frp |
| 主力净流入榜没有（数据源限制） | 扫盘缺一个核心维度 | 直连东财 push2 自爬 |
| **Agent 需要 LLM API key** | 无 key 时 agent 功能返回 None，降级为纯规则 | 配 deepseek（~0.001元/1k tok） |
| portfolio / rankings / web 后端单测未补 | 回归风险 | 半天搞定 |
| 没 PWA（不能加桌面） | 每次打开浏览器 | 半小时 |
| 没复盘报告 | 每天收盘后妈妈要自己看 | P1 |
| Server酱 免费版 5 条/天 | 严重信号 >5 时部分丢失 | 升级 VIP 或加钉钉/Telegram |
| 9 个 efinance live 测试偶发挂 | 凌晨东财挂时挂 | `pytest -m live` 标记 |
| 没 CI | 团长看不见我跑没跑测试 | ✅ M8 已加 GitHub Actions |
| 自选股 / 持仓还无法从详情页直接加 | 体验割裂 | 加「加自选」「加持仓」按钮 |

---

## 下一步候选（按团长优先级）

> 📅 2026-07-04 更新：5 模型横向对比回测完成（glm-4.7/5/5-turbo/5.1/5.2，70 条 × 5 = 350 条预测）。glm-5 最佳（50% 命中率，bullish 93%）。下一步可扩展到下跌区间验证 bearish 策略。

### ✅ 7/4 多模型 LLM 回测（已完成）
- ✅ **5 模型横向对比** —— glm-5 最佳（50% 命中率），glm-4.7 bullish 最准（96%）
- ✅ **过程完整记录** —— 每条预测含 prompt/LLM 回复/方向/理由/token/命中状态
- ✅ **Agent 原生 trial_1** —— 25 条预测，bullish 88%，零成本
- ✅ **通用回测脚本** —— `run_model.py` 参数化，可复现

### ✅ 7/4 回测 + 数据库重组
- ✅ **30 天真实数据回测** —— 154 条预测，53% 命中率，提炼 10 条知识
- ✅ **数据库分库** —— market / portfolio / agent / reference 4 库 + 迁移脚本 + AGENTS.md

### ✅ 7/1 实战验证
1. **cron 链路实跑** —— 4 个 job 修后于 7/1 8:30 盘前预热成功（拉了 105/106 只半导体资金流，hub 实际收到 webhook）
2. **mommy-hub 联动** —— web 端 三个产业链页面（机器人/半导体/材料）跑通，10+ 条实战报告入 hub SQLite
3. **多板块扫描稳定** —— 妈妈单子 / 机器人 / 半导体 / 材料 / 光模块 / 证券 全部能跑（拉 + 分析 + 推送 hub）

### ✅ 7/2 实战验证（柯力传感 + 中信业绩前瞻）
1. **柯力 603662 深挖** —— 6/22-6/29 流出 1.78 亿 + 6/30/7/2 两次放量流入 = 底部反转初期信号
2. **中信证券 H1 2026 业绩前瞻** —— 41 家公司入库 earnings_preview.db
3. **柯力业绩催化** —— H1 2026 +188~+217%，人形机器人主线 + 现价距高 84.49 还有 13% 空间
4. **多主题篮子落地** —— 13 个主题 group 覆盖 41 家公司（柯力跨「传感器」「机器人」2 组）
5. **earnings_actual 模块** —— 7 文件 / 51 测试 / CLI 集成 / 全部离线通过

### ✅ M8 Infra Upgrade 已完成（P0-P3）
- ✅ **GitHub Actions CI**（ruff + mypy + pytest）— `.github/workflows/ci.yml`
- ✅ **MCP Server**（stdio 协议，`mommy-mcp` 独立入口）
- ✅ **统一 TOML 配置**（`mommy-chaogu config init`）
- ✅ **持久记忆**（ConversationMemory SQLite）
- ✅ **回测引擎**（BacktestEngine，`mommy-flows backtest`）
- ✅ **基本面 / 新闻 / 龙虎榜 API**
- ✅ **组合分析**（PortfolioAnalyzer：集中度 / 相关性 / 回撤 / Sharpe）
- ✅ **自定义告警**（CustomAlertStore，`mommy-watchlist alert`）
- ✅ **Docker 部署**（`Dockerfile`）

### 🟧 P1 — 该做但没做
1. **实战测试** —— MCP client 连接验证 / backtest 真实数据回放 / config 在 cron 中的表现
2. **EfinanceEarningsAdapter 实战** —— 7/15 中报季拉取真实业绩数据
3. **EarningsCalendar 公告日历爬取** —— 交易所 / 东财 公告披露日期
4. **业绩预告 cron 集成** —— 7/15 起每天 16:00 扫描业绩预告 → 比对 → 推微信
5. **pytest -m live 标记** —— 区分离线/网络测试
6. **多氟多/联特类「故事+量价背离」监控规则** —— 避免追高被套
7. **语音版报告集成** —— `say -v Tingting` + m4a 推送微信

### 🟨 P2 — 体验升级
6. **详情页 Tab 化改造**（场景 B — 持仓决策驾驶舱）
7. **PWA 配置**（妈妈加到桌面像 App）
8. **板块榜加轮动热力图**（什么板块在涨）
9. **详情页加「加自选」「加持仓」按钮」（体验闭环）
10. **mommy-hub 产业链详情的筛选 + 导出** —— 可以一键导出 PDF 给妈妈看

### 🟦 P3 — 大件
11. **微信小程序**（基于 web/src 复用，Taro 重新跑）—— 3-5 天
12. **多用户支持**（妈妈 + 丈母娘 + 团长）—— 2-3 天
13. **内网穿透**（Cloudflare Tunnel，0 配置）—— 1 小时

---

## 7/2 实战数据快照

**中信证券 H1 2026 业绩前瞻分析**（2026-07-02）

| 场景 | 结果 | 关键发现 |
|---|---|---|
| **柯力 603662 深挖** | 7/2 11:04 实时 | 现价 75.13, PE 68.85, 6/22-6/29 主力 -1.78亿 → 6/30 +1.31亿 / 7/2 +0.77亿 = 反转初期 |
| **柯力业绩催化** | H1 +188%~+217% | 人形机器人主线 + 现价距高 -10.7% 还有空间 + 中性偏空评分是滞后指标 |
| **中信证券 H1 2026 前瞻** | 41 家公司入库 | 平均增速 +217.8% / +200% 以上 10 家 / 下滑 4 家 |
| **业绩弹性 TOP 5** | 兆易/木林森/新益昌/君正/露笑 | +1070%+~+627% 区间，均为 Convexity Plays 重仓候选 |
| **多主题篮子** | 13 主题 + 3 持仓 | 传感器 / 机器人 / AI算力 / PCB / 面板 / LED / 半导体 6 子类 |

### 交易信号（7/2 实战应用）

| 股 | 预测 | 趋势 | 建议 |
|---|---|---|---|
| **603662 柯力** | +188~+217% | 反转初期 | 7/3-7/5 流入信号确认后加仓 |
| **603986 兆易** | +1070~+1370% | Convexity 强 | 重仓博弈（PE 171 需谨慎）|
| **688256 寒武纪** | +126~+183% | AI 主题 | 中仓 |
| **002371 北方华创** | +30~+50% | 自主可控 | 中仓 |

## 7/1 实战数据快照

**实时扫盘记录**（2026-07-01 18:45 收尾）

| 场景 | 结果 | 关键发现 |
|---|---|---|
| 盘前预热 8:30 | 105/106 拉成功 | 002549 timeout 12.6s，hub webhook 收到推送（id=2） |
| 盘中扫半导体 10:42 | 82涨/55跌 | 均价 +0.74%，资金 +2.50亿 |
| AI 推理芯片 10:51 | 4 只表现 | 寒武纪 -4.11% 高位调整 |
| 光模块 10:42 | 14 只均价 -2.74% | 联特 +4.75% 异动（主现 0.01亿） |
| 潍柴动力 13:38-15:47 | 5/20/60 日资金流 | **半年机构 -43.17亿** 派发（修正"接盘"误判） |
| 证券 15:47 | 18 只均价 +4.55% | **6 月机构 +12.5亿 龙头建仓** |
| 人形机器人 16:43-17:06 | 25 只均价 +2.38% | 6 强股深挖：雷赛智能「机构 5日 +1.79亿」最稳健 |
| 材料板块 18:24 | 41 只均价 +1.20% | 化工 +3.62% 强， 稀土 -3.17% 弱 |
| 多氟多 18:39 | **60 日 +100%** | **20 日机构 -87.70亿出货** + 5日 +15.75亿 重新进场 |
| 雷赛智能 18:22 | 现价 57.48 | 5/10 日机构 +1.79/+2.40亿 |

**关键观察：**
1. 「**机构 5 日在买 vs 20 日仍在出货**」是市场普遍形态（多氟多 / 雷赛 / 联特 都是）
2. 「**价格已 price in**」是主要风险——多氟多 60 日 +100% / 250 日 +408%
3. 「**量价背离 -0.5 以下**」是另一重要信号（多氟多 10 日 -0.48）
4. 「**半年数据是真相，5 日数据是噪声**」—— 潍柴 5 日看似"接盘"实为 -43亿派发

---

## 7/1 产出的 3 个新数据资产

| 文件 | 内容 | 状态 |
|---|---|---|
| `data/supply_chains/humanoid_robot.json` | 25 只人形机器人供应链 | 本次 commit 追踪 |
| `data/supply_chains/semiconductor.json` | 106 只半导体产业链 | 本次 commit 追踪 |
| `data/supply_chains/materials.json` | 41 只材料板块（含 10 子类）| 本次 commit 追踪 |

**复用方式：**
```python
import json
data = json.loads(Path('data/supply_chains/semiconductor.json').read_text())
for s in data['stocks']:
    print(s['code'], s['name'], s['change_pct'])
```

**Mommy-hub 同步：** `~/Git/mommy-hub/data/chains/*.json` 同步保留，hub 3 个产业链页面直接读。


---

## 团长的话（产品方向）

团长在 2026-06-28 微信对话中明确指出：

> **核心定位**：用本地可编程主机能力，做一款**比券商 APP 更聚焦、更快、更主动**的行情陪伴工具。

**核心痛点**：
- 信息太多 → 单一屏幕只展示关心的数据
- 操作太复杂 → 一步到位
- 延迟高 → 本地直连 + 5 秒轮询

**两大场景**：
- **场景 A：观察盘面（发现新机会）** —— 已交付（盘面 Tab）
- **场景 B：管理仓位（细节决策）** —— 进行中（详情页驾驶舱待做）

> 完整讨论：`docs/DISCUSSION-NOTES.md`

---

## 相关文档

- `docs/DESIGN.md` — 架构 + 5 份 ADR
- `docs/LEDGER.md` — 逐条时间线（commit 级别）
- `docs/KLINE-SPEC.md` — K线技术规格
- `docs/DISCUSSION-NOTES.md` — 产品讨论纪要
- `README.md` — 快速上手