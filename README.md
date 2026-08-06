# mommy-chaogu

<div align="center">

**本地优先的 A 股 / 美股投研助手。用一句话看行情、查资金、分析持仓，并把判断变成可验证的投研记录。**

[![CI](https://github.com/coffee-man666/mommy-chaogu/actions/workflows/ci.yml/badge.svg)](https://github.com/coffee-man666/mommy-chaogu/actions/workflows/ci.yml)
[![Python 3.12+](https://img.shields.io/badge/python-3.12+-blue.svg)](https://www.python.org/downloads/)
[![Release: v1.4.0](https://img.shields.io/badge/release-v1.4.0-blue.svg)](CHANGELOG.md)
[![License: MIT](https://img.shields.io/badge/license-MIT-yellow.svg)](LICENSE)

</div>

mommy-chaogu 把实时行情、资金流、持仓、信号、记忆和 AI Agent 放进同一条对话，
同时覆盖 A 股与美股（Massive/Polygon + Yahoo Finance 双数据源）。它可以作为独立
CLI / TUI / Web App 使用，也可以把投研能力接入 Claude Code、Kimi Code 或微信。

## 为什么是 mommy-chaogu

- **一句话开始研究**：从市场概览到个股、板块、资金流和持仓，不用先学习一套命令。
- **不只生成一段答案**：保存研究结论和预测，持续验证判断是否成立。
- **一个内核，多种入口**：终端、Web、微信和外部 Coding Agent 使用同一套投研工具。
- **A 股 + 美股一个入口**：Massive/Polygon 美股主源、Yahoo Finance 免 key 兜底，
  `^` 前缀指数（`^GSPC` / `^VIX` / `^TNX`）和美股大盘简报同样一句话可查。
- **把观点变成可执行工作流**：用自然语言描述交易观点，自动编译成可复现、可校验的
  结构化工作流，持久化后随时重跑。
- **本地优先**：密钥、持仓、记忆和数据库由用户自己的设备保存。

## 30 秒启动

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
`~/.config/mommy-chaogu/.env`；如果项目已有 `.env`，则更新项目配置。

如果首次配置时跳过了微信，之后可以单独扫码连接：

```bash
mommy channel weixin connect   # 显示二维码，扫码后在后台上线
mommy channel weixin status    # 查看授权和运行状态
mommy channel weixin stop      # 停止网关，但保留本机授权
```

微信模式不需要公网 IP、域名或开放端口，只接受扫码账号的私聊。消息会经过微信服务，投研
内容会发送给用户选择的 LLM Provider。详细权限与排障见
[微信本地频道](docs/WEIXIN-CHANNEL.md)。

## 美股数据源

美股行情优先走 Massive / Polygon（Base 免费档即可，日线 T+1）。在
[https://massive.com](https://massive.com) 注册后，把 API key 写入 `.env`：

```bash
MASSIVE_API_KEY=your_key_here
```

旧名称 `POLYGON_API_KEY` 同样生效。接口文档见
[Massive REST Stocks](https://massive.com/docs/rest/stocks/overview)。

不配置 key 也不影响使用：Yahoo Finance 回退源免 key，美股行情、`^` 前缀指数
（`^GSPC` / `^VIX` / `^TNX`）和美债利率依然可查。

## 启动方式

| 你想要的体验 | 启动命令 | 说明 |
|---|---|---|
| 连续自然语言对话 | `mommy` | 最轻量的交互式入口 |
| Coding Agent 风格终端 | `mommy tui` | 富卡片、slash 命令、`@` 股票联想、流式状态 |
| 本机网页 | `mommy web` | 打开 `http://127.0.0.1:8000`，本机默认免登录 |
| Claude Code | `mommy connect claude` | 复用 Claude 登录，不再配置一套 LLM Key |
| Kimi Code | `mommy connect kimi` | 安装本地 MCP 和 `mommy-research` Skill |
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

更复杂的交易观点可以编译成可执行工作流：

```bash
mommy workflow create "开盘 30 分钟后，如果创业板主力资金净流入超过 50bp 就提醒我"
mommy workflow run <id>       # 随时重跑
mommy workflow list           # 查看内置和自定义工作流
```

## 本地优先

- API Key、持仓、记忆和数据库默认保存在本机。
- 本机 Web 只监听 `127.0.0.1`，不要求访问口令。
- 局域网访问必须显式配置令牌；不建议把 HTTP 端口直接暴露到公网。
- Coding Agent 接入默认使用 `market-only`，不开放持仓、记忆和写操作；只有用户主动选择
  `personal` 才会扩大权限。
- 微信网关只接受扫码账号私聊，但消息仍会经过微信服务和用户选择的 LLM Provider。

完整配置位置、Provider、权限模式、局域网和 Docker 说明见
[从安装到运行](docs/GETTING-STARTED.md)。

## 文档

- [从安装到运行](docs/GETTING-STARTED.md) — 安装、模型配置、各运行模式和安全边界
- [场景化使用指南](docs/USER-GUIDE.md) — 盘前、个股、资金流、持仓和记忆实战
- [微信本地频道](docs/WEIXIN-CHANNEL.md) — 扫码、后台网关与隐私边界
- [Agent 交互指南](docs/AGENT-INTERACTION-GUIDE.md) — 工作流、工具和 MCP 接入
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
