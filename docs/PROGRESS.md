# 进度总结 (PROGRESS.md)

> mommy-chaogu 当前在哪个位置？**做完什么**、**还差什么**、**接下来做什么**。

最后更新：2026-07-01 18:45

---

## TL;DR

| 维度 | 状态 |
|---|---|
| 项目阶段 | **M6.x 完成（cron 修复 + reports 结构化 + supply_chains 数据资产）** |
| 代码量 | **~14,200+ 行**（Python src 9300 + tests 2400 + web 2500） |
| 测试 | **125+ 个**（119 离线通过 + 6 实时网络） |
| 供应链数据资产 | **3 个 JSON**（机器人 25 / 半导体 106 / 材料 41， 总计 172 只） |
| 数据报告 | 10+ 条实战推送（hub SQLite 留底） |
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

> 📅 2026-07-01 18:45 更新：M6.x 完成，下面反映的是 7/1 实战后的优先级。

### ✅ 已验证（7/1 实战）
1. **cron 链路实跑** —— 4 个 job 修后于 7/1 8:30 盘前预热成功（拉了 105/106 只半导体资金流，hub 实际收到 webhook）
2. **mommy-hub 联动** —— web 端 三个产业链页面（机器人/半导体/材料）跑通，10+ 条实战报告入 hub SQLite
3. **多板块扫描稳定** —— 妈妈单子 / 机器人 / 半导体 / 材料 / 光模块 / 证券 全部能跑（拉 + 分析 + 推送 hub）

### 🟧 P1 — 该做但没做
1. **GitHub Actions CI**（ruff + mypy + pytest）—— 半小时
2. **pytest -m live 标记** —— 区分离线/网络测试
3. **CI 推 supply_chains JSON 验证** —— 确保供应链数据格式不破
4. **多氟多/联特类「故事+量价背离」」监控规则** —— 避免追高被套
5. **语音版报告集成** —— `say -v Tingting` + m4a 推送微信（7/1 已验证，可集成进 15:30 cron）

### 🟨 P2 — 体验升级
6. **详情页 Tab 化改造**（场景 B — 持仓决策驾驶舱）
7. **PWA 配置**（妈妈加到桌面像 App）
8. **板块榜加轮动热力图**（什么板块在涨）
9. **详情页加「加自选」「加持仓」按钮」（体验闭环）
10. **mommy-hub 产业链详情的筛选 + 导出** —— 可以一键导出 PDF 给妈妈看

### 🟦 P3 — 大件
11. **微信小程序**（基于 web/src 复用，Taro 重新跑）—— 3-5 天
12. **回测引擎**（验证信号规则历史表现）—— 1-2 周
13. **多用户支持**（妈妈 + 丈母娘 + 团长）—— 2-3 天
14. **内网穿透**（Cloudflare Tunnel，0 配置）—— 1 小时

---

## 7/1 实战数据快照

**实时扫盘记录**（2026-07-01 18:45 收尾）

| 场景 | 结果 | 关键发现 |
|---|---|---|
| 盘前预热 8:30 | 105/106 拉成功 | 002549 timeout 12.6s，hub webhook 收到推送（id=2） |
| 盘中扫半导体 10:42 | 82涨/55跌 | 均价 +0.74%，资金 +2.50亿 |
| AI 推理芯片 10:51 | 4 只表现 | 寒武纪 -4.11% 高位调整 |
| 光模块 10:42 | 14 只均价 -2.74% | 联特 +4.75% 异动（主现 0.01亿） |
| 潍柴动力 13:38-15:47 | 5/20/60 日资金流 | **半年机构 -43.17亿** 派发（修正"接盘"误判） |
| 证券 15:47 | 18 只均价 +4.55% | **6 月机构 +12.5亿 龙头建仓** |
| 人形机器人 16:43-17:06 | 25 只均价 +2.38% | 6 强股深挖：雷赛智能「机构 5日 +1.79亿」最稳健 |
| 材料板块 18:24 | 41 只均价 +1.20% | 化工 +3.62% 强， 稀土 -3.17% 弱 |
| 多氟多 18:39 | **60 日 +100%** | **20 日机构 -87.70亿出货** + 5日 +15.75亿 重新进场 |
| 雷赛智能 18:22 | 现价 57.48 | 5/10 日机构 +1.79/+2.40亿 |

**关键观察：**
1. 「**机构 5 日在买 vs 20 日仍在出货**」是市场普遍形态（多氟多 / 雷赛 / 联特 都是）
2. 「**价格已 price in**」是主要风险——多氟多 60 日 +100% / 250 日 +408%
3. 「**量价背离 -0.5 以下**」是另一重要信号（多氟多 10 日 -0.48）
4. 「**半年数据是真相，5 日数据是噪声**」—— 潍柴 5 日看似"接盘"实为 -43亿派发

---

## 7/1 产出的 3 个新数据资产

| 文件 | 内容 | 状态 |
|---|---|---|
| `data/supply_chains/humanoid_robot.json` | 25 只人形机器人供应链 | 本次 commit 追踪 |
| `data/supply_chains/semiconductor.json` | 106 只半导体产业链 | 本次 commit 追踪 |
| `data/supply_chains/materials.json` | 41 只材料板块（含 10 子类）| 本次 commit 追踪 |

**复用方式：**
```python
import json
data = json.loads(Path('data/supply_chains/semiconductor.json').read_text())
for s in data['stocks']:
    print(s['code'], s['name'], s['change_pct'])
```

**Mommy-hub 同步：** `~/Git/mommy-hub/data/chains/*.json` 同步保留，hub 3 个产业链页面直接读。


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