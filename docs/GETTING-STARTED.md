# 从安装到运行

这份文档解释 mommy-chaogu 的安装、模型配置和不同运行模式。想先体验功能，可以直接回到
[README 的 30 秒启动](../README.md#30-秒启动)。

## 1. 一行安装

macOS / Linux：

```bash
curl -LsSf https://github.com/coffee-man666/mommy-chaogu/raw/refs/heads/main/install.sh | sh
mommy
```

脚本会在缺少 uv 时安装 uv，再用隔离的 Python 3.12 环境安装 mommy-chaogu。重复运行同一
命令可更新安装。第一次运行 `mommy` 会自动进入模型配置。用户配置保存在
`~/.config/mommy-chaogu/`，数据库默认保存在 `~/.local/share/mommy-chaogu/`，不会因为
从不同目录启动而产生多套数据。

如需先审阅脚本：

```bash
curl -LO https://github.com/coffee-man666/mommy-chaogu/raw/refs/heads/main/install.sh
less install.sh
sh install.sh
```

Windows 安装脚本尚未提供。

## 2. 从源码运行

需要 Python 3.12+ 和 uv：

```bash
git clone https://github.com/coffee-man666/mommy-chaogu.git
cd mommy-chaogu
uv run mommy
```

`uv run` 会根据锁文件准备运行环境。开发者需要测试和检查工具时运行：

```bash
uv sync --frozen --extra dev
```

本文后续示例以源码运行展示 `uv run mommy`。通过一行脚本安装的用户直接运行 `mommy`，
例如把 `uv run mommy setup` 写成 `mommy setup`。

## 3. 配置内置 AI

首次运行 `mommy` 会在没有可用模型配置时自动启动向导，也可以随时手动运行：

```bash
uv run mommy setup
```

向导会依次完成：

1. 选择 LLM Provider。
2. 接受默认模型，或输入兼容模型名。
3. 隐藏输入 API Key，并用最小请求验证连接。
4. 以 `0600` 权限保存配置。
5. 可选显示微信二维码，扫码后启动本地微信网关。

如果当前仓库已有 `.env`，向导会更新它；否则默认写入
`~/.config/mommy-chaogu/.env`。常用选项：

```bash
uv run mommy setup --local       # 强制写入当前项目 .env
uv run mommy setup --no-weixin   # 不询问微信连接
uv run mommy setup --no-verify   # 暂时无法联网时跳过验证
```

### 支持的 Provider

| Provider | Key 环境变量 | 默认模型 | 说明 |
|---|---|---|---|
| DeepSeek | `DEEPSEEK_API_KEY` | `deepseek-chat` | 默认推荐 |
| OpenAI | `OPENAI_API_KEY` | `gpt-4o-mini` | 支持向量检索 |
| Kimi | `MOONSHOT_API_KEY` | `kimi-k2.6` | Kimi Coding API |
| z.ai | `ZAI_API_KEY` | `glm-4.7` | GLM Coding API |
| Nova Bridge | `NOVA_API_KEY` | `nova-bridge` | 本机 `127.0.0.1:9999/v1` 桥接 |
| MiniMax | `MINIMAX_API_KEY` | `MiniMax-M3` | 开放平台按量 API，非 Coding Plan |

也可以复制 `.env.example` 手动配置：

```dotenv
DEEPSEEK_API_KEY=sk-xxxxxxxx
AGENT_PROVIDER=deepseek
AGENT_MODEL=deepseek-chat
```

配置优先级为：shell 环境变量 → 项目 `.env` → 用户级 `.env` → `config.toml` / 默认值。
不要提交包含真实密钥的 `.env`。

## 4. 不配置 LLM

报价、K 线、资金流和预定义工作流不需要 LLM Key：

```bash
uv run mommy "今天大盘怎么样"
uv run mommy watchlist add 600519 --group 白酒
uv run mommy watchlist list
uv run mommy flows top
```

第一次运行自然语言入口时可以跳过配置。固定工作流仍会返回结构化结果，但不会生成 LLM
总结；开放式问题会提示配置模型。

## 5. CLI、TUI 与本机 Web

```bash
uv run mommy                         # 自然语言 REPL
uv run mommy "分析一下比亚迪"       # 单次查询
uv run mommy -v "分析 600519"       # 查看路由和工具调用
uv run mommy tui                     # 单屏终端 UI
uv run mommy web --port 8765         # 本机 Web
```

本机 Web 默认只监听 `127.0.0.1`，即使配置中保留了公网令牌，也不会要求本机浏览器重复
输入。打开 `http://127.0.0.1:8765` 即可使用。

## 6. 连接 Claude Code 或 Kimi Code

外部 Coding Agent 已经有自己的模型，因此不需要再给 mommy-chaogu 配一套 LLM Key：

```bash
uv run mommy connect claude          # 或 kimi
uv run mommy connect status
uv run mommy connect test claude
```

连接命令会注册本地 stdio MCP Server、安装 `mommy-research` Skill，并执行连通测试。默认
`market-only` 只发布公共行情和研究工具，不读取持仓、自选和历史记忆，也不写入结论。

明确需要个人投研闭环时才切换：

```bash
uv run mommy connect claude --profile personal
uv run mommy connect test claude
```

`personal` 工具结果会进入所选 Coding Agent 的模型上下文。MCP 不会把 API Key 作为工具
结果返回，但 profile 不约束 Coding Agent 自身的文件系统权限；不要在敏感目录开启跳过
确认或 YOLO 模式。

```bash
uv run mommy connect disconnect claude
uv run mommy connect disconnect all
```

## 7. 微信本地网关

微信模式需要先配置内置 LLM：

```bash
uv run mommy channel weixin connect
uv run mommy channel weixin status
```

扫码后，本地进程主动长轮询，不需要公网 IP、域名或开放端口。它默认只接受扫码账号的
私聊。常用生命周期命令：

```bash
uv run mommy channel weixin stop       # 停止网关，保留授权
uv run mommy channel weixin start      # 使用已有授权上线
uv run mommy channel weixin logout     # 删除当前设备上的授权
```

微信消息会经过腾讯服务，投研问题会经过所选 LLM Provider。更多说明见
[微信本地频道](WEIXIN-CHANNEL.md)。

## 8. 局域网手机访问 Web

监听非本机地址时必须设置长随机令牌：

```bash
export MOMMY_API_TOKEN="$(openssl rand -hex 32)"
uv run mommy web --host 0.0.0.0 --port 8765
```

手机与电脑连接同一可信局域网，打开 `http://电脑局域网IP:8765`，然后在“我的 → 访问
令牌”输入同一令牌。令牌只保存在浏览器会话，WebSocket 使用短期 ticket。

不要把 HTTP 端口直接暴露到公网。公网使用应增加 HTTPS 反向代理或私有网络隧道，并
限制 CORS。本机需要测试认证时运行：

```bash
uv run mommy web --require-auth --api-token "你的长随机令牌"
```

## 9. Docker Web

Docker 默认只映射到宿主机 `127.0.0.1:8000`：

```bash
docker compose up -d
# 打开 http://127.0.0.1:8000
```

没有 Key 时仍可使用数据页面。AI 对话需要项目 `.env`：

```bash
cp .env.example .env
# 编辑 .env，填写 Provider Key、AGENT_PROVIDER 和 AGENT_MODEL
docker compose up -d --build
```

如果本机已经安装 uv，也可以运行 `uv run mommy setup --local --no-weixin` 生成容器读取的
项目 `.env`。云端方案见 [Railway 部署指南](RAILWAY-DEPLOYMENT.md)。

## 下一步

- 用真实场景学习：[场景化使用指南](USER-GUIDE.md)
- 理解 Agent 工具：[Agent 交互指南](AGENT-INTERACTION-GUIDE.md)
- 查看全部命令和架构：[详细架构](DETAILED-ARCHITECTURE.md)
