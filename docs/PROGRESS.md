# 进度总结 (PROGRESS.md)

> mommy-chaogu 当前在哪个位置？**做完什么**、**还差什么**、**接下来做什么**。

最后更新：2026-06-27

---

## TL;DR

| 维度 | 状态 |
|---|---|
| 项目阶段 | **M2.5 完成，M3 起步** |
| 代码量 | **~6900 行**（src 4593 + tests 1891 + scripts 391） |
| 测试 | **125 个，119 离线通过 + 6 efinance 实时网络**（凌晨抽风时偶发挂） |
| 代码质量 | ruff ✅ / mypy strict ✅ 0 errors |
| 文档 | **本次新增 DESIGN + LEDGER + PROGRESS** |
| 实战验证 | ✅ 凌晨东财挂、腾讯顶上、5 只自选股 + 8 条信号全触发 |

---

## 当前架构总览

```
┌──────────────────────────────────────────────────────────────┐
│  CLI (mommy-chaogu)                                          │
│  ├─ mommy-watchlist (自选股管理)                              │
│  ├─ mommy-monitor (实时监控)                                  │
│  └─ mommy-cache (缓存管理)                                    │
└────────┬─────────────────────────────────────────────────────┘
         │
         ↓
┌──────────────────────────────────────────────────────────────┐
│  业务层                                                      │
│  ├─ monitor.poller   (snapshot / 持续轮询)                    │
│  ├─ signals.alerter  (7 条规则 + 落盘)                        │
│  └─ watchlist.store  (Group + StockEntry)                    │
└────────┬─────────────────────────────────────────────────────┘
         │
         ↓  (all via MarketDataAdapter Protocol)
┌──────────────────────────────────────────────────────────────┐
│  装饰器链                                                    │
│  ┌────────────────────────────────────────┐                  │
│  │ CachedMarketDataAdapter               │ ← 缓存 + 节流    │
│  │  ├─ DB 命中 → 直接返回 [hit]           │                  │
│  │  ├─ DB miss → 拉新 → 写回 [miss]       │                  │
│  │  └─ 拉新失败 → 静默 fallback 旧数据     │                  │
│  └────────────────────────────────────────┘                  │
│           ↓                                                   │
│  ┌────────────────────────────────────────┐                  │
│  │ FallbackAdapter                        │ ← 多源 fallback │
│  │  ├─ EfinanceAdapter (主)                │                  │
│  │  └─ TencentAdapter  (备)                │                  │
│  └────────────────────────────────────────┘                  │
└────────┬─────────────────────────────────────────────────────┘
         │
         ↓
┌──────────────────────────────────────────────────────────────┐
│  数据源                                                      │
│  ├─ qt.gtimg.cn (腾讯)   行情 + 5 档                          │
│  └─ push2.eastmoney.com (东财)  K线 + 资金流 + 板块 + 全市场   │
└──────────────────────────────────────────────────────────────┘
```

---

## 已完成的里程碑

### ✅ M0 — 行情数据层（2026-06-26）
**Commit**：`dc8fd33` · **行数**：~800

- 11 个 dataclass + 4 个 StrEnum
- `MarketDataAdapter` Protocol
- `EfinanceAdapter` 覆盖 11 路数据
- 冒烟脚本 11 段全绿

### ✅ M1 — 自选池 + 监控（2026-06-26）
**Commit**：`dac4f8d` · **行数**：~800

- `watchlist/` SQLite + SQLAlchemy 2.0 ORM
- `monitor/` snapshot + 持续轮询
- CLI: `mommy-watchlist` / `mommy-monitor`
- 控制台表格 + `data/monitor.log`

### ✅ M1.5 — 信号告警（2026-06-26）
**Commit**：`2a44ed8` · **行数**：~900

- 7 条内置规则（价格/跳空/资金/量/换手/自选股联动）
- `Alerter` 聚合 + 去重 + 落盘
- 31 单测

### ✅ M2 — 缓存层（2026-06-26）
**Commit**：`30fad29` · **行数**：~1900

- 5 张表 DDL（带双时间戳）
- `CachedMarketDataAdapter` 装饰器
- `CacheManager` warmup / refresh / stats / freshness
- CLI: `mommy-cache` 6 子命令

### ✅ M2.5 — 腾讯兜底（2026-06-27）
**Commit**：`1910bc1` · **行数**：~850

- `TencentAdapter`（qt.gtimg.cn）
- `FallbackAdapter` 多源 fallback
- **凌晨实战验证**：东财挂、腾讯顶、5/5 成功

### ✅ M0.5 — 文档体系（2026-06-27）
**Commit**：（本次提交）· **行数**：~700（markdown）

- `docs/DESIGN.md` — 架构 + 原则 + 5 份 ADR
- `docs/LEDGER.md` — 5 个 milestone 逐条时间线
- `docs/PROGRESS.md` — 本文

---

## 当前功能矩阵

| 能力 | 数据源 | 缓存 | 监控 | 信号 | 状态 |
|---|---|---|---|---|---|
| 实时报价 | ✅ efin+tencent | ✅ | ✅ | ✅ | 🟢 |
| 5 档盘口 | ✅ efin+tencent | ✅ | ❌ | ❌ | 🟡 |
| K 线 | ✅ efinance | ✅ | ❌ | ❌ | 🟡 |
| 资金流（当日） | ✅ efinance | ✅ | ✅ | ✅ | 🟢 |
| 资金流（历史） | ✅ efinance | ✅ | ❌ | ❌ | 🟡 |
| 板块列表 | ✅ efinance | ✅ | ❌ | ❌ | 🟡 |
| 全市场快照 | ✅ efinance | ✅ | ✅ | ✅ | 🟢 |
| 自选股分组 | — | — | ✅ | ✅ | 🟢 |
| 信号告警 | — | — | ✅ | ✅ | 🟢 |
| 数据新鲜度报告 | — | ✅ | ❌ | — | 🟢 |

🟢 完整可用 · 🟡 数据可达但未深度集成 · ❌ 未实现

---

## 测试覆盖

```
tests/
├── test_market_data/
│   ├── test_types.py            13  # dataclass 验证
│   ├── test_efinance_adapter.py 11  # 实时网络（凌晨抽风时挂）
│   └── test_tencent_adapter.py  17  # 解析 + 边界
├── test_watchlist/
│   └── test_store.py            17  # CRUD
├── test_monitor/
│   └── test_poller.py           10  # 轮询逻辑（Mock）
├── test_signals/
│   └── test_rules.py            31  # 7 条规则各 3-5 case
└── test_cache/
    └── test_adapter.py          26  # 命中/拉新/失败 fallback/节流/历史
                                  ──
                              125 total
```

- **离线 119 个全绿**（Mock adapter + 单元逻辑）
- **efinance 实时网络 6 个** — 凌晨东财抽风时挂，正常时段全绿
- 后续可加 `pytest -m "not live"` 跳过网络测试

---

## 已知问题 & 限制

### 技术债

1. **CLI 没用 `click` / `typer`**：argparse 写得有点冗长
2. **没接异步 HTTP**：`requests` 同步，K线/全市场慢的话需要 aiohttp
3. **SQLAlchemy session 管理**：异步 + 长生命周期监控要小心
4. **6 个 efinance 实时测试偶发挂**：东财接口不稳（已知问题，监控层已 fallback）

### 缺失能力（从 README 路线图看）

- [ ] **M2** — 复盘报告（每日收盘后生成 markdown）
- [ ] **M2** — 微信 / Server酱 推送（信号触发主动推）
- [ ] **M3** — K线信号（跌破均线 / 金叉死叉 / MACD）
- [ ] **M3** — 投资组合跟踪（成本 / 盈亏 / 持仓占比）
- [ ] **M3** — 风险提示（涨停板 / 跌停板 / 异动）
- [ ] **M4** — Web UI（妈妈不会用 CLI 的备选）
- [ ] **M4** — 买点信号 + 止盈止损策略

---

## 下一步建议（按团长优先级）

### 🟥 优先级 P0：马上做
1. **配置 CI（GitHub Actions）** — ruff + mypy + pytest 自动化
2. **`pytest -m live` 标记** — 区分离线/网络测试
3. **修复 6 个 flaky efinance 测试** — 加 retry + skip 机制

### 🟧 优先级 P1：本周
4. **复盘报告** — 妈妈收盘后看「今天自选股发生了什么」
5. **微信推送** — 信号触发主动推（Server酱最简单）
6. **风险提示规则** — 涨停板 / 跌停板 / 单股异动

### 🟨 优先级 P2：本月
7. **K线信号** — MA / MACD / BOLL
8. **组合跟踪** — 成本 / 盈亏
9. **Web UI** — FastAPI + Vue 3 简化版

### 🟦 优先级 P3：未来
10. **回测引擎** — 验证信号规则历史表现
11. **多用户支持** — 妈妈 + 丈母娘 + 团长
12. **智能推荐** — 不荐股，只做「类似历史异动」检索

---

## 重要数据点

| 指标 | 值 | 说明 |
|---|---|---|
| 代码量 | **6875 行** | src 4593 + tests 1891 + scripts 391 |
| Commit 数 | **6** | 5 个 milestone + 1 个文档 |
| 测试数 | **125** | 119 离线 + 6 实时网络 |
| ruff | ✅ | All checks passed |
| mypy --strict | ✅ | 0 errors |
| pytest | ✅ | 119 passed / 6 flaky live |
| 数据源 | 2 | efinance (主) + tencent (备) |
| CLI 子命令 | **14** | watchlist 7 + monitor 5 + cache 6 + root |
| 业务规则 | **7** | 价格/跳空/资金/量/换手/自选股联动 |
| 数据库表 | **8** | 5 cache + 2 watchlist + 1 signals |

---

## 给团长的话

**做得不错，但离「牛逼」还差：**

1. **CI 没接** — 现在是「我手动跑」状态，不够稳
2. **没推送给妈妈** — 信号触发了，团长要看 `data/signals.log` 才知道 → 妈妈看不到
3. **没复盘** — 每天收盘后要主动 `mommy-monitor log` 看 → 麻烦
4. **没风险提示** — 涨停板、跌停板这种「应该立刻知道」的事没规则

**建议下次先做 P0+P1**：
- CI 半小时能配好
- Server酱 推送也是 1 小时内
- 复盘报告半天

**做完 P1，妈妈就真的能「躺着用」了**。

---

## 相关文档

- `docs/DESIGN.md` — 架构 + 原则 + 5 份 ADR
- `docs/LEDGER.md` — 逐条时间线（commit 级别）
- `README.md` — 快速上手
