# 场景化使用指南

> 本指南通过真实使用场景，带你和你的 AI agent 从零开始玩转 mommy-chaogu。

---

## 目录

1. [场景一：首次上手（Onboarding）](#场景一首次上手onboarding)
2. [场景二：盘前决策——"今天该怎么操作？"](#场景二盘前决策今天该怎么操作)
3. [场景三：个股深度分析](#场景三个股深度分析)
4. [场景四：资金流监控——"主力在买什么？"](#场景四资金流监控主力在买什么)
5. [场景五：记忆系统——"它记住了什么？"](#场景五记忆系统它记住了什么)
6. [场景六：AI Agent 工具调用全流程](#场景六ai-agent-工具调用全流程)
7. [场景七：LLM 回测验证](#场景七llm-回测验证)
8. [场景八：信号告警与微信推送](#场景八信号告警与微信推送)
9. [场景九：Web UI 日常使用](#场景九web-ui-日常使用)
10. [场景十：TUI 终端工作台](#场景十tui-终端工作台)
11. [场景十一：AI Agent 自动化操作](#场景十一ai-agent-自动化操作)
12. [附录：完整命令速查](#附录完整命令速查)

---

## 场景一：首次上手（Onboarding）

### 你的处境

你是第一次接触这个项目。你刚 clone 了仓库，想知道怎么最快跑起来。

### Step 1：安装

**方式 A：Docker（推荐，3 步搞定）**

```bash
git clone https://github.com/coffee-man666/mommy-chaogu.git
cd mommy-chaogu

# 配置密钥
cp .env.example .env
# 编辑 .env，填入一个 LLM provider 的 key（四选一）

# 启动
docker compose up -d
# 打开 http://localhost:8000
```

**方式 B：本地安装**

```bash
git clone https://github.com/coffee-man666/mommy-chaogu.git
cd mommy-chaogu
uv sync --extra dev
```

### Step 2：配置 LLM（交互式引导）

```bash
uv run mommy --setup
```

系统会引导你完成：

```
╭─ mommy-chaogu 首次配置 ─╮
│                        │
│  选择 LLM 提供商：       │
│  1) DeepSeek (推荐)     │
│  2) OpenAI             │
│  3) Kimi / Moonshot    │
│  4) z.ai / GLM         │
│                        │
╰────────────────────────╯

请选择 [1-4]: 1
请输入 DEEPSEEK_API_KEY: sk-xxxxxxxx

是否配置微信推送？(y/n): n

✅ 配置完成！.env 已生成。
```

> **没有 API key？** 也能用。行情查询、资金流分析等 9 个预定义工作流不需要 LLM。
> 只有 "AI 对话" 功能需要 API key。运行 `mommy "今天大盘怎么样"` 会正常工作，
> 但 `mommy "帮我分析一下这个股的投资逻辑"` 会提示需要配置 key。

### Step 3：验证

```bash
# 测试行情查询（不需要 API key）
uv run mommy "今天怎么样"
```

你应该看到：

```
  [匹配: 今日行情概览：大盘 + 板块 + 自选股]

  ⠹ 获取大盘指数...
  ✓ 获取大盘指数
  ⠹ 获取板块排行...
  ✓ 获取板块排行
  ⠹ 获取自选股报价...
  ✓ 获取自选股报价

  上证指数: 3205.12 (+0.35%)
  深证成指: 10231.45 (+0.52%)
  ...
```

✅ 看到这个输出，说明你的环境已经就绪。

---

## 场景二：盘前决策——"今天该怎么操作？"

### 你的需求

早上 9:00，你想快速了解大盘状况、持仓表现、有没有异常信号。

### 方式 A：自然语言（最快）

```bash
uv run mommy "今天大盘怎么样"
```

系统会执行 `market_check` 工作流：获取上证/深证/创业板指数 + 板块排行。

```bash
uv run mommy "持仓怎么样"
```

系统会执行 `portfolio_review` 工作流：查询持仓报价 + 分析盈亏。

### 方式 B：交互式 REPL

```bash
uv run mommy
```

进入对话模式，连续提问：

```
❯ 今天大盘怎么样
  [匹配: 大盘指数 + 板块行情]
  ✓ 获取大盘指数
  ✓ 获取板块排行
  上证指数: 3205.12 (+0.35%) ...

❯ 主力在买什么
  [匹配: 主力资金流分析]
  ✓ 获取自选股资金流
  ✓ 获取板块排行
  ...

❯ 半导体板块怎么样
  [匹配: 板块分析：排行 + 成分股]
  ...
```

### 方式 C：Web 看板

```bash
uv run mommy web --port 8765
```

手机打开 `http://你的IP:8765`，首页 Dashboard 一屏看完：指数 + 自选股 + 持仓 + 信号。

---

## 场景三：个股深度分析

### 你的需求

你想深入分析一只股票：报价、K 线、资金流、基本面、近期公告。

### 自然语言方式

```bash
uv run mommy "分析一下比亚迪"
```

系统执行 `stock_analysis` 工作流：报价 + K 线 + 资金流，三步自动完成。

### AI Agent 深度分析

```bash
uv run mommy agent "中芯国际最近资金流怎么样？有什么值得注意的？"
```

Agent 会自主选择工具调用链：

```
  🔧 调用: get_money_flow_today...
  🔧 调用: get_money_flow_history...
  🔧 调用: get_fundamentals...
  🔧 调用: search_similar_events...

中芯国际（688981）分析：

**资金面**：近 3 日主力净流入 2.3 亿元，其中超大单占比 65%...
**基本面**：PE 45.2，PB 3.1，ROE 8.7%...
**历史记忆**：上周三曾出现类似的资金流入模式，随后 3 天上涨 4.2%...
```

### 查看工具调用详情

加 `-v` / `--verbose` 看完整路由 + 工具参数：

```bash
uv run mommy -v "分析 600519"
```

输出：

```
  [匹配工作流: 单只股票深度分析：报价 + K线 + 资金流] (id=stock_analysis)

  ⠹ 获取实时报价...     ✓
  ⠹ 获取日K线数据...    ✓
  ⠹ 获取资金流数据...   ✓
```

---

## 场景四：资金流监控——"主力在买什么？"

### 你的需求

你想持续监控资金流向，发现主力异动。

### 一次性扫描

```bash
# 拉取自选股的资金流数据
uv run mommy flows pull

# 查看主力净流入 TOP 20
uv run mommy flows top --direction in --n 20

# 查看主力净流出 TOP 20
uv run mommy flows top --direction out --n 20

# 单只股票资金流详情
uv run mommy flows show 688981 --days 30
```

### 持续监控

```bash
# 每 5 分钟扫描一次，检测资金流异动
uv run mommy flows run --interval 300
```

系统会实时检测 ratio 信号（主力净流入占流通市值的比例异常），发现异动时记录到日志。

### 收盘日报

```bash
# 生成今日收盘资金流报告（Markdown）
uv run mommy flows report
```

报告包含：板块资金流排行、个股异动、自选股汇总。

### 半导体板块专项

```bash
# 从半导体产业链池拉取资金流
uv run mommy flows pull --pool semicon --days 30
uv run mommy flows top --pool semicon --direction in
```

---

## 场景五：记忆系统——"它记住了什么？"

### 你的需求

你用了几天后，想知道 AI 到底记住了哪些信息。

### 查看记忆统计

```bash
uv run mommy memory stats
```

```
📊 记忆系统统计
──────────────────────────────────
  对话记录:    47 条
  情景事件:    23 条 (最近 7 天)
  预测记录:    18 条 (命中 8 / 未中 6 / 待验证 4)
    命中率:   57.1%
  语义知识:    5 条 (活跃 4 / 过期 1)
```

### 查看近期事件

```bash
uv run mommy memory events
```

```
📅 情景事件（最近 20 条）
──────────────────────────────────
  2026-07-10 14:30  analysis_record  688981  中芯国际主力净流入异常放大...
  2026-07-10 11:20  signal_alert     002129  TCL中环涨幅超过 5%...
  2026-07-09 15:00  analysis_record  600519  贵州茅台高位放量...
```

### 查看预测记录

```bash
# 所有预测
uv run mommy memory predictions

# 只看命中的
uv run mommy memory predictions --status hit

# 只看待验证的
uv run mommy memory predictions --status pending
```

### 查看知识库

```bash
uv run mommy memory knowledge
```

系统会从对话和分析中自动提炼语义知识，比如：
- 板块叙事："半导体板块近期受益于 AI 算力需求..."
- 市场规律："主力净流入 > 3% 且连续 2 天，后市上涨概率 65%"

### 查看对话历史

```bash
uv run mommy memory history --limit 10
```

### 记忆如何工作

```
你提问 → Agent 分析 → 自动提取事件/预测 → 存入记忆
                                      ↓
下次提问 → 注入历史记忆到 system prompt → Agent 基于记忆回答
                                      ↓
预测到期 → 自动验证 → 回填 hit/missed → 定期提炼为语义知识
```

你不需要手动操作——记忆系统会在每次对话后自动提取和存储。

---

## 场景六：AI Agent 工具调用全流程

### 你的需求

你想了解 Agent 有哪些工具，以及它是怎么自主选择工具的。

### 查看可用工具

```bash
uv run mommy agent tools
```

24 个 function-calling 工具一览：

| 类别 | 工具 | 用途 |
|------|------|------|
| **行情** | `get_quote` / `get_quotes` / `get_market_indexes` | 实时报价 |
| | `get_bars` | K 线数据（日/周/月/分钟级） |
| | `get_sector_ranking` / `search_sector` / `get_sector_stocks` | 板块行情 |
| **资金流** | `get_money_flow_today` / `get_money_flow_history` | 主力资金流 |
| **基本面** | `get_fundamentals` | PE/PB/ROE/市值等 |
| **组合** | `get_watchlist` / `get_portfolio` / `get_portfolio_analysis` | 自选股/持仓/组合分析 |
| **资讯** | `search_news` / `get_announcements` / `get_longhuban` | 新闻/公告/龙虎榜 |
| **告警** | `manage_alert` | 价格/涨跌幅告警 |
| **记忆** | `search_similar_events` / `get_prediction_history` / `get_market_narrative` | 记忆检索 |
| **主题** | `list_themes` / `get_theme_stocks` | 产业链参考库 |
| **维护** | `backfill_history` / `get_memory_context` | 数据回填/记忆导出 |

### Agent 自主推理示例

```bash
uv run mommy agent "帮我看看白酒板块最近怎么样，有没有机会"
```

Agent 内部推理链：

```
🔧 调用: search_sector("白酒")
   → 找到板块代码 BK0477

🔧 调用: get_sector_stocks("BK0477", sort="change_pct")
   → 获取白酒板块成分股

🔧 调用: get_money_flow_today("600519,000858,...")
   → 获取主力资金流

🔧 调用: search_similar_events(query="白酒板块资金流")
   → 检索历史记忆

🔧 调用: get_prediction_history(code="600519")
   → 查看历史预测准确率

→ 综合分析后输出结论
```

你看到的输出：

```
  🔧 调用: search_sector...
  🔧 调用: get_sector_stocks...
  🔧 调用: get_money_flow_today...
  🔧 调用: search_similar_events...

白酒板块分析：

📊 整体表现：今日下跌 1.2%，近 5 日累计下跌 3.5%...
💰 资金面：主力净流出 4.2 亿，五粮液流出最多...
💡 历史参考：上次类似资金流出出现在 6 月 20 日，随后反弹 5%...
⚠️ 建议：短期观望，关注 600519 在 1680 附近支撑...
```

---

## 场景七：LLM 回测验证

### 你的需求

你想验证 Agent 的预测到底准不准，用历史数据跑回测。

### LLM 回测（离线）

```bash
# 基本回测（默认 10 只股票，7 天窗口）
uv run python scripts/backtest_llm.py \
  --model glm-4.7 --provider zai \
  --max-dates 7 --horizon 5

# 指定股票池
uv run python scripts/backtest_llm.py \
  --model glm-4.7 --provider zai \
  --stocks 688981,600519,002129 \
  --max-dates 14 --horizon 5

# 带记忆系统的回测（记忆进化 + 知识提炼）
uv run python scripts/backtest_llm.py \
  --model glm-4.7 --provider zai \
  --db data/backtest.db --memory-db data/memory.db \
  --max-dates 14 --horizon 5

# Dry run（不调 LLM，只看上下文构建）
uv run python scripts/backtest_llm.py --dry-run
```

回测报告输出：

```
命中率: 42.9% (Wilson 95% CI: [24.5%, 63.5%], p=0.66)
Buy-and-hold 基准: 67%
Alpha (策略-基准): -24%

分方向
  bullish : 5/8 62.5%
  bearish : 4/13 30.8%

记忆系统进化
  Episodic events: 27 条
  Predictions: 21 条 (hit 9, missed 12)
  Semantic knowledge: 3 条
  Traceability: 21/21 条预测关联了 episodic event (100%)
```

### 规则引擎回测（在线）

```bash
# 基于资金流信号的规则回测（30 天，拉取实时数据）
uv run python scripts/backtest_evolution.py

# 指定数据库
uv run python scripts/backtest_evolution.py --db /tmp/backtest.db
```

### 回测的关键指标

| 指标 | 含义 |
|------|------|
| 命中率 | 预测方向与实际方向一致的比例（±2% 死区） |
| Wilson CI | 命中率的 95% 置信区间（样本小时区间很宽） |
| Alpha | 策略命中率减去 buy-and-hold 基准 |
| 分方向 | bullish / bearish 分别的命中率 |
| Traceability | 预测关联了情景事件的比例 |

---

## 场景八：信号告警与微信推送

### 你的需求

你想在盘中自动收到信号告警，不用一直盯盘。

### Step 1：配置推送

```bash
uv run mommy --setup
# 选择 "是否配置微信推送？" → y
# 输入 SERVER_CHAN_KEY（去 sct.ftqq.com 申请）
```

或手动在 `.env` 中添加：

```bash
SERVER_CHAN_KEY=SCTxxxxxxxxxxxxxxxxxxxxxxxx
WEB_BASE_URL=http://192.168.1.100:8765
```

### Step 2：添加自定义告警

```bash
# 价格告警：贵州茅台跌破 1600 提醒
uv run mommy watchlist add-alert 600519 --rule "price <= 1600" --severity warning

# 涨跌幅告警：TCL中环涨超 5% 提醒
uv run mommy watchlist add-alert 002129 --rule "change_pct >= 5" --severity info
```

### Step 3：启动监控

```bash
# CLI 监控（每 30 秒轮询）
uv run mommy monitor run --interval 30

# 或启动 Web 服务（后台自动监控 + 推送）
uv run mommy web
```

### 告警效果

微信收到的推送消息：

```
ℹ️ [INFO] TCL中环(002129)
  触发规则: 涨幅 ≥ 5%
  当前涨幅: +5.32%
  时间: 2026-07-10 10:35:22
  → 查看 K 线
```

### 内置告警规则（7 条）

| 规则 | 触发条件 | 严重度 |
|------|----------|--------|
| 涨幅超 5% | change_pct >= 5 | INFO |
| 跌幅超 5% | change_pct <= -5 | WARNING |
| 涨幅超 9% | change_pct >= 9 | WARNING |
| 跌幅超 9% | change_pct <= -9 | WARNING |
| 主力流入放大 | money_flow_ratio >= 3% | WARNING |
| 成交量放大 | volume > 2× avg | INFO |
| 价格突破告警线 | 自定义 | 自定义 |

> **推送频率控制**：同一只股票 + 同一条规则 + 当天只推送一次（自动去重）。

---

## 场景九：Web UI 日常使用

### 你的需求

你想用手机在沙发上查看行情和 AI 对话。

### 启动

```bash
uv run mommy web --port 8765
# 或 Docker: docker compose up -d
```

### 页面一览

| 页面 | 用途 | 移动端入口 |
|------|------|-----------|
| **首页** | 指数 + 自选股 + 持仓 + 信号一览 | 底部 Tab "首页" |
| **行情** | 全市场报价，支持搜索 | 底部 Tab "行情" |
| **主题** | 半导体/创新药/机器人等产业链 | 从首页进入 |
| **持仓** | 持仓明细 + 盈亏分析 | 底部 Tab "持仓" |
| **AI 对话** | 自然语言聊天 + 工具调用可视化 | 底部 Tab "问" |
| **信号** | 历史告警记录 | 底部 Tab "信号" |
| **个股详情** | K 线图 + 资金流 + 基本面 | 点击股票进入 |

### AI 对话页面交互

1. **快速提问**：底部有 7 个预设问题药丸（"今天怎么样？"、"分析持仓"等），点击即发送
2. **工作流匹配**：命中工作流时显示 ⚡ 标记 + 步骤进度
3. **工具调用**：可折叠区域显示调用了哪些工具
4. **连接状态**：标题旁的小圆点（🟢 已连接 / 🟡 待命 / 🔴 已断开）
5. **失败重试**：网络问题时出现"重试"按钮，自动重发上次消息

### API 接口（给你的 AI agent 用）

Web 服务暴露 RESTful API，你的 AI agent 可以直接调用：

```bash
# 查询行情
curl http://localhost:8765/api/quotes/688981

# 获取板块排行
curl http://localhost:8765/api/market/sectors

# 查询持仓
curl http://localhost:8765/api/portfolio

# AI 聊天（非流式）
curl -X POST http://localhost:8765/api/agent/chat \
  -H "Content-Type: application/json" \
  -d '{"message": "分析一下比亚迪"}'

# 路由匹配检测
curl -X POST http://localhost:8765/api/agent/route \
  -H "Content-Type: application/json" \
  -d '{"message": "今天怎么样"}'
```

WebSocket 接口：

```javascript
// 实时行情
const ws = new WebSocket('ws://localhost:8765/ws/quotes')

// AI 流式对话
const ws = new WebSocket('ws://localhost:8765/ws/agent')
ws.onopen = () => ws.send(JSON.stringify({ message: '今天怎么样' }))
ws.onmessage = (e) => {
  const msg = JSON.parse(e.data)
  if (msg.type === 'chunk') console.log(msg.text)  // 流式文本
  if (msg.type === 'done') console.log('完成')      // 工具调用信息在 msg.tools_used
}
```

---

## 场景十：TUI 终端工作台

### 你的需求

你是高级用户，想在终端里同时看数据和对话，不想开浏览器。

### 启动

```bash
uv run mommy tui
```

### 两种模式（Tab 键切换）

**模式 A：AI 对话**

- Markdown 流式渲染
- 工具调用折叠面板
- 底部输入框，自然语言提问

**模式 B：数据看板**

- TabbedContent：自选股 / 持仓 / 主题 / 信号
- 状态栏显示：连接状态 + 时间
- 直接调用内部 adapter（不走 HTTP，响应更快）

---

## 场景十一：AI Agent 自动化操作

### 你的需求

你是另一个 AI agent（如 Claude Desktop），想通过 MCP 协议接入 mommy-chaogu 的数据能力。

### MCP Server

```bash
# 启动 MCP Server（stdio 协议）
uv run mommy mcp
```

在 Claude Desktop 的配置文件中添加：

```json
{
  "mcpServers": {
    "mommy-chaogu": {
      "command": "uv",
      "args": ["run", "mommy-mcp"],
      "cwd": "/path/to/mommy-chaogu"
    }
  }
}
```

接入后，Claude 可以：
- 查询 A 股实时行情
- 分析资金流
- 获取基本面数据
- 查看历史记忆和预测
- 管理自选股和告警

### 通过 API 自动化

你的脚本也可以通过 Python 模块直接调用：

```python
from mommy_chaogu.cache import CachedMarketDataAdapter, CacheStore
from mommy_chaogu.market_data import EfinanceAdapter, FallbackAdapter, TencentAdapter
from mommy_chaogu.db_paths import MARKET_DB

# 构建数据适配器
adapter = CachedMarketDataAdapter(
    FallbackAdapter([EfinanceAdapter(), TencentAdapter()]),
    CacheStore(MARKET_DB),
)

# 查询报价
quote = adapter.get_quote("688981")
print(f"中芯国际: {quote.price} ({quote.change_pct:+.2f}%)")

# 查看数据来源
print(f"数据来源: {adapter.format_source_label()}")  # "东方财富 实时" 或 "本地缓存"
```

---

## 附录：完整命令速查

### 自然语言入口

```bash
mommy                           # 交互式 REPL
mommy "今天怎么样"               # 单次自然语言查询
mommy -v "分析 600519"          # --verbose 显示工具调用详情
mommy --setup                   # 首次配置引导
```

### 结构化子命令

```bash
# 自选股管理
mommy watchlist add 600519 --group 白酒
mommy watchlist list --by-group
mommy watchlist groups
mommy watchlist stats

# 行情监控
mommy monitor snapshot          # 一次性快照
mommy monitor run --interval 30 # 持续监控

# 缓存管理
mommy cache stats               # 命中率 + 覆盖率
mommy cache warmup              # 预热全市场
mommy cache refresh             # 刷新缓存

# 资金流
mommy flows pull                # 拉取资金流
mommy flows top --direction in  # 主力流入排行
mommy flows show 688981         # 单股资金流
mommy flows report              # 收盘日报

# 记忆系统
mommy memory stats              # 记忆统计
mommy memory events             # 近期事件
mommy memory predictions        # 预测记录
mommy memory knowledge          # 语义知识
mommy memory history            # 对话历史

# AI Agent
mommy agent "你的问题"          # 单次对话
mommy agent tools               # 列出工具

# 其他
mommy web --port 8765           # Web UI
mommy tui                       # 终端 UI
mommy semicon list              # 半导体产业链
mommy report render             # HTML 报告
```

### LLM Provider 切换

```bash
# 临时切换（环境变量）
AGENT_PROVIDER=zai uv run mommy "今天怎么样"

# 永久切换（.env 文件）
# 编辑 .env: AGENT_PROVIDER=zai
# 确保对应的 key 已填入: ZAI_API_KEY=xxx

# 重新运行配置向导
uv run mommy --setup
```

### 数据库位置

| 数据库 | 路径 | 环境变量覆盖 |
|--------|------|-------------|
| market | `data/market.db` | `MOMMY_MARKET_DB` |
| portfolio | `data/portfolio.db` | `MOMMY_PORTFOLIO_DB` |
| agent | `data/agent.db` | `MOMMY_AGENT_DB` |
| reference | `data/reference.db` | `MOMMY_REFERENCE_DB` |

---

> 💡 **有问题？** [提 Issue](https://github.com/coffee-man666/mommy-chaogu/issues) 或 [发起 Discussion](https://github.com/coffee-man666/mommy-chaogu/discussions)。
>
> ⚠️ **免责声明**：本项目仅供学习和个人投资参考，不构成任何投资建议。A 股投资有风险，入市需谨慎。
