# ADR 0002: AKShare 数据源集成（第一步 + 第二步）

- Status: Accepted
- Date: 2026-07-25

## Context

行情数据层原先只有 `EfinanceAdapter`（主源）+ `TencentAdapter`（实时报价兜底）。两者
通过 `FallbackAdapter` 串联。efinance 走东财 `push2his.eastmoney.com`，单股 `get_quote`
字段经常缺 PE/PB/市值；腾讯只给报价不给 K 线。

考虑过 Tushare（见被拒的 `tushare-integration.patch`），但 Tushare 需要 token + 2000 积分，
且 patch 里有三个阻塞性 bug（`Money * Decimal` 崩溃、`moneyflow` 字段名捏造、
provider 配置改动与 `llm.py` 单一真相源重组冲突）。

AKShare 是开源、无 token、走东财 + 新浪等多源后端的库，`stock_zh_a_spot_em` 一次性给
PE/PB/总市值/流通市值/换手率/量比，是 efinance 单股接口的字段补全源。

## Decision

把 AKShare 作为 fallback 链的**第三档**接入，定位为"字段补全源"而非"故障兜底"：

```
EfinanceAdapter (主源)  →  TencentAdapter (异构兜底)  →  AkShareAdapter (字段补全)
```

**为什么 akshare 不是主源或故障兜底**：它和 efinance 都走东财后端，东财挂的时候两个
一起挂——真正的故障多样性在 东财 ↔ 腾讯 这条轴上。akshare 的增量价值是字段更全的
`stock_zh_a_spot_em` 和另一条 K 线实现路径（`stock_zh_a_hist`）。

### 第一步实现范围（最小可用）

只实现覆盖 90% 场景的三个方法，其余返回空让 fallback 链接管：

| 方法 | akshare 函数 | 备注 |
|---|---|---|
| `list_market_quotes` / `get_quote` / `get_quotes` | `stock_zh_a_spot_em` | 全市场一次拉取再过滤 |
| `get_bars`（日/周/月） | `stock_zh_a_hist(symbol, period, start_date, end_date, adjust)` | 复权直接传 qfq/hfq/"" |
| `get_bars`（分钟） | `stock_zh_a_hist_min_em(...)` | 只能返回近期数据 |
| `health_check` | `stock_zh_a_spot_em` 拉一行 | |

**第一步不实现**（返回空，留给 efinance/腾讯）：`get_order_book` / `get_ticks` /
`get_belonging_boards`。

### 第二步实现范围（资金流）

| 方法 | akshare 函数 | 备注 |
|---|---|---|
| `get_today_money_flow` | `stock_individual_fund_flow(stock, market)` 取首行 | 盘后更新 |
| `get_history_money_flow` | 同上（接口给 ~100 天） | 客户端按 `days` 截断 |

字段映射（来自 akshare 源码 `stock_fund_em.py:52-68`，非文档）：
`主力净流入-净额` / `主力净流入-净占比` / `超大单净流入-净额` /
`大单净流入-净额` / `中单净流入-净额` / `小单净流入-净额`。
接口的 `market` 参数（sh/sz/bj）由代码头推断。

**板块反查仍返回空**：akshare 没有"单股 → 所属板块"的直接接口，反查要遍历所有
板块成分股（~200 次 HTTP），太重。efinance.get_belong_board 是单股直查（1 次 HTTP），
已在 fallback 链里兜底，akshare 在这里没有增量价值。

### 工厂模式：`build_default_adapter()`

新增 `market_data/builder.py`，业务层不再直接写
`FallbackAdapter([EfinanceAdapter(), TencentAdapter()])`，统一调
`build_default_adapter(with_cache=True, cache_store=...)`。

未来调整顺序、加源、改链都只动这一个文件。已迁移 9 个生产调用点 + 1 个脚本
（CLI / monitor / agent / MCP / TUI / web / flows / cron_verify）。

### akshare 作为可选依赖

akshare 体积大（~100MB，拉 mini-racer / lxml / decoractor 等），不放进主依赖。
放在 `[project.optional-dependencies].dev` 里。`builder._akshare_available()` 在运行时
探测，没装就跳过——普通用户 `uv sync` 不会被强加这个重量。

## Consequences

- **正向**：实时报价字段补全（PE/PB/市值不再常缺）；K 线多一条实现路径；
  业务层装配点统一，未来加源成本降低。
- **负向**：开发依赖体积增加 ~100MB（只在 dev extra）；
  akshare 版本飘移时 `stock_zh_a_hist` 可能 KeyError（已在每个方法 try/except 兜住）；
  akshare 列名是中文（与 efinance 同约定，版本变了立刻 KeyError 暴露反而稳）。
- **不做的事**：不在 Protocol 上塞财务报表接口（`stock_financial_*`）。
  Protocol 是为行情设计的；财务数据应像 semicon 模块做成独立参考库服务。
  这也是被拒 Tushare patch 的设计问题之一。
