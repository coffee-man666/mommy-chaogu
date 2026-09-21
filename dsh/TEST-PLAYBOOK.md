# DSH 嫁接 GUI 测试手册（含 2026-09-13 完整测试日志）

> 用途：在内置浏览器（IAB）里对 mommy-chaogu × DSH 嫁接做端到端 GUI 回归。
> 本文 = 可复跑的操作手册 + 2026-09-13 的真实测试日志（基线：宿主 0.1.5-rc.2，
> bundle `f661635..91d5d4b` 五件套升级后，dock 可拖拽修复后）。
> 复跑时按 §2 启动环境 → §3 预检 → §5 逐条执行 → §6 对照异常登记表。
> 配套：`AGENT-CHECKLIST.md`——修复批次（doctor 基线/kline 死区/quote source/
> WAL 失效/dock 三缺陷）的前端回归清单，给会操作前端的 Agent 直接执行。

## 1. 覆盖范围

| 域 | 能力 | 测试点 |
|---|---|---|
| 布局 | shell.overlay 停靠 | T1 不遮侧栏 / T6 拖拽·收起·展开·复位 |
| 行情 | get_quote / get_quotes | P1 A股+美股+指数四标的 |
| 指数板块 | get_market_indexes / get_sector_ranking | P2 非交易时段空态 |
| 资金流 | get_money_flow_today / history | P3 当日失败态 + 历史稀疏 |
| K线均线 | get_bars include_ma | T2 10 根窗口 MA5 可算 / MA20 诚实拒绝 |
| 信号 | check_kline_signal | T3 volume_breakout 0 命中诚实上报；P8 fast/slow 金叉参数化 |
| 回测 | run_backtest | T4 caveats 原文展示 + 拒绝张冠李戴 |
| 基本面公告 | get_fundamentals / announcements / check_earnings_catalyst | P4（本轮受阻待复跑） |
| 产业链新闻 | themes / search_news | P5（同上） |
| 美股龙虎榜 | research_us_market / get_longhuban | P6（同上） |
| 筛选 | screen_inflow_stocks | P7（同上） |
| 写操作闸门 | manage_watchlist（personal 档） | 已单独验证：Waiting for approval → Allow once → 落盘 → dock SSE 联动 |

## 2. 环境启动（每次复跑从零开始）

```bash
cd /Users/hanyan/CoffeeMan/mommy-chaogu
pnpm -C dsh build                       # 浏览器半 + host 半，含纯度门禁
pnpm -C dsh test                        # 97 用例
uv run pytest tests/test_dsh_adapter.py -q
uv run mommy dsh install                # 刷新 profile 内 file: 副本 + Skill 五件套
uv run mommy dsh doctor                 # 期望：产品 profile 可用

# 清掉上次残留的僵尸 MCP 服务（见异常 A10）
pkill -f "mommy_chaogu.agent.mcp_server"
pkill -f "dsh --profile mommy"

# 启动（--no-open 必带：不拉起系统浏览器；宿主版本必须钉 rc.2）
export ZAI_API_KEY=$(grep -E "^ZAI_API_KEY=" .env | cut -d= -f2 | tr -d '"')
DSH_HOME=$PWD/data/dsh-home nohup npx -y @deepseek-ai/dsh@0.1.5-rc.2 \
  --profile mommy --no-open > /tmp/dsh-host.log 2>&1 &
sleep 10
grep "MCP server started\|dsh web:" /tmp/dsh-host.log
```

- 浏览器只用内置 IAB，入口 = 日志里的 `http://127.0.0.1:3080/?token=<新token>`。
- 首次进入：关闭 Internal Testing Notice → 选工作区 `dsh-workspace`
  （空目录 `~/.local/share/mommy-chaogu/dsh-workspace`，勿用 mommy 仓库本体）
  → agent 模式选「mommy 投研助手」。
- 宿主 LLM：`data/dsh-home/settings.yaml` 内 zai 自定义 provider
  （glm-5.3-flash，key 走 `ZAI_API_KEY` 环境变量，不落盘）。

## 3. 预检（每次复跑必做，一票否决）

1. `uv run mommy dsh doctor` → 除 dsh_binary 警告（npx 形态，已知）外全 ✅。
2. **MCP 探针**：新会话发一句 `查一下 600519 的最新价格`，回答出现的同时执行
   `grep -c CallToolRequest /tmp/dsh-host.log`。**必须 ≥1**。
   若为 0：模型在无工具状态下作答（看似研究、实则未经验证——最危险形态），
   按异常 A11 处理：彻底重启宿主 + 关闭全部旧标签页 + 全新会话，直至探针通过。
3. dock 探针：页面左侧 `[data-mommy-dock]` 存在且显示 `Watchlist · N`，
   左缘 ≥ 侧栏宽度（不遮挡）。

## 4. 操作手法（IAB 自动化的坑，全部实测）

- **发送消息**：`fill(composer)` → 等 800ms → `press("Enter")`；以「turns 计数 +1」
  判定发出。composer 偶发被重渲染夺焦导致 Enter 落空——发后 10s 检查 turns，
  未 +1 则再按一次 Enter。**禁止用 JS 注入点击**（黑盒纪律）。
- **IAB 合成点击（cua.click）不可靠**：下拉菜单可用；弹窗按钮 / Send / 工具行
  展开组 / Settings / dock 收起按钮会无响应（elementFromPoint 证明元素在最上层
  也不响应）。受阻时如实记录，勿用 JS click 硬撬。
- **AppFrame 横向滚动 bug**（宿主侧，H1）：点 New session 后 frame.scrollLeft
  可能变 466，整屏内容左移出视口。每次导航/新会话后执行
  `frame.scrollLeft = 0`（属环境修复，需在日志声明）。
- **截图**：`tab.screenshot()` 偶发 `capture failed for guest` /
  `surface preparation timed out`——等 1.5~4s 重试；连续失败换新标签页重进；
  整个 guest 退化时以 DOM 快照文字证据替代并在报告标注。
- **长会话上下文混淆**（A7）：同一会话连发不相关请求会被旧话题吞掉。
  每个测试组开新会话，或请求前缀「新话题，和XX无关：」。

## 5. 测试点明细（提示词原文 + 判定标准 + 本次结果）

### T1 布局回归 ✅
- 操作：打开入口 URL，等 4s。
- 判定：`dock.getBoundingClientRect().left >= 侧栏宽度`；截图侧栏完整。
- 本次：288 ≥ 280 ✅（证据 `gui-test-screenshots/t1_initial_layout.png`）。

### T2 均线参数化（get_bars include_ma）✅
- 提示词：`用 get_bars 查 600519 最近 10 根日K，带 5 日和 20 日均线`
- 判定：回答含 MA 数值；MA20 算不出时必须诚实说明窗口不足（服务端均线纪律）。
- 本次：10 根日 K 表 + 「已跌破 MA5（1295.30）」+「20 日均线至少需要 20 根 K 线…
  可以用 limit=40 重新拉」✅（`t2_bars_ma.png`）。

### T3 新工具 check_kline_signal ✅（卡片展开受阻）
- 提示词：`用 check_kline_signal 看 600519 有没有放量上涨信号`
- 判定：工具被调用；结果为空时如实说「0 条命中」，不编造。
- 本次：思考流可见「result is empty — report honestly」；回答「当前没有放量上涨
  （volume_breakout）信号 —— 返回 0 条命中」✅（`t3_kline_signal.png`）。
- 受阻：工具行折叠组无法用合成点击展开（KlineSignalCard 视觉确认留待人工
  点击；逻辑层有 parse 单测 + slot 崩溃处理器零触发兜底）。

### T4 run_backtest ✅
- 提示词：`回测一下 600519 的放量上涨信号，持有 3 天看看历史效果`
- 判定：caveats（市值前视近似 / 只读本地缓存 / 探索性评估）必须原文展示；
  工具不支持 volume_breakout 时必须明说，不得拿 flow_in_spike 结果冒充。
- 本次：全部满足，且模型主动区分「flow_in_spike 不是你问的 volume_breakout…
  我不会假装能做」✅（`t4_backtest_caveats.png`）。0 触发的结构性解读
  （5bp 阈值对 1.6 万亿市值 = 8 亿/日）亦正确。

### P1 批量报价多源 ✅
- 提示词：`新话题，和回测无关：用报价工具同时查 600519、000858、AAPL、^GSPC 四个标的的最新价格，逐个列出`
- 本次：四标的数值全部出现在回答（1275.16 / 69.75 / AAPL / 标普）✅。
  注意首次发送被旧话题吞掉（A7），加话题前缀后成功。

### P2 大盘指数 + 板块排行 ✅（空态诚实）
- 提示词：`再换个话题：看看现在大盘指数怎么样，以及今天 A 股板块涨跌排行前几名`
- 本次（周日非交易时段）：空态被诚实上报（「为空/取不到/没有返回」类表述）✅。

### P3 资金流当日 + 历史 ✅
- 提示词：`再换个话题：600519 今天的资金流情况如何？另外把它最近的资金流历史也拉出来看看`
- 本次：get_money_flow_history / research_money_flow 被调用 ✅。
  已知数据面：当日资金流非交易日查询失败；历史仅缓存 7 月初 3 条（A2/A3）。

### P4 基本面 + 公告 ⏸ 受阻待复跑
- 提示词：`换个话题：查一下 600519 的基本面指标（PE/PB/ROE 这些），再看看它最近有什么公告或业绩催化`
- 判定：get_fundamentals 对 A 股当前返回全空（A4），回答必须如实标注而非编数；
  公告/业绩催化工具正常返回。
- 本次：消息两次进入会话但 agent 回合从未启动（A8），且环境随后进入
  A11（MCP 调用归零）状态，未获得有效回答。

### P5 产业链 + 新闻 / P6 美股 + 龙虎榜 / P7 筛选 / P8 金叉参数化 ⏸ 待复跑
- 提示词备好（复跑直接用）：
  - P5 `半导体产业链里有哪些环节和代表股票？再搜一下最近的半导体新闻`
  - P6 `美股三大指数现在什么情况？今天的 A 股龙虎榜有哪些票？`
  - P7 `用资金流筛选工具看看主力净流入占比超过 50bp 的股票有哪些`
  - P8 `用 check_kline_signal 的均线金叉模式看 600519，5 日线上穿 20 日线`
- 判定要点：P6 龙虎榜非交易日为空需诚实；P8 确认 fast/slow 参数真实传参
  （对回答里出现的均线窗口数字核对）。

### T6 dock 交互 ✅（拖拽）/ ⚠️（收起为合成点击受限）
- 拖拽：`cua.drag` 标题栏 (350,27) → (850,260)：面板移动 + localStorage
  `mommy.dock.v1` 持久化 ✅。
- 收起/展开/双击复位：JS 路径全通；真实 cua 点击 Collapse 按钮在 IAB 环境无响应
  （H3），人工浏览器不受影响。

## 6. 异常登记表（2026-09-13 实测）

| # | 类型 | 现象 | 根因定位 | 严重度 | 规避 |
|---|---|---|---|---|---|
| A1 | 数据 | 指数/板块排行非交易时段返回空 | 上游数据源 | 低 | 模型已诚实上报 ✅ |
| A2 | 数据 | 当日资金流非交易日查询失败 | 上游/时点 | 低 | 模型如实说明 ✅ |
| A3 | 数据 | 历史资金流仅 3 条（7 月初），近两月缺失 | 本地缓存覆盖薄 | 中 | 回填：backfill_history |
| A4 | 数据 | get_fundamentals 对 A 股返回全空（PE 仅报价带） | 基本面源未接 | 中 | 回答须标注「暂缺」，禁编数 |
| A5 | 工具 | run_backtest 仅支持 flow_in_spike | 设计如此 | 低 | 模型已主动区分并拒编 ✅ |
| A6 | 数据 | 10 根窗口 MA20 无法计算 | 服务端均线纪律 | 低 | 提示 limit≥40 重拉 ✅ |
| A7 | 回复 | 长会话中新请求被旧话题吞掉（报价请求被回测回答覆盖） | LLM 上下文混淆 | 中 | 每测试组新会话 / 话题前缀 |
| A8 | 工具链 | 会话接受消息但 agent 回合静默不启动（无 Stop/无报错/无回答），复现 4 次 | ✅ 已定位（2026-09-17，GUI 复现 2 次取证）：宿主一元 RPC 无 deadline，传输挂起时 promise 永不结算；用户气泡是 `beginSubmission` 本地 echo，仅 RPC 报错才退场 → 三重静默丢失。与上游 Discussions #2060 同链（该帖促成 prompt 类 RPC 去 deadline，误杀修复翻转成静默挂起）。此前「疑似 LLM provider 静默失败」系误判 | **高** | ✅ 已修（2026-09-18）：客户端看门狗 `src/client/sendWatchdog.ts`——boot 包装 fetch，按 `{"type":"client-request"}` 信封识别一元请求，30s 无响应展示可操作横幅（不 abort、零干扰，迟到结算自动撤） |
| A9 | 数据源 | eastmoney push2his 连接失败（RemoteDisconnected，重试 3 次耗尽） | 上游拒连（周日？风控？） | 中 | get_bars 走缓存兜底 ✅（拉新失败保留旧数据纪律生效） |
| A10 | 工具链 | **mcp_server 僵尸进程泄漏**：11 个并存，最老 2d20h（每会话孵化一个，断开后不退出） | 宿主不回收 stdio 子进程；server 侧无自愈 | **高** | ✅ 已修（2026-09-13）：空闲看门狗（默认 30 分钟无请求自杀，`MOMMY_MCP_IDLE_TIMEOUT` 可配/0 禁用），见 `src/mommy_chaogu/agent/mcp_server.py` |
| A11 | 工具链 | 明确要求用工具的请求完成但 CallToolRequest=0，模型纯知识作答（数据可信度归零） | 会话级 MCP 连接退化，定位未完成 | **高** | §3 探针一票否决；宿主重启+全新会话 |
| H1 | 宿主 UI | AppFrame 被横向滚动 466px（scrollWidth 1857），整屏左移出视口；右侧 details 面板 814–1391 超视口 111px | 宿主布局 bug | 中 | frame.scrollLeft=0 修复 |
| H2 | 宿主 UI | IAB 合成点击对部分按钮失效（弹窗/Send/Collapse/工具行组/Settings） | IAB↔宿主事件兼容 | 低（自动化） | 真实用户不受影响 |
| H3 | 运行时 | IAB 截图间歇性 `capture failed for guest` | IAB guest 退化 | 低（自动化） | 重试/换标签页/DOM 取证 |

## 7. 复跑清单（copy-paste 顺序）

1. §2 环境启动 → 2. §3 预检（doctor + MCP 探针 + dock 探针）→
3. T1 → T2 → T3 → T4（同一新会话顺序执行，每条之间确认 turns +1）→
4. P1 → P2 → P3（同一会话可继续）→
5. P4 → P5 → P6 → P7 → P8（建议各自新会话，规避 A7）→
6. T6 拖拽/收起（人工点击补视觉确认）→
7. 对照 §6 登记：已知异常复现是否一致，新异常追加编号 →
8. 收尾：`pkill -f "dsh --profile mommy"`，截图归档至 `gui-test-screenshots/`。

## 8. 2026-09-13 结论摘要

- 通过：T1、T2、T3、T4、P1、P2、P3（GUI 操作 + 截图/DOM 双证据，见
  `gui-test-screenshots/`）；写操作闸门链路（personal 档）此前已单独验证通过。
- 受阻：T3 卡片视觉展开、T6 收起（IAB 合成点击限制）；P4–P8（A8/A11 环境退化，
  提示词与判定标准已备好，环境恢复后按 §7 直跑）。
- 需要修的产品级问题：**A10 僵尸 mcp_server 泄漏**、**A8 回合静默不启动**、
  **A11 工具调用归零的会话级退化**（后两者建议在宿主侧加「回合启动失败」的
  可见错误态，静默卡死对投研场景不可接受）。
- 当日修复（mommy 侧四项）：
  - `mommy dsh run` 参数透传：`--no-open` 显式项 + `-- ` 后任意参数直达底层 dsh
    （§2 临时绕过的 `DSH_HOME=... npx ...` 不再需要）；
  - A10 看门狗（见 §6 登记行）；
  - dock 首屏「自选股为空」竞态：根因是 profile patch live-reload 先后——首屏
    fetch 可能落在覆盖行生效前的旧桥（默认数据目录 → 空表）。修复 = SSE 断线
    指数退避重连（1s→30s × 6 次）+ 连接（重）建立时统一重拉并清空 revision
    去重基数（换桥后 revision 从 1 重计，旧基数会吞新信号）；
  - dock 遮挡侧栏：面板默认贴侧栏右缘（frame 内联 gridTemplateColumns 首列 +
    MutationObserver 跟随拖宽/折叠），标题栏可拖拽、双击归位、可收起成药丸，
    localStorage 持久化。
