# UX 改进执行台账

> 分支: `feat/ux-improvements`
> 基于: 用户反馈分析（19 条建议）
> 创建时间: 2026-07-11

---

## 总览

| Phase | 主题 | 状态 | 测试 |
|-------|------|------|------|
| P0 | Docker 一键启动 + CLI 统一入口 | ✅ 完成 | 893 passed |
| P1 | 首次启动引导 + 工具调用可视化 | ✅ 完成 | 911 passed |
| P2 | Web 移动端改进 + 记忆可见性 | ✅ 完成 | 921 passed |
| P3 | 健壮性 + LLM 降级模式 | ✅ 完成 | 928 passed |
| P4 | 文档重构 + 社区模板 | ✅ 完成 | 928 passed |

---

## Phase 0: Docker 一键启动 + CLI 统一入口 (P0)

### 目标
消除 Python 版本和 uv 的安装门槛，统一 12 个子命令为 `mommy` 子命令模式。

### 任务清单

#### 0.1 docker-compose.yml
- [ ] 创建 `docker-compose.yml`（backend + web + 数据卷）
- [ ] 改进 Dockerfile 支持 .env 文件注入
- [ ] 添加 `data/` 卷持久化

#### 0.2 CLI 统一入口
- [ ] `mommy` 支持 `watchlist/monitor/cache/flows/report/semicon` 作为子命令（不再需要 `--raw`）
- [ ] 保留旧入口的向后兼容（mommy-watchlist 等仍可用）
- [ ] `mommy --help` 显示所有可用子命令
- [ ] 子命令 `--help` 添加使用示例

#### 0.3 README Docker 优先
- [ ] README 安装部分 Docker 放最前面
- [ ] uv 安装方式移入折叠区块

### 执行状态
- 开始时间: 2026-07-11
- 完成时间: 2026-07-11
- 测试结果: 893 passed, 0 failed
- 变更文件:
  - `Dockerfile` — 重写为多阶段构建（builder + runtime）
  - `docker-compose.yml` — 新建（单服务 + 数据卷 + env_file）
  - `.dockerignore` — 新建
  - `src/mommy_chaogu/cli.py` — `main_mommy()` 支持 `mommy watchlist list` 直接子命令
  - `README.md` — Docker 安放最前、CLI 速查更新为统一入口

---

## Phase 1: 首次启动引导 + 工具调用可视化 (P1)

### 目标
降低首次配置门槛，消除 AI 黑盒感，让用户感知系统能力。

### 任务清单

#### 1.1 首次启动交互式引导
- [ ] 检测 `.env` 是否已配置（有无 API key）
- [ ] 交互式选择 LLM provider（DeepSeek/OpenAI/Kimi/z.ai）
- [ ] 只让用户填选中的那一个 key
- [ ] 零配置启动：无 key 时 fallback 到规则模式（仅行情，不做 AI 分析）

#### 1.2 工具调用可视化（CLI）
- [ ] Agent 工具调用过程实时显示（`🔧 调用: get_quote(600519)...`）
- [ ] NLRouter 匹配成功时显示 `[匹配: 大盘快照工作流]`
- [ ] NLRouter fallback 时显示 `[未命中预设工作流，进入 AI 对话]`
- [ ] `--verbose` 开关显示完整路由决策过程

#### 1.3 AgentService 回调机制
- [ ] 在 `_run_loop()` 中添加 `on_tool_start` / `on_tool_end` 回调
- [ ] CLI 注入回调打印工具调用进度
- [ ] TUI 注入回调显示工具调用

### 执行状态
- 开始时间: 2026-07-11
- 完成时间: 2026-07-11
- 测试结果: 911 passed, 0 failed (+18 新增 setup 测试)
- 变更文件:
  - `src/mommy_chaogu/setup.py` — 新建：首次启动交互式配置向导
  - `tests/test_setup.py` — 新建：setup 向导测试（18 个测试）
  - `src/mommy_chaogu/agent/service.py` — `_run_loop()` / `chat()` / `chat_raw()` 添加 `on_tool_call` 回调
  - `src/mommy_chaogu/cli.py` — NLRouter 匹配反馈、工具调用可视化、`--verbose` 开关、`--setup` 命令

---

## Phase 2: Web 移动端改进 + 记忆可见性 (P2)

### 目标
改善移动端导航体验，让记忆系统对用户可见。

### 任务清单

#### 2.1 Web 移动端导航
- [ ] 底部 Tab 补充 Dashboard 和 Signals 入口（或优化为 5 个最优入口）
- [ ] WebSocket 连接状态指示器（绿/黄/红圆点）
- [ ] 断线期间用户输入暂存

#### 2.2 记忆可见性
- [ ] `mommy memory` CLI 命令查看记忆（对话历史/事件/预测/知识）
- [ ] Agent 回复中标注记忆引用数量（`💡 基于 3 条历史记忆`）
- [ ] `mommy memory stats` 显示记忆统计

#### 2.3 CLI --help 使用示例
- [ ] 每个子命令 help 底部添加 EXAMPLES 区块

### 执行状态
- 开始时间: 2026-07-11
- 完成时间: 2026-07-11
- 测试结果: 921 passed, 0 failed (+10 新增 memory CLI 测试)
- 变更文件:
  - `web/src/App.vue` — 移动端底部 Tab 优化（首页+信号替换主题+设置）
  - `web/src/pages/agent/index.vue` — WS 连接状态指示器 + 失败消息重试
  - `src/mommy_chaogu/cli.py` — `mommy memory` 命令（stats/events/predictions/knowledge/history）
  - `pyproject.toml` — 注册 `mommy-memory` 脚本
  - `tests/test_memory_cli.py` — 新建：memory CLI 测试（10 个测试）

---

## Phase 3: 健壮性 + LLM 降级模式 (P3)

### 目标
提升网络失败和 LLM 不可用时的用户体验。

### 任务清单

#### 3.1 数据来源标注
- [ ] 输出中标注数据来源（`[数据: 东方财富 实时]` / `[数据: 本地缓存 2小时前]`）
- [ ] 所有数据源挂掉时返回自然语言说明

#### 3.2 LLM 降级模式
- [ ] API key 无效/额度用完时，自动 fallback 到规则引擎
- [ ] 明确提示用户当前处于降级模式
- [ ] 规则引擎生成结构化快照报告

#### 3.3 WebSocket 稳定性
- [ ] Agent WebSocket 断线自动重连
- [ ] 连接状态前端指示器

### 执行状态
- 开始时间: 2026-07-11
- 完成时间: 2026-07-11
- 测试结果: 928 passed, 0 failed (+7 数据来源标注测试)
- 变更文件:
  - `src/mommy_chaogu/cache/adapter.py` — `last_source` side-channel + `format_source_label()` 方法
  - `tests/test_cache/test_adapter.py` — 7 个新测试
  - `src/mommy_chaogu/cli.py` — LLM 错误分类提示（rate limit/quota/auth）
  - `web/src/api/agent.ts` — WebSocket 初始连接失败重试

---

## Phase 4: 文档重构 + 社区模板 (P4)

### 目标
降低阅读门槛，建立社区贡献基础。

### 任务清单

#### 4.1 README 精简重构
- [ ] README 只保留核心内容（描述 + 架构图 + 安装 + 示例 + 徽章）
- [ ] 详细内容拆分到 docs/ 目录
- [ ] 添加 "5 分钟快速体验" 指南

#### 4.2 GitHub 社区
- [ ] Issue 模板（Bug 报告 / 功能请求 / 使用问题）
- [ ] PR 模板
- [ ] CONTRIBUTING.md 更新（对齐新 CLI 结构）

#### 4.3 CLI help 统一风格
- [ ] 所有子命令 epilog 添加示例区块
- [ ] 统一帮助文案风格

### 执行状态
- 开始时间: 2026-07-11
- 完成时间: 2026-07-11
- 测试结果: 928 passed, 0 failed
- 变更文件:
  - `README.md` — 精简重构（454→192 行，核心内容 + 5 分钟快速体验 + 3 个示例 + 架构图 + 项目数据）
  - `docs/DETAILED-ARCHITECTURE.md` — 新建：从 README 拆出的详细内容（335 行）
  - `.github/ISSUE_TEMPLATE/bug_report.yml` — Bug 报告模板（替换旧 .md）
  - `.github/ISSUE_TEMPLATE/feature_request.yml` — 功能请求模板（替换旧 .md）
  - `.github/ISSUE_TEMPLATE/config.yml` — 禁用空白 Issue，引导到 Discussions
  - `.github/PULL_REQUEST_TEMPLATE.md` — PR 模板（替换旧小写文件）
  - `.github/CODEOWNERS` — 代码所有权占位
  - `CONTRIBUTING.md` — 更新 CLI 入口说明 + Issue 指南
  - `src/mommy_chaogu/cli.py` — 6 个 parser builder 添加 EXAMPLES epilog + RawDescriptionHelpFormatter
