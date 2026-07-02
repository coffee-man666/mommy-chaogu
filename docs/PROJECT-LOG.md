# 项目总览 (PROJECT-LOG.md)

> mommy-chaogu 的**一站式总览文档**。M0 → M3.2.1 全链路串成一份，**新团队成员 / 未来自己**看完这一份就能拿到 80% 的项目上下文。
>
> 跟其他文档的关系（避免重复）：
> - **DESIGN.md** — 讲「为什么这样设计」（架构原则、5 份 ADR）
> - **LEDGER.md** — 讲「具体怎么走到这一步」（commit 级时间线，含验证数据）
> - **PROGRESS.md** — 讲「现在在哪儿」（当前架构 + 已完成 + 下一步）
> - **本文件** — 上面三份的「快速入口 + 一站式 narrative」
>
> 最后更新：2026-07-01（M7 Agent-Centric Phase 1-4，branch feature/agent-centric）

---

## TL;DR

| 维度 | 数据 |
|---|---|
| 项目阶段 | **M7 Agent-Centric Phase 1-4**（feature/agent-centric 分支） |
| 累计 commits | **15+** 推 main |
| 代码量 | **~16,600 行**（src 11000 + tests 2600 + web 3000） |
| 测试 | **217 个**（196 离线 + 9 实时网络 + 12 agent mock） |
| 代码质量 | ruff ✅ / mypy strict ✅ 0 errors |
| 数据源 | 东财（主）+ 腾讯（仅 quote 兜底） |
| 数据点 | 5 只自选股 + 106 只半导体产业链股 |
| 缓存 | `data/watchlist.db`（cache）+ `data/semicon.db`（产业链 reference） |
| 自动化 | 4 个 OpenClaw cron jobs（盘前预热/盘中监控/收盘日报/周报） |
| 微信推送 | Server酱 bot，目标 = 团长当前聊天 |
| AI Agent | 11 tools + AgentService（deepseek/openai/kimi）+ Web 对话页 |

---

## 1. 项目是什么

**妈妈炒股 / mommy-chaogu** — 给妈妈用的 A 股行情监控 + 投资陪伴工具。

**核心定位**（从一句话需求演化）：
> "妈妈想看自己持仓 + 关注的自选股实时行情 + 异动告警 + 每日复盘"。
> 后续扩展："还要能研究半导体产业链（106 只 A 股）的资金流"。

**为什么是这个工具**：
- 妈妈的金融工具盲区大 → 界面要极简（手机字号大、不用专业术语）
- 团长能写代码 → 自己造，不靠商业软件
- Mac mini 跑 cron → 自动化推送，不打扰团长

**用户分层**：
- 👩 **妈妈**（终端用户，看手机 H5）
- 👨 **团长**（开发者 + 高级用户，看 Web + 接收推送）
- 🤖 **京爷**（AI 助手，开发协作 + 自动化编排）

---

## 2. 关键里程碑（全链路）

> 时间倒序：M3.2.1 → M3.2 → M3.1 → M3.0 → M2.5 → M2 → M1.5 → M1 → M0

### M7（2026-07-01） — Agent-Centric 重构（Phase 1-4）🤖

**痛点**：7 条 if-else 规则没有语境感知，"主力净流入 8000万"在牛市是噪声在熊市是信号。

**对策**：引入 LLM agent 作为核心推理层，规则退居二线。

| Phase | 内容 | 文件 |
|---|---|---|
| 1 | 11 个 function-calling tools | agent/tools.py + market_data/sector_api.py |
| 2 | AgentService（LLM + tools 循环） | agent/service.py + agent/prompt.py |
| 3 | Agent 收盘日报 + CLI | agent/reports.py + cli.py (mommy-agent) |
| 4 | Web 对话页 | web/routes/agent.py + web/src/pages/agent/index.vue |

**设计要点**：
- 数据层完全不动（market_data / cache / flows 原样保留）
- 7 条 signals 规则保留为 fallback，不删
- Agent 工具中立：兼容 OpenAI / DeepSeek / Kimi（通过 AGENT_PROVIDER 环境变量切换）
- 无 API key 时优雅降级（Web 对话页返回"未配置"提示，不崩溃）
- WebSocket 流式回复（分 chunk 发送，打字机效果）

**新增 11 个工具**：get_quote / get_quotes / get_market_indexes / get_sector_ranking / search_sector / get_sector_stocks / get_money_flow_today / get_money_flow_history / get_bars / get_watchlist / get_portfolio

### M3.2.1（2026-06-29 17:30） — OpenClaw cron 自动化 🔧

**痛点**：人工每天手动跑 report + 推送 → 容易忘

**对策**：4 个 OpenClaw cron jobs（model=deepseek-flash 省 token）：

| 时间 | 名称 | Job ID | 推送 |
|---|---|---|---|
| 8:30 周一~五 | 盘前预热 | `f3fa79c8-…-b617e5830b17` | silent |
| 9:30 周一~五 | 盘中监控启动 | `f39f3cbc-…-28a2f5b1576b` | silent |
| 15:30 周一~五 | 收盘日报 | `94bd6c91-…-cdc4c0c89af7` | **推微信** |
| 周六 10:00 | 周报汇总 | `e902f385-…-db5d79634aa2` | **推微信** |

**关键设计点**：
- 监控进程用 `--max-seconds 19800`（5.5h）自动退出，比 cron pkill 干净
- 启动前 `pgrep` 幂等检查
- silent 启动不打扰，只 15:30 + 周六推送
- 推送目标 = 团长当前聊天（`openclaw-weixin` channel）

### M3.2（2026-06-29） — 资金流 ratio 监控 + 收盘日报 📊

**痛点**：团长反馈"阈值不能用绝对人民币值，要用市值比率"

**原因**：同样 5,000 万净流入对茅台（1.5 万亿）= 0.03bp（噪声），对凯美特气（144 亿）= 35bp（异动）—— 差 1000 倍。

**产出**：
- `flows/signals.py` — 4 条 ratio-based 默认规则（5min delta > 5bp/10bp 净流入/流出）
- `flows/monitor.py` — FlowMonitor 持续轮询 + 断点续传 + 失败告警
- `flows/report.py` — FlowReport 收盘日报（板块 ratio + TOP 10 + 矛盾股清单）
- ratio = `main_net / circulating_market_cap`

**5 条默认规则**：

| rule_id | 触发条件 | severity |
|---|---|---|
| `flow_in_spike` | 5min delta > 5bp 净流入 | WARN |
| `flow_in_surge` | 5min delta > 10bp 净流入 | CRIT |
| `flow_out_spike` | 5min delta > 5bp 净流出 | WARN |
| `flow_out_surge` | 5min delta > 10bp 净流出 | CRIT |

### M3.1（2026-06-29） — flows 拉新 + 排行（基础设施）🔌

**新模块**：`mommy_chaogu.flows` — 资金流拉新 + 排行 + 缓存

- `PoolSource` 抽象：把「拉哪几只」从「怎么拉」里解耦
  - `WatchlistPool`（5 只自选股）/ `SemiconPool`（106 只产业链）/ `CustomPool`（手动指定）
- `FlowService` 高层 API：`pull_today` / `pull_history` / `top_today` / `top_history` / `show` / `stats` / `clear`
- 复用 `CachedMarketDataAdapter`（节流 + Tencent fallback + cache 表）— **不重发明轮子**

**实战验证**：106 只 × today pull 13.5s（105/106 成功）+ 30d history pull 12.4s（106/106 成功）

### M3.0（2026-06-29） — 半导体产业链参考库 📚

**新模块**：`mommy_chaogu.semicon` — 106 只 A 股种子数据

**Schema**：一张表 `semicon_stocks`，三层粒度

| 字段 | 含义 |
|---|---|
| `code` | 股票代码（unique） |
| `chain_position` | 上游 / 中游 / 下游 / 末端 |
| `subcategory` | EDA / IP / 设备 / 材料 / 存储 / MCU / 处理器 / 模拟 / 射频 / 功率 / 传感器 / FPGA / 制造 / 封测 / 分销 |
| `product` | 具体产品（如「介质刻蚀」「NOR Flash」） |
| `board` | 主板 / 创业板 / 科创板 / 北交所 |

**CLI**：`mommy-semicon seed / list / search / get / stats / add / remove`

### M2.5（2026-06-27 凌晨 2 点） — TencentAdapter + FallbackAdapter 🛡️

**触发事件**：凌晨 2 点东财 push2 主动断（Empty reply），monitor 5/0 失败。

**对策**：加 `TencentAdapter`（qt.gtimg.cn）+ `FallbackAdapter` 多源兜底
- 腾讯 5/5 成功，5 只自选股 + 8 条信号全触发 ✅
- 17 新单测 + 修测试跨午夜硬编码日期 bug
- `CachedMarketDataAdapter(Fallback([Efinance, Tencent]))` 装饰器链顺序确认

### M2（2026-06-26 晚） — 时间戳驱动缓存 + 装饰器模式 💾

**新模块**：`mommy_chaogu.cache` — 5 张表 + 节流

| 表 | 用途 |
|---|---|
| `quote_cache` | 自选股实时报价 |
| `bar_cache` | K 线（按日期永久保留） |
| `today_money_flow_cache` | 当日资金流最新 |
| `money_flow_cache` | 历史资金流（按日期永久） |
| `market_snapshot_cache` | 全市场快照（保留 30 份） |

**核心设计**：
- **节流 vs TTL 分离**：节流只控制「拉新频率」，不决定「数据是否可用」
- **失败保留旧数据**：拉新失败 → 数据库照常能读，妈妈看得见新鲜度
- **装饰器模式**：`CachedMarketDataAdapter(base, store)` 包装任意 adapter

### M1.5（2026-06-26） — 7 条内置告警规则 + Alerter 🚨

- `flows_in_spike` / `flows_out_spike`（资金净流入/流出阈值）
- `price_change_threshold` / `gap_open` / `main_flow_threshold` / `volume_surge` / `turnover_surge` / `portfolio_breadth`
- Alerter 服务：每轮评估 → 写 `data/signals.log`

### M1（2026-06-26） — 自选池分组管理 + 实时监控 📋

- `WatchlistStore` ORM：Group + StockEntry（多对多）
- `Monitor` 服务：每轮拉 quote → 评估 signals → 写 monitor.log
- CLI：`mommy-watchlist add / list / groups / stats`

### M0（2026-06-26 上午） — 通用行情数据层 + efinance 适配器 🏗️

**项目骨架**：
- `market_data/types.py` — 11 个 `@dataclass(frozen=True)` + 4 个 `StrEnum`
- `market_data/adapter.py` — `MarketDataAdapter` Protocol（runtime_checkable）
- `market_data/efinance_adapter.py` — EfinanceAdapter（覆盖 11 路数据）

**支持数据**：实时报价 / 5档盘口 / K线 / Tick / 当日资金流 / 历史资金流 / 板块归属 / 全市场快照

---

## 3. 当前架构全景

```
┌────────────────────────────────────────────────────────────────┐
│  🤖 AI / Cron 编排（OpenClaw cron）                            │
│  ├─ 8:30 盘前预热                                               │
│  ├─ 9:30 启动监控（nohup + max-seconds 19800）                  │
│  ├─ 15:30 收盘日报 → 推微信                                     │
│  └─ 周六 10:00 周报汇总 → 推微信                                │
└────────────────┬───────────────────────────────────────────────┘
                 ↓ agentTurn prompt
┌────────────────────────────────────────────────────────────────┐
│  📱 妈妈手机 / 👨 团长浏览器                                   │
│  ├─ Web H5 (Vite + Vue 3)         ← 主动看                     │
│  ├─ WebSocket 实时推送                                           │
│  └─ 微信 Server酱推送              ← 被动收（每日 1-2 条）        │
└────────────────┬───────────────────────────────────────────────┘
                 ↓
┌────────────────────────────────────────────────────────────────┐
│  FastAPI（uvicorn :8000）                                      │
│  ├─ /api/* REST 端点（行情 / 自选 / 资金流 / 持仓）             │
│  ├─ /ws/* WebSocket（实时推送）                                 │
│  └─ BackgroundService（5s 轮询 + signal 评估 + 微信推送）       │
└────────────────┬───────────────────────────────────────────────────────┘
                 ↓
┌────────────────────────────────────────────────────────────────┐
│  🤖 Agent 层（LLM + 工具调用）                                 │
│  ├─ POST /api/agent/chat（单轮问答）                          │
│  ├─ WS /ws/agent（流式对话）                                   │
│  ├─ AgentService（deepseek/openai/kimi 可切换）                │
│  ├─ ToolRegistry（11 个工具：quote/sector/flow/bars/...）      │
│  └─ AgentReportService（agent 生成收盘分析日报）               │
└────────────────┬───────────────────────────────────────────────┘
                 ↓
┌────────────────────────────────────────────────────────────────┐
│  mommy-chaogu 核心模块                                         │
│  ├─ market_data：Quote/Bar/MoneyFlow 数据类                    │
│  ├─ monitor：snapshot + signals                                │
│  ├─ flows：ratio 信号 + 持续监控 + 收盘日报 ⭐                 │
│  ├─ semicon：106 只产业链 reference                            │
│  ├─ watchlist：5 只自选股 ORM                                  │
│  ├─ signals：7 条内置告警规则                                  │
│  ├─ cache：5 张缓存表 + 装饰器                                 │
│  └─ web：FastAPI + WebSocket                                   │
└────────────────┬───────────────────────────────────────────────┘
                 ↓ CachedMarketDataAdapter (Fallback [E, T])
┌────────────────────────────────────────────────────────────────┐
│  数据源                                                         │
│  ├─ 东财 push2.eastmoney.com（主，全功能）                     │
│  └─ 腾讯 qt.gtimg.cn（仅 quote 兜底，资金流没有）             │
└────────────────────────────────────────────────────────────────┘
```

---

## 4. 数据流（资金流为例） ⭐

```
【盘前 8:30 cron】
mommy-flows pull --target all --force
  └─ FlowService.pull_today(SemiconPool, force=True)
  └─ FlowService.pull_history(SemiconPool, days=30, force=True)
     └─ 对每只 code:  CachedMarketDataAdapter.get_today_money_flow / get_history_money_flow
        ├─ 节流检查（force=True 重置，所以一定真打接口）
        ├─ FallbackAdapter 内部：先 Efinance → 失败用 Tencent（资金流永远走 Efinance）
        └─ 写缓存：today_money_flow_cache + money_flow_cache（key=code+date）

【盘中 9:30 - 15:00 cron】
nohup mommy-flows run --interval 300 --max-seconds 19800
  └─ 每 300s 循环：
     ├─ pool.codes() → 106 只
     ├─ service.get_market_caps(codes) → 拿流通市值（force reset 节流）
     │   └─ 内部调 get_quote → 写 quote_cache
     ├─ adapter.get_today_money_flow(code) → 最新一条（节流，5min 一次）
     ├─ 构造 StockSnapshot(code, name, main_net, float_market_cap)
     ├─ ratio = main_net / float_market_cap
     ├─ 与上一轮 ratio 比 → delta_ratio
     ├─ evaluate(snapshots, prev_ratios, rules) → 触发的 signals
     ├─ 写 data/flows_monitor.log（结构化）
     ├─ 更新 state：data/.flow_monitor_state.json
     └─ sleep 300

【收盘 15:30 cron】
mommy-flows report --day $(date +%F)
  └─ FlowReport.generate(pool, day, output=data/flows_report_YYYY-MM-DD.md)
     ├─ 读 today_money_flow_cache + money_flow_cache + quote_cache
     ├─ 当日：每只 stock 取 today 最新一条 → ratio
     ├─ 30d：每只 stock 按 trade_date 取每日最后一条累加 → ratio
     ├─ 板块汇总（上游/中游/下游/末端 ratio 合计）
     ├─ TOP 10 流入 / TOP 10 流出（按 ratio）
     └─ 矛盾股清单：今日 ratio>0 但 30d ratio<0

【推送 15:30】
agentTurn prompt 提取关键指标 → 微信推送
  └─ 板块 4 行 + TOP 3 流入 + TOP 3 流出 + 矛盾股 TOP 3 + 文件路径
```

---

## 5. 设计原则（沉淀的）

### 数据层
- **Protocol + runtime_checkable** — 不用抽象基类，duck typing
- **dataclass(frozen=True, slots=True)** — 不可变 + 省内存
- **Decimal 而非 float** — 金额一律 Decimal
- **StrEnum 而非 enum** — 字符串兼容 + IDE 提示

### 缓存层
- **节流 ≠ TTL** — 节流控制「拉新频率」，TTL 控制「数据是否过期」
- **失败保留旧数据** — 拉新失败不删 cache，妈妈看得见新鲜度
- **装饰器链** — `CachedMarketDataAdapter(FallbackAdapter(base))` 可读可拆
- **timestamp 是真相** — 记录 `fetched_at`（我们什么时候拉的）和 `quote_ts`（数据自身时间）

### ratio 信号 ⭐
- **相对市值比率而非绝对人民币** — 消除大票小票偏差（茅台 vs 凯美特气差 1000 倍）
- **bp = 1/10000** — 流通市值的 0.01%
- **5bp WARN / 10bp CRIT** — 经验值，跑两天观察触发频率再调

### 工程实践
- **KISS / DRY / YAGNI / SOLID** — 不过度抽象
- **Conventional Commits** — `feat / fix / docs / refactor / chore`
- **ruff + mypy --strict** — 质量门
- **测试金字塔** — 大量单元 + 适量集成 + 少量 E2E
- **subagent 并行** — 团长喜欢，但任务要真独立才并行

### Agent 层 ⭐
- **工具中立** — ToolRegistry 包装现有 adapter，不耦合具体 LLM provider
- **规则退居二线** — 7 条 if-else 保留为 fallback，默认路径走 agent 推理
- **system prompt 内嵌分析原则** — bp 比率思维、量价关系、板块联动，但以"参考"表达
- **无 API key 优雅降级** — 不崩溃，返回提示文本

---

## 6. 关键决策日志（ADR 摘要）

| ID | 决策 | 原因 |
|---|---|---|
| D-01 | Protocol 而非 ABC | duck typing，避免继承耦合 |
| D-02 | Decimal 而非 float | 金额精度 |
| D-03 | 时区戳 UTC 存储 | 避免时区 bug |
| D-04 | 装饰器链缓存 | 可读、可拆、可单测 |
| D-05 | 失败保留旧数据 | 数据永远不"消失" |
| D-06 | ratio-based 信号 | 消除大票小票偏差（团长反馈） |
| D-07 | 资金流缓存落 watchlist.db | 缓存按 code 维度，跨池复用 |
| D-08 | OpenClaw cron 而非 shell cron | 集成 delivery + 监控 + agentTurn |

---

## 7. 实战数据沉淀（2026-06-29 收盘）

### API 稳定性摸底

**东财资金流**（唯一可用源）：
- 单只连续 10 次 today：10/10 ✅，0.15s/次
- 10 只 batch × 5 轮：50/50 ✅，1.22s/轮
- 20 轮持续轮询：20/20 ✅，2.29s/轮
- 5min 节奏推算：106 只 × 0.13s = 13.5s/轮，**富余 22 倍**
- 弱点：收盘后 15:00-15:30 可能有 30s 数据空窗

**腾讯资金流**：
- ❌ **没有**资金流接口（qt.gtimg.cn 无此 API）
- `get_today_money_flow` / `get_history_money_flow` 是 stub，永远返回 `[]`
- **含义**：资金流没有兜底，东财挂了 = 资金流断供

### 半导体产业链 6/29 实战

**板块 ratio**：上游 +14.3bp / 中游 +10.1bp / 末端 -25.0bp / 下游 -77.4bp

**TOP 流入（按 ratio）**：
1. 凯美特气（材料）+358bp
2. 聚辰股份（存储）+127bp
3. 深科技（封测）+104bp

**TOP 流出（按 ratio）**：
1. 晶方科技（封测）-191bp
2. 长电科技（封测）-161bp
3. 华天科技（封测）-156bp

**矛盾股 15 只**（今日 ratio>0 但 30d ratio<0）：
- **澜起科技**（30d -73亿 → 今日 +22亿）— 最大反转信号
- **兆易创新**（30d -59亿 → 今日 +4.4亿）⚠️ 团长自选股
- 深科技、士兰微、斯达半导、紫光国微

---

## 8. 当前状态（2026-06-29）

### ✅ 已完成

- **M0-M3.2.1** 全部完成（详见 LEDGER.md）
- 4 个 cron jobs 调度已上线（盘前/盘中/收盘/周报）
- 15+ commits 推 main
- 154 个测试（145 离线 + 9 网络）
- ruff + mypy --strict 全绿
- 资金流 ratio 信号 + 收盘日报实战验证（6/29 数据有效）

### ⏳ 进行中

- 等待 6/30 第一次 cron 完整跑通（盘前预热 8:30 / 监控启动 9:30 / 收盘日报 15:30 / 周报 7/4）
- 等待 15:30 第一次微信推送成功

### 📋 待办（按优先级）

1. **验证整条 cron 链路**（6/30 周二）
2. **调 ratio 阈值** — 跑两天看触发频率，太频繁就调高
3. **GitHub Actions CI** — P0 一直没做（ruff + mypy + pytest）
4. **pytest -m live 标记** — 区分离线/网络测试
5. **信号日志汇总** — 每个交易日收盘后统计本日触发了几条 spike/surge
6. **风险提示规则** — 涨停/跌停/异动 → 接到 monitor

---

## 9. 文档索引

| 文档 | 用途 | 何时看 |
|---|---|---|
| **本文件 PROJECT-LOG.md** | 一站式总览 | 第一次接触项目 / 想看全貌 |
| [DESIGN.md](DESIGN.md) | 架构 + 5 份 ADR | 设计讨论 / 改架构前 |
| [LEDGER.md](LEDGER.md) | commit 级时间线 | 想知道某次 commit 干了啥 |
| [PROGRESS.md](PROGRESS.md) | 当前状态 + 下一步 | 每个 sprint 开始 |
| [KLINE-SPEC.md](KLINE-SPEC.md) | K 线组件规范 | 改 K 线 UI 时 |
| [DISCUSSION-NOTES.md](DISCUSSION-NOTES.md) | 讨论笔记 | 找回历史决策上下文 |
| [WEB-UI-PROPOSAL.md](WEB-UI-PROPOSAL.md) | Web UI 设计提案 | 改 UI 设计时 |
| [README.md](../README.md) | 快速上手 + CLI 速查 | 第一次跑命令 |

---

## 10. 给未来自己的提醒

### 易踩的坑（从实战中学到的）

- **东财 push2 接口在凌晨 2-3 点会主动断**（2026-06-27 实测）→ 靠 Tencent 兜底
- **中午 12:30-13:00 高峰**东财接口会整体抽风 → 代码容错处理
- **`list_market_quotes()` 全市场扫描在监控模式下挂** → 改用 `get_quotes(codes)`
- **`get_latest_quote(code) 冷启动超时** → 改用全市场 + filter
- **5档盘口字段名是 `买1价/买1数量`**，不是 `买1/买1量`
- **下午收盘 15:00 后 30s 内资金流接口空数据** → 正常，等收盘结算

### 仍需小心

- 本机没有 Docker，DB 集成测试暂时跑不了
- GitHub 网络偶尔不稳定，clone 大仓库可能超时
- memory_search 索引需要重建（embedding provider 变了）

### 价值观

- 妈妈是终端用户，不是「会写代码的人」→ UI 永远要简单
- 团长能写代码 → 不靠商业软件，自己造
- 京爷（我）协作而非替代 → 写代码 + 自动化 + 解释，不直接做用户的金融决策