# mommy-chaogu

<div align="center">

**本地优先的 A 股投研助手。用一句话看行情、查资金、分析持仓，并把判断变成可验证的投研记录。**

[![CI](https://github.com/coffee-man666/mommy-chaogu/actions/workflows/ci.yml/badge.svg)](https://github.com/coffee-man666/mommy-chaogu/actions/workflows/ci.yml)
[![Python 3.12+](https://img.shields.io/badge/python-3.12+-blue.svg)](https://www.python.org/downloads/)
[![Release: v1.2.0](https://img.shields.io/badge/release-v1.2.0-blue.svg)](CHANGELOG.md)
[![License: MIT](https://img.shields.io/badge/license-MIT-yellow.svg)](LICENSE)

</div>

mommy-chaogu 把实时行情、资金流、持仓、信号、记忆和 AI Agent 放进同一条对话。
它可以作为独立 CLI / TUI / Web App 使用，也可以把投研能力接入 Claude Code、Kimi Code
或微信。

## 为什么是 mommy-chaogu

- **一句话开始研究**：从市场概览到个股、板块、资金流和持仓，不用先学习一套命令。
- **不只生成一段答案**：保存研究结论和预测，持续验证判断是否成立。
- **一个内核，多种入口**：终端、Web、微信和外部 Coding Agent 使用同一套投研工具。
- **本地优先**：密钥、持仓、记忆和数据库由用户自己的设备保存。

## 30 秒启动

需要 [Python 3.12+](https://www.python.org/downloads/) 和
[uv](https://docs.astral.sh/uv/getting-started/installation/)：

```bash
git clone https://github.com/coffee-man666/mommy-chaogu.git
cd mommy-chaogu
uv run mommy
```

第一次运行会自动引导你选择模型、隐藏输入并验证 API Key；配置只保存在当前设备。
没有 Key 也可以跳过，继续使用行情、资金流和预定义工作流。

> 官方一行安装脚本正在准备中。在正式发布前，README 只提供已经可用的安装方式。

## 配置模型与微信

首次启动会自动进入配置，也可以随时重新运行：

```bash
uv run mommy setup
```

向导会让你选择 Provider 和模型、隐藏输入并验证 API Key，然后询问是否连接微信。当前支持
DeepSeek、OpenAI、Kimi、z.ai、Nova Bridge 和 MiniMax。配置默认以 `0600` 权限保存到
`~/.config/mommy-chaogu/.env`；如果项目已有 `.env`，则更新项目配置。

如果首次配置时跳过了微信，之后可以单独扫码连接：

```bash
uv run mommy channel weixin connect   # 显示二维码，扫码后在后台上线
uv run mommy channel weixin status    # 查看授权和运行状态
uv run mommy channel weixin stop      # 停止网关，但保留本机授权
```

微信模式不需要公网 IP、域名或开放端口，只接受扫码账号的私聊。消息会经过微信服务，投研
内容会发送给用户选择的 LLM Provider。详细权限与排障见
[微信本地频道](docs/WEIXIN-CHANNEL.md)。

## 启动方式

| 你想要的体验 | 启动命令 | 说明 |
|---|---|---|
| 连续自然语言对话 | `uv run mommy` | 最轻量的交互式入口 |
| Coding Agent 风格终端 | `uv run mommy tui` | 富卡片、slash 命令、`@` 股票联想、流式状态 |
| 本机网页 | `uv run mommy web` | 打开 `http://127.0.0.1:8000`，本机默认免登录 |
| Claude Code | `uv run mommy connect claude` | 复用 Claude 登录，不再配置一套 LLM Key |
| Kimi Code | `uv run mommy connect kimi` | 安装本地 MCP 和 `mommy-research` Skill |
| 微信远程对话 | `uv run mommy channel weixin connect` | 扫码连接本地网关，不开放公网端口 |

已经通过安装包安装时，去掉命令前的 `uv run`，直接使用 `mommy`。

## 直接试试

```bash
uv run mommy "今天大盘怎么样"
uv run mommy "分析一下比亚迪"
uv run mommy "半导体板块最近强不强"
uv run mommy "主力资金在买什么"
uv run mommy -v "分析 600519"       # 展开路由和工具调用
```

命中固定工作流时，mommy 会直接获取结构化数据；需要开放式判断时，再交给 LLM Agent
自主选择工具。事实、工具结果和模型推断保持可区分。

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
