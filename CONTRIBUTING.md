# 贡献指南

感谢你有兴趣参与 **mommy-chaogu** 的开发！🎉

## 项目目标

这个项目的核心目标很明确：
- 给妈妈用的 **A 股行情监控 + 投资陪伴** 工具
- 「简单、可靠、有用」优先于「功能多、技术新」
- 每个 PR 都要回答这个问题：**这对妈妈有什么帮助？**

不是每个好点子都适合这个项目。如果不确定，开个 Issue 讨论。

---

## 开发流程

### 1. Fork + Branch

```bash
git clone https://github.com/<your-fork>/mommy-chaogu.git
cd mommy-chaogu
git checkout -b feat/your-feature-name
```

**Branch 命名约定**：
- `feat/xxx` — 新功能
- `fix/xxx` — bug 修复
- `docs/xxx` — 文档
- `refactor/xxx` — 重构（不改行为）
- `test/xxx` — 测试补充

### 2. 写代码

**必读**：[`docs/DESIGN.md`](docs/DESIGN.md) — 架构原则和 ADR

关键设计原则（红线）：
1. **接口先行**：新数据源走 `Adapter Protocol`，不要直接 import 第三方库
2. **dataclass 化**：所有数据用 `@dataclass(frozen=True, slots=True)`
3. **金额用 Decimal**：禁止 float 表示钱
4. **降级优先**：网络/解析失败 → 返回空 list，不抛
5. **测试覆盖**：新功能必须有测试（`tests/`）

### 3. 质量门（必须全过）

```bash
uv run ruff format .             # 格式化
uv run ruff check .              # lint（必须 0 errors）
uv run mypy --strict src         # type check（必须 0 errors）
uv run pytest -m "not network"   # 离线测试（必须 100% 通过）
```

CI 会在 PR 时自动跑这些检查。

### 4. Commit 规范

用 [Conventional Commits](https://www.conventionalcommits.org/) 格式：

```
feat(market_data): 添加东方财富公告日历接口
fix(earnings): 修复 Decimal 精度丢失
docs(readme): 更新 CLI 速查
refactor(cache): 抽离 TTL 装饰器
test(earnings): 添加 EfinanceEarningsAdapter 测试
```

格式：`<type>(<scope>): <subject>`，subject 中文/英文都行但保持简洁。

### 5. Push + PR

```bash
git push origin feat/your-feature-name
gh pr create --fill
```

**PR 必须包含**：
- 改动描述（改了什么 + 为什么）
- 测试说明（怎么验证的）
- 关联的 Issue（如果有）

---

## 代码风格

### Python

- **3.12+** 语法（match / walrus / type alias）
- 不用 `any`（除非有注释说明原因）
- 类型注解严格（mypy strict mode）
- Docstring 用 Google 风格

### 项目惯例

- 模块顶层导出用 `__all__`
- Protocol 加 `@runtime_checkable` 装饰器
- 测试文件命名 `test_xxx.py`
- 用 `from __future__ import annotations`
- 所有 public 函数都有 docstring

### 数据层

```python
# ✅ 好的做法
@dataclass(frozen=True, slots=True)
class Quote:
    code: str
    price: Decimal
    ...

# ❌ 不好的做法
class Quote:
    def __init__(self, code: str, price: float):
        self.code = code
        self.price = price
```

### Adapter 模式

```python
# ✅ 所有数据源走 Protocol
@runtime_checkable
class EarningsAdapter(Protocol):
    def fetch_actual(self, code: str, period: str) -> list[EarningsActual]: ...

# ❌ 直接 import 第三方库
import efinance as ef
df = ef.stock.get_history_bill(code)
```

---

## 测试指南

### 测试分类

| 类型 | 标记 | 网络 | 何时跑 |
|---|---|---|---|
| 离线单元测试 | 无 | ❌ | CI 必跑 |
| 网络集成测试 | `@pytest.mark.network` | ✅ | 仅手动 / nightly |

### 写测试的 5 条原则

1. **测行为不测实现** — 改内部实现不应该破坏测试
2. **边界情况必测** — 空 list / None / 极大极小数
3. **Mock 外部依赖** — 不要真实拉取数据
4. **测试名要可读** — `test_score_returns_super_beat_when_actual_above_high`
5. **每个测试独立** — 不依赖其他测试的执行顺序

### Mock 模板

```python
from unittest.mock import patch

@patch.object(MyAdapter, "_fetch_external")
def test_my_function(mock_fetch):
    mock_fetch.return_value = make_fake_data()
    result = my_function()
    assert result == expected
```

---

## 数据资产贡献

项目里有些 **data/ 目录下的 SQLite 文件**和 **supply_chains/*.json** 数据资产是手工维护的：

- `data/earnings_preview.db` — 券商业绩前瞻（跨券商可叠加）
- `data/supply_chains/semiconductor.json` — 半导体产业链（106 只）
- `data/supply_chains/humanoid_robot.json` — 人形机器人（25 只）
- `data/supply_chains/materials.json` — 材料（41 只）

**新增板块？**：
1. 创建 `data/supply_chains/<your_sector>.json`
2. 在 `scripts/load_supply_chains.py` 里加 loader
3. 在 hub API 加端点

**新增券商预测？**：
```bash
# 复制一份 loader
cp scripts/load_earnings_preview.py scripts/load_earnings_preview_<broker>.py
# 改 DATA 和 REPORT_SOURCE
uv run python scripts/load_earnings_preview_<broker>.py --summary
```

UNIQUE(code, period, source) 约束保证跨券商不重复。

---

## Issue 指南

### Bug Report

请用 `.github/ISSUE_TEMPLATE/bug_report.md` 模板，包含：
- 复现步骤
- 期望行为 vs 实际行为
- 环境信息（Python 版本 / OS / 妈妈用什么终端）
- 截图 / 日志

### Feature Request

请用 `.github/ISSUE_TEMPLATE/feature_request.md` 模板，包含：
- 用户故事（妈妈为什么要这个？）
- 建议的实现方案
- 替代方案（如果存在）

---

## 提交信息

提交 PR 时请确认：

- [ ] 跑过 `ruff format .` 和 `ruff check .`（无 errors）
- [ ] 跑过 `mypy --strict src`（无 errors）
- [ ] 跑过 `pytest -m "not network"`（100% 通过）
- [ ] 新功能有对应测试
- [ ] commit message 符合 Conventional Commits
- [ ] PR 描述清楚「改了什么 + 为什么 + 怎么验证」

---

## 社区准则

- 友善、尊重、包容
- 假设对方是善意的
- 给反馈时对事不对人
- 不接受任何形式的歧视、骚扰

---

## 联系方式

- **GitHub Issues**: 主要沟通渠道
- **Discussions**: 想法 / 提问 / 经验分享

---

## License

贡献的代码默认采用 [MIT License](LICENSE)。

---

**最后一句**：每个 PR 都应该问自己一个问题 ——「这个改动会让妈妈用得更开心吗？」如果是，就提交。如果不是，再想想。