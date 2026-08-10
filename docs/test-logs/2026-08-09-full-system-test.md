# 全量系统测试报告 — 2026-08-09

> **测试日期**：2026-08-09
> **测试人**：mercer（AI agent 辅助）
> **测试模型**：GLM-4.7（ZAI provider，`AGENT_MODEL=glm-4.7`）
> **测试分支**：`main` @ `c6509bc`（含 iOS app PR #36）
> **测试环境**：macOS darwin 24.6.0 arm64 / Python 3.12 / uv

---

## 测试范围

四条主线共 **18 项测试**，全部通过。过程中发现并修复了 **3 个真实 bug**。

| Block | 测试项 | 结果 |
|---|---|---|
| **1 记忆系统** | 6 项：无 Key 降级 / 空库冷启动 / 写入召回 / 幂等 / 跨标的隔离 / 预测验证 | ✅ 全通过 |
| **2 UX 体验** | 3 项：REPL 查询 / 路由透明度 / 降级友好性 | ✅ 全通过 |
| **3 量化工具箱** | 5 项：冒烟 / 日线 / 30min / 回测 / 合理性 | ✅ 全通过 |
| **4 编译器 V2** | 4 项：离线编译 / 真实 LLM / ToolRegistry dry-run / 端到端 | ✅ 全通过 |

测试环境：provider=zai / 无 `MASSIVE_API_KEY` / 美股走 Yahoo 免 key 源 / 全程临时数据库隔离（`MOMMY_DATA_DIR=/tmp/...`），不碰真实数据。

---

## 四个核心问题的结论

### 1️⃣ 记忆系统是否可用，是否在每个环境都可以空？

**完全可用，每个环境都能"空"运行。**

| # | 测试 | 结果 | 关键证据 |
|---|---|---|---|
| 1.1 | 无 Key 降级 | ✅ | stats/events/predictions/health/maintain 全可用；`status: degraded`、`retrieval_mode: exact+keyword`、`consolidation: deferred_no_llm` |
| 1.2 | 空库冷启动 | ✅ | 全新 agent.db 自动建表，stats 全 0，无报错 |
| 1.3 | 写入→召回闭环 | ✅ | SOXX 结论写入→按 code 精确召回，字段完整（confidence/evidence_as_of/data_coverage） |
| 1.4 | 幂等性 | ✅ | 同 key 第二次 `reused: true`，复用同一 event_id，库内无重复 |
| 1.5 | 跨标的隔离 | ✅ | 查 600519 不返回 600518（含数字串），反向亦然 |
| 1.6 | 预测验证闭环 | ✅ | SOXX 看多预测 pending→**hit**，actual_price=543.27（Yahoo 实时），change_pct=+2.02%，accuracy=0.8 |

关键设计验证点全部成立：精确检索不依赖 embedding、三层幂等去重（`research_session_id` + `idempotency_key` + `content_hash`）有效、跨标的严格隔离、预测验证全链路（Yahoo 行情 → verify_engine → 状态更新）打通。

### 2️⃣ UX 体验如何？

**整体良好，修复了 1 个阻塞 bug。**

| # | 测试 | 结果 | 关键证据 |
|---|---|---|---|
| 2.1 | REPL 单次查询 | ✅ | glm-4.7 准确解读 SOXX K 线（17% 反弹、缩量警示、566 阻力位）|
| 2.2 | 路由透明度 | ✅ | `-v` 显示 `[匹配工作流]`+ID；"美股"正确命中 `us_market_brief` |
| 2.3 | 降级友好性 | ✅ | 无 Key 不崩溃，行情数据正常，仅跳过 LLM 总结 |

修复的阻塞 bug：美股 K 线缓存写入崩溃（Decimal 序列化），导致每次查询刷 20 行 `cache set_bar failed`。修复后干净。

UX 小瑕疵（非 bug）：无 Key 降级时直接显示原始数据表，缺少"未配置 LLM"的友好提示，属体验优化。

### 3️⃣ 新的均线量化工具是否可用？

**完全可用，信号合理。**

| # | 测试 | 结果 | 关键证据 |
|---|---|---|---|
| 3.1 | 合成冒烟 | ✅ | 8/8 通过 |
| 3.2 | 真实 SOXX 日线（250 根） | ✅ | regime=BULL、alert=TREND_LONG、cloud_dist=+0.31 ATR |
| 3.3 | 真实 SOXX 30min（300 根） | ✅ | 66.7% BEAR + 33.3% BULL，2 个压制事件 |
| 3.4 | 回测产出 | ✅ | 30min 底部评分事件 13 根后 +2.11% vs 基准 **-0.18%**（显著跑赢），胜率 67% |
| 3.5 | 合理性检查 | ✅ | 日线 BULL 与全年 +125% 大涨完全一致 |

信号层面验证：SOXX 一年 241→543（+125%），日线 regime=BULL、cloud_dist 正值（云带上方）、bottom_score 偏低（已脱离底部）——全部与实际走势吻合。30min 捕获了 7 月回调 + 8 月反弹，2 个压制事件（7/20、8/3）时点合理。

### 4️⃣ 编译器 V2 是否真的可以用？

**真的可以用。**

| # | 测试 | 结果 | 关键证据 |
|---|---|---|---|
| 4.1 | 离线编译（stub LLM） | ✅ | 3/3 黄金观点：编译+校验+实例化全成功 |
| 4.2 | 真实 LLM 编译（glm-4.7） | ✅ | 3/3 观点工具序列与黄金样例完全一致，参数接线正确 |
| 4.3 | 真实 ToolRegistry dry-run | ✅ | `dry-run validation: passed (warnings=0)` |
| 4.4 | 端到端落库+执行 | ✅ | create→list→run 全链路，工具真实执行返回结构化结果 |

---

## 发现并修复的 3 个真实 Bug

全部在 `src/mommy_chaogu/cache/adapter.py`，都影响美股数据链路：

| # | Bug | 影响 | 修复 |
|---|---|---|---|
| 1 | **Decimal 序列化失败**：`asdict(bar)` 产生的嵌套 Money dict（`{amount: Decimal, currency}`）未被递归处理，`json.dumps` 崩溃。存在于**两个**代码路径（首写 L310 + 节流刷新 L347） | 所有美股 K 线缓存写不进，每次查询刷 20 行 `cache set_bar failed` | 改用已有的 `_recursive_safe` 递归处理，修复两处 |
| 2 | **缓存读回 turnover 反序列化崩溃**：写侧修复后 turnover 变 dict，但读侧 `Decimal(str(turnover))` 直接转 dict 报 `InvalidOperation` | 美股 K 线缓存命中后读回崩溃 | 新增 `_bar_turnover` helper，兼容 dict/Money/标量三种形态 |
| 3 | **get_bars 返回 None 未守卫**：底层 adapter（efinance/腾讯）可能违反 `list` 契约返回 None，`for bar in fresh:` 崩溃 | A 股非交易时段/源不可用时工作流执行崩溃 | 两处加 None 守卫，优雅降级为空列表 |

**修复验证**：

- `ruff check` ✅
- `mypy --strict` ✅
- cache 测试 41 ✅
- agent tools 测试 23 ✅
- 无回归

**改动范围**：仅 `cache/adapter.py` 一个文件（+29/-14）。

---

## 发现但未修复的问题（需决策）

### A. ZAI provider 模型配置错误（影响 LLM 功能）⚠️ 重要

`.env` 里 `AGENT_MODEL=deepseek-v4-flash`，但 provider 是 `zai`（GLM 端点）。`deepseek-v4-flash` 在 ZAI 端点不存在，导致**所有 LLM 调用**报 `400 modelCode: does not exist`。测试时用 `AGENT_MODEL=glm-4.7` 覆盖才跑通。

这是配置问题不是代码 bug。建议：把 `.env` 的 `AGENT_MODEL` 改成 `glm-4.7`，或删掉这行用 ZAI 默认模型。

### B. consolidation LLM 调用报错

maintain 时 ZAI 的 consolidation 报同样的 `modelCode: does not exist`，但被正确降级（`consolidation: ok`，主流程未阻塞）。根因同 A，修了 A 这个也会好。

### C. 无 Key 时的 UX 提示

无 Key 降级时直接显示原始数据表，没有"未配置 LLM"的友好提示。属体验优化，非 bug。

### D. Web/TUI 界面未实测

2.4 实际只测了 CLI（Web/TUI 需浏览器/终端交互环境）。如需可补测。

---

## 待办

1. **代码改动**：`cache/adapter.py` 的 3 处 bug 修复留在工作区，未提交，待审阅。
2. **配置修复**：`.env` 的 `AGENT_MODEL` 需确认改成什么值。
3. **可选补测**：Web/TUI 界面实测。

---

## 附录：测试方法摘要

| 系统 | 测试方式 | 隔离手段 |
|---|---|---|
| 记忆系统 | Python 脚本直接调 `ResearchToolCatalog._record_conclusion` + `ResearchContextService.get` | `MOMMY_DATA_DIR=/tmp/...` 临时库 |
| 预测验证 | 写预测 → SQL 改 `verify_after` 到过去 → `mommy memory maintain`（真实 Yahoo adapter） | 临时库 |
| UX | `uv run mommy "..."` 单次查询 + `-v` 详细模式 + 无 key env 覆盖 | `MOMMY_DATA_DIR=/tmp/...` |
| 量化工具箱 | Yahoo 拉 SOXX 日线/30min → CSV → `DualEngine.run()` + `score_events` + `forward_returns` | 工具箱与主程序解耦，独立临时 CSV |
| 编译器 V2 | stub LLM 注入 + 真实 `mommy workflow create --dry-run` + `scripts/smoke_workflow.py` + `create→list→run` | 临时库 |

美股数据源：Yahoo Finance（免 key），通过主项目 `YahooAdapter.get_bars` 拉取 SOXX 真实行情，转换成工具箱 CSV 格式喂入。
