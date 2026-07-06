# 项目质量评估报告 — eval-quality

**日期**: 2026-07-06
**项目**: mommy-chaogu (A 股投资分析 CLI/Web)
**环境**: macOS / Python 3.12 (venv 实际 3.13) / uv

---

## 1. 测试通过率

### 执行命令

```bash
uv run pytest -m "not network" --tb=short 2>&1
```

### 关键结果

| 指标 | 数值 |
|---|---|
| 总测试数（含 network） | 755 |
| 非 network 测试 | 742 |
| network 测试（deselected） | 13 |
| **通过** | **738** |
| **失败** | **4** |
| 通过率 | **99.46%** (738/742) |
| 耗时 | 3.16s |

### 失败的 4 个测试（均在 `tests/test_config.py`）

```
FAILED tests/test_config.py::test_load_config_defaults_when_no_file
FAILED tests/test_config.py::test_load_config_reads_toml
FAILED tests/test_config.py::test_env_overrides[DEEPSEEK_API_KEY-env_secret-agent.api_key-env_secret]
FAILED tests/test_config.py::test_create_default_config
```

### 根因分析

`load_config()` 在入口处调用 `dotenv.load_dotenv()`，会读取项目根目录的 `.env` 文件。本地 `.env` 中配置了 `AGENT_PROVIDER=zai`，这会覆盖 `AgentConfig` 的默认值 `deepseek`。

```
# config.py:108
env_provider = os.environ.get("AGENT_PROVIDER")
if env_provider:
    cfg.agent.provider = env_provider    # → provider = "zai"
```

失败信息：
```
>   assert cfg.agent.provider == "deepseek"
E   AssertionError: assert 'zai' == 'deepseek'
```

**结论**：这 4 个测试在 CI 中会通过（CI 环境无 `.env` 文件），但在本地 `.env` 存在时必然失败。属于**测试隔离缺陷**——测试没有通过 `monkeypatch` 或 `tmp_path` 隔离 `.env` 加载，导致本地环境状态泄漏到测试中。

---

## 2. 测试分布

### 执行命令

```bash
uv run pytest -m "not network" --collect-only -q 2>&1
```

### 按模块分布（测试文件 → 测试数）

| 测试目录/文件 | 测试数 |
|---|---|
| `tests/test_agent/` (20 文件) | ~320 |
| `tests/test_backtest*.py` (7 文件) | ~100 |
| `tests/earnings/` (6 文件) | ~74 |
| `tests/test_market_data/` (4 文件) | ~63 |
| `tests/test_web/` (7 文件) | ~63 |
| `tests/test_signals/` (2 文件) | ~41 |
| `tests/test_watchlist/` (2 文件) | ~36 |
| `tests/test_push/` (3 文件) | ~29 |
| `tests/test_cache/` (1 文件) | ~26 |
| `tests/test_backtest_stats.py` | 23 |
| `tests/test_config.py` | 8 |
| `tests/test_monitor/` | 10 |
| `test_agent` 中最大单文件 | test_token_tracker 36 / test_semantic 38 |

### network 测试（13 个，不参与 CI）

| 文件 | 测试数 | 说明 |
|---|---|---|
| `tests/test_market_data/test_efinance_adapter.py` | 11 | 东财实时接口 |
| `tests/earnings/test_efinance_adapter.py` | 2 | 业绩数据拉取 |

---

## 3. Lint 检查

### 执行命令

```bash
uv run ruff check . 2>&1
uv run ruff format --check . 2>&1
```

### 结果

| 检查项 | 结果 |
|---|---|
| `ruff check .` | ✅ **All checks passed!** |
| `ruff format --check .` | ✅ **179 files already formatted** |

**结论**：代码风格 100% 合规，无 lint 错误。

### ruff 配置（pyproject.toml）

```toml
[tool.ruff]
line-length = 100
target-version = "py312"

[tool.ruff.lint]
select = ["E", "F", "I", "N", "W", "UP", "B", "SIM", "RUF"]
# 忽略: E501 (行太长), RUF001/002/003 (中文全角字符歧义)
ignore = ["E501", "RUF001", "RUF002", "RUF003"]
```

规则集合理（pyflakes + pycodestyle + isort + pep8-naming + pyupgrade + bugbear + simplify + ruff-specific）。忽略项针对中文项目做了适当调整。

---

## 4. 类型检查

### 执行命令

```bash
uv run mypy --strict src 2>&1 | tail -5
```

### 结果

```
Success: no issues found in 104 source files
```

✅ **104 个源文件全部通过 `--strict` 模式类型检查。**

### 注意事项

pyproject.toml 中有多个 `ignore_errors = true` 的 override：

| 模块 | 原因 |
|---|---|
| `mommy_chaogu.cache.*` | JSON 反序列化类型推导弱 |
| `mommy_chaogu.market_data.tencent_adapter` / `fallback_adapter` | Protocol override 大量 type:ignore |
| `mommy_chaogu.web.*` | FastAPI 依赖注入 + Pydantic |
| `mommy_chaogu.agent.*` | LLM 交互动态性强 |
| `mommy_chaogu.backtest.*` | 回测引擎 |
| `mommy_chaogu.cli` | argparse 入口 |

**结论**：核心模块（config, db_paths, earnings, flows, monitor, portfolio, push, report_render, semicon, signals, watchlist）在 strict 下检查通过。约 40% 的源文件（cache/web/agent/backtest/cli/market_data adapters）通过 override 放宽了检查——这些是动态类型密集的模块，放宽合理但留有技术债务。

---

## 5. 端到端 / 集成测试分析

### 执行命令

```bash
# 搜索 tests/ 目录
grep -ri "e2e\|integration\|end_to_end\|end-to-end" tests/
```

### 结果

**仅有 1 个名义端到端测试**：

- `tests/test_backtest_regime.py:197::test_end_to_end_pipeline` — 模拟 bull + bear 两段行情，完整走一遍 regime 分析管道（构造数据 → analyze_by_regime → format_regime_report → 断言结果）。

这是一个**模块级端到端**（backtest regime 模块内部），而非**系统级端到端**（如 CLI 输入 → 数据拉取 → 信号计算 → 推送输出）。

### 缺失的系统级集成测试

无以下场景的集成测试：
- CLI 命令端到端执行（如 `mommy-watchlist add` → `mommy-monitor snapshot`）
- 数据源适配器 → 缓存 → 信号 → 推送完整链路
- Web API 端到端（虽然有 FastAPI TestClient 单元测试，但未覆盖多路由组合流程）
- 数据库迁移脚本验证

---

## 6. 模块测试覆盖分析

### 已覆盖模块（16/18）

| 模块 | 代码行 | 测试文件数 | 覆盖质量 |
|---|---|---|---|
| `agent/` | 大 | 20 | ⭐ 优秀 |
| `backtest/` | 大 | 7 | ⭐ 优秀 |
| `earnings/` | 中 | 6 | ⭐ 优秀 |
| `market_data/` | 中 | 4 | ✅ 良好 |
| `web/` | 中 | 7 | ✅ 良好 |
| `signals/` | 中 | 2 | ✅ 良好 |
| `watchlist/` | 中 | 2 | ✅ 良好 |
| `push/` | 小 | 3 | ✅ 良好 |
| `cache/` | 中 | 1 | ✅ 一般 |
| `monitor/` | 小 | 1 | ✅ 一般 |
| `config.py` | 小 | 1 | ⚠️ 存在隔离缺陷 |

### 未覆盖模块（6 个，共约 4,627 行代码无测试）

| 模块 | 代码行 | 风险 |
|---|---|---|
| `cli.py` | **1,492** | 🔴 高 — argparse 入口，12 个子命令无单测 |
| `flows/` | **1,338** | 🔴 高 — 资金流信号 + 监控 + 收盘日报 |
| `portfolio/` | **668** | 🟡 中 — 持仓 + 组合分析 |
| `semicon/` | **621** | 🟡 中 — 半导体产业链参考库 |
| `report_render/` | **508** | 🟡 中 — 报告渲染（HTML/Markdown） |
| `db_paths.py` | 小 | 🟢 低 — 纯路径常量 |

> 注：CI 的 `build` job 通过 `--help` 验证了 CLI 命令可执行，但这只验证了 argparse 注册不崩溃，不验证业务逻辑。

---

## 7. CI Pipeline 评估

### 文件: `.github/workflows/ci.yml`

### Pipeline 结构

```
push/PR → quality job → build job (needs: quality)
```

### Quality Job 步骤

| 步骤 | 评价 |
|---|---|
| Install uv + cache | ✅ 合理 |
| Python 3.12 only (matrix) | ⚠️ 仅单一版本 |
| `uv sync --extra dev` | ✅ |
| `ruff format --check .` | ✅ |
| `ruff check .` | ✅ |
| `mypy --strict src` | ✅ |
| `pytest -m "not network" -v --tb=short` | ✅ 正确过滤了 network |
| Step summary 输出 | ✅ |

### Build Job 步骤

验证 9 个 CLI 入口的 `--help`：mommy-watchlist / monitor / cache / earnings / flows / semicon / report / agent / mcp。

✅ 合理的冒烟测试，确保入口点可执行。

### CI 缺失项

| 缺失 | 严重度 | 建议 |
|---|---|---|
| **无覆盖率报告** | 🔴 高 | 已有 `pytest-cov` 依赖但 CI 未使用 |
| **无多版本 Python matrix** | 🟡 中 | 仅 3.12，但项目 `requires-python >= 3.12` |
| **无安全扫描** | 🟡 中 | 无 `pip-audit` / `safety` / Dependabot |
| **无依赖锁定验证** | 🟢 低 | uv.lock 已存在 |
| **无缓存 key 校验** | 🟢 低 | uv cache 已启用 |

---

## 8. Pytest Markers 配置

### pyproject.toml `[tool.pytest.ini_options]`

```toml
[tool.pytest.ini_options]
testpaths = ["tests"]
addopts = "-ra -q"
markers = [
    "network: requires live efinance API access (东财接口)",
]
```

### 评价

- ✅ 只定义了 `network` marker，用于隔离需要联网的测试
- ✅ CI 正确使用 `-m "not network"` 过滤
- ⚠️ 可考虑增加的 marker：
  - `slow` — 标记耗时较长的测试（如 token_tracker 36 个测试）
  - `integration` — 标记集成测试（目前没有但将来应加）
- ✅ `addopts = "-ra -q"` 合理（显示所有非通过结果摘要，安静模式）

---

## 9. 测试质量综合评估

### 测试隔离性

| 手段 | 使用情况 |
|---|---|
| `tmp_path` | 199 处，29 个文件 — ✅ 数据库测试隔离良好 |
| `monkeypatch` | 27 处，4 个文件 — ⚠️ 偏少 |
| Mock/Fake/Stub | 797 处，32 个文件 — ✅ 广泛使用 |

**结论**：数据库测试隔离（tmp_path）做得好；但环境变量隔离（monkeypatch）不足——config.py 的 4 个失败测试就是直接后果。

### 测试真实性

- 数据源适配器使用 Mock/Fake Adapter 测试（`test_cache/test_adapter.py` 63 处 mock）
- Web 测试使用 FastAPI TestClient + mock 依赖注入
- Agent 测试大量 mock LLM 响应（`test_agent/test_monitor.py` 105 处 mock）
- 无真实 LLM API 调用测试（合理，避免成本和不确定性）

### 警告（206 个）

主要是两类 DeprecationWarning：
1. `datetime.utcnow()` 已废弃（earnings/adapter.py）
2. SQLAlchemy datetime adapter 在 Python 3.12+ 废弃

建议修复以保持前向兼容（venv 使用 Python 3.13，这些将在未来版本变为错误）。

---

## 10. 改进建议（优先级排序）

### P0 — 必须修复

1. **修复 config 测试隔离缺陷**
   - 在 `test_config.py` 中使用 `monkeypatch.delenv("AGENT_PROVIDER", raising=False)` 或 mock `load_dotenv`
   - 确保 `load_config` 测试不受本地 `.env` 影响
   - 影响：4 个测试本地稳定通过

2. **为 `flows/` 模块（1,338 行）补充测试**
   - 资金流信号、监控、收盘日报是核心业务逻辑
   - 优先测试 `flows/signals.py`（ratio 信号计算）和 `flows/service.py`

### P1 — 强烈建议

3. **在 CI 中添加覆盖率报告**
   - 已有 `pytest-cov` 依赖，只需在 CI 加：
     ```yaml
     - name: Pytest with coverage
       run: uv run pytest -m "not network" --cov=mommy_chaogu --cov-report=term-missing --cov-report=xml
     ```
   - 可添加最低覆盖率门槛（如 `--cov-fail-under=70`）

4. **为 `cli.py`（1,492 行）补充关键路径测试**
   - 至少覆盖 argparse 参数解析和子命令路由逻辑
   - 可用 `subprocess` 或直接调用 `main_*()` 函数测试

5. **修复 DeprecationWarning（206 个）**
   - `datetime.utcnow()` → `datetime.now(datetime.UTC)`
   - SQLAlchemy datetime adapter → 使用 `type_decorator` 或显式 converter

### P2 — 建议改进

6. **添加系统级集成测试**
   - 至少 1-2 个覆盖 CLI → 数据库 → 信号 → 输出的完整链路
   - 可用 mock 数据源 + tmp_path 数据库

7. **为 `portfolio/` 和 `semicon/` 补充单元测试**
   - 各约 600+ 行代码完全无测试

8. **CI 添加多版本 Python matrix**
   - 至少 3.12 + 3.13（venv 已在用 3.13）

9. **CI 添加安全扫描**
   - `pip-audit` 或 `safety` 扫描依赖漏洞

10. **添加 `slow` / `integration` pytest marker**
    - 为未来扩展做准备

---

## 总结评分

| 维度 | 评分 | 说明 |
|---|---|---|
| 测试覆盖广度 | 7/10 | 742 个测试覆盖核心模块，但 6 个模块零测试 |
| 测试通过率 | 9.5/10 | 99.46%，4 个失败为隔离缺陷非逻辑错误 |
| 测试隔离性 | 8/10 | tmp_path 使用充分，monkeypatch 不足 |
| Lint/格式 | 10/10 | 零违规 |
| 类型安全 | 8/10 | strict 通过，但 40% 模块 override |
| CI 完善度 | 6/10 | 基本流程完整，缺覆盖率/安全扫描/多版本 |
| **综合** | **8/10** | 高质量项目，有明确改进空间 |

该项目在核心交易分析逻辑（agent/backtest/earnings）上测试充分且质量高，lint/type-check 完美通过。主要短板在于外围模块（flows/cli/portfolio/semicon）无测试覆盖，以及 CI 缺少覆盖率报告和安全扫描。
