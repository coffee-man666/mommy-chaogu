# 技术债台账（Tech Debt）

> 发布 v1.0.0 前的如实记录：质量门的真实覆盖范围与已知遗留项。
> 每项包含现状、原因与收敛方向。本文件随质量门变化同步更新。

## mypy 豁免清单

`pyproject.toml` 中对以下模块设置了 `ignore_errors = true`。
核心数据链路（market_data 主体、watchlist、signals、flows、earnings、
portfolio、workflow、services、记忆系统核心）保持 `mypy --strict` 零错误
（144 个源文件通过，v1.0.0 实测）。

| 豁免模块 | 原因 | 收敛方向 |
|---|---|---|
| `mommy_chaogu.cache.*` | JSON 反序列化类型推导弱，整体放宽 | 为反序列化引入 TypedDict / 泛型后逐文件收紧 |
| `mommy_chaogu.market_data.tencent_adapter`、`fallback_adapter` | 以大量 `# type: ignore[override]` 实现 Protocol | 对齐 Protocol 签名，逐个移除 ignore |
| `mommy_chaogu.web.*` | FastAPI 依赖注入 + Pydantic 动态边界 | 按路由模块逐个收紧 |
| `mommy_chaogu.backtest.*` | 数值/统计计算类型标注不足 | 补齐 Decimal 与返回值标注 |
| `mommy_chaogu.agent.{service, mcp_server, extractor, consolidator, monitor, narrative, vector_search}` | OpenAI / MCP 动态响应对象 | 在边界定义窄类型（TypedDict）后向内推进 |
| `mommy_chaogu.cli`、`cli_commands.*` | argparse Namespace 与动态注册回调 | 回调签名显式化或集中 cast |

> 豁免清单以 `pyproject.toml` 为唯一真相源，本表是其说明文档。

**已收敛**：`agent.tools`（v1.0.0 后）——拆分为 `agent/tools/` 包
（base / registry + 9 个域模块），并在 `holdings.py` 边界以
`_PortfolioSummary` TypedDict 窄化 `PortfolioStore.summary()` 契约，
全包通过 `mypy --strict`，豁免已移除。

## 测试告警

- **258 个 DeprecationWarning**（v1.0.0 实测）：`sqlite3` 默认 datetime /
  timestamp adapter 自 Python 3.12 起弃用，集中在 `earnings/store.py`、
  `watchlist` 等 SQLAlchemy 用法。
  方向：注册自定义 adapter，或统一改为 TEXT 存储 ISO8601 字符串。

## 待决策项

- **`frontend/`（Taro 小程序目录）**：已废弃，`.gitignore` 注释注明“保留作
  mini program 参考”。发布稳定版后建议移除或归档到独立分支/仓库。
- **`data/` 本地实验数据库**（`bt_*.db`、`*_memory.db` 等）：未入版本控制，
  属本地回测产物，可由使用者随时删除，不影响代码与测试。
