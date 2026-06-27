# 妈妈炒股 (mommy-chaogu)

> 给妈妈用的行情监控和投资陪伴工具。
>
> **从「行情监控」切入，逐步扩展到「复盘 + 推送 + 风险提示」**。

## 目标

- ✅ **M0** — 行情数据层（实时报价 / K线 / 资金流 / 板块）
- ✅ **M1** — 自选池 + 实时监控
- ✅ **M1.5** — 7 条内置告警规则
- ✅ **M2** — 时间戳驱动缓存
- ✅ **M2.5** — 多数据源 fallback（东财 + 腾讯）
- ✅ **M3.0** — Web UI（Vite + Vue 3 + FastAPI + WebSocket，妈妈手机可用）
- ✅ **M3.1** — Server酱 微信推送（信号主动推妈妈微信）
- ⏳ **M3+** — 复盘报告 / 风险提示 / PWA / CI

详见 [`docs/PROGRESS.md`](docs/PROGRESS.md)

## 文档体系

| 文档 | 解决什么问题 |
|---|---|
| [`docs/PROGRESS.md`](docs/PROGRESS.md) | 现在在哪？做完什么？还差什么？ |
| [`docs/DESIGN.md`](docs/DESIGN.md) | 为什么这样设计？架构、原则、ADR |
| [`docs/LEDGER.md`](docs/LEDGER.md) | 怎么走到这一步的？commit 级别时间线 |

## 架构原则

- **接口先行**：所有数据源（efinance / 腾讯 / 自爬）走统一 `MarketDataAdapter` Protocol
- **dataclass 化**：行情数据用 `@dataclass(frozen=True)` 定义，金额一律 `Decimal`
- **降级优先**：第三方接口挂了要能优雅 fallback（`FallbackAdapter` + 缓存层双保险）
- **数据库是唯一真相源**：拉新失败 → 静默 fallback 到旧数据，妈妈无感

详见 [`docs/DESIGN.md`](docs/DESIGN.md)

## 项目结构

```
mommy-chaogu/
├── docs/
│   ├── DESIGN.md        # 架构 + 5 份 ADR
│   ├── LEDGER.md        # 5 个 milestone 逐条时间线
│   └── PROGRESS.md      # 当前进度 + 下一步
├── src/mommy_chaogu/
│   ├── market_data/     # 数据源适配层
│   │   ├── types.py             # 11 个 dataclass + 4 个 StrEnum
│   │   ├── adapter.py           # MarketDataAdapter Protocol
│   │   ├── efinance_adapter.py  # 东方财富（主力）
│   │   ├── tencent_adapter.py   # 腾讯财经（备力）
│   │   └── fallback_adapter.py  # 多源 fallback 装饰器
│   ├── watchlist/       # 自选池（SQLite + SQLAlchemy 2.0）
│   ├── monitor/         # 监控（snapshot / 持续轮询）
│   ├── signals/         # 7 条告警规则 + Alerter
│   ├── cache/           # 装饰器链（5 张表 + 节流 + freshness）
│   ├── web/             # FastAPI 后端（Web UI 服務）
│   ├── push/            # Server酱 微信推送（Pusher/Deduper Protocol）
│   └── cli.py           # argparse 入口
├── web/                 # Vite + Vue 3 前端（H5 / 手机友好）
├── tests/               # 154 测试（145 离线 + 9 实时网络）
├── scripts/
│   ├── smoke_market_data.py  # 行情冒烟
│   ├── demo_signals.py       # 信号 mock 演示
│   └── demo_cache.py         # 缓存 mock 演示
└── data/                # 运行时数据（不入库）
    ├── watchlist.db
    ├── monitor.log
    ├── signals.log
    └── pushed.json      # Server酱 去重记录（自动生成）
```

## 快速上手

```bash
uv sync --extra dev      # 安装依赖

# 自选股管理
uv run mommy-watchlist add-group 持仓
uv run mommy-watchlist add 600519 --group 持仓
uv run mommy-watchlist list

# 行情监控（snapshot 一次 / run 持续轮询）
uv run mommy-monitor snapshot
uv run mommy-monitor run          # Ctrl+C 退出

# 缓存管理
uv run mommy-cache stats          # 命中率 + 新鲜度
uv run mommy-cache warmup         # 盘前预热
uv run mommy-cache refresh        # 强制刷新

# Web UI 服务（手机访问 http://<host>:8765/）
uv run mommy-web --port 8765 --poll-interval 3
# 带 Server酱 微信推送
export SERVER_CHAN_KEY="SCT123xxx"
export WEB_BASE_URL="https://mommy.example.com"
uv run mommy-web --port 8765

# 开发
uv run pytest                      # 跑测试（154）
uv run ruff check .                # lint
uv run mypy src                    # type check (--strict)
```

## CLI 速查

```
mommy-chaogu
├── mommy-watchlist    # 自选股管理
│   ├── add-group / remove-group / groups
│   └── add / remove / list / stats
├── mommy-monitor      # 行情监控
│   ├── snapshot / run / log
│   └── signals / rules
├── mommy-cache        # 缓存管理
│   ├── stats / warmup / refresh / clear
│   └── snapshots / config
└── mommy-web          # Web 服务（手机 UI + WS 推送）
    └── --port / --poll-interval / --server-chan-key / --web-base-url
```

## 📱 Web UI 使用（妈妈手机）

```bash
# 启动服务（默认 0.0.0.0:8000）
uv run mommy-web --port 8765 --poll-interval 3

# 手机浏览器访问
http://<mac-mini-ip>:8765/
# 例：http://192.168.10.84:8765/
```

4 个页面：
- **首页** — 5 只自选股 + 主力合计 + 涨跌统计 + WebSocket 实时推送
- **详情** — K 线（klinecharts）+ MA5/10/30/60 + 5 档盘口 + 资金流
- **信号** — 触发历史（点跳详情页 K 线）
- **设置** — 服务状态 + 缓存命中率 + 自选股 CRUD

## 🔔 Server酱 微信推送

**目的**：信号触发后主动推妈妈微信，妈妈不用打开 Web。

**一次性配置**：

1. 微信扫码关注公众号「[Server酱³](https://sct.ftqq.com/)」（同一个公众号就能接多个 SendKey）
2. 登录 https://sct.ftqq.com/ 拿 SendKey（以 `SCT` 开头）
3. 启动服务时传入：

```bash
# 推荐：环境变量
export SERVER_CHAN_KEY="SCT123xxx"
export WEB_BASE_URL="http://192.168.10.84:8765"   # 推送消息里的「查看详情」链接
uv run mommy-web --port 8765
```

**推送规则**：
- 只推 `WARNING` + `CRITICAL` 信号（INFO 太多刷屏）
- 同一 `(股票代码, 规则ID, 日期)` 同一天只推 1 次（JSON 去重）
- 免费版限额 5 条/天（VIP ¥9/月 无限）
- **没配置 SendKey → 完全不推送，Web 服务照常运行**

**推送内容示例**：

```
🚨 CRIT 600519 贵州茅台

主力净流入警告
· 主力净额：1.2 亿（阈值 8000 万）
· 现价：1680.50 (+1.85%)
· 时间：2026-06-27 14:32:15

[查看详情](http://192.168.10.84:8765/#/detail/600519)
```

## 关键技术指标

| 指标 | 值 |
|---|---|
| 代码量 | ~12000 行（src 7300 + tests 2270 + web Vite 2000 + scripts 391） |
| 测试 | **154**（145 离线 + 9 实时网络） |
| ruff | ✅ All checks passed |
| mypy --strict | ✅ 0 errors |
| pytest | ✅ 145 passed / 9 flaky live |
| 数据源 | 2（efinance 主 + tencent 备） |
| CLI 子命令 | 4 子应用 / 18 子命令 |
| 业务规则 | 7 |
| 数据库表 | 8 + 推送去重 1 |
| Web 端点 | 14 REST + 2 WebSocket |
| 推送渠道 | Server酱³（微信） |

## 当前里程碑

**M3.1 完成（2026-06-27 22:35）**。
- M3.0 Web UI（Vite + Vue 3 + FastAPI + WS）：妈妈手机访问 `http://192.168.10.84:8765/` 可用
- M3.1 Server酱 推送：信号触发主动推妈妈微信（等团长拿到 SendKey 实测）

下一步：**后端 web 单测 + 复盘报告 + CI 配置**。

## License

Private（暂不开源）
