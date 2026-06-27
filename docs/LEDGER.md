# 执行台账 (LEDGER.md)

> mommy-chaogu 的逐条时间线。**commit 级别**的「做了什么 / 为什么 / 怎么验证的 / 学到什么」。
>
> 跟 DESIGN 互补：DESIGN 讲「为什么这样设计」，LEDGER 讲「具体怎么走到这一步」。

最后更新：2026-06-27

---

## 目录

| ID | 日期 | 标题 | Commit | 状态 |
|---|---|---|---|---|
| M0 | 2026-06-26 | 通用行情数据层 + efinance 适配器 | `dc8fd33` | ✅ |
| M1 | 2026-06-26 | 自选池分组管理 + 实时监控 | `dac4f8d` | ✅ |
| M1.5 | 2026-06-26 | 7 条内置告警规则 + Alerter 服务 | `2a44ed8` | ✅ |
| M2 | 2026-06-26 | 时间戳驱动缓存 + 装饰器模式 | `30fad29` | ✅ |
| M2.5 | 2026-06-27 | TencentAdapter + FallbackAdapter | `1910bc1` | ✅ |
| M0.5 | 2026-06-27 | 设计文档 + 执行台账 + 进度总结 | （本文） | ✅ |
| M3+ | TBD | 见 PROGRESS.md 下一步 | — | ⏳ |

---

## M0 — 通用行情数据层 + efinance 适配器

**日期**：2026-06-26 上午
**Commit**：`dc8fd33` — `feat(market_data): 通用行情数据层 + efinance 适配器`
**代码量**：~500 行 src + ~300 行 tests

### 目标

建立项目骨架：定义「行情数据」长什么样，怎么从 efinance 拉，怎么抽象成 Protocol。

### 产出

| 文件 | 作用 | LOC |
|---|---|---|
| `src/mommy_chaogu/market_data/types.py` | 11 个 `@dataclass(frozen=True)` + 4 个 `StrEnum` | 206 |
| `src/mommy_chaogu/market_data/adapter.py` | `MarketDataAdapter` Protocol | 128 |
| `src/mommy_chaogu/market_data/efinance_adapter.py` | EfinanceAdapter（覆盖 11 路数据） | 521 |
| `scripts/smoke_market_data.py` | 端到端冒烟（11 段） | 89 |

**支持的数据**：
- 实时报价 / 批量报价
- 5 档盘口
- K线（5min / 15min / 30min / 1h / 1d / 1w / 1m）
- 历史资金流
- 当日资金流
- 全市场快照
- 板块列表

### 关键决策

- **金额用 `Decimal`**：避免 float 精度问题
- **接口用 `Protocol`**：鸭子类型，业务层零依赖具体源
- **efinance 而非 akshare/tushare**：覆盖全、无需 token（详见 DESIGN §5 ADR-001）

### 踩坑

| 坑 | 解决 |
|---|---|
| `get_deal_detail` 默认 `max_count=1,000,000` 超时 | 限到 5000 |
| `get_quote_history` 默认拉 1900-2050 全量会断 | 按 `interval` 自动收缩（5min→近 5 天） |
| 5 档盘口字段是 `买1价/买1数量` 不是 `买1/买1量` | 看 efinance 源码确认 |
| **get_latest_quote 冷启动超时** | 改用 `list_market_quotes()` 全市场 + filter |
| **中午高峰 push2 整体抽风** | 失败时优雅返回空 list + warning |

### 验证

- 冒烟脚本 11 段全绿
- 24 测试：13 离线（dataclass/Protocol/monkey duck）+ 11 真实网络（efinance）
- ruff / mypy strict / pytest 全过

### 学到

- efinance 接口命名乱，必须**反复看官方示例 + 实战**
- Protocol + dataclass 组合 → IDE 补全 + 单测 Mock 都很爽
- **「网络依赖的测试」要明确标 live，可以接受偶发挂**（后续加 `pytest -m live` 标记会更清晰）

---

## M1 — 自选池分组管理 + 实时监控

**日期**：2026-06-26 中午
**Commit**：`dac4f8d` — `feat(watchlist+monitor): 自选池分组管理 + 实时监控 (M1)`
**代码量**：~500 行 src + ~300 行 tests

### 目标

妈妈有「持仓」/「关注」/「板块」三组自选股；想看的时候拉一次快照，或后台一直监控。

### 产出

| 文件 | 作用 | LOC |
|---|---|---|
| `src/mommy_chaogu/watchlist/models.py` | `Group` + `StockEntry` ORM | 83 |
| `src/mommy_chaogu/watchlist/store.py` | CRUD API（add/remove/list/stats） | 259 |
| `src/mommy_chaogu/monitor/poller.py` | `snapshot_now` / `run`（持续轮询） | 287 |
| `src/mommy_chaogu/monitor/output.py` | 控制台表格 + 单行日志格式 | 102 |
| `src/mommy_chaogu/cli.py` | argparse 入口（mommy-watchlist / mommy-monitor / mommy-chaogu） | 580 |

**CLI 子命令**：

```
mommy-watchlist
  ├── add-group / remove-group / groups
  ├── add / remove / list / stats
mommy-monitor
  ├── snapshot  拉一次快照并打印
  ├── run       持续轮询 (Ctrl+C 退出)
  ├── log       查看监控日志（tail）
  ├── signals   查看信号日志（tail）
  └── rules     列出所有内置告警规则
```

### 关键决策

- **SQLite + SQLAlchemy 2.0 async**：单用户场景，async 准备好后续上 FastAPI（详见 DESIGN §5 ADR-004）
- **Group 是 first-class 实体**：妈妈按「持仓/关注/板块」分组，比单层 tag 直观
- **轮询间隔默认 30s**：实时性 vs 接口压力的折中

### 踩坑

| 坑 | 解决 |
|---|---|
| SQLAlchemy 2.0 async session 生命周期 | 用 `async with async_session()` 上下文 |
| 控制台表格宽动态变化（涨跌平 emoji 颜色） | 手动算列宽 + emoji 状态 |
| monitor 在中午东财抽风时整个挂 | 加 try/except + warning 日志，单股失败不中断整批 |

### 验证

- 17 watchlist 单测（增删改查 / 分组 / 持久化）
- 10 monitor 单测（Mock adapter，轮询逻辑）
- 妈妈实战 5 只自选股、3 个分组、snapshot 一次 ~1s
- ruff / mypy strict / pytest 40 全过

### 学到

- **「业务层 Mock adapter」比「业务层 Mock HTTP」好写一万倍**（Protocol 的复利）
- CLI 表格比 JSON 友好，但**先实现 JSON 逻辑、再包装表格**最稳
- 监控类工具要给「快速退路」：`Ctrl+C` 必须优雅退出 + 写一条收尾日志

---

## M1.5 — 7 条内置告警规则 + Alerter 服务

**日期**：2026-06-26 下午
**Commit**：`2a44ed8` — `feat(signals): 7 条内置告警规则 + Alerter 服务 (M1.5)`
**代码量**：~500 行 src + ~400 行 tests

### 目标

妈妈不需要盯盘，**关键时刻主动推**。先做 7 条基础规则，覆盖「异动 + 资金 + 自选股联动」。

### 产出

| 文件 | 作用 | LOC |
|---|---|---|
| `src/mommy_chaogu/signals/types.py` | `Signal` / `RuleConfig` / `RuleEvaluation` | 101 |
| `src/mommy_chaogu/signals/rules.py` | `Rule` Protocol + 7 条规则实现 | 426 |
| `src/mommy_chaogu/signals/alerter.py` | Alerter（聚合 + 去重 + 落盘） | 81 |
| `scripts/demo_signals.py` | Mock 数据验证 8 条信号触发 | ~80 |

**7 条内置规则**：

| 规则 | 触发条件 | 严重度 |
|---|---|---|
| `price_change_threshold` | 单股涨跌幅 > 阈值 | 中 |
| `gap_open` | 开盘价 vs 昨收 跳空 > 阈值 | 中 |
| `main_flow_threshold` | 主力净流入 > 阈值 | 高 |
| `volume_surge` | 量比 > 阈值 | 中 |
| `turnover_surge` | 换手率 > 阈值 | 中 |
| `portfolio_breadth` | 自选池整体涨跌家数比异常 | 低 |
| `portfolio_main_flow` | 自选池主力净流入合计异常 | 高 |

### 关键决策

- **规则用 `Rule` Protocol + 装饰器**（`@register_rule`）：新增规则 = 一个文件 + 一个函数
- **Alerter 去重**：同一规则同一股 5 分钟内不重复触发
- **落盘 `data/signals.log`**：妈妈事后可以查信号历史

### 踩坑

| 坑 | 解决 |
|---|---|
| 规则接口的入参是「单个 quote」还是「多股 snapshot」 | 统一接受 `list[Quote]` + `list[MoneyFlow]`，规则内部判断 |
| 阈值应该放哪 | `RuleConfig` 注入，规则本体可测 |
| 自选股联动规则需要 watchlist 上下文 | Alerter 启动时注入 `WatchlistStore` |

### 验证

- 31 signals 单测（每条规则 3-5 个 case + 边界）
- `demo_signals.py` 8 条 mock 信号全部触发
- ruff / mypy strict / pytest 71 全过

### 学到

- **Protocol 化一切**让规则扩展几乎零成本（这次新增规则测试只花了 5 分钟）
- **去重要做在 Alerter 层**而不是规则层（规则不知道历史）
- **demo 脚本比 unit test 更能验证业务效果**（mock 数据贴近真实场景）

---

## M2 — 时间戳驱动缓存 + 装饰器模式

**日期**：2026-06-26 下午晚
**Commit**：`30fad29` — `feat(cache): 时间戳驱动缓存 + 装饰器模式 + 数据新鲜度报告 (M2)`
**代码量**：~1200 行 src + ~700 行 tests

### 目标

efinance 抽风时 monitor 不能断；妈妈看得见数据新不新鲜；盘前可以预热。

### 产出

| 文件 | 作用 | LOC |
|---|---|---|
| `src/mommy_chaogu/cache/schema.py` | 5 张表 DDL（带 fetched_at / quote_ts） | 61 |
| `src/mommy_chaogu/cache/config.py` | `CacheConfig` 拉新间隔 | 41 |
| `src/mommy_chaogu/cache/serializer.py` | dataclass ↔ JSON（Decimal / Money 拆 dict） | 131 |
| `src/mommy_chaogu/cache/store.py` | `CacheStore` CRUD | 348 |
| `src/mommy_chaogu/cache/adapter.py` | `CachedMarketDataAdapter` 装饰器 | 487 |
| `src/mommy_chaogu/cache/manager.py` | `CacheManager`（warmup / refresh / stats / freshness） | 113 |
| `scripts/demo_cache.py` | Mock 演示 4 场景 | 126 |

**CLI 新增**：

```
mommy-cache
  ├── stats         命中率 + 缓存条目数 + 数据新鲜度（emoji 颜色编码）
  ├── warmup        盘前预热（全市场 + 自选股）
  ├── refresh       强制刷新（--code 刷单股 / 不填刷全市场）
  ├── clear         清空缓存（--all 全部 / 不填只清 quote_cache）
  ├── snapshots     列出全市场快照历史
  └── config        查看拉新间隔
```

### 关键决策

- **数据库是唯一真相源**（详见 DESIGN §2 P2）：拉新失败静默 fallback 到旧数据
- **双时间戳**：`fetched_at`（拉取时间）+ `quote_ts`（数据自身时间，如行情时间）
- **节流**：5min 间隔避免高频拉新被东财封 IP
- **历史快照保留**：`market_snapshot_cache` 保留最近 30 份，可回看历史涨跌榜

### 踩坑

| 坑 | 解决 |
|---|---|
| `Quote` 序列化：`Decimal` 直接 JSON 报错 | 全部 `str(d)` 转换 |
| `Money` 嵌套在 `MoneyFlow` 里，asdict 不递归 | 手动 `serializer.py` 拆分 |
| **拉新 early-return bug**：`return []` 阻断后面 cached 分支 | 重写为 `if/else` 结构 |
| cache 装饰器和 fallback 装饰器谁包谁？ | **`Cached(Fallback([Efinance, Tencent]))`** — 缓存外层，fallback 内层 |

### 验证

- 26 cache 单测（命中/拉新/失败 fallback/数据持久化/节流/历史快照/Manager）
- ruff / mypy strict / pytest 97 全过
- `demo_cache.py` 4 场景全部复现

### 学到

- **「装饰器链的顺序」很关键**：缓存外层才能让 fallback 结果也进缓存
- **JSON 序列化 dataclass 不要用 `asdict`**：嵌套类型（Money / Decimal）必须手写
- **early-return 是 bug 温床**：复杂条件用 if/else 显式分支更可控

---

## M2.5 — TencentAdapter + FallbackAdapter

**日期**：2026-06-27 凌晨
**Commit**：`1910bc1` — `feat(market_data): TencentAdapter + FallbackAdapter (东财崩了腾讯顶上)`
**代码量**：~500 行 src + ~350 行 tests

### 触发事件

**凌晨 2 点实战**：东财 push2.eastmoney.com 主动断（Empty reply），monitor 监控里 5 只自选股全部数据空。

```
$ efinance.get_quote("600519")
[Empty reply from server]    # 5/5 calls fail

$ curl -s "https://qt.gtimg.cn/q=sh600519"
v_sh600519="1~贵州茅台~600519~...~"   # ✅ 200 OK
```

立即决定：**加腾讯兜底**。

### 产出

| 文件 | 作用 | LOC |
|---|---|---|
| `src/mommy_chaogu/market_data/tencent_adapter.py` | 腾讯财经（qt.gtimg.cn） | 362 |
| `src/mommy_chaogu/market_data/fallback_adapter.py` | 多源 fallback 装饰器 | 137 |
| `tests/test_market_data/test_tencent_adapter.py` | 17 个单测（解析 + fallback 4 场景） | 349 |

**腾讯支持的**：实时报价（批量）/ 5档盘口（嵌在行情里）/ 行情字段（涨跌幅、量比、PE、换手、市值等）
**腾讯不支持的**（走 efinance）：K线 / 资金流 / 板块 / 全市场

### 关键决策

- **Fallback 链 `Efinance → Tencent`**（详见 DESIGN §5 ADR-003）
- **每个方法独立 fallback**（一个方法在主源失败不影响其他方法）
- **不缓存 fallback 结果**（避免缓存层 + fallback 层互相干扰）
- **指标统计**：`primary_hits` / `fallback_hits` / `all_fail` / 各 adapter 单独计数

### 踩坑

| 坑 | 解决 |
|---|---|
| 腾讯返回 GBK 编码 | `response.content.decode("gbk")` |
| 5 档盘口字段位置深（9-18 是买档，19-28 是卖档） | 写常量 `_BUY_OFFSET_START = 9` 等 |
| 成交量单位是「手」要 ×100 | 转换时乘 100 |
| 成交额单位是「万元」要 ×10000 | 转换时乘 10000 |
| 流通市值/总市值单位是「亿」要 ×1e8 | 转换时乘 1e8 |
| 腾讯不返回 `change` / `change_pct` 字段 | 主动算：`现价 - 昨收` / `现价 / 昨收 - 1` |
| 测试跨午夜硬编码日期 `2026-06-26` 报错 | 改 `datetime.now(UTC).date()` 动态日期 |

### 验证

- **凌晨 2 点实战**：efinance 5/0 成功，tencent 5/5 成功，5 只自选股数据 + 8 条信号全部触发 ✅
- 17 新单测 + 修测试日期 bug
- ruff / mypy strict / pytest 114 全过

### 学到

- **「凌晨发现的问题」最有价值**——生产环境的真相，单元测试覆盖不到
- **多数据源不是设计选择，是生存策略**——只要一个数据源能跑，妈妈无感
- **`# type: ignore[override]` 在 Protocol 实现时很常见**——类型噪音不值得为它牺牲代码量

---

## M0.5 — 文档体系（设计 / 台账 / 进度）

**日期**：2026-06-27 早上
**Commit**：（本文提交）
**代码量**：~700 行文档

### 触发

团长：「可以做得很牛逼，咱们先把这一个进度总结一下，写一个文档。对了，你之前写过设计文档吗？设计文档和执行台账这个如果没有的话，都加一下吧」

### 产出

| 文件 | 作用 |
|---|---|
| `docs/DESIGN.md` | 架构、原则、ADR（**为什么**） |
| `docs/LEDGER.md` | 逐条时间线（**怎么走到这一步**） |
| `docs/PROGRESS.md` | 当前进度 + 下一步（**现在在哪**） |

### 关键决策

- **DESIGN / LEDGER / PROGRESS 三件套**：
  - DESIGN 解决「新人快速理解架构」
  - LEDGER 解决「commit 级别的可追溯性」
  - PROGRESS 解决「下次接续时知道从哪开始」
- **不写成「文档套文档」**——每份有明确读者和场景

### 学到

- **文档不是装饰品**——是项目状态机的一部分
- **没文档的项目没有真正的 history**——git log 能查「改了什么」，但查不到「为什么这么改」

---

## 重大 lessons learned（跨 milestone）

1. **Protocol 化一切接口** → 业务层永远 Mock 单测
2. **数据库是唯一真相源** → 拉新失败不致命
3. **多数据源 fallback 是生存策略** → 不是 nice-to-have
4. **early-return 是 bug 温床** → 复杂逻辑用 if/else 显式分支
5. **JSON 序列化 dataclass 不要用 asdict** → 嵌套类型（Money / Decimal）必须手写
6. **装饰器链的顺序很关键** → 外层缓存 + 内层 fallback
7. **凌晨实战最有价值** → 单元测试覆盖不到的真实故障

## 工具链统计

- **Python**：3.12 + uv + hatchling
- **Lint**：ruff（All checks passed）
- **Type check**：mypy --strict（0 errors）
- **Test**：pytest 125（119 离线通过 + 6 efinance 实时网络，凌晨抽风时挂）
- **Code**：src 4593 行 + tests 1891 行 + scripts 391 行 ≈ 6875 行
- **CI**：未配（待加 GitHub Actions）
