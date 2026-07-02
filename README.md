# 妈妈炒股 (mommy-chaogu)

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.12+](https://img.shields.io/badge/python-3.12+-blue.svg)](https://www.python.org/downloads/)
[![Tests](https://img.shields.io/badge/tests-270%20passed-brightgreen.svg)](#测试)
[![Code style: ruff](https://img.shields.io/badge/code%20style-ruff-000000.svg)](https://github.com/astral-sh/ruff)
[![Type check: mypy strict](https://img.shields.io/badge/mypy--strict-0%20errors-blue.svg)](https://mypy-lang.org/)

> 给妈妈用的 **A 股行情监控 + 投资陪伴** 工具。
> 从「行情监控」切入，逐步扩展到「资金流 / 产业链 / 财报 / 推送 / 风险提示」。

妈妈不需要成为技术专家，妈妈的手机应该比基金经理的彭博终端更懂她 —— 这是这个项目的初衷。

---

## ✨ 为什么做这个

- 妈妈 50 多岁开始学炒股，但行情软件太复杂（5 档盘口 + Level-2 + 各种技术指标）
- 主力资金动向（A 股最关键的信息）散落在各种研报、论坛、付费软件里
- 妈妈应该在**收盘后**做决策，不是在交易时段盯盘
- 中报 / 季报窗口是 A 股 alpha 的关键节点，但预告日期 + 实际值对比都是手动跟踪

**解决方案**：一个为妈妈定制的 Python 工具集，提供：
1. 实时行情 + K 线 + 资金流（手机 Web 可访问）
2. 多源 fallback（东财主 + 腾讯备）
3. 信号告警 + 微信推送（妈妈不用主动打开）
4. 财报窗口的预告 vs 实际比对系统
5. 业绩弹性 / 板块轮动 / 配对交易的多维分析

---

## 🚀 核心特性

| 能力 | 实现 |
|---|---|
| **实时行情** | 报价 / K 线 / 5档盘口 / 大盘指数 / 板块榜 |
| **资金流** | 日内分时累计 + 历史日级 + 流通市值比率 (bp) |
| **多源 fallback** | efinance → tencent → cached（无感降级）|
| **自选股** | SQLite + SQLAlchemy 2.0，按主题分组（M:N 支持）|
| **信号告警** | 7 条内置规则（price / flow / portfolio / ...）|
| **微信推送** | Server酱³，阈值过滤 + JSON 去重 |
| **Web UI** | Vite + Vue 3 + FastAPI，手机访问 |
| **财报窗口** | 业绩前瞻入库 + actual vs predicted 自动打分 |
| **OpenClaw cron** | 4 个自动化 jobs（盘前 / 盘中 / 收盘 / 周报）|
| **质量门** | ruff + mypy --strict + 270 个测试 |

---

## 📦 快速上手

```bash
# 1. 安装（需要 Python 3.12+）
git clone https://github.com/coffee-man666/mommy-chaogu.git
cd mommy-chaogu
uv sync --extra dev

# 2. 自选股分组管理
uv run mommy-watchlist add-group 白酒 --description "持仓分组"
uv run mommy-watchlist add 600519 --group 白酒
uv run mommy-watchlist list

# 3. 实时监控（持续轮询，按 Ctrl+C 退出）
uv run mommy-monitor snapshot    # 一次快照
uv run mommy-monitor run         # 持续 5min 轮询

# 4. Web UI（手机可访问）
uv run mommy-web --port 8765 --poll-interval 3
# → http://<host>:8765/

# 5. 财报窗口分析（7/15-8/31 实战）
uv run mommy-earnings pull --codes 603662,603986 --period "H1 2026"
uv run mommy-earnings score --period "H1 2026"
uv run mommy-earnings summary --period "H1 2026"

# 6. 资金流扫描（板块维度）
uv run mommy-flows pull --pool semicon --days 30
uv run mommy-report render --chain humanoid_robot
```

---

## 🏗️ 架构

```
┌────────────────────────────────────────────────────────────┐
│  Web UI (Vite + Vue 3)                                     │
│  ├─ 首页 (5 只自选 + 主力合计 + WebSocket)                 │
│  ├─ 详情 (klinecharts K线 + 5档 + 资金流)                  │
│  ├─ 板块扫描 (沪深 + 行业 + 概念)                          │
│  ├─ 信号中心 (实时告警列表)                                │
│  └─ 设置 (服务状态 + 缓存命中率 + 自选股 CRUD)             │
└────────────────────┬───────────────────────────────────────┘
                     │ HTTP / WebSocket
                     ↓
┌────────────────────────────────────────────────────────────┐
│  FastAPI (uvicorn :8765)                                    │
│  ├─ /api/* REST (20+ 端点)                                 │
│  ├─ /ws/* WebSocket                                         │
│  └─ BackgroundService (5s 轮询 + SignalNotifier)            │
└────────────────────┬───────────────────────────────────────┘
                     │
   ┌─────────────────┼─────────────────┐
   ↓                 ↓                 ↓
┌────────┐    ┌────────────┐    ┌──────────┐
│ Cache  │ →  │ Adapter    │ →  │ Data     │
│ Layer  │    │ Fallback   │    │ Sources  │
│ SQLite │    │ (Protocol) │    │ • efin   │
│ 5 表   │    │            │    │ • tencent│
└────────┘    └────────────┘    │ • cninfo │
                                 └──────────┘
```

### 核心设计原则

1. **接口先行 (Protocol-first)**：所有数据源走 `MarketDataAdapter` Protocol，加新数据源只需实现 Protocol
2. **dataclass 化**：行情数据用 `@dataclass(frozen=True, slots=True)` 定义，金额一律 `Decimal`
3. **降级优先 (Graceful degradation)**：第三方接口挂了 → 缓存兜底 → 妈妈无感
4. **数据库是唯一真相源**：拉新失败保留旧数据，从不主动清空
5. **测试金字塔**：大量离线单元测试 + 少量网络集成测试（`@pytest.mark.network`）

---

## 📊 功能模块

### 数据层

| 模块 | 行数 | 说明 |
|---|---|---|
| `market_data/` | ~1500 | efinance / tencent / fallback 三种 adapter |
| `cache/` | ~900 | SQLite + 装饰器链 + 节流 + freshness |
| `watchlist/` | ~600 | SQLite + SQLAlchemy 2.0，自选分组 |

### 业务层

| 模块 | 行数 | 说明 |
|---|---|---|
| `flows/` | ~1200 | 资金流 ratio 监控 + 板块扫描 + 收盘日报 |
| `signals/` | ~700 | 7 条内置告警规则 + Alerter |
| `earnings/` | ~1900 | 业绩前瞻 + actual vs predicted 自动打分 |
| `semicon/` | ~400 | 半导体产业链种子库（106 只）|

### 服务层

| 模块 | 行数 | 说明 |
|---|---|---|
| `monitor/` | ~500 | snapshot + 持续轮询 |
| `web/` | ~1500 | FastAPI + 20 REST + 2 WebSocket |
| `push/` | ~300 | Server酱 推送 + 去重 |
| `report_render/` | ~600 | 报告 HTML 渲染 |

---

## 🎯 财报窗口实战（新模块）

> 中报 / 季报窗口（7/15-8/31）是 A 股 alpha 的关键节点。这个项目内置了完整的实战流水线。

### 工作流

```
1. 业绩前瞻入库
   scripts/load_earnings_preview.py
   → data/earnings_preview.db（券商预测 41 家公司）

2. 主题分组
   scripts/seed_thematic_groups.py
   → watchlist.db 13 个主题组

3. 实际披露拉取（7/15 起）
   uv run mommy-earnings pull --codes 603662 --period "H1 2026"
   → ef.stock.get_all_company_performance() 实时数据

4. 实际 vs 预测打分
   uv run mommy-earnings score --period "H1 2026"
   → data/earnings_actual.db
   → 4 种 verdict: SUPER_BEAT / BEAT / MEET / MISS / DEEP_MISS

5. 信号触发
   uv run mommy-earnings watch --days 7
   → T-7 警示 + 超预期 / 低于预期 即时告警
```

### 4 大实战策略（详见 [`docs/EARNINGS-HANDBOOK.md`](docs/EARNINGS-HANDBOOK.md)）

1. **超预期交易**：T+1 9:30-9:35 行动窗口，70% 跳空开盘
2. **Convexity Plays**：预测 +200% 以上的标的具备期权式 payoff
3. **板块内配对**：AI 算力 long 寒武纪 / short 海光
4. **板块轮动**：半导体 / 面板 / LED 超配，消费电子低配

---

## 🛠️ CLI 速查（9 个子应用）

```
mommy-chaogu
├── mommy-watchlist    # 自选股管理（按主题分组）
├── mommy-monitor      # 实时监控（snapshot / 持续轮询）
├── mommy-cache        # 缓存管理（命中率 / warmup / refresh）
├── mommy-report       # 报告渲染（HTML）
├── mommy-flows        # 资金流拉新 + 板块扫描
├── mommy-semicon      # 半导体产业链查询
├── mommy-earnings     # 财报前瞻 vs 实际 比对 ⭐ 新增
└── mommy-web          # Web 服务（手机 UI + WS）
```

---

## 📱 Web UI

```bash
uv run mommy-web --port 8765 --poll-interval 3
```

手机浏览器访问 `http://<host>:8765/`。

**4+ 个页面**：
- **首页** — 自选股 + 主力合计 + 涨跌统计 + WebSocket 实时推送
- **详情** — K 线（klinecharts）+ MA5/10/30/60 + 资金流 5 维图表
- **板块扫描** — 沪深 + 行业 + 概念，30 秒轮询
- **信号中心** — 触发历史（点跳详情页 K 线）
- **设置** — 服务状态 + 缓存命中率 + 自选股 CRUD

---

## 📡 数据源

| 数据源 | 用途 | 接口 |
|---|---|---|
| **东方财富 (efinance)** | 主力数据源（行情 / K 线 / 资金流 / 业绩）| `ef.stock.*` |
| **腾讯财经 (Tencent)** | 备援（行情）| `qt.gtimg.cn` |
| **巨潮资讯 (cninfo)** | 公告日历 | `hisAnnouncement/query` |

多源 fallback 装饰器链：`CachedMarketDataAdapter(FallbackAdapter([EfinanceAdapter, TencentAdapter]))`

> ⚠️ efinance 凌晨 2-3 点会主动断（东财服务器维护），fallback 自动接管

---

## 🔔 Server酱 微信推送（可选）

```bash
export SERVER_CHAN_KEY="SCT2*****"
export WEB_BASE_URL="http://192.168.10.84:8765"
uv run mommy-web --port 8765
```

**推送规则**：
- 只推 WARNING + CRITICAL（INFO 太多刷屏）
- 同一 `(股票代码, 规则ID, 日期)` 同一天只推 1 次（JSON 去重）
- 免费版 5 条/天，VIP ¥9/月无限

---

## ⏰ OpenClaw 自动化（4 个 cron jobs）

| 时间 | 任务 | 行为 |
|---|---|---|
| 周一~五 8:30 | 盘前预热 | 拉全市场资金流 / warmup 缓存 |
| 周一~五 9:30 | 盘中监控启动 | 启动 `mommy-monitor run --max-seconds 19800` |
| 周一~五 15:30 | 收盘日报 | 渲染 HTML + 推微信 |
| 周六 10:00 | 周报汇总 | 复盘一周实战 |

详细配置见 [`docs/`](docs/) 下的对应文档。

---

## 📚 文档体系（7 份）

| 文档 | 用途 |
|---|---|
| **[`docs/PROJECT-LOG.md`](docs/PROJECT-LOG.md)** | 🆕 一站式总览（新人 / 未来自己 必读）|
| [`docs/PROGRESS.md`](docs/PROGRESS.md) | 当前进度 + 下一步优先级 |
| [`docs/DESIGN.md`](docs/DESIGN.md) | 架构 + 5 份 ADR |
| [`docs/LEDGER.md`](docs/LEDGER.md) | commit 级别时间线 |
| **[`docs/EARNINGS-HANDBOOK.md`](docs/EARNINGS-HANDBOOK.md)** | 🆕 2026 中报窗口实战手册 |
| [`docs/KLINE-SPEC.md`](docs/KLINE-SPEC.md) | K 线组件规范 |
| [`docs/DISCUSSION-NOTES.md`](docs/DISCUSSION-NOTES.md) | 历史决策上下文 |

---

## 🧪 开发

### 安装开发依赖

```bash
uv sync --extra dev
```

### 跑测试

```bash
# 离线测试（270 个，应该全过）
uv run pytest -m "not network"

# 网络测试（需要联网，标记 network）
uv run pytest -m network

# 全部
uv run pytest

# 单个模块
uv run pytest tests/earnings/ -v
```

### 代码质量门

```bash
uv run ruff check .             # lint
uv run ruff format .            # format
uv run mypy --strict src        # type check
```

### 项目结构

```
mommy-chaogu/
├── src/mommy_chaogu/
│   ├── market_data/      # 数据源适配层
│   ├── cache/            # SQLite 缓存
│   ├── watchlist/        # 自选股 ORM
│   ├── monitor/          # 实时监控
│   ├── signals/          # 告警规则
│   ├── flows/            # 资金流
│   ├── earnings/         # 财报比对 ⭐
│   ├── semicon/          # 半导体产业链
│   ├── web/              # FastAPI 后端
│   ├── push/             # 微信推送
│   ├── report_render/    # 报告 HTML
│   └── cli.py            # CLI 入口
├── web/                  # Vite + Vue 3 前端
├── tests/                # 270 个测试
├── docs/                 # 7 份文档
├── scripts/              # loader 脚本
├── data/                 # 运行时数据（不入库）
├── supply_chains/        # 产业链数据资产
├── reports/              # 实战产物
└── pyproject.toml        # 项目配置
```

---

## 🤝 贡献

欢迎 PR / Issue！

**PR 流程**：
1. fork → branch (`feat/xxx` 或 `fix/xxx`)
2. 写测试（保持覆盖率）
3. `uv run ruff format . && uv run ruff check . && uv run mypy --strict src`
4. `uv run pytest -m "not network"` 全过
5. commit（`feat:` / `fix:` / `docs:` 前缀）→ push → PR

**Issue 模板**：见 `.github/ISSUE_TEMPLATE/`

---

## 📜 License

[MIT](LICENSE) © 2026 coffee-man666

---

## 🙏 致谢

- [efinance](https://github.com/Micro-sheep/efinance) — 主力行情数据源
- [腾讯财经](https://qt.gtimg.cn/) — 备援数据源
- [巨潮资讯](http://www.cninfo.com.cn/) — 公告数据
- [FastAPI](https://fastapi.tiangolo.com/) + [Vite](https://vitejs.dev/) + [Vue 3](https://vuejs.org/)
- [Server酱³](https://sct.ftqq.com/) — 微信推送
- [OpenClaw](https://github.com/openclaw/openclaw) — 多 agent 调度

---

## 📈 项目数据

| 指标 | 值 |
|---|---|
| 代码量 | ~16,000 行（src 11,300 + tests 4,100 + web ~800 + scripts 600 + docs 1,000）|
| 测试 | **270 passed**（247 离线 + 23 网络 marked）|
| ruff | ✅ All checks passed |
| mypy --strict | ✅ 0 errors |
| 数据源 | 3（efinance / tencent / cninfo）|
| CLI 子应用 | 9 / 子命令 30+ |
| 业务规则 | 7（signals）+ 4（earnings）|
| 数据库表 | 13+ |
| Web 端点 | 20+ REST + 2 WebSocket |
| Push 渠道 | Server酱³（微信）|

---

**⚠️ 免责声明**：本项目仅供学习和个人投资参考，不构成任何投资建议。A 股投资有风险，入市需谨慎。