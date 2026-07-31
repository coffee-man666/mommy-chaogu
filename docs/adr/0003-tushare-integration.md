# ADR 0003: Tushare 数据源集成

- Status: Accepted
- Date: 2026-07-31

## Context

ADR 0002 时曾评估过 Tushare（`tushare-integration.patch`），当时因三个阻塞性 bug
拒绝：`Money * Decimal` 崩溃、`moneyflow` 字段名捏造、provider 配置与 `llm.py`
单一真相源冲突。

Tushare 的价值仍在：财务三表/分红/历史 K 线业内最全，且服务部署在阿里云，
**海外 IP 直连稳定**——efinance/腾讯/akshare 对境外用户都不友好。本次重新集成，
并在代码审核中对照 tushare.pro 官方文档修掉了上一轮遗留的正确性问题。

## Decision

把 Tushare 作为 fallback 链的**第三档**接入，定位为"EOD 强项源"：

```
EfinanceAdapter (主源) → TencentAdapter (实时异构兜底) → TushareAdapter (EOD 强项) → AkShareAdapter (字段补全)
```

**为什么排在腾讯之后**：`TushareAdapter.get_quote` 返回的是 daily + daily_basic
合成的 EOD 快照（最早可能滞后 30 天）。若排在腾讯之前，efinance 挂掉时会被这份
过期快照截胡，真正的实时异构兜底永远轮不到。EOD 快照只在 东财+腾讯 同时失败时
才有价值（境外场景）。

**仅在有 token 时启用**：`TUSHARE_TOKEN` 未配置则 `is_available=False`，builder
自动跳过，不进入链。

### 接口范围与关键约定

| 方法 | Tushare 接口 | 关键约定 |
|---|---|---|
| `get_quote` / `get_quotes` | daily + daily_basic 合成 | EOD 快照；amount 单位**千元** ×1000；市值万元 ×10000 |
| `get_bars`（日/周/月） | pro_bar(adj=qfq/hfq/None) | **分钟线不支持**（stk_mins 需单独权限，且 pro_bar 在 adj≠None 时 drop trade_date 列） |
| `get_today/history_money_flow` | moneyflow | 需 2000 积分；只覆盖沪深；amount 单位**万元** ×10000；四档净流入 = buy_xx − sell_xx 自算 |
| 财务三表/分红/指标 | income/balancesheet/cashflow/dividend/fina_indicator | 返回原始 dict，键名与 Tushare 一致 |
| `get_order_book` / `get_ticks` / `get_belonging_boards` / `list_market_quotes` | — | 返回空，交给链上其它源 |

### 复权公式（与 pro_bar 对齐）

Tushare `adj_factor` 上市首日 = 1，随分红送股**递增**（越晚越大）。因此：

- 前复权：`price × cur_factor / latest_factor`（最新价不变，历史价压低）
- 后复权：`price × cur_factor / earliest_factor`（最早价不变）

`apply_adjustment` 曾因"因子越早越大"的错误假设把两个公式写反，本轮已修正，
测试 fixture 改为使用递增因子的真实语义。

## Consequences

- K 线/资金流/财务数据在海外 IP 下可用，且复权价与 Tushare 官方一致
- 成交额/资金流金额与 efinance 一样统一为**元**（Decimal），跨源量纲一致
- moneyflow/adj_factor 需 2000 积分，积分不足时静默降级为空——需自行在
  tushare.pro 后台确认积分等级
