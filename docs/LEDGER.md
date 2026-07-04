# 执行台账 (LEDGER.md)

> mommy-chaogu 的逐条时间线。**commit 级别**的「做了什么 / 为什么 / 怎么验证的 / 学到什么」。
>
> 跟 DESIGN 互补：DESIGN 讲「为什么这样设计」，LEDGER 讲「具体怎么走到这一步」。

最后更新：2026-07-04（Agent 原生回测 trial_1 完成，memory-system-v1 分支）

---

## 目录

| ID | 日期 | 标题 | Commit | 状态 |
|---|---|---|---|---|
| M0 | 2026-06-26 | 通用行情数据层 + efinance 适配器 | `dc8fd33` | ✅ |
| M1 | 2026-06-26 | 自选池分组管理 + 实时监控 | `dac4f8d` | ✅ |
| M1.5 | 2026-06-26 | 7 条内置告警规则 + Alerter 服务 | `2a44ed8` | ✅ |
| M2 | 2026-06-26 | 时间戳驱动缓存 + 装饰器模式 | `30fad29` | ✅ |
| M2.5 | 2026-06-27 | TencentAdapter + FallbackAdapter | `1910bc1` | ✅ |
| M0.5 | 2026-06-27 | 设计文档 + 执行台账 + 进度总结 | （本文件） | ✅ |
| M3.0 | 2026-06-27 | FastAPI 后端 + Web UI（4 页） | `ee4170b` 等 | ✅ |
| M3.1 | 2026-06-27 | Server酱 微信推送 + 去重 | `3402e19` | ✅ |
| M4 | 2026-06-28 | 持仓 + 语音 + 资金流图表 + 盘面扫描 | `8033e07` 等 | ✅ |
| **M5** | **2026-06-29** | **半导体产业链参考库** | **`3a37aa2`** | **✅** |
| **M5.1** | **2026-06-29** | **资金流拉新 + 排行（基础设施）** | **`d41bc0a`** | **✅** |
| **M5.2** | **2026-06-29** | **ratio 信号 + 盘中监控 + 收盘日报** | **`45e20fa`** | **✅** |
| **M5.3** | **2026-06-29** | **OpenClaw cron 4 jobs 自动化** | **（pending commit）** | **✅** |
| M6 | TBD | 详情页驾驶舱改造（场景 B） + 复盘报告 | — | ⏳ |
| **M7.1** | **2026-07-02** | **中信 H1 业绩前瞻 DB + schema** | **`5326b1e`** | **✅** |
| **M7.2** | **2026-07-02** | **Thematic watchlist groups + 41 家公司入库** | **`4d96d83`** | **✅** |
| **M7.3** | **2026-07-02** | **中报窗口实战手册 v1.0（12 章节）** | **`018b276`** | **✅** |
| **M7.4** | **2026-07-02** | **earnings_actual 模块（types/store/service/signals/adapter/cli）** | **(待提交)** | **✅** |
| **M7.5** | **2026-07-02** | **柯力 603662 + 中信报告实战分析** | **(本文档)** | **✅** |
| **M7.6** | **2026-07-02** | **EfinanceEarningsAdapter + 真实东财数据** | **`cb02971`** | **✅** |
| **Merge-1** | **2026-07-03** | **main + agent-centric 分支合并** | **`830d67b`** | **✅** |
| **Mem-1** | **2026-07-03** | **记忆系统 Phase 1（情景+预测+验证+抽取）** | **`d4e3a2b`** | **✅** |
| **Mem-3** | **2026-07-03** | **记忆系统 Phase 3+4（脉络+语义+提炼）** | **`a5f9c1e`** | **✅** |
| **Mem-5** | **2026-07-03** | **记忆系统 Phase 5（向量检索 sqlite-vec）** | **`be9700b`** | **✅** |
| **Mem-Docs** | **2026-07-03** | **文档更新（PROGRESS/PROJECT-LOG/LEDGER/README）** | **`8dbba16`** | **✅** |
| **BT-1** | **2026-07-04** | **30 天真实数据回测（154 条预测，53% 命中率）** | **`4649e5e`** | **✅** |
| **DB-1** | **2026-07-04** | **数据库分库重组（market/portfolio/agent/reference）** | **`79f7adc`** | **✅** |
| **LLM-BT** | **2026-07-04** | **LLM 回测框架 + Token Tracker + zai provider** | **`e6edf43` / `863acf8`** | **✅** |
| **Agent-BT** | **2026-07-04** | **Agent 原生回测 trial_1（25 条预测，47% 命中率，bullish 88%）** | **本次提交** | **✅** |

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

## M3.0 — Web UI（妈妈不用 CLI）

**日期**：2026-06-27 14:00 – 21:00
**Commit**：`ee4170b` / `8c9e38f` / `eb23fe5` / `22f4e8b`（4 个）
**代码量**：~2400 行（Python web/ 1100 + 前端 Vite 1300）

### 触发

团长：「妈妈不用 CLI」「web 应该统一一个端口入口」「如果要框架的话可以从简单的开始」

### 产出

#### 后端 src/mommy_chaogu/web/（commit `ee4170b`）
| 文件 | 行 | 作用 |
|---|---|---|
| `app.py` | 200 | FastAPI 工厂 + lifespan |
| `deps.py` | 80 | 单例 adapter/store/alerter 注入 |
| `background.py` | 220 | 单 asyncio 任务 5s 轮询 + WS 广播 |
| `schemas.py` | 130 | 14 个 Pydantic（Decimal → str） |
| `mappers.py` | 150 | dataclass → Pydantic 转换 |
| `routes/{quotes,watchlist,signals,cache,ws}.py` | 280 | 5 个路由文件 |
| CLI: `mommy-web --port 8765 --poll-interval 3` | — | uvicorn 入口 |

14 REST + 2 WebSocket 端点。

#### 前端（Vite + Vue 3 + TS，commit `eb23fe5`）
- `web/` 目录：Vite 6 + Vue 3 + TS + vue-router + klinecharts 9.8
- 4 页面：`index` / `detail` / `signals` / `settings`
- API 模块：`api/{client,types,index,watchlist,signals,cache,ws}.ts`
- 5 build 后 `web/dist/`，~500ms

#### UI 优化（commit `22f4e8b`）
- **5档盘口颜色修对**（A 股：卖=红 买=绿）
- 大字号（妈妈手机友好，+20%）
- 骨架屏（感知性能 +30%）
- 信号点击跳 K 线
- 「今日收盘」标签代替「X 秒前·实时」（避免凌晨误导）

#### Taro 实验（commit `8c9e38f`，**已放弃**）
- 2 小时调试：webpack 5.91 不兼容 / 加载器错位 / 「没有找到页面实例」router 错误
- 最终切换到 Vite + Vue 3，15 分钟跑通
- `frontend/` 目录保留作为未来 mini program 参考

### 关键决策

- **Vite > Taro for H5**：MVP 极致简化 > 正统大而全
- **不写 Taro `<view>/<text>` 组件**：用原生 HTML 跨平台兼容
- **单 BackgroundService 撑所有 WS**：100 客户端 = 1 轮询任务 + 广播
- **Decimal → string in JSON**：避免 float 精度问题
- **A 股红涨绿跌 强制约定**：所有页面统一
- **StaticFiles mount 必须在 app.get(/) 之后**：否则抢路由

### 学到

- **GLM-5.2 的「正统方案」(Taro + Vue 3 + Vant + ECharts) 调试 2h 失败，最终 Vite + Vue 3 + klinecharts 15min 搞定**——MVP 极致简化 > 框架统一
- **妈妈的用户体验 ≠ 程序员的用户体验**：大字号 / 骨架屏 / 颜色约定都要单独考虑
- **测试覆盖 mappers > 测试覆盖 routes**：mappers 是 Decimal/Money/datetime 高发错误点
- **headless iPhone 14 viewport（390x844, 2x DPR）** 是验证 H5 的最简工具

### 实战验证

团长手机 + 模拟器都过：
- 首页：5 只自选股 + 主力合计 + 涨跌统计
- 详情：K 线 + 5 档盘口 + 11 个数据点
- 信号：8 条触发 + 严重度 emoji
- 设置：服务状态 + 缓存 + 自选股 CRUD

服务运行中：`http://192.168.10.84:8765/`（LAN IP，妈妈 WiFi 下用）

---

## M3.1 — Server酱 微信推送（信号主动到手机）

**日期**：2026-06-27 21:30
**Commit**：`3402e19`
**代码量**：~430 行（src 329 + tests 100）

### 触发

团长：「做完 M3.0 推送就做」「之后会测试 Server酱」

### 背景

妈妈不会主动打开 Web 看信号 → 必须被动推送到微信。
Server酱³ 是最轻方案：
- API 一行 POST（`https://sctapi.ftqq.com/{SendKey}.send`）
- 免费 5 条/天，正好对应每天 ~5 条 warning/critical
- 推到「妈妈炒股的信号」公众号

### 产出

| 模块 | 行 | 作用 |
|---|---|---|
| `push/base.py` | 110 | `Pusher`/`Deduper` Protocol + `SignalNotifier` |
| `push/server_chan.py` | 109 | Server酱³ 实现 + emoji 标题 + Markdown desp |
| `push/deduper.py` | 84 | JSON 文件去重（按日清空，原子写） |
| `push/__init__.py` | 26 | 模块导出 |
| 测试 29 个（10 + 10 + 9） | 379 | server_chan / deduper / notifier |

### 关键设计

- **Protocol 抽象**：`Pusher` / `Deduper` 接口，未来加钉钉/Telegram/Bark 直接换实现
- **严重度阈值过滤**：默认只推 `WARNING` + `CRITICAL`，INFO 不推避免刷屏
- **JSON 文件去重**：key = `code|rule_id|date`，每天自动清空昨天的
  - 原子写（tmp + rename）
  - 损坏文件容错（损坏则当新文件）
- **优雅降级**：
  - 没 SendKey → 完全不推送，Web 服务正常
  - 推送初始化失败 → 记日志但继续运行
  - 单条推送异常 → 吞掉不影响其他 ticker
- **Markdown desp**：代码 / 时间 / 触发值 / 阈值 / K 线链接（HTTPS 公网 URL）

### CLI 集成

```bash
# 方式 1：命令行参数
mommy-web --server-chan-key SCT123xxx --web-base-url https://mommy.example.com

# 方式 2：环境变量（推荐生产）
export SERVER_CHAN_KEY="SCT123xxx"
export WEB_BASE_URL="https://mommy.example.com"
mommy-web --port 8765
```

### 学到

- **Protocol 化设计节省 100x 工作量**：未来加钉钉只写 `DingTalkPusher` 即可，集成代码不动
- **去重要持久化**：内存 dict 重启就丢，妈妈不会重启后又被同一信号刷屏
- **JSON 文件原子写**：tmp + rename 模式，比直接 write 安全 10x
- **免费版限额是设计依据**：5 条/天 决定了「阈值过滤」必须默认开（INFO 全关）

### 测试覆盖

- 10 server_chan：成功/失败/网络异常/JSON 异常/web 链接/严重度 emoji
- 10 deduper：首推/重推/不同 code/不同 rule/跨日/损坏文件/clear/原子写
- 9 notifier：阈值过滤/去重/失败不标记/异常处理/batch 通知

---

## 重大 lessons learned（跨 milestone）

1. **Protocol 化一切接口** → 业务层永远 Mock 单测
2. **数据库是唯一真相源** → 拉新失败不致命
3. **多数据源 fallback 是生存策略** → 不是 nice-to-have
4. **early-return 是 bug 温床** → 复杂逻辑用 if/else 显式分支
5. **JSON 序列化 dataclass 不要用 asdict** → 嵌套类型（Money / Decimal）必须手写
6. **装饰器链的顺序很关键** → 外层缓存 + 内层 fallback
7. **凌晨实战最有价值** → 单元测试覆盖不到的真实故障
8. **MVP 极致简化 > 正统大而全** → Taro 调试 2h 失败 vs Vite 15min 跑通
9. **Protocol 化推送抽象 → 多渠道 0 成本** → 微信 / 钉钉 / Telegram 同一接口
10. **优雅降级是生产级标准** → 没 key / 推送挂 / 重启 都得保证主服务不挂
11. **产品定位清晰比功能多更重要** —— 团长在 2026-06-28 明确「券商三大痛点」+「两个场景」，决定后续开发顺序
12. **efinance get_today_bill 返回累计值** → 不是增量，盘日总货最取最后一条
13. **Vue 模板里调函数不能响应式更新** → computed / watch 才是正解（资金流 SVG NaN bug）
14. **K线库指标叠加要判重** → createIndicator 不去重会重复创建（切换周期多个 VOL）

## M4 — 持仓管理 + 语音录入 + 资金流图表 + 盘面扫描

**日期**：2026-06-28 全天
**状态**：✅ 全部完成并验证
**代码量**：~1500 行后端 + ~2000 行前端

### 完整交付清单

#### 后端

1. **持仓管理模块**（~600 行）
   - `portfolio/models.py` — Position + PositionAdjustment ORM
   - `portfolio/store.py` — PortfolioStore（CRUD + 加权平均成本 + 盈亏汇总）
   - `web/routes/portfolio.py` — 6 个 REST 端点
   - schemas: `PositionOut` / `PositionDetailOut` / `PortfolioSummaryOut` / `AddPositionIn` / `AddAdjustmentIn` / `AdjustmentOut`

2. **资金流增强**（~100 行修改）
   - `money_flow/today` 返回结构改为 `{items, cumulative}`，累计取最后一条
   - 新增 `money_flow/history?days=N` 端点，返回 5 维累计
   - 修复 `cache/store.py` 中 `get_money_flow_history` JSON 反序列化 bug（用 wrapper 存 trade_date）

3. **盘面排行模块**（~300 行）
   - `market_data/rankings.py` — 直连东财 push2 接口
     - 6 个大盘指数（沪深300 / 上证 / 深证 / 创业板 / 科创50 / 上证50）
     - 30 个板块涨跌幅（行业 + 概念合并去重）
   - `web/routes/market.py` — 4 个端点

#### 前端

1. **语音录入 composable**（`composables/useSpeechRecognition.ts`）
   - webkitSpeechRecognition 封装
   - 中文自然语言解析（「茅台买入价1680 100股」 → 字段）
   - fallback / 错误处理 / iOS Safari 兼容

2. **盘面页**（`pages/market/index.vue`，~600 行）
   - 6 个大盘指数卡片（上证 / 深证 / 创业板 / 沪深300 / 科创50 / 上证50）
   - 三个 Tab 切换：涨幅榜 / 跌幅榜 / 板块榜，各 TOP20
   - 持仓快览条联动跳持仓页
   - 30 秒轮询 + 数据年龄显示

3. **持仓页**（`pages/portfolio/index.vue`，~400 行）
   - 总市值 / 总成本 / 浮盈亏 大字号卡片
   - 持仓列表：成本 / 现价 / 股数 / 市值 / 盈亏标签
   - 「+ 录入」表单（代码/名称/价格/股数/日期/备注）
   - 🎙️ 语音录入弹窗（可点麦克风开始说话）

4. **详情页改造**
   - 删除盘口信息（聚焦资金流）
   - 资金流：5 维累计卡片 + 日内 SVG 折线 + 历史 SVG 柱状（零线居中）
   - 7 / 30 / 90 天切换

#### 文档

- `KLINE-SPEC.md` — K线技术规格完整文档
- `DISCUSSION-NOTES.md` — 产品讨论纪要（核心痛点 / 两大场景 / 设计哲学 / 待办事项）

### 修复的 bug

1. **buy_date 类型**（mappers.py）— date 对象不能调 _aware()，改为直传
2. **DetachedInstanceError**（store.py）— `cost_basis` 访问 `pos.adjustments` lazy load 失败，加 `selectinload`
3. **today 累计值错误**（routes/quotes.py）— sum 所有 items 是错的，取最后一条
4. **缓存层 money_flow JSON 类型错误**（cache/store.py）— 用 wrapper 包装 list
5. **K线 createIndicator 不判重**（detail/index.vue）— 用 isFirstInit 标志
6. **Vue function 不响应式**（detail/index.vue）— 改 computed

### 测试

- 后端 ruff + mypy strict 全过
- 前端 vite build 无警告
- 启动服务后全链路验证：录入持仓 → 实时拉价 → 计算盈亏 → 推送 → 资金流图 → 盘面榜
- 没补 portfolio / rankings 单测（P0 清单里）

### 团长交互记录

1. "来我们先跑起来我内网看看" — 启动服务
2. "我们来考虑如何丰富功能吧" — 讨论方向
3. "方向一可以，专注持仓管理也很重要" — 确定方向
4. "行这个输入仓位的时候，有没有更简单点的办法" — 提出录入问题
5. "要不直接 OCR 这样可以批量，然后再加语音" → "额还是先走语音吧" — 决策语音优先
6. "好资金流可不可以用图" — 资金流图表化
7. "有个 Bug：选一个时间尺度，就会增加一个交易量的图" — K线 bug
8. "跑一个测试给我截图看看效果，尤其是 K 线和资金流" — 验证截图
9. "说说 6 张呢，怎么只有一张啊" / "继续啊，继续发呀" — 微信渠道限制
10. "先去掉盘口信息，然后我们讨论如何改进界面" — 删除盘口
11. "现在的界面前信息量太少" — 信息量不足
12. "观察大盘行情 / 关注仓位信息 / 两套逻辑" — 产品哲学重大修正
13. "按计划开始推进吧" — 开工
14. "把讨论纪要总结成文档发给我" — DISCUSSION-NOTES.md
15. "把我的发言总结一下" — 后续产品哲学提炼

### 关键设计决策（产品方向）

**两大场景分开：**
- 场景 A：扫盘（盘面 Tab）—— 发现新机会
- 场景 B：盯盘（详情页驾驶舱）—— 决策仓位调整

**下一步**：详情页驾驶舱改造（顶部指标常驻 + Tab 切换 K线/资金流/成交/持仓），完成场景 B。

---

## 工具链统计

- **Python**：3.12 + uv + hatchling
- **Lint**：ruff（All checks passed）
- **Type check**：mypy --strict（0 errors）
- **Test**：pytest 154（145 离线通过 + 9 实时网络，凌晨抽风时偶发挂，**M4 未补单测**）
- **Code**：src 8500 行 + tests 2270 行 + scripts 391 行 + web (TS+Vite) 4500 行 ≈ 15000 行
- **CI**：未配（待加 GitHub Actions）

---

## M5 — 半导体产业链参考库

**日期**：2026-06-29 上午
**Commit**：`3a37aa2` — `feat(semicon): 半导体产业链参考库 + 106 条 A 股种子数据`
**代码量**：~600 行 src（4 文件：models / store / seed / __init__）

### 目标

妈妈和团长想研究「半导体产业链」，但没有一份结构化的 reference。新模块充当「知识库」，方便后续资金流研究锁定 106 只 A 股。

### 产出

| 文件 | 作用 | LOC |
|---|---|---|
| `src/mommy_chaogu/semicon/__init__.py` | 公共 API | 28 |
| `src/mommy_chaogu/semicon/models.py` | `SemiconStock` ORM（一张表） | 73 |
| `src/mommy_chaogu/semicon/seed.py` | 106 条种子数据 | 234 |
| `src/mommy_chaogu/semicon/store.py` | CRUD + 查询 + StrEnum 常量 | 273 |

**Schema 设计（一张表 semicon_stocks）**：

```
code              UNIQUE  股票代码
name                       中文名
chain_position             上游 / 中游 / 下游 / 末端
subcategory                EDA / IP / 设备 / 材料 / 存储 / ... / 制造 / 封测 / 分销
product                    具体产品（介质刻蚀 / NOR Flash 等）
board                      主板 / 创业板 / 科创板 / 北交所
note                       备注（跨分类 / 龙头标识）
created_at / updated_at
```

**关键设计决策**：
- **独立 db `data/semicon.db`**（不复用 watchlist.db）— 自选股是「我的池子」（动态），产业链是「参考知识库」（基本只读），语义不同
- **StrEnum 而非 Python enum** — IDE 提示有，但 schema 故意不用 enum 约束，加新分类时不需要改 schema
- **跨分类公司用 note 兜底** — 韦尔放「传感器」/ 复旦微电放「FPGA」/ 士兰微放「制造」+ note 写「兼：xxx」

### 验证

- ruff ✅ / mypy --strict ✅
- 106 条种子成功灌入
- 分布：上游 37 / 中游 55 / 下游 9 / 末端 5

---

## M5.1 — 资金流拉新 + 排行（基础设施）

**日期**：2026-06-29 下午
**Commit**：`d41bc0a` — `feat(flows): 资金流拉新 + 排行 CLI（按股票池）`
**代码量**：~600 行 src（3 文件：pool / service / __init__）

### 目标

把「拉哪几只」从「怎么拉」里解耦，避免将来每加一种股票池（比如新能源、白酒）都要复制粘贴一遍。

### 产出

| 文件 | 作用 | LOC |
|---|---|---|
| `src/mommy_chaogu/flows/__init__.py` | 公共 API | 36 |
| `src/mommy_chaogu/flows/pool.py` | `PoolSource` Protocol + 3 实现 | 99 |
| `src/mommy_chaogu/flows/service.py` | `FlowService` 高层 API | 414 |

**PoolSource 三实现**：
- `WatchlistPool`（5 只自选股，db=data/watchlist.db）
- `SemiconPool`（106 只产业链股，db=data/semicon.db）
- `CustomPool`（CLI --codes 手动指定）

**FlowService API**：`pull_today` / `pull_history` / `top_today` / `top_history` / `show` / `stats` / `clear`

**关键设计决策**：
- **复用 `CachedMarketDataAdapter`**（节流 + Tencent fallback + cache 表全部白嫖）
- **资金流缓存落 `data/watchlist.db`** 而非 `data/semicon.db`（缓存按 code 维度，跨池复用）
- **`--force` 选项**：重置节流时间戳，强制真打接口（首次 warmup 用）

### 验证

- ruff ✅ / mypy --strict ✅
- 113 个非网络测试全绿
- 实战：106 只 × today pull 13.5s（105/106 成功）+ 30d history pull 12.4s（106/106 成功）
- TOP 当日 净流入：澜起 +22亿 / 中微 +11亿 / 深科技 +9.66亿
- TOP 当日 净流出：长电 -29.7亿 / 华天 -11.3亿 / 通富 -6.2亿

---

## M5.2 — 资金流 ratio 信号 + 盘中监控 + 收盘日报

**日期**：2026-06-29 傍晚
**Commit**：`45e20fa` — `feat(flows): ratio-based 异动监控 + 收盘日报`

### 触发事件 + 团长反馈

**团长原话**：「数据规则是OK的，但是阈值这个你不要用人民币的绝对值，而是要用相对于市值的比值，这样更有信息量，不会有这个偏差」

**为什么 ratio 更合理**：
- 同样 5,000万净流入对茅台（1.5万亿）= 0.03bp（噪声）
- 对凯美特气（144亿）= 35bp（异动）
- 差 **1000 倍** —— 绝对值完全看不出来

### 产出（3 个新文件）

| 文件 | 作用 | LOC |
|---|---|---|
| `src/mommy_chaogu/flows/signals.py` | 4 条 ratio-based 规则 + evaluate() | 174 |
| `src/mommy_chaogu/flows/monitor.py` | `FlowMonitor` 持续轮询类 | 215 |
| `src/mommy_chaogu/flows/report.py` | `FlowReport` 收盘日报 markdown | 268 |

**ratio 信号公式**：
```
ratio = main_net / circulating_market_cap
1 bp = 1/10000 = 0.01%
```

**5 条默认规则**：

| rule_id | 触发条件 | severity |
|---|---|---|
| `flow_in_spike` | 5min delta > 5bp 净流入 | WARN |
| `flow_in_surge` | 5min delta > 10bp 净流入 | CRIT |
| `flow_out_spike` | 5min delta > 5bp 净流出 | WARN |
| `flow_out_surge` | 5min delta > 10bp 净流出 | CRIT |

**FlowMonitor 安全机制**：
- 状态持久化：`data/.flow_monitor_state.json`（断点续传）
- 失败告警：连续 3 轮 ≥ 50% 失败 → stdout 警告
- 信号写：`data/flows_monitor.log`

**FlowReport 收盘日报 markdown 包含**：
1. 池子概况 + 当日/30d 合计
2. **板块汇总**（按 ratio）：上游/中游/下游/末端
3. **TOP 10 流入 / TOP 10 流出**（按 ratio，不是绝对值）
4. **「矛盾股」清单**：今日 ratio>0 但 30d ratio<0

### 修复 bug

`flows/report.py` 第 191 行：板块汇总用错变量名 `cp`（tuple）导致 4 行都显示「中游」

### 实战数据（6/29 收盘）

- 板块 ratio：上游 +14.3bp / 中游 +10.1bp / 末端 -25.0bp / 下游 -77.4bp
- TOP 流入：凯美特气 +358bp / 聚辰 +127bp / 深科技 +104bp
- TOP 流出：晶方 -191bp / 长电 -161bp / 华天 -156bp
- 矛盾股 15 只（含澜起 +22亿/兆易 +4.4亿 反转信号）

### 验证

- ruff ✅ / mypy --strict ✅
- 113 个非网络测试全绿

---

## M5.3 — OpenClaw cron 4 jobs 自动化

**日期**：2026-06-29 17:30
**Commit**：（待 commit）— `chore(docs): M5.3 cron jobs + PROJECT-LOG 总览`

### 目标

把「每天盘前/盘中/收盘/周报」从手动 → 自动化。妈妈和团长不用记着跑命令。

### 4 个 OpenClaw cron jobs（model=deepseek-flash 省 token）

| 时间 | 名称 | Job ID | 推送 |
|---|---|---|---|
| 8:30 周一~五 | 盘前预热 | `f3fa79c8-689a-42e6-9db4-b617e5830b17` | silent |
| 9:30 周一~五 | 盘中监控启动 | `f39f3cbc-d723-49f8-b65e-28a2f5b1576b` | silent |
| 15:30 周一~五 | 收盘日报 | `94bd6c91-aadc-4796-b324-cdc4c0c89af7` | 推微信 |
| 周六 10:00 | 周报汇总 | `e902f385-3394-42d9-aeb0-db5d79634aa2` | 推微信 |

**关键设计决策**：
- **监控进程用 `--max-seconds 19800`（5.5h）自动退出** — 9:30 → 15:00，比 cron `pkill` 干净
- **启动前 `pgrep` 幂等检查** — 避免昨天没退干净时重复启动
- **silent 启动不打扰** — 只 15:30 + 周六推送，一天最多 1-2 条机器人消息
- **推送目标 = 团长当前聊天**（`channel=openclaw-weixin, accountId=0b4018927074-im-bot`）

### API 稳定性摸底结论（同步到本文件）

**东财资金流**：10/10、50/50、20/20 全绿，5min 节奏富余 22 倍
**腾讯资金流**：❌ 没有（stub 永远返回 []），资金流没有兜底

### 实战待验证

- ⏳ 6/30 周二第一次 cron 完整跑通（盘前预热 8:30 / 监控启动 9:30 / 收盘日报 15:30 / 周报 7/4）

---

## M6.1 — 修 cron model + 实战第一次跑通

**日期**：2026-07-01 08:30
**Commit**：（本次 7/1 文档 commit 一起）

### 触发事件

早上 8:30 盘前预热 cron 报错 `HTTP 401: Authentication Fails, Your api key: ****e993 is invalid`。

### 根因 + 修复

- **根因**：4 个 cron job 用的 `model: "minimax/MiniMax-M2.7"` 在新 provider 上不存在（M2.7 已下线，M3 上线）
- **修复**：
  1. 4 个 job model 改为 `deepseek/deepseek-v4-flash`（按 MEMORY 设计本的省 token 路径）
  2. message 顶部加 `export PATH="$HOME/.local/bin:$PATH"`，避免 cron 里 `uv` 找不到

### 验证结果（7/1 当日实战）

- 8:30 盘前预热：**105/106 只半导体资金流拉成功**（仅 002549 timeout 12.6s）
- 13.2s 总耗时，hub webhook **实际收到**（id=2 task_id=f3fa79c8）
- 证明：mommy-chaogu → hub → SQLite → 前端 ReportList **全链路打通**

---

## M6.2 — reports 目录结构化

**日期**：2026-07-01 07:30
**Commit**：`5bf2323 docs: reports/ 目录结构化（README + .gitignore）`

### 改动

- `reports/README.md`：解释用途 / 命名规则 / 怎么生成
- `reports/.gitignore`：排除 `index.html`（临时索引）+ `*.tmp.html`
- 保留 `reports/{YYYY-MM-DD}.html` 作为每日实战产物入仓
- 现有 `reports/2026-06-29.html` 6/29 首份实战保留

---

## M6.3 — supply_chains 数据资产

**日期**：2026-07-01 16:43-18:24
**Commit**：（本次 7/1 一起）

### 触发

发现 mommy-chaogu 缺一个标准化的"产业链标的数据"格式，妈妈需要扫描多板块时，每次都现拉现分析，效率低。

### 新增 3 个 JSON

| 文件 | 标的 | 大小 | 内容 |
|---|---|---|---|
| `data/supply_chains/humanoid_robot.json` | 25 只 | 13.5KB | 4 个层级（核心/Tier1/总成/设备）+ 16 个角色 |
| `data/supply_chains/semiconductor.json` | 106 只 | 39.5KB | 4 个 chain_position + 15 个 subcategory |
| `data/supply_chains/materials.json` | 41 只 | 19.0KB | **10 个子类**（化工/钢铁/煤炭/建材/稀土/工业金属/贵金属/小金属/新能源金属/石油）|

### 共同结构

```json
{
  "meta": {
    "name": "...",
    "description": "...",
    "total_stocks": N,
    "levels": [...]    // 或 categories / chain_positions
  },
  "snapshot": {
    "ts": "...",
    "up": N, "down": N, "flat": N,
    "sector_avg_pct": X,
    "total_main_net_yi": Y
  },
  "stocks": [
    {
      "code": "...",
      "name": "...",
      "role": "...",
      "level": "..." | "category": "..." | "subcategory": "...",
      "price": X, "change_pct": X, "volume_ratio": X,
      "circulating_market_cap": X, "pe_dynamic": X,
      "main_net": X, "super_large_net": X, ...
    },
    ...
  ]
}
```

### 复用方式

```python
import json
from pathlib import Path
data = json.loads(Path('data/supply_chains/semiconductor.json').read_text())
# 按 level 过滤
上游 = [s for s in data['stocks'] if s['level'] == '上游']
# 按涨幅排序
data['stocks'].sort(key=lambda x: -x['change_pct'])
```

### Mommy-hub 同步

3 个 JSON 同步复制到 `~/Git/mommy-hub/data/chains/`，hub 通过 `/api/chains` 自动发现。

---

## M6.4 — 7/1 多板块实战扫描

**日期**：2026-07-01 09:00-18:30
**Commit**：（本次 7/1 一起）

### 实战记录

一天内完成 10+ 次板块扫描 + 6 个股深挖，全部推 hub 留底。

| 时间 | 板块/个股 | 关键发现 | hub report |
|---|---|---|---|
| 09:47 | 自选股 5 只 | 全跌，主力 -19.4亿（宁德 -12.15亿）| — |
| 10:42 | 半导体 106 只 | 涨 82/跌 23，均价 +0.74%，上游强 | — |
| 10:51 | AI 推理 4 只 | 寒武纪 -4.11% 高位调整 | — |
| 10:42 | 光模块 14 只 | 普跌 -2.74%，联特 +4.75% 异动 | — |
| 13:38 | 联特科技深挖 | PE 514 倍 + 60 日 +55.4% = 已 price in | — |
| 13:39 | 潍柴动力深挖 | **半年主力 -43.17亿出货**（修正"接盘"误判）| — |
| 15:47 | 证券 18 只 | +4.55% 普涨，**6 月机构 +12.5亿 龙头建仓** | — |
| 16:43 | 机器人 25 只 | 21 涨/4 跌，均价 +2.38% | id=9 |
| 17:06 | 机器人 6 只强股 | 雷赛智能「5日机构 +1.79亿」最稳健 | — |
| 18:22 | 雷赛智能深挖 | 5/10 日机构 +1.79/+2.40亿 + 量价 +0.65 | — |
| 18:24 | 材料 41 只 | 化工 +3.62% 强，稀土 -3.17% 弱 | id=10 |
| 18:39 | 多氟多深挖 | 60日+100% / 250日+408% / 20日机构 -87.7亿 | — |

### 5 大教训

1. **「机构 5 日在买 vs 20 日仍在出货」** 是市场普遍形态（多氟多/雷赛/联特都如此）
2. **「价格已 price in」** 是主要风险——多氟多 60 日 +100% / 250 日 +408%
3. **「量价背离 -0.5 以下」** 是出货信号（多氟多 10 日 -0.48）
4. **「半年数据是真相，5 日数据是噪声」**—— 潍柴 5 日看似"接盘"实为 -43亿派发
5. **「Efinance push2his 接口凌晨 2-3 点会主动断」**—— 改用腾讯 K线作为备选

### 临时脚本（不提交，存 /tmp）

- `screenshot.js` / `screenshot_chains.js` —— playwright + chromium 截图 hub 前端
- `voice_brief.txt` + `voice_brief.m4a` —— macOS `say` + `afconvert` 生成语音版简报
- `push_scan_report.py` —— 推扫描结果到 hub webhook

---

## M7.1 — 中信证券 H1 2026 业绩前瞻 DB

**日期**：2026-07-02 上午
**Commit**：`5326b1e` — `feat(data): H1 2026 业绩前瞻数据库 schema + loader 脚本`

### 触发场景

团长发来中信证券《电子行业 2026 年中报业绩前瞻》图，要求「囊括这里的所有信息」。

### 产出

| 文件 | 作用 | 行数 |
|---|---|---|
| `data/earnings_preview.db` | 41 家公司业绩前瞻 SQLite | 45KB |
| `scripts/load_earnings_preview.py` | loader（dry-run / summary / upsert）| 367 |
| `docs/EARNINGS-HANDBOOK.md` | 实战手册（12 章节 / 407 行）| （M7.3） |

### 设计决策

1. **SQLite + Decimal TEXT 存储** —— 避免 SQLite 浮点精度问题
2. **UNIQUE(code, period, source) 约束** —— 支持跨券商研报 upsert
3. **v_sector_summary 视图** —— 板块家数/平均增速/业绩弹性分组
4. **sector + subsector 双层分类** —— 一级板块（半导体/PCB/...）+ 二级细分（存储/设计/设备/...）

### 41 家公司分布

| 板块 | 家数 | 平均增速 | +200% | 下滑 |
|---|---|---|---|---|
| LED | 2 | +518.5% | 1 | 1 |
| 半导体 | 19 | +217.8% | 7 | 1 |
| 面板 | 3 | +152.7% | 1 | 0 |
| AI算力 | 2 | +122.0% | 0 | 0 |
| 传感器 | 2 | +115.3% | 1 | 0 |
| PCB | 5 | +39.4% | 0 | 1 |
| 机器人 | 1 | +35.0% | 0 | 0 |
| 消费电子 | 7 | +28.1% | 0 | 1 |

### 5 维度评分与教训

1. **业绩弹性不是绝对值，是 ratio**——同样 +200% 净利润增长，3 亿市值 vs 300 亿市值意义天差地别
2. **券商预测偏差 30-50%**——7/15 起 actual 披露后需校准
3. **板块整体向上不代表个股向上**——半导体 19 家中 1 家下滑（斯达半导）
4. **Convexity > Alpha 本身**—— +200% 以上标的具备期权式 payoff
5. **业绩预告日 70% 跳空**—— 7/15 起 T+1 开盘是关键决策点

---

## M7.2 — Thematic watchlist groups + 41 家公司入库

**日期**：2026-07-02 中午
**Commit**：`4d96d83` — `feat(watchlist): 按主题分组 H1 2026 业绩前瞻 + 41 家公司入库`

### 触发需求

团长说：「我们要把这里面涉及到的所有的这个股票，按类别按主题把它分成不同的自选观察列表...我并不在乎到底什么是自选的主要...不需要说啊说我就这些都是自选股，然后他们就是一类自选股」。

### 设计哲学

- **多 group 而非单一「自选股」**——13 个主题 group
- **持仓（白酒/银行/新能源）与主题（13 个）分离**——团长要的「主题篮子」模型
- **一只股可属多 group**（M:N 通过多条 StockEntry）——柯力 603662 在「传感器」+「机器人」2 组
- **StockEntry.note 存业绩信息**——例如「+188%~+217% | driver=机器人/工业 | ⭐」

### 13 个主题组

```
消费电子         (7) - 领益/歌尔/水晶/蓝思/华勤/协创/雷神
半导体-IC设计    (6) - 韦尔/纳芯微/思特威/星宸/瑞芯微/汇成
PCB            (5) - 沪电/胜宏/深南/广合/世运
半导体-材料     (4) - 南亚新材/富创精密/露笑/斯达半导
半导体-设备     (4) - 北方华创/中微/华海清科/芯源微
面板            (3) - TCL/京东方/三孚
AI算力          (2) - 寒武纪/海光
LED            (2) - 木林森/聚灿
传感器          (2) - 柯力/优利德
半导体-存储      (2) - 兆易/北京君正
半导体-封测      (2) - 通富/长电
机器人          (2) - 柯力(跨组)/双环传动
半导体-LED设备   (1) - 新益昌
```

### 实战洞察

- **柯力 603662 跨 2 组**——既是六维力传感器龙头，又是人形机器人核心标的
- **半导体 6 子类细分**——避免一篮子堆 19 家难选股
- **现行 schema 已支持 M:N**——(code, group_id) UNIQUE + 多次插入 = 一股多组

---

## M7.3 — 中报窗口实战手册 v1.0

**日期**：2026-07-02 下午
**Commit**：`018b276` — `docs(EARNINGS-HANDBOOK): 2026 中报窗口实战手册 v1.0`

### 12 章节结构

```
一、TL;DR — 3 条铁律
二、关键时间线 (7/2 → 8/31)
三、监控规则 (T-7 / T-0 / T+1)
四、4 大实战策略 (超预期 / Convexity / 配对 / 板块轮动)
五、仓位管理节奏 (单股 ≤10% / 板块 ≤25%)
六、风险控制 (止损 / 黑天鹅 / 心理纪律)
七、4 条交易信号定义
八、实战案例：柯力 603662 (三情景推演)
九、操作清单 (每日 / 每周 / 阶段)
十、相关数据资产
十一、决策心法 (7 条实战沉淀)
十二、版本
```

### 核心策略

1. **超预期交易**：T-7 入选 → T-0 比对 → T+1 9:30-9:35 行动
2. **Convexity Plays**：预测 +200% 以上 = 期权式 payoff
3. **板块内配对**：AI 算力 long 寒武纪 / short 海光；LED long 木林森 / short 聚灿
4. **板块轮动**：半导体/面板/LED/AI算力超配，消费电子低配

### 柯力 603662 三情景

| 情景 | actual | T+1 开盘 | 操作 |
|---|---|---|---|
| A | +220% (超) | +8-12% | T+1 加仓至 8%，T+7 减半 |
| B | +200% (中位) | ±2% | HOLD |
| C | +180% (低) | -5~-8% | T+1 减仓 50%，跌破 65 元清仓 |

---

## M7.4 — earnings_actual 模块（types/store/service/signals/adapter/cli）

**日期**：2026-07-02 下午
**Commit**：待提交
**代码量**：1263 行 src + 911 行 tests + 1163 行 docs = **2074 行**

### 模块结构

```
src/mommy_chaogu/earnings/
├── __init__.py        # public API
├── types.py           # EarningsActual/Calendar/Score/Verdict
├── schema.py          # 3 表 + 9 索引 + v_recent_disclosures 视图
├── store.py           # EarningsStore (SQLite ORM-like)
├── adapter.py         # EarningsAdapter Protocol + MockEarningsAdapter
├── service.py         # EarningsService (pull/score/watch/summary)
├── signals.py         # 4 条 earnings 信号规则
└── cli.py             # mommy-earnings CLI (pull/score/watch/summary)
```

### 3 张表

| 表 | 字段数 | UNIQUE 约束 | 用途 |
|---|---|---|---|
| earnings_actual | 11 | (code, period, source) | 实际披露业绩 |
| earnings_score | 13 | (code, period) | actual vs predicted 比对 |
| earnings_calendar | 7 | (code, period) | 公告日期日历 |

### 4 条信号规则

| 规则 | 触发条件 | 严重度 |
|---|---|---|
| earnings_beat | actual > predicted_high | CRITICAL |
| earnings_meet | 在预测区间内 | INFO |
| earnings_miss | actual < predicted_low | CRITICAL |
| earnings_approaching | T-7 内 + predicted_high > 100% | WARNING |

### CLI 测试

```bash
$ mommy-earnings pull --codes 603662,603986 --period "H1 2026"
📥 拉取完成: 成功 2, 失败 0
   耗时: 0.00s

$ mommy-earnings score --period "H1 2026"
📊 比对完成: 成功 2, 失败 0
🏆 TOP 5:
603662 柯力传感    188~217%   202.5%    🟡 符合
603986 兆易创新   1070~1370%  1220.0%   🟡 符合

$ mommy-earnings summary --period "H1 2026"
verdict          数量       占比
🟢 超预期             0     0.0%
🟡 符合              2   100.0%
🔴 大幅低于           0     0.0%
```

### 设计教训

1. **Protocol + dataclass 是 mypy strict 的好搭档**——但 mutable attribute 必须显式定义
2. **RUF012 mutable default**——MOCK_DATA 用 ClassVar 解决
3. **RUF009 function call in dataclass defaults**——用 field(default_factory=...)
4. **frozen dataclass + Protocol attribute 冲突**——去掉 frozen 或用 property
5. **sqlite3.ProgrammingError 的 UPDATE 参数错位**——明确按索引取值，不依赖切片

### 待补（P1 - 财报窗口前）

- [ ] EfinanceEarningsAdapter（替换 Mock）
- [ ] EarningsCalendar 公告日历爬取（东财 / 交易所）
- [ ] 7/15 起 cron job 集成（每天 16:00 扫描 + 比对 + 推微信）
- [ ] 与 signals/alerter.py 集成（生成 Signal 后推微信）

---

## M7.5 — 柯力 603662 + 中信报告实战分析

**日期**：2026-07-02 全天
**类型**：实战演练（非代码 commit）

### 实战时间线

| 时间 | 动作 | 关键发现 |
|---|---|---|
| 11:04 | 柯力深挖 | 现价 75.13, 主力 +0.77 亿 (+36.5bp), 10 日累计 -1.78 亿 |
| 11:30 | 中信 H1 前瞻图 | 41 家公司业绩弹性分布 |
| 12:08 | 柯力业绩催化 | H1 +188~+217%, 人形机器人主线 |
| 12:27 | 多主题 group 入库 | 13 主题 / 42 条记录 |
| 14:04 | 实战手册发布 | 12 章节 / 407 行 |
| 15:29 | P1 + docs 落地 | earnings_actual 模块 + CLI + 51 测试 |

### 核心结论

- **柯力 603662** = 反转初期信号 + 业绩催化 + 主线题材三重共振
- **预警**：「中性偏空」评分是滞后指标，10 日累计 -1.78 亿 包含了 6/22-6/29 流出段，今日反转尚未计入
- **建议**：7/3-7/5 流入信号确认后加仓；10 日累计转正后视为趋势确立

### 5 大心法

1. **Convexity > Alpha 本身**——预测 +200% 以上 vs +50% 标的，赔率天差地别
2. **半年报窗口 = alpha 窗口**——7/15-8/31 这 45 天，主线资金的进出决定一切
3. **业绩预告日 70% 跳空**——T+1 9:30-9:35 行动窗口稍纵即逝
4. **多主题篮子 > 单一自选股**——团长要的「主题篮子」模型落地
5. **数据 → 策略 → 实战**——3 步走，每步都有 commit + 测试 + 文档

---

## LLM-BT — LLM 回测框架 + Token Tracker

**日期**：2026-07-04
**Commit**：`e6edf43` — `feat: LLM backtest framework + token tracker + backtest report`
**Commit**：`863acf8` — `feat(backtest): add zai/glm-4.7 provider for LLM backtest`
**代码量**：~800 行（token_tracker 300 + backtest_llm 600 + 测试 300）

### 目标

规则引擎回测只看资金流两个维度。LLM 回测用完整 agent 工具链对同样数据做更立体的
判断，衡量「LLM + 多数据源」相对于纯规则的增益，以及 token 成本是否值得。

团长特别要求：跑 LLM 回测之前先搭一个可以观测 LLM Token 使用量的系统。

### 产出

| 文件 | 作用 | 行数 |
|---|---|---|
| `src/mommy_chaogu/agent/token_tracker.py` | Token 用量追踪（per-provider / per-model 统计 + 成本估算） | ~300 |
| `tests/test_agent/test_token_tracker.py` | 36 个单测 | ~300 |
| `scripts/backtest_llm.py` | LLM 驱动回测脚本（离线读 market.db，4 provider 支持） | ~600 |
| `docs/BACKTEST-REPORT.md` | 回测报告（方法学 + 规则引擎结果 + LLM 框架状态） | ~320 |

### Token Tracker 设计

- **`TokenUsage` dataclass** — 累计 prompt/completion/total tokens + 估算成本
- **`TokenTracker`** — 按 provider + model 维度聚合，支持 session 级和全局统计
- **定价表** — 内置 6 个模型（deepseek-chat / deepseek-coder / gpt-4o / gpt-4o-mini /
  moonshot-v1-8k / glm-4.7）的每百万 token 单价（¥/M input, ¥/M output）
- **持久化** — 写入 `data/agent.db` 的 `token_usage` 表

### LLM 回测脚本设计

- **离线**：从 `data/market.db` 读 klines + flows，不联网
- **滑动窗口**：每个交易日 × 每只股票，取前 N 天数据拼成上下文喂 LLM
- **JSON 输出**：LLM 返回 `{direction, rationale}` 结构化预测
- **T+N 验证**：同规则引擎 `verify_prediction()`，对比入场价 vs T+5 收盘
- **4 provider**：deepseek / openai / kimi（moonshot）/ zai（z.ai / glm-4.7）
- **dry-run 模式**：不调 LLM，只打印上下文，验证数据管线

### 关键决策

1. **离线读 market.db 而非实时拉取** — 保证可复现，不受网络波动影响
2. **z.ai 可作为 LLM provider** — kimi-code 自身就是 LLM，可直接调 z.ai 接口，
   不需要外部 API key
3. **Token Tracker 独立于回测** — 也能用于生产环境的 AgentService token 监控

### 验证

- 36 token tracker 单测全过
- dry-run 验证通过（能读 market.db 真实数据、构建上下文）
- 518 passed（482 + 36 token tracker），ruff ✅，mypy ✅
- 注意：5 月 K 线存在但资金流数据从 6/4 开始，LLM 回测有效窗口约 15 个交易日

### 当前状态

框架全部就绪，**trial_1 尚未实跑**。上一个 session 在配置 zai provider 时中断。
下次只需：

```bash
export ZAI_API_KEY="..."
uv run python scripts/backtest_llm.py --provider zai --model glm-4.7
```

---

## Agent-BT — Agent 原生回测 trial_1

**日期**：2026-07-04
**Commit**：本次提交

### 目标

在没有外部 API key 的情况下，利用 coding agent 自身的 LLM 能力直接分析真实市场
数据，完成首次 LLM 回测 trial_1。同时验证「agent 原生回测」作为第三种回测方法的
可行性。

### 方法

1. `scripts/prepare_agent_backtest.py` 从 `data/market.db` 抽取 5 只半导体链股票 ×
   5 个日期 = 25 条数据包，每条包含前 10 天 K 线 + 资金流上下文
2. **数据/答案分离**：数据包不含 T+5 收盘价，单独输出到 answers 文件（防 look-ahead bias）
3. Agent 直接读取数据包 JSON，逐条分析 K 线形态 + 资金流趋势 + 量价关系，输出预测
4. 用与规则引擎完全相同的评分逻辑验证（direction → change_pct → hit/missed + score）

### 结果

| 指标 | 值 | vs 规则引擎 |
|---|---|---|
| 方向性预测 | 19 条（+6 条 neutral） | 规则引擎无 neutral |
| **总命中率** | **47%（9/19）** | 规则引擎 53%（-6pp） |
| **Bullish 命中率** | **88%（7/8）** | 规则引擎 41%（**+47pp** ✅） |
| **Bearish 命中率** | **18%（2/11）** | 规则引擎 57%（**-39pp** ❌） |
| 估算成本 | **¥0** | ¥0 |

### 核心发现

**LLM bullish 判断远胜规则引擎（88% vs 41%）**，但 bearish 判断严重失准（18%）。
原因：回测区间半导体板块整体强势上涨，LLM 基于短期资金流流出的 bearish 判断被
板块趋势反复打脸。

**两种方法互补性极强**：bullish 用 LLM + bearish 用规则引擎，理论混合命中率可达 73%。

### 产出

| 文件 | 作用 |
|---|---|
| `scripts/prepare_agent_backtest.py` | Agent 原生回测数据准备脚本（通用基础设施） |
| `docs/BACKTEST-REPORT.md` §3.4 | Agent 原生 trial_1 完整结果 |
| `docs/BACKTEST-REPORT.md` §3.5 | Agent 原生回测模式文档（概念 / 优劣 / 复现步骤） |
