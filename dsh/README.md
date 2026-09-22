# mommy-chaogu × DSH 产品嫁接

把 mommy-chaogu 作为**产品**嫁接到 DSH（DeepSeek Harness）web 宿主上：独立
DSH_HOME + 专属 profile，不改宿主一行源码，全部走官方扩展面。参考实现是
dsh-trading monorepo（四面嫁接机制的实证出处）。

```
快速上手（仓库内）
  pnpm -C dsh install && pnpm -C dsh build   # 构建浏览器半 + host 半
  pnpm -C dsh typecheck && pnpm -C dsh test  # 类型门禁 + 进程内单测
  uv run mommy dsh install                   # 落 profile + 覆盖行 + Skills
  uv run mommy dsh doctor                    # 逐项体检
  uv run mommy dsh run                       # DSH_HOME=<数据目录>/dsh-home dsh --profile mommy
```

## 架构：Python 内核 + TS 薄壳

mommy 的全部价值在 Python 侧（四库布局、Decimal 纪律、数据源适配、37 个 MCP
工具）；`dsh/` 子工程的 TS 代码只做嫁接机制——patch 行、审批闸门、HTTP 桥、
浏览器 UI slot——**任何市场计算逻辑不得落到 TS 侧**（GUI 壳可替换，数据契约
不可替换）。

工具面走 MCP（五个宿主共用同一份代码），数据面走 CLI JSON（`mommy watchlist
list --json` / `mommy quote ...`，CLI 是工具箱的稳定契约），浏览器半经 node 半
`/mommy/api` 同源桥取数（宿主认证栅栏内）。

## 四面机制（全部真机验证于 DSH 0.1.5-rc 系）

| 面 | 交付物 | 机制 |
|---|---|---|
| 1 Profile+bundle patch | `cordis.patch.yml`（6 行：gate/preset-installer/mcp/client/bridge + agent-presets 覆盖行） | `dsh.profile.bundles` 层序组合；同 id 覆盖行 config 全键 restate |
| 2 Agent preset | `assets/preset/mommy-investor/`（persona + 技能目录行） | boot 时幂等自安装到 `<数据目录>/dsh-presets`；托管 hash，用户改过的文件永不覆盖 |
| 3 审批闸门 | `src/gate.ts` | `tools/pre-execute` waterfall 只 ask 不 allow；判定表逐条移植 `agent/service.py` 的 requires_confirmation；headless 无审批者自动 deny（fail-closed 白送） |
| 4 前端 | `src/client/`（13 张 toolview 富卡片 + 右缘自选停靠（固定吸附、可收起为右缘垂直拉手，不做自由拖拽/浮动药丸） + 停靠设置菜单）+ `src/bridge.ts`（HTTP/SSE） | 三段 CJS 模块包裹 + 构建期纯度门禁 + CSS Modules 内联；`shell.overlay` / `tool.call.toolview` 官方 slot |

发送链路看门狗（2026-09-18）：宿主一元 RPC（POST `/api/*`，信封
`{"type":"client-request"}`）无 deadline，传输挂起时用户消息三重静默丢失
（气泡滞留 / 无 promptError 横幅 / 宿主零痕迹，GUI 实测复现两次）。客户端
boot 时包装 `fetch`，按信封精确识别一元请求，30s 无响应展示可操作提醒横幅
（不 abort、零干扰，迟到结算自动撤横幅）——`src/client/sendWatchdog.ts`，
`test/sendWatchdog.test.ts` 钉判定与判死/结算语义。

浏览器配置（2026-09-17）：停靠面板头部 ⚙ 菜单可切 get_bars 卡渲染模式——`table`（迷你表，
历史行为）/ `svg`（自绘蜡烛 + 服务端 MA 折线，零依赖默认）/ `lwc`（Lightweight-Charts 交互图，
整包内联使 client.js 升至 ~85KB gzip，`test/clientBundleSize.test.ts` 钉 90KB 预算）。停靠位置契约（同日重设计）：固定右缘满高面板，唯一持久化是展开/收起
（`localStorage(mommy.dock.v2)` 只存 collapsed；v1 自由坐标语义废弃）。
配置存
`localStorage(mommy.client.config.v1)`，只放展示偏好；行情口径唯一真相源仍是服务端工具参数，
三种模式均不落任何指标计算（MA 一律来自服务端 `ma_<w>` 字段）。

MCP 工具在宿主里的公开名是 `mcp__mommy-chaogu__<rawName>`——闸门与卡片 key
都按这个词法。写工具 7 个（strategy_save / strategy_archive /
strategy_activate_monitor / manage_watchlist{add,remove} / manage_alert{add,remove}
/ backfill_history 除外恒确认的三件套按动作判定）过闸门；读工具不打扰。

## 能力覆盖（四星提升后）

- **技术分析**：`check_kline_signal` 均线窗口可参数化（fast/slow，默认 5/20）；
  `get_bars` 支持 `include_ma`（MA 序列**服务端**计算，浏览器只渲染）+ 迷你表卡
  MA 列 + 信号卡；basket-analysis / market-watch-loop 两个分析 Skill 随产品安装
  （`PRODUCT_SKILL_NAMES` 五件套）。
- **回测**：`run_backtest` 工具域（flow_in_spike 信号回放，净成本口径 + caveats
  前置的探索性评估语义）market-only 发布；回测指标卡（信号数/胜率/净收益/回撤/
  Sharpe + caveats 提示）。
- **记忆**：相似历史事件检索卡（search_similar_events）+ 研究结论写入回执卡
  （record_research_conclusion 三态：saved / 待确认 / 跳过）。
- **数据流**：历史资金流趋势卡（get_money_flow_history）+ 主力净流入筛选卡
  （screen_inflow_stocks）补齐历史维度。

## 承重纪律（违反会炸启动或在 review 被拍回）

- **patch 顶层必须是 YAML 数组**；insert 行 id 全生态唯一（`mommy-chaogu-*`）。
- **client 行指向包根**：宿主 `exactPackageSpecifier` 对 scoped 包只认裸包名，
  子路径行永远不是 client row；root 入口 = 空 apply host 半，浏览器半由
  `dsh.client` 声明经 `__DSH_BOOT__` 扫描发现。
- **cordis `ctx.effect(fn)` = 立即执行 fn、fn 返回值即清理函数**——副作用必须
  在 effect 体内发起并返回注销器（`effect(() => webServer.register(route))`），
  写成 `effect(() => dispose())` 会注册完立刻反注册（真机踩过）。
- **覆盖行 config 全键 restate**：agent-presets 覆盖行必须带全
  default/roots/includeShippedRoot/includeUserRoot。
- **安装闭包 + file: 副本刷新**：patch 行引用的每个包进 bundle dependencies；
  pnpm 对 file: 依赖按 lockfile 缓存，产物更新后安装器先删 profile 内旧副本再
  install（`_install_profile_node_modules`）。
- **桥子进程显式钉 `MOMMY_DATA_DIR`**：cwd 继承自宿主进程，不钉住会解析错库。
- **宿主服务鸭式最小面**（`src/types.ts` / `src/client/types.ts`）：不对宿主
  包产生构建期依赖；浏览器数据一律过 `coerceQuote` 强制转换（原始 snake_case
  字典直接渲染会 `undefined.toFixed` 崩掉整个 slot 条目——真机踩过）。
- **DSH pre-1.0 接口漂移**：验证基线 `0.1.5-rc.2`（`PRODUCT_TESTED_DSH_VERSION`）；
  升级宿主后重跑 `pnpm -C dsh test` + 真机四步验收。

## 真机验收手法（改完必跑）

1. `uv run mommy dsh install` → `dsh --profile mommy --dump-config`：确认
   mommy 六行 + 四条覆盖行（绝对路径）出现在组合树；
2. 启动宿主，看 boot 日志出现 `mommy-chaogu MCP server started`（工具面）；
3. cookie 认证后 curl `/mommy/api/watchlist|quotes|events`（数据面 + SSE）；
4. 浏览器打开 tokenized URL：DOM 里 `data-mommy-dock` 存在、console 无错；
   CDP 抓 console 的脚本见本 README 历史验收记录（`/tmp/cdp-dock.mjs` 模式）。

## mommy CLI 新数据面

```
mommy watchlist list --json        # [{code,name,group,note}]
mommy quote 600519 AAPL ^GSPC      # {source, quotes:[get_quotes 同形状]}
```

`mommy dsh install|uninstall|doctor|run` 为产品模式入口；增强模式
（`mommy connect dsh`，往用户 ~/.dsh 合并 MCP 行）与产品模式互补共存。
