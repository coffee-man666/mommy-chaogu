# 微信本地频道

微信频道把微信作为本地个人助手的远程对话入口。行情、持仓、记忆和 LLM 凭据仍由
用户自己的电脑保存；本地进程主动长轮询微信服务，不开放公网端口。

## 使用

```bash
# 推荐：一次配置 Provider、模型、Key；扫码后自动在后台上线
uv run mommy setup

# 已有 AI 配置时，也可只连接微信
uv run mommy channel weixin login

# 在后台启动消息网关（终端可以关闭）
uv run mommy channel weixin start

# 前台运行消息网关（调试用，Ctrl+C 停止）
uv run mommy channel weixin run

# 也可以一次完成登录并启动
uv run mommy channel weixin connect

# 查看状态 / 解除本地授权
uv run mommy channel weixin status
uv run mommy channel weixin stop
uv run mommy channel weixin logout
```

`login` 只保存扫码授权；`setup` 会在扫码成功后自动启动后台网关。`status` 会明确显示
“未授权”“已授权但离线”或“在线”，不再把保存了凭据误报成已经上线。后台日志保存在
同一私有目录下的 `gateway.log`。

凭据默认保存在 `~/.config/mommy-chaogu/channels/weixin/credentials.json`，目录权限尽量
设置为 `0700`，文件权限设置为 `0600`。可以通过 `MOMMY_CHANNEL_STATE_DIR` 或
`--state-dir` 覆盖根目录。凭据不会写入仓库、`.env` 或浏览器存储。

## 信任边界

- 只接受扫码者的私聊；其他发送者、群聊和机器人消息默认丢弃。
- 每个微信账号和发送者映射到独立的 Agent 对话 session。
- 日志不打印 bot token、context token 或完整授权响应。
- 微信消息会经过腾讯服务；发送给 LLM 的内容会经过用户配置的模型 Provider。
- 当前版本只支持文本收发；图片、语音、文件和高风险操作确认尚未开放。

## 后续增强

- 支持扫码账号在微信中查看和切换模型；模型来自受控列表，同时保留手动填写兼容模型名的入口。
- 切换配置需要明确确认，不在聊天或日志中回显 API key，并与 Web、TUI、CLI 共用同一份配置。

## 协议来源

二维码登录、iLink 请求头、`getupdates`、`sendmessage` 和本地 allowlist 设计参考
[Tencent/openclaw-weixin](https://github.com/Tencent/openclaw-weixin)。该项目由腾讯以
MIT License 发布。这里没有引入 OpenClaw 运行时，只实现本项目所需的最小 Python
适配层。
