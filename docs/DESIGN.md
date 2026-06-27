# 设计文档 (DESIGN.md)

> mommy-chaogu 的架构、原则、关键决策。本文回答「**为什么这样设计**」。

最后更新：2026-06-27

---

## 1. 项目定位

**给妈妈用的行情监控 + 投资陪伴工具。**

- **核心场景**：妈妈看行情、看资金流、看板块联动；系统在关键时刻主动提醒。
- **核心约束**：
  - 妈妈不会用复杂工具 → **CLI 要克制，输出要直观**
  - 第三方接口随时挂（东财 push2 凌晨会断）→ **降级优先，断流不致命**
  - 不预测、不荐股 → **只做事实呈现 + 规则化提醒**
- **数据源**：东方财富 efinance（主）+ 腾讯财经 qt.gtimg.cn（备）
- **不做什么**：不下单、不做实盘、不做量化策略。

## 2. 设计原则

按重要性排序，违反时回头打脸用。

### P0 — 接口先行 (Protocol-first)

所有外部数据源走**统一 `MarketDataAdapter` Protocol**（`@runtime_checkable`）。

```python
class MarketDataAdapter(Protocol):
    name: str
    def get_quote(self, code: str) -> Quote | None: ...
    def get_quotes(self, codes: list[str]) -> list[Quote]: ...
    def get_order_book(self, code: str) -> OrderBook: ...
    def get_bars(self, code, interval, ...) -> list[Bar]: ...
    def get_money_flow(self, code, ...) -> list[MoneyFlow]: ...
    def get_today_money_flow(self, code) -> list[MoneyFlow]: ...
    def list_market_quotes(self) -> list[Quote]: ...
    def list_boards(self) -> list[Board]: ...
    def health_check(self) -> bool: ...
```

**收益**：
- 业务层（monitor / signals / cache）零依赖具体数据源
- 切换数据源 = 改一个 `EfinanceAdapter()` 就行
- 单元测试可以用 `Mock` adapter 完全脱离网络

**反例**：如果某天加了 `TushareAdapter`，所有调用方不用改一行代码。

### P1 — dataclass 化 + 强类型

行情数据全部用 `@dataclass(frozen=True)` 定义：
- **金额一律 `Decimal`**（避免 float 精度问题）
- **时间一律 `datetime` + `UTC`**
- **不可变**（防止业务层误改）

**反例**：如果用 dict/typed_dict 串数据，IDE 没法补全，重构容易漏字段。

### P2 — 数据库是唯一真相源 (Database as Source of Truth)

缓存层是**有状态**的：DB 有数据就用，没有才拉新。**永远不主动丢弃数据**。

```
[DB] ←→ [CachedMarketDataAdapter] ←→ [业务层 (Monitor / Signals)]
              ↓
       [MarketDataAdapter] (efinance / tencent / mock)
```

每条缓存记录带**双时间戳**：
- `fetched_at`：什么时候拉取的
- `quote_ts`：数据自身的时间戳（如行情时间）

妈妈能在 `mommy-cache stats` 里看到「这条数据是 5 分钟前拉的还是 5 秒前」。

### P3 — 降级优先 (Graceful Degradation)

第三方接口挂了 ≠ 监控挂。层层降级：

| 层 | 降级策略 |
|---|---|
| **数据源层** | `FallbackAdapter([Efinance, Tencent])`：主源失败 → 次源 |
| **缓存层** | 拉新失败 → 静默返回旧数据 + warning 日志 |
| **业务层** | 单股拉取失败 → 标 `-`，不中断整批 |

**实战案例**：2026-06-27 凌晨 2 点东财 push2 主动断开（Empty reply），5 次调用 0 成功；腾讯 qt.gtimg.cn 全程稳定，5 只自选股数据 + 8 条信号全部触发 ✅。

### P4 — 装饰器链 (Decorator Chain)

能力以**装饰器**形式叠加，每层独立可测：

```
EfinanceAdapter  ←  TencentAdapter
       ↓
FallbackAdapter  ←  任何方法都按顺序 fallback
       ↓
CachedMarketDataAdapter  ←  加 DB 缓存 + 节流
       ↓
业务层（Monitor / Signals / CLI）
```

**好处**：
- 每层职责单一，单测可以 Mock 上下游
- 新增能力（限流？熔断？）= 加一个装饰器，不动业务

### P5 — KISS / YAGNI / DRY

- 不写框架级的「通用缓存库」，只写「这项目需要的缓存」
- 不引入重量级依赖（无 Celery / Redis / Kafka）
- 8 张表（5 缓存 + 2 watchlist + 1 signals）都用 SQLite + SQLAlchemy 2.0 async 起步

## 3. 模块架构

```
src/mommy_chaogu/
├── market_data/         # 数据源适配层
│   ├── types.py             # 11 个 dataclass + 4 个 StrEnum
│   ├── adapter.py           # MarketDataAdapter Protocol
│   ├── efinance_adapter.py  # 东方财富（主力）
│   ├── tencent_adapter.py   # 腾讯财经（备力）
│   └── fallback_adapter.py  # 多源 fallback 装饰器
│
├── watchlist/           # 自选池
│   ├── models.py            # Group + StockEntry ORM
│   └── store.py             # CRUD API
│
├── monitor/             # 监控
│   ├── poller.py            # snapshot_now / 持续轮询
│   └── output.py            # 控制台表格 + 单行日志
│
├── signals/             # 告警规则
│   ├── types.py             # Signal / RuleConfig
│   ├── rules.py             # 7 条内置规则 + Rule Protocol
│   └── alerter.py           # 告警聚合 + 日志落盘
│
├── cache/               # 缓存
│   ├── schema.py            # 5 张表 DDL
│   ├── config.py            # 拉新间隔配置
│   ├── serializer.py        # dataclass ↔ JSON
│   ├── store.py             # CacheStore CRUD
│   ├── adapter.py           # CachedMarketDataAdapter 装饰器
│   └── manager.py           # CacheManager（warmup / refresh / stats）
│
└── cli.py               # argparse 入口
    ├── mommy-watchlist      # 自选股管理
    ├── mommy-monitor        # 行情监控
    └── mommy-cache          # 缓存管理
```

## 4. 数据流（一次 `get_quote("600519")` 的全链路）

```
[CLI: mommy-monitor run]
    ↓ every N seconds
[Monitor.snapshot_now("600519")]
    ↓
[CachedMarketDataAdapter.get_quote("600519")]
    ↓ 1. 查 DB quote_cache WHERE code='600519'
    │    → 命中 + 未过期 → 直接返回 [hit]
    │    → 命中 + 已过期 → 走拉新 [stale_hit]
    │    → miss → 走拉新 [miss]
    ↓ 2. 距离上次拉新 < interval (5min) → 跳过拉新 [throttled]
    ↓ 3. 拉新
    ↓
[FallbackAdapter.get_quote("600519")]
    ↓ try EfinanceAdapter
    │    → 成功 → 返回 [primary_hit]
    │    → 抛异常/None → try TencentAdapter
    │                    → 成功 → 返回 [fallback_hit]
    │                    → 失败 → 返回 None [all_fail]
    ↓
[CacheStore.upsert_quote(quote)]  ← 双时间戳
    ↓
[Monitor.format_table(quotes)]  ← 控制台 + data/monitor.log
    ↓
[Signals.Alerter.evaluate(quotes, rules)]
    ↓ 触发 → data/signals.log
```

**总耗时**：
- 命中缓存：~5ms（SQLite 本地）
- 拉新 + 命中：~200ms（HTTP）
- 拉新失败 fallback：~400ms（2 次 HTTP）

## 5. 关键决策记录 (ADR-lite)

### ADR-001: 用 efinance 而不是 akshare / tushare
**日期**：2026-06-26（M0）
**结论**：efinance 优先
**原因**：
- 数据覆盖全（A 股实时/K线/资金流/板块）
- 无需 token，免费
- 接口相对稳定
**代价**：efinance 没有 type stub，类型注解靠手写

### ADR-002: 缓存默认节流 5 分钟
**日期**：2026-06-26（M2）
**结论**：quote 5min / today_flow 5min / market_snapshot 1h / bar 1d
**原因**：
- 行情数据本身就有 N 分钟延迟，5min 节流是合理的
- 妈妈看监控不是高频交易，5min 完全够用
- 节流可以降低东财被封 IP 的风险
**反悔条件**：如果妈妈需要「逐笔」级监控 → 改 30s

### ADR-003: Fallback 链 efinance → tencent
**日期**：2026-06-27（M2.5）
**结论**：efinance 优先，tencent 兜底
**原因**：
- efinance 数据更全（K线/资金流/板块）
- tencent 在 efinance 挂时稳定（凌晨实战验证）
- 腾讯的 5 档盘口直接嵌在行情里，少一次 HTTP
**代价**：tencent 不支持 K线/资金流/板块 → 这些方法在 tencent 永远走 efinance

### ADR-004: SQLite + SQLAlchemy 2.0 async
**日期**：2026-06-26（M1）
**结论**：本地 SQLite 起步，不上 Postgres
**原因**：
- 单用户场景（妈妈），并发 QPS 极低
- 一个 `.db` 文件好备份、好迁移
- SQLAlchemy ORM 写起来舒服
**升级条件**：未来要做多用户 / Web 端 → 切 Postgres

### ADR-005: ruff + mypy strict + pytest
**日期**：2026-06-26（项目初始化）
**结论**：CI 三件套全开
**原因**：
- ruff：快，替 flake8/isort/black
- mypy strict：类型问题编译期发现
- pytest：标准，fixture 体系成熟
**例外**：`cache/*` 和 `cli.py` 用 `ignore_errors`（JSON 反序列化类型天然弱 / 太多 MarketDataAdapter 类型）

## 6. 错误处理约定

| 情况 | 处理 |
|---|---|
| 第三方 API 抛异常 | `FallbackAdapter` 内部 `contextlib.suppress` 吞掉 → 试下一个源 |
| 缓存拉新失败 | `CachedMarketDataAdapter` 静默 + warning 日志 + 返回旧数据 |
| 监控单股拉取失败 | 该行显示 `-`，不中断整批 |
| 数据格式异常 | 抛 `ValueError`（fail fast） |
| 内部 bug | 抛带 context 的 `RuntimeError` |

**永远不**：空 catch、print 后继续、把异常吞成 `None` 后假装成功。

## 7. 安全 & 隐私

- 妈妈用，**无登录 / 无网络暴露**（纯本地 CLI）
- 行情数据公开，无敏感信息
- `data/*.db` 加 `.gitignore`，不入库
- 不写日志到 `~` 或 `/tmp`，统一 `data/`

## 8. 性能预算

| 操作 | 目标 | 实际 |
|---|---|---|
| `get_quote` 命中缓存 | <10ms | ~5ms |
| `get_quote` 拉新 | <500ms | ~200ms |
| `list_market_quotes` 全市场 | <5s | ~3s |
| `monitor snapshot` (5只股) | <2s | ~1s |
| 内存占用 | <100MB | ~60MB |

## 9. 相关文档

- `docs/PROGRESS.md` — 当前进度 + 下一步
- `docs/LEDGER.md` — 逐条时间线（commit 级别）
- `README.md` — 快速上手
