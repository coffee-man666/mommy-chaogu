# 更新日志 (Changelog)

> mommy-chaogu 的所有重要变更记录。
> 格式基于 [Keep a Changelog](https://keepachangelog.com/)。

---

## [未发布] - 2026-07-02

### 新增 ⭐

- **earnings 模块（业绩前瞻 + actual 比对）** — `src/mommy_chaogu/earnings/`
  - `types.py` — 4 dataclass + 2 StrEnum（EarningsActual / Calendar / Score / Verdict）
  - `schema.py` — 3 表 + 9 索引 + v_recent_disclosures 视图
  - `store.py` — EarningsStore（Decimal TEXT 精度安全）
  - `adapter.py` — EarningsAdapter Protocol + MockEarningsAdapter
  - `efinance_adapter.py` — EfinanceEarningsAdapter（真实东财数据）
  - `service.py` — EarningsService（pull / score / watch / summary）
  - `signals.py` — 4 条规则（beat / meet / miss / approaching）
  - `cli.py` — `mommy-earnings` 命令行
- **业绩前瞻数据资产** — `data/earnings_preview.db`（41 家公司中信证券 H1 2026）
- **实战手册** — `docs/EARNINGS-HANDBOOK.md`（12 章节 / 407 行）
- **主题分组** — 13 个 watchlist 主题组（半导体 6 子类 / AI算力 / PCB / 面板 / LED / 传感器 / 机器人 / 消费电子）
- **mommy-earnings CLI** — 4 子命令（pull / score / watch / summary）
- **EfinanceEarningsAdapter** — 真实东财业绩拉取（实测 H1 2025 数据完整）

### 改进

- **质量门**：ruff ✅ / mypy --strict ✅ / pytest 270 通过（196 原有 + 51 earnings + 23 efinance_adapter）
- **CLI 默认 adapter**：`mommy-earnings` 默认用 EfinanceEarningsAdapter（真实数据），可加 `--adapter mock` 切换
- **README 大改**：10KB / 389 行，含架构图、CLI 速查、财报窗口实战、开发指南

---

## [0.6.x] - 2026-07-01

### 新增

- **supply_chains 数据资产** — 3 个 JSON
  - `humanoid_robot.json` — 25 只人形机器人
  - `semiconductor.json` — 106 只半导体（中游-存储/MCU/处理器/...）
  - `materials.json` — 41 只材料（化工/钢铁/煤炭/...）
- **mommy-hub 联动** — 三个产业链页面（机器人/半导体/材料）
- **cron 修复** — 4 个 jobs（M6.1-M6.2）
- **reports 结构化** — 实战产物目录 `.gitignore` + `README.md`
- **Web UI 完整化（M5.4）** — 后端 web + 前端 Vue + money flow API

### 实战验证

- 妈妈已能用 Web + 资金流 ratio 监控跑通
- 7/1 多次板块扫描稳定（机器人 / 半导体 / 材料 / 光模块 / 证券）

---

## [0.5.x] - 2026-06-29

### 新增

- **半导体产业链参考库** — `src/mommy_chaogu/semicon/`（106 只）
- **资金流 ratio 监控 + 收盘日报** — `flows/signals.py`（4 条 ratio-based 默认规则）
- **FlowMonitor** — 持续轮询 + 状态持久化 + 失败告警
- **FlowReport** — 收盘日报 markdown（板块汇总 + TOP 流入/流出 + 矛盾股）
- **mommy-semicon / mommy-flows / mommy-report CLI**
- **OpenClaw cron 4 jobs 自动化**（M6.1-M6.4）
  - 8:30 盘前预热 / 9:30 盘中监控 / 15:30 收盘日报 / 周六 10:00 周报

---

## [0.4.x] - 2026-06-28

### 新增

- **持仓管理** — `portfolio/` 模块（Position + PositionAdjustment 表 / 6 API 端点 / 加权平均成本）
- **语音录入** — `useSpeechRecognition` composable（webkitSpeechRecognition）
- **资金流图表** — 5 维累计卡片 + 日内分时 SVG + 历史柱状图
- **盘面扫描** — 大盘 6 指数 / 涨幅榜 / 跌幅榜 / 板块榜
- **持仓快览** — 首页持仓条 + 盘面页联动

---

## [0.3.x] - 2026-06-27

### 新增

- **Web UI（M3.0）** — Vite + Vue 3 + FastAPI + WebSocket（妈妈手机可用）
  - 首页（5 自选 + 主力合计 + WebSocket）
  - 详情（klinecharts K线 + MA 均线 + VOL）
  - 信号（触发历史）
  - 设置（服务状态 + 自选股 CRUD）
- **Server酱 微信推送（M3.1）** — 阈值过滤 + JSON 去重

---

## [0.2.x] - 2026-06-26

### 新增

- **数据层**（M0 - M2.5）
  - M0 — 通用行情数据层 + efinance 适配器
  - M1 — 自选池 + 实时监控
  - M1.5 — 7 条内置告警规则 + Alerter
  - M2 — 时间戳驱动缓存 + 装饰器
  - M2.5 — TencentAdapter + FallbackAdapter（凌晨实战）
- **CLI** — `mommy-watchlist` / `mommy-monitor` / `mommy-cache` 4 子应用
- **设计文档** — `docs/DESIGN.md` / `LEDGER.md` / `PROGRESS.md`

---

## [0.1.0] - 2026-06-25

### 新增

- 项目初始化
- 数据契约 + MarketDataAdapter Protocol
- efinance 适配器（11 路数据）
- 端到端冒烟脚本（`scripts/smoke_market_data.py`）
- 24 测试（13 离线 + 11 实时网络）

---

## 版本说明

- **0.1.x** — 数据层（行情 / 自选 / 信号 / 缓存）
- **0.2.x** — 实战验证 + 凌晨 fallback 修复
- **0.3.x** — Web UI + 推送
- **0.4.x** — 持仓 + 语音录入
- **0.5.x** — 资金流 ratio + 自动化
- **0.6.x** — 产业链数据 + hub 联动
- **0.7.x** — 财报窗口 + 实战手册
- **1.0.0** — 待定（等妈妈稳定使用 3 个月）

---

## 贡献者

- **coffee-man666** — 主要开发者 + 项目维护者

---

**License**: [MIT](LICENSE)