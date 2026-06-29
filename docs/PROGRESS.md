# 进度总结 (PROGRESS.md)

> mommy-chaogu 当前在哪个位置？**做完什么**、**还差什么**、**接下来做什么**。

最后更新：2026-06-28 22:45

---

## TL;DR

| 维度 | 状态 |
|---|---|
| 项目阶段 | **M5.3 完成（cron 自动化）+ PROJECT-LOG 总览上线** |
| 代码量 | **~14,000+ 行**（Python src 9300 + tests 2400 + web 2500） |
| 测试 | **154+ 个**（145 离线通过 + 9 实时网络） |
| 代码质量 | ruff ✅ / mypy strict ✅ 0 errors |
| 文档 | DESIGN / **PROJECT-LOG** / LEDGER / PROGRESS / KLINE-SPEC / DISCUSSION-NOTES **6 份齐** |
| 自动化 | **4 个 OpenClaw cron jobs**（盘前/盘中/收盘/周报） |
| **实战验证** | ✅ 妈妈已能用 Web + 资金流 ratio 监控跑通 + 明天第一次自动推送 |

---

## 当前架构总览

```
              📱 妈妈手机                📱 妈妈微信（Server酱³）
              Web 主动看                      ↑ 被动收
                    ↑                          │
                    │ HTTP/WS                  │ POST https://sctapi.ftqq.com/{key}.send
                    │                          │
        ┌─────────────────────────────┐        │
        │  Vite-built 静态文件         │        │
        └────────────┬────────────────┘        │
                     ↓                          │
        ┌─────────────────────────────┐        │
        │  FastAPI (uvicorn :8000)    │        │
        │  ├─ /api/* REST (20+ 端点)  │        │
        │  ├─ /ws/* WebSocket          │        │
        │  └─ 后台轮询（5s）+ WS 广播  │        │
        └────────────┬────────────────┘        │
                     ↓                          │
        ┌─────────────────────────────┐        │
        │  BackgroundService          │────────┘
        │  ├─ snapshot + signals      │
        │  └─ SignalNotifier          │ ← 推送：阈值过滤 + JSON 去重 + 微信
        └────────────┬────────────────┘
                     ↓
        ┌─────────────────────────────┐
        │  CachedMarketDataAdapter    │
        │  ↓                           │
        │  FallbackAdapter            │
        │  ├─ EfinanceAdapter (主)     │
        │  └─ TencentAdapter  (备)     │
        └─────────────────────────────┘
                     + 东方财富 push2.eastmoney.com 直连
                       （大盘指数 / 板块排行 / 龙虎榜）
```

---

## 已完成的里程碑

### ✅ 数据层（M0–M2.5，5 个 milestone）
| ID | commit | 标题 | 行数 |
|---|---|---|---|
| M0 | `dc8fd33` | 通用行情数据层 + efinance 适配器 | ~800 |
| M1 | `dac4f8d` | 自选池 + 实时监控 | ~800 |
| M1.5 | `2a44ed8` | 7 条内置告警规则 + Alerter | ~900 |
| M2 | `30fad29` | 时间戳驱动缓存 + 装饰器 | ~1900 |
| M2.5 | `1910bc1` | TencentAdapter + FallbackAdapter（凌晨实战） | ~850 |

### ✅ Web UI（M3.0，4 个 commit）
| commit | 标题 | 内容 |
|---|---|---|
| `ee4170b` | FastAPI 后端 + WebSocket | 14 REST 端点 + 2 WS + 后台轮询 + 依赖注入 |
| `eb23fe5` | Vite + Vue 3 切换 + 4 页通过实测 | 切换到 Vite，15 分钟跑通 K 线 + 盘口 |
| `22f4e8b` | UI 优化 for 妈妈 | 5档盘口修色 + 大字号 + 骨架屏 + 信号跳转 |

### ✅ 推送（M3.1）
| commit | 标题 |
|---|---|
| `3402e19` | Server酱 微信推送 + JSON 文件去重 |

### ✅ 持仓管理 + 语音录入 + 资金流图表 + 盘面扫描（M4, 2026-06-28）
| 主题 | 内容 |
|---|---|
| **持仓管理** | Position + PositionAdjustment 表 / PortfolioStore / 6 个 API 端点 / 加权平均成本 / 实时盈亏计算 |
| **语音录入** | useSpeechRecognition composable（webkitSpeechRecognition）/ 自然语言解析（"茅台买入价1680 100股"）/ 弹窗录入 |
| **资金流图表** | 5 维累计卡片 + 日内分时 SVG 折线 + 历史柱状 SVG（零线居中）/ 7/30/90 天切换 |
| **盘面扫描** | 大盘 6 指数 / 涨幅榜 TOP20 / 跌幅榜 TOP20 / 板块榜 TOP20 / 30 秒轮询 |
| **持仓快览** | 首页持仓条 + 盘面页持仓条联动 |
| **删除盘口** | 详情页盘口信息隐藏（聚焦资金流） |
| **K线 bug 修复** | createIndicator 不判重导致切换周期叠加多张副图 → 用 isFirstInit 标志 |
| **文档** | KLINE-SPEC.md / DISCUSSION-NOTES.md |

---

## 当前功能矩阵（M4）

| 能力 | 数据源 | 缓存 | Web UI | 信号 | 推送 |
|---|---|---|---|---|---|
| 实时报价 | ✅ efin+tencent | ✅ | ✅ 盘面页 + 详情 | ✅ | ✅ ⚠️→🚨 |
| 5 档盘口 | ✅ efin+tencent | ✅ | ❌ 已隐藏 | ❌ | — |
| K 线（日/周/月 + 5/15/30/60 分） | ✅ efinance | ✅ | ✅ klinecharts + MA 均线 + VOL（修 bug 后稳定） | ❌ | — |
| 资金流（日内 + 历史） | ✅ efinance | ✅ | ✅ 累计卡片 + 折线图 + 柱状图 | ✅ | ✅ |
| 全市场快照 | ✅ efinance | ✅ | ✅ 涨幅榜/跌幅榜 | ❌ | — |
| 大盘指数（沪深300等6个） | ✅ 东财 push2 | ❌ | ✅ 指数卡片网格 | ❌ | — |
| 板块涨跌幅榜 | ✅ 东财 push2 | ❌ | ✅ 板块榜 TOP20 | ❌ | — |
| 自选股分组管理 | — | ✅ | ✅ 设置页 CRUD | ❌ | — |
| **持仓管理** | — | ✅ | ✅ 持仓页 + 总览 + 盈亏 | — | — |
| **语音录入持仓** | 浏览器 SpeechRecognition | — | ✅ 语音弹窗 | — | — |
| 信号告警（7 条规则） | — | — | ✅ 信号中心 | ✅ 实时 | ✅ JSON 去重 |
| 数据新鲜度报告 | — | ✅ | ✅ 设置页 | ❌ | — |
| 微信推送（Server酱³） | — | — | ⚠️ 设置页未集成入口 | ✅ 阈值过滤 | ✅ Markdown + 链接 |

🟢 妈妈能用 · 🟡 数据可达未深度集成 · ❌ 未实现

---

## M4 已交付细节

### 后端（~1500 行新增）

#### 持仓管理模块
- `src/mommy_chaogu/portfolio/models.py` — Position + PositionAdjustment 两表
- `src/mommy_chaogu/portfolio/store.py` — PortfolioStore（CRUD + 加权平均成本 + summary）
- `src/mommy_chaogu/web/routes/portfolio.py` — 6 个端点
- 6 个 Pydantic schemas + mappers

#### 资金流增强
- `routes/quotes.py` 改 `money_flow/today` 为 dict（含 cumulative）
- 新增 `money_flow/history?days=N` 端点
- 修复缓存层 `store.get_money_flow_history` bug（dict/list 类型混淆）

#### 盘面排行模块
- `src/mommy_chaogu/market_data/rankings.py` — 直连东财 push2
  - `fetch_indexes()` — 6 个大盘指数
  - `fetch_sector_ranking()` — 行业+概念板块合并去重
- `src/mommy_chaogu/web/routes/market.py` — 4 个端点
  - `GET /api/market/indexes`
  - `GET /api/market/sectors?limit=30`
  - `GET /api/market/gainers?limit=20`
  - `GET /api/market/losers?limit=20`

### 前端

#### 新增文件
- `web/src/composables/useSpeechRecognition.ts` — 语音识别 composable
- `web/src/api/market.ts` — 盘面 API client
- `web/src/api/portfolio.ts` — 持仓 API client
- `web/src/pages/market/index.vue` — 盘面 Tab（**新的首页**）
- `web/src/pages/portfolio/index.vue` — 持仓 Tab

#### 改造文件
- `web/src/router/index.ts` — 路由：index.vue → market/index.vue
- `web/src/App.vue` — 底部 Tab 加「💰 持仓」
- `web/src/pages/index/index.vue` → 删除（被 market 取代）
- `web/src/pages/detail/index.vue`
  - 删除盘口信息
  - 资金流改 SVG 图表（折线 + 柱状）
  - 用 computed 替代 function（修复响应式 bug）
- `web/src/api/types.ts` — 加 IndexQuote / SectorQuote / RankingQuote / Position / MoneyFlow

---

## 测试覆盖

```
src/mommy_chaogu/market_data/    13 dataclass + 11 efinance + 17 tencent (含 4 fallback 场景)
src/mommy_chaogu/watchlist/       17 CRUD
src/mommy_chaogu/monitor/         10 轮询（Mock adapter）
src/mommy_chaogu/signals/         31 规则（每条 3-5 case）
src/mommy_chaogu/cache/           26 命中/拉新/失败/节流/历史/Manager
src/mommy_chaogu/push/            29 server_chan + deduper + notifier
src/mommy_chaogu/portfolio/       ⚠️ TODO — 当前 0 测试，急补
src/mommy_chaogu/web/             ⚠️ TODO — 后端单测
src/mommy_chaogu/market_data/rankings.py  ⚠️ TODO — 排行单测
                              ───
                              154 total（145 离线 + 9 live） + M4 未补
```

- `ruff`: All checks passed
- `mypy --strict`: 0 errors

---

## 已修复的 bug

1. **Decimal vs Money 误判**（mappers.py × 3）
2. **5档盘口颜色反了** → 已隐藏盘口
3. **Taro 4 H5 加载器错位** → 切换到 Vite + Vue 3
4. **FastAPI StaticFiles 抢路由** → 移到最后注册
5. **Naive datetime vs aware** → mappers 自动转 UTC
6. **Server酱 emoji 在标题里 markdown 化** → desp 用 `\n\n` 分段
7. **JSON Decimal 序列化 NaN** → Money/Decimal 一律转 str
8. **today 资金流累计用 sum 而非最后一条**（efinance 返回的是累计值）→ 取 items[-1]
9. **money_flow_cache 缓存层 JSON 反序列化类型错误** → 用 wrapper 存 trade_date
10. **K线 createIndicator 不判重**（切换周期叠加多张 VOL）→ 用 isFirstInit 标志
11. **Vue function 模板调用不响应式**（资金流 SVG NaN）→ 改 computed

---

## 已知限制

| 限制 | 影响 | 何时修 |
|---|---|---|
| Mac mini 内网 IP，妈妈出门不能访问 | 只能在 WiFi 下用 | Cloudflare Tunnel / frp |
| 主力净流入榜没有（数据源限制） | 扫盘缺一个核心维度 | 直连东财 push2 自爬 |
| portfolio / rankings / web 后端单测未补 | 回归风险 | 半天搞定 |
| 没 PWA（不能加桌面） | 每次打开浏览器 | 半小时 |
| 没复盘报告 | 每天收盘后妈妈要自己看 | P1 |
| Server酱 免费版 5 条/天 | 严重信号 >5 时部分丢失 | 升级 VIP 或加钉钉/Telegram |
| 9 个 efinance live 测试偶发挂 | 凌晨东财挂时挂 | `pytest -m live` 标记 |
| 没 CI | 团长看不见我跑没跑测试 | 待加 GitHub Actions |
| 自选股 / 持仓还无法从详情页直接加 | 体验割裂 | 加「加自选」「加持仓」按钮 |

---

## 下一步候选（按团长优先级）

> 📅 2026-06-29 17:30 更新：M5.3 cron 自动化刚上线，等明天（6/30）验证全链路跑通后再重新评估。

### 🔴 验证中 — M5.3 cron
1. **明天（6/30 周二）验证 cron 链路** —— 8:30 预热 / 9:30 启动 / 15:30 推送 / 周六 10:00 周报
2. **观察 15:30 推送内容质量** —— 板块 + TOP 3 + 矛盾股格式是否合适
3. **调 ratio 阈值** —— 跑两天看 5bp/10bp 触发频率，太频繁就调高

### 🟧 P1 — 该做但没做
1. **GitHub Actions CI**（ruff + mypy + pytest）—— 半小时
2. **pytest -m live 标记** —— 区分离线/网络测试
3. **信号日志汇总** —— 每个交易日收盘后统计本日触发了几条 spike/surge
4. **风险提示规则** —— 涨停/跌停/异动 → 接到 monitor

### 🟨 P2 — 体验升级
5. **详情页 Tab 化改造**（场景 B — 持仓决策驾驶舱）
6. **PWA 配置**（妈妈加到桌面像 App）
7. **板块榜加轮动热力图**（什么板块在涨）
8. **详情页加「加自选」「加持仓」按钮」（体验闭环）

### 🟦 P3 — 大件
9. **微信小程序**（基于 web/src 复用，Taro 重新跑）—— 3-5 天
10. **回测引擎**（验证信号规则历史表现）—— 1-2 周
11. **多用户支持**（妈妈 + 丈母娘 + 团长）—— 2-3 天
12. **内网穿透**（Cloudflare Tunnel，0 配置）—— 1 小时

---

## 团长的话（产品方向）

团长在 2026-06-28 微信对话中明确指出：

> **核心定位**：用本地可编程主机能力，做一款**比券商 APP 更聚焦、更快、更主动**的行情陪伴工具。

**核心痛点**：
- 信息太多 → 单一屏幕只展示关心的数据
- 操作太复杂 → 一步到位
- 延迟高 → 本地直连 + 5 秒轮询

**两大场景**：
- **场景 A：观察盘面（发现新机会）** —— 已交付（盘面 Tab）
- **场景 B：管理仓位（细节决策）** —— 进行中（详情页驾驶舱待做）

> 完整讨论：`docs/DISCUSSION-NOTES.md`

---

## 相关文档

- `docs/DESIGN.md` — 架构 + 5 份 ADR
- `docs/LEDGER.md` — 逐条时间线（commit 级别）
- `docs/KLINE-SPEC.md` — K线技术规格
- `docs/DISCUSSION-NOTES.md` — 产品讨论纪要
- `README.md` — 快速上手