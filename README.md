# mommy-chaogu

> 原生 iOS MVP 已加入：[iOS 运行与架构说明](ios/README.md)。

<div align="center">

**可以被你现有 Agent 接管的本地 A 股 / 美股投研能力。你表达目标，Agent 负责安装、研究、记录和维护。**

[![CI](https://github.com/coffee-man666/mommy-chaogu/actions/workflows/ci.yml/badge.svg)](https://github.com/coffee-man666/mommy-chaogu/actions/workflows/ci.yml)
[![Python 3.12+](https://img.shields.io/badge/python-3.12+-blue.svg)](https://www.python.org/downloads/)
[![Release: v1.4.0](https://img.shields.io/badge/release-v1.4.0-blue.svg)](CHANGELOG.md)
[![License: MIT](https://img.shields.io/badge/license-MIT-yellow.svg)](LICENSE)

</div>

mommy-chaogu 把实时行情、资金流、持仓、信号、记忆和策略卡做成本地能力，同时覆盖 A 股与
美股。它首先是一套 Agent-managed product：Claude Code、Kimi Code、Cline、Codex 或其他
MCP Agent 负责理解用户，后端提供确定性数据、保存和监控；CLI / TUI / Web 继续作为可选入口。

## 让你的 Agent 接管

把下面这句话发给你的 Agent：

> 请阅读
> `https://raw.githubusercontent.com/coffee-man666/mommy-chaogu/main/agent-start.md`，先向我展示安装、
> 文件修改和权限计划；得到我同意后安装并做真实检查，再问我第一次想研究什么，直到给出一份有
> 证据、说明数据缺口的研究结果。

Agent 会先以公共市场数据开始，不要求再配置一套项目内 LLM Key。安装成功或 MCP 工具可见不算
完成；用户拿到并理解第一次真实研究结果才算。

## 为什么是 mommy-chaogu

- **一句话开始研究**：从市场概览到个股、板块、资金流和持仓，不用先学习一套命令。
- **不只生成一段答案**：保存研究结论和预测，持续验证判断是否成立。
- **一个内核，多种入口**：终端、Web、微信和外部 Coding Agent 使用同一套投研工具。
- **A 股 + 美股一个入口**：Massive/Polygon 美股主源、Yahoo Finance 免 key 兜底，
  `^` 前缀指数（`^GSPC` / `^VIX` / `^TNX`）和美股大盘简报同样一句话可查。
- **把方法沉淀成策略卡**：文章、研报或个人方法先由 Agent 忠实整理；用户修正、确认后才保存，
  以后可以说“按这套方法看 X”。不能自动判断的条件会明确标为人工或当前不可用。
- **本地优先**：密钥、持仓、记忆和数据库由用户自己的设备保存。

## 独立 App 启动

macOS / Linux：

```bash
curl -LsSf https://raw.githubusercontent.com/coffee-man666/mommy-chaogu/13004434117c239aca5195d80522261ce023fab0/install.sh | sh
mommy
```

安装脚本会自动准备独立的 Python 环境并安装完整应用。第一次运行 `mommy` 会引导你选择
模型、隐藏输入并验证 API Key；配置只保存在当前设备。没有 Key 也可以跳过，继续使用
行情、资金流和预定义工作流。

不喜欢直接执行远程脚本？可以先下载并检查：

```bash
curl -LO https://raw.githubusercontent.com/coffee-man666/mommy-chaogu/13004434117c239aca5195d80522261ce023fab0/install.sh
less install.sh
sh install.sh
```

域名安装地址上线后会替换这条 GitHub Raw URL，安装逻辑保持不变。从源码运行和 Docker
方式见 [从安装到运行](docs/GETTING-STARTED.md)。

## 配置模型与微信

首次运行 `mommy` 会自动进入配置，也可以随时重新运行：

```bash
mommy setup
```

向导会让你选择 Provider 和模型、隐藏输入并验证 API Key，然后询问是否连接微信。当前支持
DeepSeek、OpenAI、Kimi、z.ai 和 MiniMax。配置默认以 `0600` 权限保存到
`~/.config/mommy-chaogu/.env`。只有项目 `.env` 已包含有效模型配置时才会继续更新它；
空白模板不会改变配置作用域。可用 `mommy setup --local` 强制写项目配置，或用
`mommy setup --user` 强制写用户级配置。

排查配置时运行 `mommy setup --check`。它会显示实际生效的 Provider、模型、密钥变量
及来源和文件权限，但绝不显示密钥内容。

如果首次配置时跳过了微信，之后可以单独扫码连接：

```bash
mommy channel weixin connect   # 显示二维码，扫码后在后台上线
mommy channel weixin status    # 查看授权和运行状态
mommy channel weixin stop      # 停止网关，但保留本机授权
```

微信模式不需要公网 IP、域名或开放端口，只接受扫码账号的私聊。消息会经过微信服务，投研
内容会发送给用户选择的 LLM Provider。详细权限与排障见
[微信本地频道](docs/WEIXIN-CHANNEL.md)。

## 启动方式

| 你想要的体验 | 启动命令 | 说明 |
|---|---|---|
| 连续自然语言对话 | `mommy` | 最轻量的交互式入口 |
| Coding Agent 风格终端 | `mommy tui` | 富卡片、slash 命令、`@` 股票联想、流式状态 |
| 本机网页 | `mommy web` | 打开 `http://127.0.0.1:8000`，本机默认免登录 |
| Claude Code | `mommy agent plan --host claude --json` | 先看修改与权限计划，再由 Agent 连接 |
| Kimi Code | `mommy agent plan --host kimi --json` | 安装 onboarding / research / strategy 三层 Skill |
| Cline | `mommy agent plan --host cline --json` | 计划确认后写入本地 MCP 配置 |
| Codex | `mommy agent plan --host codex --json` | 复用 Codex 登录，不再配置一套 LLM Key |
| 微信远程对话 | `mommy channel weixin connect` | 扫码连接本地网关，不开放公网端口 |

开发者如果不想安装全局命令，可以在源码仓库中把 `mommy` 替换为 `uv run mommy`。

## 直接试试

```bash
mommy "今天大盘怎么样"
mommy "美股今天怎么样"
mommy "分析一下比亚迪"
mommy "分析一下 AAPL"
mommy "半导体板块最近强不强"
mommy "主力资金在买什么"
mommy -v "分析 600519"       # 展开路由和工具调用
```

命中固定工作流时，mommy 会直接获取结构化数据；需要开放式判断时，再交给 LLM Agent
自主选择工具。事实、工具结果和模型推断保持可区分。

连接 Agent 后，可以直接说：

```text
“把这篇研报的方法整理成一张我能修改的策略卡，先不要保存。”
“我确认这版忠于原意，保存在本机。”
“按上次那套方法看看 600519 今天，不能判断的条件直接告诉我。”
“把其中真正支持的价格条件准备成监控，启用前再问我。”
```

策略沉淀不是回测或收益验证。第一版不把自然语言编译成任意策略代码，也不为提高自动化率而偷偷
替换用户原规则。

## 本地优先

- API Key、持仓、记忆和数据库默认保存在本机。
- 本机 Web 只监听 `127.0.0.1`，不要求访问口令。
- 局域网访问必须显式配置令牌；不建议把 HTTP 端口直接暴露到公网。
- Coding Agent 新接入默认使用 `market-only`，不读取持仓、记忆和策略卡。用户看到新的权限计划并
  明确同意后才切换到 `personal`；保存策略卡和启用监控仍分别需要明确确认。
- 微信网关只接受扫码账号私聊，但消息仍会经过微信服务和用户选择的 LLM Provider。

完整配置位置、Provider、权限模式、局域网和 Docker 说明见
[从安装到运行](docs/GETTING-STARTED.md)。

## 数据源

行情按市场自动路由：A 股代码走 A 股源，美股 / `^` 前缀指数走美股源，主源失败自动
降级到下一层兜底。

### A 股数据源

- **东方财富（efinance）**——A 股行情、资金流和板块数据主源，免费、无需配置 key。
- **腾讯财经（兜底）**——主源不可用时自动降级。

### 美股数据源

- **Massive / Polygon**——美股行情主源。在 [massive.com](https://massive.com) 注册
  后（Base 免费档即可，日线 T+1），把 API key 写入 `.env`：

  ```bash
  MASSIVE_API_KEY=your_key_here
  ```

  旧名称 `POLYGON_API_KEY` 同样生效。接口文档见
  [Massive REST Stocks](https://massive.com/docs/rest/stocks/overview)。
- **Yahoo Finance（兜底）**——免 key，美股行情、`^` 前缀指数（`^GSPC` / `^VIX` /
  `^TNX`）和美债利率依然可查；不配置美股 key 不影响使用。

## 文档

- [从安装到运行](docs/GETTING-STARTED.md) — 安装、模型配置、各运行模式和安全边界
- [场景化使用指南](docs/USER-GUIDE.md) — 盘前、个股、资金流、持仓和记忆实战
- [微信本地频道](docs/WEIXIN-CHANNEL.md) — 扫码、后台网关与隐私边界
- [Agent 交互指南](docs/AGENT-INTERACTION-GUIDE.md) — 工作流、工具和 MCP 接入
- [Strategy Distillation RFC](docs/STRATEGY-DISTILLATION-RFC.md) — 策略卡、授权与当前能力边界
- [Railway 部署](docs/RAILWAY-DEPLOYMENT.md) — 云端部署与持久化
- [详细架构](docs/DETAILED-ARCHITECTURE.md) — 数据库、记忆系统、回测和 CLI 参考

完整索引见 [docs/README.md](docs/README.md)，版本变化见 [CHANGELOG.md](CHANGELOG.md)。

## 开发

```bash
uv sync --frozen --extra dev
uv run pytest -m "not network"
uv run ruff check .
uv run mypy --strict src
```

项目使用 Python 3.12+、Vue 3、FastAPI、Textual 和 SQLite。贡献代码前请阅读
[AGENTS.md](AGENTS.md) 与 [技术债台账](docs/TECH-DEBT.md)。

## License

[MIT](LICENSE)

**免责声明**：本项目仅供学习和个人投资参考，不构成任何投资建议。A 股投资有风险，入市需谨慎。
