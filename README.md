# mommy-chaogu

<div align="center">

[![License: MIT](https://img.shields.io/badge/License-MIT-yellow.svg)](LICENSE)
[![Python 3.12+](https://img.shields.io/badge/python-3.12+-blue.svg)](https://www.python.org/downloads/)
[![CI](https://github.com/coffee-man666/mommy-chaogu/actions/workflows/ci.yml/badge.svg)](https://github.com/coffee-man666/mommy-chaogu/actions/workflows/ci.yml)
[![Release: v1.2.0](https://img.shields.io/badge/release-v1.2.0-blue.svg)](CHANGELOG.md)
[![Tests](https://img.shields.io/badge/tests-1%2C541-brightgreen.svg)](#项目数据)
[![Code style: ruff](https://img.shields.io/badge/code%20style-ruff-000000.svg)](https://github.com/astral-sh/ruff)
[![Type check: mypy strict (core)](https://img.shields.io/badge/mypy-strict%20%E6%A0%B8%E5%BF%83%E6%A8%A1%E5%9D%97-blue.svg)](docs/TECH-DEBT.md)

</div>

A 股投研工具集 — 行情监控、资金流分析、AI agent 对话、自进化记忆系统、回测引擎。

从一个「给妈妈用的手机行情工具」起步，逐步演进为涵盖数据采集、信号告警、LLM 分析、预测验证闭环、回测评估的完整投研框架。当前版本 **v1.2.0**，变更记录见 [CHANGELOG](CHANGELOG.md)。

---

## 界面一览

**Web 对话首页（桌面）**

![Web 对话首页：对话主轴与投研上下文栏](docs/images/web-conversation.png)

**Web 投研上下文（移动端）**

<img src="docs/images/web-context-drawer.png" alt="移动端投研上下文抽屉" width="390" />

**终端 TUI 单屏对话**

![TUI 单屏对话与今日总览卡片](docs/images/tui-conversation.svg)

---

## 核心能力

| 能力 | 说明 |
|---|---|
| **自然语言入口** | `mommy` 命令：用自然语言描述需求，自动匹配 9 个预定义工作流，未命中 fallback 到 LLM agent |
| **统一首次配置** | 首次运行 `mommy` 自动引导选择 Provider / 模型、隐藏输入并验证 Key，可继续微信扫码；用户级配置换目录仍生效 |
| **工具调用可视化** | `--verbose` 显示完整路由决策 + 工具调用过程（`🔧 调用: get_quote...`），消除 AI 黑盒感 |
| **行情数据** | 多源 fallback（东财 + 腾讯 + 缓存），报价 / K 线 / 资金流 / 板块排行 / 基本面 |
| **资金流分析** | 主力净流入比率 (bp) 信号、板块扫描、收盘日报、历史回测 |
| **AI Agent** | 25 个 function-calling 工具，支持 deepseek / openai / kimi / z.ai (GLM) / Nova Bridge / MiniMax，Web 聊天 + 流式推送 |
| **自进化记忆** | 5 层记忆架构（工作/情景/预测验证/语义知识/向量检索），`mommy memory` 命令查看记忆 |
| **回测引擎** | 规则回测 + LLM 回测 + 组合分析 + walk-forward 过拟合检测 + 市场环境分组分析 |
| **财报窗口** | 业绩前瞻入库 + actual vs predicted 自动打分，4 种 verdict 分级 |
| **信号告警** | 7 条内置规则 + 自定义价格/涨跌幅告警，可在 Web 信号页和 TUI `/signals` 查看 |
| **Web UI** | 移动优先的对话首页 + 投研上下文栏，支持名称搜股、对话排队、语音输入、预测/信号闭环与 WebSocket 流式推送 |
| **终端 TUI** | `mommy tui`：Claude Code 风格单屏投研对话，富卡片、`@` 股票联想、slash 命令、忙时排队与 Esc 中断 |
| **安全边界** | 单用户 Bearer 令牌 + WebSocket 短期签名 ticket + 受限 CORS；Web 服务默认仅监听 127.0.0.1 |
| **Docker 部署** | `docker compose up -d` 一键启动，可复现构建 + 非 root 运行 |

---

## 5 分钟快速上手

需要 [Python 3.12+](https://www.python.org/downloads/) 和
[uv](https://docs.astral.sh/uv/getting-started/installation/)：

```bash
git clone https://github.com/coffee-man666/mommy-chaogu.git
cd mommy-chaogu
uv sync --frozen

# 交互式配置 Provider、模型和 API Key；最后可选微信扫码
uv run mommy setup

# 任选一个入口开始使用
uv run mommy                         # 自然语言 REPL
uv run mommy tui                     # 单屏终端界面
uv run mommy web                     # Web UI：http://127.0.0.1:8000
uv run mommy "分析一下比亚迪"       # 单次查询
```

配置向导会验证模型是否可用，并把密钥写入当前用户的私有配置文件，输入时不会回显。
如果当前仓库已经有 `.env`，向导会更新它；否则默认写入
`~/.config/mommy-chaogu/.env`。换到其他目录后仍可使用。

> 没有 API Key 也能使用报价、K 线、资金流和预定义工作流；自由对话、AI 总结、Web AI
> 对话和微信助手需要 LLM。已经使用 Claude Code 或 Kimi Code 的用户也可以复用 Coding
> Agent 的登录，见下方“模式 C”。

---

## 选择使用模式

| 模式 | 适合场景 | 是否需要 mommy 的 LLM Key | 数据边界 | 启动方式 |
|---|---|---:|---|---|
| **A. 本地内置助手** | CLI / TUI / Web 的完整 AI 体验 | 是 | Key、数据库和记忆保存在本机；请求发往所选 Provider | `mommy` / `mommy tui` / `mommy web` |
| **B. 无 AI 数据工具** | 只看行情、资金流、自选和固定工作流 | 否 | 数据保存在本机 | 结构化命令或能命中工作流的自然语言 |
| **C. Claude/Kimi 接入** | 在已有 Coding Agent 中调用本项目投研逻辑 | 否，复用 Agent 登录 | 默认只开放公共行情；可显式开放个人数据 | `mommy connect claude` / `mommy connect kimi` |
| **D. 微信本地网关** | 电脑运行服务，微信远程对话 | 是 | 不开放公网端口；消息经过微信和所选 LLM Provider | `mommy channel weixin connect` |
| **E. Docker Web** | 不安装本地 Python/Node，浏览器使用 | AI 对话需要 | 容器数据保存在 Docker volume | `docker compose up -d` |

以下命令从源码仓库运行，因此使用 `uv run`。如果以后通过安装包安装，可直接去掉
`uv run`，例如运行 `mommy setup`、`mommy tui`。

### 模式 A：配置并使用内置 AI

推荐使用统一配置向导：

```bash
uv run mommy setup
```

向导依次完成：

1. 选择 LLM Provider。
2. 接受默认模型，或填写该 Provider 支持的其他模型名。
3. 隐藏输入 API Key，并发起一次最小请求验证配置。
4. 以 `0600` 权限保存配置。
5. 可选：显示微信二维码，扫码后启动本地微信网关。

当前内置 Provider：

| Provider | Key 环境变量 | 默认模型 | 说明 |
|---|---|---|---|
| DeepSeek | `DEEPSEEK_API_KEY` | `deepseek-chat` | 默认推荐 |
| OpenAI | `OPENAI_API_KEY` | `gpt-4o-mini` | 支持向量检索 |
| Kimi | `MOONSHOT_API_KEY` | `kimi-k2.6` | Kimi Coding API |
| z.ai | `ZAI_API_KEY` | `glm-4.7` | GLM Coding API |
| Nova Bridge | `NOVA_API_KEY` | `nova-bridge` | 本机 `127.0.0.1:9999/v1` 桥接 |
| MiniMax | `MINIMAX_API_KEY` | `MiniMax-M3` | 开放平台按量 API，非 Coding Plan |

重新配置时再次运行 `mommy setup` 即可。常用选项：

```bash
uv run mommy setup --local       # 强制写入当前项目 .env
uv run mommy setup --no-weixin   # 只配置 LLM，不询问微信连接
uv run mommy setup --no-verify   # 暂时无法联网时跳过验证
```

也可以复制 `.env.example` 手动配置。至少填写所选 Provider 的 Key、
`AGENT_PROVIDER` 和可选的 `AGENT_MODEL`：

```dotenv
DEEPSEEK_API_KEY=sk-xxxxxxxx
AGENT_PROVIDER=deepseek
AGENT_MODEL=deepseek-chat
```

配置优先级为：shell 环境变量 → 项目 `.env` → 用户级 `.env` → 项目默认配置。
不要提交包含真实密钥的 `.env`。

配置完成后可选择任一界面：

```bash
# 自然语言 REPL / 单次问题
uv run mommy
uv run mommy "今天大盘怎么样"
uv run mommy -v "分析 600519"     # 显示路由和工具调用

# Claude Code 风格单屏 TUI
uv run mommy tui

# 本机 Web：默认免登录，只监听 127.0.0.1
uv run mommy web --port 8765
# 打开 http://127.0.0.1:8765
```

`mommy` 会先匹配 9 个预定义工作流；未命中时再交给 LLM Agent。TUI 支持富卡片、
slash 命令、`@` 股票联想、忙时排队和 Esc 中断。Web 提供移动端底部导航与桌面端
投研上下文栏。

### 模式 B：不配置 LLM，只使用本地数据能力

行情和固定工作流不依赖 LLM Key：

```bash
uv run mommy "今天大盘怎么样"
uv run mommy watchlist add 600519 --group 白酒
uv run mommy watchlist list
uv run mommy flows top
```

命中固定工作流时会返回结构化结果，但不会生成 LLM 总结；自由提问会提示先运行
`mommy setup`。旧的独立命令（`mommy-watchlist`、`mommy-monitor` 等）仍向后兼容。

### 模式 C：连接 Claude Code 或 Kimi Code

如果用户已经安装并登录 Claude Code 或 Kimi Code，可以让它直接调用本地投研工具，
不需要再给 mommy-chaogu 配置 LLM Key：

```bash
uv run mommy connect claude          # 或：uv run mommy connect kimi
uv run mommy connect status
uv run mommy connect test claude
```

连接命令会注册本地 stdio MCP Server、安装 `mommy-research` Skill，并做连通测试。
重启或新开对应 Coding Agent 后，可以直接说“用 mommy 分析 600519”。

默认 profile 是更安全的 `market-only`，只发布公共行情和研究工具，不读取持仓、
自选、对话记忆，也不写入结论。明确需要个人投研闭环时才切换：

```bash
uv run mommy connect claude --profile personal
uv run mommy connect test claude
```

`personal` 工具返回的数据会进入所选 Coding Agent 的模型上下文。MCP 工具不会把 API
Key 作为结果返回，数据库文件仍保留在本机；但 Coding Agent 本身仍能看到工具返回值，
也可能拥有独立的文件系统权限。profile 只约束 MCP 工具，因此不要在敏感目录中开启
跳过确认/YOLO 模式。

```bash
uv run mommy connect disconnect claude   # 只移除托管的 Claude 配置和 Skill
uv run mommy connect disconnect all      # 断开全部 Coding Agent
```

### 模式 D：微信作为本地远程入口（Beta）

先按模式 A 配置 LLM，然后运行：

```bash
uv run mommy channel weixin connect
uv run mommy channel weixin status
```

终端会显示二维码；扫码确认后，本地网关在后台主动长轮询，不需要公网 IP、域名或开放
端口。它默认只接受扫码账号的私聊，授权信息仅保存在当前设备。

```bash
uv run mommy channel weixin stop       # 停止后台网关，保留授权
uv run mommy channel weixin start      # 使用已有授权重新上线
uv run mommy channel weixin logout     # 删除本机微信授权
```

微信消息会经过腾讯服务，投研问题会经过所选 LLM Provider。完整信任边界和诊断方法见
[微信本地频道](docs/WEIXIN-CHANNEL.md)。

### 局域网手机访问 Web

只在本机打开 Web 不需要口令。只有监听非本机地址时才强制配置访问令牌：

```bash
export MOMMY_API_TOKEN="$(openssl rand -hex 32)"
uv run mommy web --host 0.0.0.0 --port 8765
```

让手机与电脑连接同一可信局域网，打开 `http://电脑局域网IP:8765`，然后在
“我的 → 访问令牌”输入同一令牌。令牌只保存在当前浏览器会话；WebSocket 使用短期
ticket，不把长期令牌放进 URL。不要把这个 HTTP 端口直接暴露到公网；公网使用应在前面
增加 HTTPS 反向代理或私有网络隧道，并限制 CORS。

本机确需测试认证时使用：

```bash
uv run mommy web --require-auth --api-token "你的长随机令牌"
```

### 模式 E：Docker Web

Docker 默认只映射到宿主机 `127.0.0.1:8000`，因此本机浏览器免登录：

```bash
docker compose up -d
# 打开 http://127.0.0.1:8000
```

不配置 Key 时可使用数据页面。要使用 AI 对话，可先编辑项目 `.env`：

```bash
cp .env.example .env
# 编辑 .env，填写 Provider Key、AGENT_PROVIDER 和 AGENT_MODEL
docker compose up -d --build
```

如果本机已有 Python 和 uv，也可用 `uv run mommy setup --local --no-weixin` 生成容器读取的
项目 `.env`。部署到 Railway 时还需要公网令牌和持久化卷，见
[Railway 部署指南](docs/RAILWAY-DEPLOYMENT.md)。

<details>
<summary>开发者安装与质量门</summary>

```bash
uv sync --frozen --extra dev
uv run pytest -m "not network"
uv run ruff check .
uv run mypy --strict src
```

</details>

> 📖 更多功能：[场景化使用指南](docs/USER-GUIDE.md) | [CLI 速查](docs/DETAILED-ARCHITECTURE.md#cli-速查) | [记忆系统](docs/DETAILED-ARCHITECTURE.md#自进化记忆系统) | [回测引擎](docs/DETAILED-ARCHITECTURE.md#回测引擎)

---

## 架构

```
  用户输入（自然语言）
       |
       v
  ┌──────────┐
  │  mommy   │  自然语言入口（--setup 首次配置 / --verbose 工具可视化）
  └────┬─────┘
       |
  ┌────v──────┐     未命中 ──→ AgentService (LLM 自主选工具 + on_tool_call 回调)
  │ NLRouter  │     命中 ──→ WorkflowExecutor (预编排多步)
  └────┬──────┘              |
       |                     |  [匹配: 工作流名称] / [转交 AI 助手]
       v                     v
  ┌─────────────────────────────┐
  │      ToolRegistry (25 tools) │
  └────────────┬────────────────┘
               |
  ┌────────────v────────────┐
  │  Cache / Data Sources   │  ← last_source 标注（实时 / 本地缓存）
  │  (efinance / tencent)   │
  └─────────────────────────┘

  Web UI (Vite + Vue 3)   TUI (Textual)    CLI (mommy memory)
      |                       |                 |
      | HTTP / WebSocket      | 内部 adapter    | SQLite 查询
      v                       v                 v
  FastAPI (uvicorn)    data_service      agent_memory / episodic_events
   /     |      \                          predictions / semantic_knowledge
  /      |       \
Cache   Agent    Data Sources
(SQLite) Service  (efinance / tencent)
          |
   MemoryPipeline ---- EpisodicMemory
          |          -- PredictionTracker
          |          -- SemanticMemory
          |          -- VectorSearch
```

> 架构设计详解、数据库布局、设计原则见 [详细架构](docs/DETAILED-ARCHITECTURE.md)。

---

## 项目数据

| 指标 | 值 |
|---|---|
| 代码量 | ~51,000 行（src ~27,000 + tests ~16,000 + web ~7,000） |
| 测试 | 1,583 collected；1,570 个确定性离线测试 + 13 个定时网络探针 |
| CLI 入口 | `mommy` 统一入口 + 13 个透传子命令（新增 connect），另有 `mommy-earnings`、`mommy-mcp` 等独立入口 |
| Agent 工具 | 内置 Agent 25 个；MCP 另有 6 个确定性研究工作流，并按 privacy profile 发布 |
| 数据库 | 4 个（market / portfolio / agent / reference） |
| LLM Provider | 6 个（deepseek / openai / kimi / z.ai / Nova Bridge / MiniMax） |
| 记忆系统 | 5 层（工作/情景/预测/语义/向量） |

---

## 文档

完整索引见 [docs/README.md](docs/README.md)。版本变更记录见 [CHANGELOG.md](CHANGELOG.md)。
技术债与质量门真实覆盖范围见 [docs/TECH-DEBT.md](docs/TECH-DEBT.md)。

---

## License

[MIT](LICENSE)

---

**免责声明**：本项目仅供学习和个人投资参考，不构成任何投资建议。A 股投资有风险，入市需谨慎。
