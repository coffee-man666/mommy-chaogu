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
- ⏳ **M3+** — 复盘报告 / 微信推送 / 风险提示 / Web UI

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
│   └── cli.py           # argparse 入口
├── tests/               # 125 测试（119 离线 + 6 实时网络）
├── scripts/
│   ├── smoke_market_data.py  # 行情冒烟
│   ├── demo_signals.py       # 信号 mock 演示
│   └── demo_cache.py         # 缓存 mock 演示
└── data/                # 运行时数据（不入库）
    ├── watchlist.db
    ├── monitor.log
    └── signals.log
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

# 开发
uv run pytest                      # 跑测试（125）
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
└── mommy-cache        # 缓存管理
    ├── stats / warmup / refresh / clear
    └── snapshots / config
```

## 关键技术指标

| 指标 | 值 |
|---|---|
| 代码量 | ~6900 行（src 4593 + tests 1891 + scripts 391） |
| 测试 | **125**（119 离线 + 6 实时网络） |
| ruff | ✅ All checks passed |
| mypy --strict | ✅ 0 errors |
| pytest | ✅ 119 passed / 6 flaky live |
| 数据源 | 2（efinance 主 + tencent 备） |
| CLI 子命令 | 14 |
| 业务规则 | 7 |
| 数据库表 | 8 |

## 当前里程碑

**M2.5 完成（2026-06-27）**。凌晨实战验证东财挂、腾讯顶上，5 只自选股 + 8 条信号全触发 ✅。

下一步：**CI 配置 + 微信推送 + 复盘报告**（让妈妈真的「躺着用」）。

## License

Private（暂不开源）
