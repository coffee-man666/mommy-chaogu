# 妈咪炒股 iOS

SwiftUI iOS 17+ MVP。它不是 Web 页的壳，而是直接连接现有 FastAPI / WebSocket 数据管道的原生客户端。

## 当前能力

- 今日总览：自选行情、持仓温度、预测记忆与 AI 快捷入口
- 原生看盘：自选报价、涨跌色、Swift Charts K 线
- 持仓分析：总市值、浮盈亏、逐仓详情与一键 AI 复盘
- 股票篮子：内置主题和自定义分组的统一目录、成分股与 AI 分析
- 多对话 AI：本地会话目录、服务端历史恢复、WebSocket 流式回答、工具调用状态
- 记忆系统：读取 Agent 预测与验证状态
- 语音指挥：中文连续听写、发送 Agent、语音播报和播报打断
- 个性主题：深夜、奶油、薄荷、霓虹四套完整语义色板；行情始终保持 A 股红涨绿跌
- 多模型：模型和密钥由现有服务端统一管理，App 可无感使用 DeepSeek、OpenAI 兼容接口、Kimi、GLM 和 MiniMax

## 运行

先启动项目后端：

```bash
uv run mommy-web
```
然后打开 `MommyChaogu.xcodeproj`，选择 iPhone 模拟器运行。也可以重新生成工程：

```bash
cd ios
xcodegen generate
open MommyChaogu.xcodeproj
```

默认服务地址是 `http://127.0.0.1:8000`，适用于模拟器连接本机服务。真机请在「我的 → 模型与连接」中改成 Mac 的局域网地址，例如 `http://192.168.1.20:8000`，并确保后端监听局域网接口。

如果服务端启用了访问令牌，在同一页面填写令牌。WebSocket 会先通过 `/api/auth/ws-ticket` 获取短期票据，不会把长期令牌放进 WebSocket URL。

## 语音模型边界

当前可直接使用的闭环是：Apple Speech 中文听写 → 现有 Agent（可由 MiniMax 等模型驱动）→ 系统中文语音播报。设置页预留了 MiniMax 实时语音网关地址；生产接入时应由后端代理实时音频协议、签发短期凭据并转发 Agent 工具事件，不应把 MiniMax API Key 放进 App。

## 会话与记忆

会话标题、排序和 `session_id` 目录保存在设备；实际消息由后端 `agent_memory` 按 `session_id` 保存。这样可以立即提供多会话管理，同时复用现有五层记忆和预测抽取管道。后续做跨设备同步时，建议在后端增加会话目录 CRUD，而不是同步客户端 `UserDefaults`。

## 验证

```bash
xcodebuild \
  -project MommyChaogu.xcodeproj \
  -scheme MommyChaogu \
  -destination 'platform=iOS Simulator,name=iPhone 16 Pro' \
  -derivedDataPath /tmp/mommy-chaogu-ios-derived \
  CODE_SIGNING_ALLOWED=NO test
```

GitHub Actions 会在每次涉及 `ios/` 的推送和 PR 中重新生成工程，检查
`project.yml` 与 `xcodeproj` 是否一致，并在可用的 iPhone 模拟器上运行同一套测试。
