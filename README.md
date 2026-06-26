# 妈妈炒股 (mommy-chaogu)

给妈妈用的行情监控和投资陪伴工具。

## 目标

- **行情监控** (M0)：实时报价、K线、资金流、板块联动 — 数据源：efinance（东方财富）
- **投资陪伴** (M1)：信号提醒、复盘报告、风险提示
- **决策辅助** (M2)：组合跟踪、买点信号、止盈止损

## 架构原则

- **接口先行**：所有数据源（efinance / AKShare / Tushare / 自爬）走统一 `MarketDataAdapter` Protocol
- **dataclass 化**：行情数据用 `@dataclass(frozen=True)` 定义，业务层与具体数据源解耦
- **降级优先**：第三方接口挂了要能优雅 fallback，不让监控断流

## 项目结构

```
src/mommy_chaogu/
├── market_data/
│   ├── types.py          # 通用 dataclass: Quote, Bar, Tick, MoneyFlow, Board
│   ├── adapter.py        # MarketDataAdapter Protocol（接口契约）
│   ├── efinance_adapter.py  # EfinanceAdapter 实现
│   └── __init__.py
tests/
└── test_market_data/
    ├── test_types.py
    └── test_efinance_adapter.py
scripts/
└── smoke_market_data.py  # 端到端冒烟脚本
```

## 开发

```bash
uv sync --extra dev      # 安装依赖
uv run python scripts/smoke_market_data.py   # 冒烟
uv run pytest             # 跑测试
uv run ruff check .       # lint
uv run mypy src           # type check
```

## 当前进度

- ✅ **M0.1** — 通用行情 dataclass + MarketDataAdapter Protocol
- ✅ **M0.2** — EfinanceAdapter 实现（实时报价/K线/资金流/板块）
- ✅ **M0.3** — 冒烟脚本通过统一接口拉数据
- ⏳ **M0.4** — 单测（mock adapter + 字段校验）
- ⏳ **M1.x** — 行情监控业务逻辑（待定）
