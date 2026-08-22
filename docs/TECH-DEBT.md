# 技术债台账（Tech Debt）

> 质量门的真实覆盖范围与已知遗留项的如实记录。
> 每项包含现状、原因与收敛方向。本文件随质量门变化同步更新。
>
> **2026-08-22 大清理**：mypy 豁免全部清零、sqlite3 datetime 弃用告警修复、
> 数据源静默吞异常补日志、cli/TUI 两个巨型热点拆分、仓库卫生处理。

## mypy 豁免清单

**已全部清零（2026-08-22）**。`mypy --strict` 覆盖全部 211 个源文件，
`pyproject.toml` 中不再有任何 `ignore_errors` 项目级豁免。

历史豁免及收敛方式（供回溯）：

| 原豁免模块 | 收敛方式 |
|---|---|
| `mommy_chaogu.cache.*` | `QuoteCacheEntry.quote` 改真实 `Quote` 类型；serializer 补 `-> Quote`；`session()` 返回 `Iterator[Session]`；裸 `dict` 补参数化 |
| `mommy_chaogu.market_data.tencent/fallback/massive_adapter` | Protocol 签名对齐（返回类型补全 + `cast` 边界宽化）；massive 去重逻辑改 `dict.fromkeys` |
| `mommy_chaogu.web.*` | deps 单例标注真实类型；路由函数补返回类型；修复 market.py 变量复用与 earnings.py 字段映射两处真 bug |
| `mommy_chaogu.backtest.*` | 裸 `dict` 参数化；`math.sqrt` 替代 `**0.5`；`counts.get` 改 lambda key |
| `mommy_chaogu.agent.{service, mcp_server, extractor, consolidator, monitor, narrative, vector_search}` | OpenAI 响应边界窄化（`float(...)`/`list(...)`）；MCP content 类型显式宽化 cast；`_retry_base_delay` 出口 `float()` |
| `mommy_chaogu.cli`、`cli_commands.*` | REPL 拆出 `cli_repl.py`（strict）；工厂函数 `-> object` 全部改真实类型（CacheManager/ToolContext/FlowService/SemiconStore 等）；`_build_llm_client` 返回 `OpenAI | None` |

保留的第三方 `ignore_missing_imports`（efinance/pandas/sqlalchemy/sqlite_vec/
tiktoken/qrcode 等）是缺 stub 的库的正常处理方式，不算项目豁免。

## 测试告警

- **sqlite3 datetime adapter 弃用（已修复，2026-08-22）**：原先 ~280 个
  DeprecationWarning。在 `db_paths.py` 注册与旧默认实现逐字节兼容的
  adapter/converter（`register_sqlite3_adapters()`），`db.py` 与
  `earnings/store.py` 引用；旧库数据零迁移。核心模块测试在
  `-W error::DeprecationWarning` 下通过。
- 残留少量第三方 DeprecationWarning（httpx `content=` 用法等），非阻塞。

## 结构重构记录

- **`cli.py`（807 → 518 行）**：`_run_mommy_repl` 从 ~330 行减到 ~150 行编排
  循环；渲染/斜杠命令/agent Live 流式视图/工作流打印拆到 `cli_repl.py`
  （384 行，strict 类型；`_run_mommy_repl`/`_render_logo` 保留 cli 命名空间
  re-export 供既有测试导入）。
- **`tui/views/chat.py`（946 → 811 行）**：12 个斜杠命令卡片 builder 拆到
  `tui/views/slash_cards.py`（`SlashCardFactory`，196 行）；ChatView 保留
  线程调度与挂载职责。

## 仓库卫生（2026-08-22 处理完毕）

- ~~`frontend/`（Taro 小程序目录）~~：**已删除**（用户决策：无保留价值）。
- ~~`data/` 本地实验数据库~~：10 个 `bt_*` / `llm_backtest` / `eval-*` 实验
  db 已迁至 `data/archive/`（gitignore），`data/` 顶层只留 4 个生产库。
- `.gitignore`：整个 `output/` 忽略（原先只忽略两个子目录）；
  `node_modules/` 改全局规则。

## 当前已知遗留

- **bundled_skills 双份 80% 重复**（basket-analysis 与 food-security-analysis
  的 `html_render.py`/`analyze.py`）：用户决策维持"独立版本化 Skill payload"
  设计，不做共享库提取。两边修改需手动同步。
- `earnings/adapter.py` Mock 数据源 `fetched_at` 已改 aware UTC；若未来有
  第三方直接注入 naive datetime 的 EarningsActual，store 层 isoformat 往返
  不受影响，但直接比较需注意 naive/aware 混用。
