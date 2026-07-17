# 文档索引

> docs/ 只保留长期有效的用户与开发者文档。一次性计划、评估与实施记录
> （有日期的工程快照）保存在 [archive/](archive/)，其内容描述的是历史仓库状态。

## 使用与部署

- [USER-GUIDE.md](USER-GUIDE.md) — 场景化使用指南（真实场景 + 命令速查）
- [RAILWAY-DEPLOYMENT.md](RAILWAY-DEPLOYMENT.md) — Railway 部署指南
- [EARNINGS-HANDBOOK.md](EARNINGS-HANDBOOK.md) — 财报窗口实战手册（时效：2026 中报窗口）

## 架构与设计

- [DETAILED-ARCHITECTURE.md](DETAILED-ARCHITECTURE.md) — 详细架构（数据库布局 / 记忆系统 / 回测 / CLI 速查）
- [DESIGN.md](DESIGN.md) — 设计原则与关键决策
- [MEMORY-SYSTEM-PLAN.md](MEMORY-SYSTEM-PLAN.md) — 记忆系统（5 层）架构文档
- [KLINE-SPEC.md](KLINE-SPEC.md) — K 线模块技术规格
- [DATABASE-LIFECYCLE.md](DATABASE-LIFECYCLE.md) — 数据库句柄所有权与生命周期规则
- [AGENT-INTERACTION-GUIDE.md](AGENT-INTERACTION-GUIDE.md) — Agent 交互指南（工作流 + 工具边界）
- [AGENT-INTERFACE-EVOLUTION.md](AGENT-INTERFACE-EVOLUTION.md) — Agent 接口演进与设计教训
- [adr/](adr/) — 架构决策记录（ADR，编号自 0001 起）

## 发布与质量

- [RELEASE-CHECKLIST.md](RELEASE-CHECKLIST.md) — v1.0.0 发布门禁清单
- [TECH-DEBT.md](TECH-DEBT.md) — 技术债台账（mypy 豁免清单、测试告警、待决策项）

## 历史档案（archive/）

[archive/](archive/) 保留 25 份一次性工程记录：v1.0.0 强化计划与基线评估
（ENHANCEMENT-PLAN / EVALUATION-2026-07-14）、2026-07-06 系列评估（EVAL-*）、
回测报告（BACKTEST-REPORT）、commit 级台账（LEDGER）、进度快照（PROGRESS）、
项目总览（PROJECT-LOG）、合并分析（BRANCH-MERGE-ANALYSIS）、TUI 重写实施记录、
知乎发文草稿等。其中的数字与结论描述的是当时状态，
请以根 README、CHANGELOG 与 CI 配置为当前状态的真相源。
