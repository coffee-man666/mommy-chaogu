# Web UI 设计方案（提案）

> 给妈妈用的 Web 界面。妈妈不用 CLI，手机打开就能看行情、收信号。

状态：**提案**（等团长确认）
日期：2026-06-27

---

## 1. 核心约束

| 约束 | 影响 |
|---|---|
| 妈妈用**手机**看 | 必须 mobile-first，字大、色显、一屏能看完 |
| 妈妈**不会装 App** | 不能是原生 App，只能是网页（最好 PWA 可加桌面） |
| 妈妈通过**微信**打开 | URL 分享友好，不能要求登录（或微信 OAuth） |
| 实时性要求 | 行情 3-5s 刷新（不是逐笔），信号触发秒级推送 |
| 单用户（妈妈）为主 | 不需要复杂的权限系统，但预留多用户接口 |

## 2. 技术栈选型

### 推荐：FastAPI + Vue 3 + Vite

| 层 | 选型 | 原因 |
|---|---|---|
| **后端** | **FastAPI** | 异步、自带 OpenAPI docs、和现有 SQLAlchemy 2.0 async 天然集成 |
| **前端** | **Vue 3 + Vite** | 响应式、轻量、移动端友好、可做 PWA（妈妈加到桌面像 App） |
| **实时通信** | **WebSocket** | 行情推送 / 信号推送（比轮询省流量） |
| **图表** | **ECharts**（Vue wrapper） | A 股 K 线、资金流柱状图、中国人最熟的图表库 |
| **部署** | **uvicorn + nginx**（Mac mini 本地）| 跑在团长 Mac mini 上，妈妈手机访问局域网或内网穿透 |

### 为什么不选其他方案

| 方案 | 否掉原因 |
|---|---|
| Streamlit | 不够灵活，mobile 体验差，不适合做产品级 UI |
| HTMX + Jinja2 | 简单但难做实时行情推送（WebSocket 麻烦） |
| React | 团长项目偏 Python，Vue 学习曲线更平，够用 |
| Next.js / Nuxt | SSR 太重，单用户场景不需要 SSR |

## 3. 功能范围（M3 系列）

### M3.0 — 最小可用版（MVP）

目标：**妈妈手机打开就能看自选股行情 + 收信号**

```
页面：
├── 📊 首页（Dashboard）
│   ├── 自选股实时行情表（现价/涨跌/涨跌幅/主力净流入）
│   ├── 大盘指数摘要（上证/深证/创业板）— 后台拉全市场时顺手提取
│   ├── 涨跌统计（↑N ↓N 平N + 主力净流入合计）
│   └── 最近信号（最新 3 条，红/黄/绿颜色编码）
│
├── 📈 单股详情
│   ├── 实时报价 + 5 档盘口
│   ├── K 线图（日 K / 分时，ECharts）
│   └── 当日资金流（主力/超大单/大单/中单/小单）
│
├── 🔔 信号中心
│   └── 历史信号列表（按时间倒序，可按规则筛选）
│
└── ⚙️ 设置
    ├── 自选股管理（增删改分组）
    ├── 规则开关 + 阈值调整
    └── 缓存状态（数据新鲜度报告）
```

### M3.1 — PWA + 推送

- PWA manifest（妈妈加到手机桌面，像 App 一样打开）
- WebSocket 信号推送（前端收到弹通知）
- 离线缓存（上次数据离线可看）

### M3.2 — 增强

- 板块热力图
- 自选股组合盈亏（需录入成本价）
- 日报 / 周报（收盘自动生成 markdown）
- 微信 OAuth 登录（预留多用户）

## 4. 后端架构

### 新增模块

```
src/mommy_chaogu/
├── web/                      # 新增
│   ├── __init__.py
│   ├── app.py                # FastAPI app 工厂
│   ├── deps.py               # 依赖注入（adapter / store / alerter 单例）
│   ├── routes/
│   │   ├── quotes.py         # GET /api/quotes, GET /api/quotes/{code}
│   │   ├── watchlist.py      # CRUD /api/watchlist/*
│   │   ├── signals.py        # GET /api/signals
│   │   ├── cache.py          # GET /api/cache/stats
│   │   └── ws.py             # WS /ws/quotes, WS /ws/signals
│   └── schemas/              # Pydantic v2 响应模型
│       ├── quote.py
│       ├── signal.py
│       └── watchlist.py
├── market_data/              # 不动
├── watchlist/                # 不动
├── monitor/                  # 加一个 async snapshot 函数
├── signals/                  # 不动
├── cache/                    # 不动
└── cli.py                    # 加 mommy-web 子命令
```

### API 设计（RESTful）

| Method | Path | 说明 |
|---|---|---|
| GET | `/api/quotes` | 自选股实时报价列表（走缓存层） |
| GET | `/api/quotes/{code}` | 单股详情（报价 + 盘口 + 资金流） |
| GET | `/api/quotes/{code}/bars` | K 线数据（`?interval=1d&limit=120`） |
| GET | `/api/watchlist` | 自选股列表（带分组） |
| POST | `/api/watchlist/stocks` | 添加自选股 |
| DELETE | `/api/watchlist/stocks/{code}` | 删除自选股 |
| GET | `/api/signals` | 信号历史（`?limit=50&rule=price_change`） |
| GET | `/api/cache/stats` | 缓存命中率 + 数据新鲜度 |
| WS | `/ws/quotes` | 实时报价推送（每 N 秒推一次快照） |
| WS | `/ws/signals` | 信号触发推送（有信号就推） |

### 后台轮询架构

```
                        ┌─────────────────────┐
                        │  Background Poller  │
                        │  (asyncio task)     │
                        │  每 5s → snapshot   │
                        └────────┬────────────┘
                                 │
                    ┌────────────┼────────────┐
                    ↓            ↓            ↓
              ┌──────────┐ ┌──────────┐ ┌──────────┐
              │ WS Hub   │ │ Alerter  │ │ Cache    │
              │ (push)   │ │ (signals)│ │ (store)  │
              └──────────┘ └──────────┘ └──────────┘
                    │            │
                    ↓            ↓
              前端 WebSocket   信号日志 + WS push
```

### 依赖注入

```python
# web/deps.py（伪代码）
def get_adapter() -> MarketDataAdapter:
    """全局单例：CachedMarketDataAdapter(FallbackAdapter([Efinance, Tencent]))"""
    ...

def get_watchlist_store() -> WatchlistStore:
    ...

def get_alerter() -> Alerter:
    ...
```

FastAPI 的 `Depends()` 注入，测试时可以 Mock 替换。

## 5. 前端架构

### 技术栈

```
Vue 3 (Composition API) + Vite + TypeScript
├── Vue Router         # 页面路由
├── Pinia              # 状态管理（极简，比 Vuex 好用）
├── ECharts Vue        # K 线 + 资金流图
├── Vant               # 移动端 UI 组件库（有赞，中文 A 股场景多）
└── vite-plugin-pwa    # PWA 支持
```

### 为什么选 Vant

- **有赞**出品，专门给中文移动电商/金融场景用的 UI 库
- 组件覆盖全：PullRefresh、List、Card、Tab、Dialog、Toast
- 默认就是 mobile-first，不用自己调 CSS
- 中文文档顶级

### 目录结构

```
web/                         # 前端代码（独立目录，不在 src/ 下）
├── package.json
├── vite.config.ts
├── tsconfig.json
├── index.html
├── public/
│   └── manifest.json        # PWA
└── src/
    ├── main.ts
    ├── App.vue
    ├── router/
    │   └── index.ts
    ├── stores/
    │   ├── quotes.ts        # 行情状态
    │   ├── watchlist.ts     # 自选股状态
    │   └── signals.ts       # 信号状态
    ├── api/
    │   ├── client.ts        # axios 实例
    │   ├── quotes.ts
    │   ├── watchlist.ts
    │   └── signals.ts
    ├── composables/
    │   ├── useWebSocket.ts  # WS 连接管理
    │   └── useQuotes.ts     # 行情数据 hook
    ├── views/
    │   ├── Dashboard.vue    # 首页
    │   ├── StockDetail.vue  # 单股详情
    │   ├── Signals.vue      # 信号中心
    │   └── Settings.vue     # 设置
    └── components/
        ├── QuoteTable.vue   # 行情表格
        ├── StockCard.vue    # 单股卡片
        ├── KLineChart.vue   # K 线图
        ├── MoneyFlowChart.vue  # 资金流图
        ├── OrderBook.vue    # 5 档盘口
        ├── SignalItem.vue   # 信号条目
        └── IndexSummary.vue # 大盘指数摘要
```

## 6. 关键设计决策

### WDR-001: 前后端分离 vs 模板渲染

**选前后端分离**（FastAPI + Vue）。
**原因**：
- 实时行情推送（WebSocket）在前后端分离架构下更自然
- Vue 的响应式数据绑定做行情表格刷新体验远好于模板
- 团长未来可能加更多前端交互（组合盈亏图表等）
**代价**：多一个前端构建步骤（但 Vite 极快，热更新 <200ms）

### WDR-002: 轮询 vs WebSocket

**WebSocket 为主**，REST 为辅。
**原因**：
- 行情数据天然是 push 场景（后台拉新 → 推前端）
- WebSocket 比 polling 省流量（妈妈手机 4G 友好）
- 信号推送需要秒级到达
**代价**：WebSocket 连接管理要处理断线重连

### WDR-003: 后台轮询放在哪

**放在 FastAPI 后台 task**（`asyncio.create_task`），不是独立进程。
**原因**：
- 和 FastAPI 同进程，共享 adapter / store 单例
- 不需要额外的进程管理（systemd / supervisor）
- 妈妈不开网页时也可以不轮询（或降频到 30s）
**代价**：FastAPI 进程重启时轮询中断（但 Mac mini 稳定，可接受）

### WDR-004: 部署方式

**Mac mini 本地部署 + 内网穿透**（或 frp / Cloudflare Tunnel）。
**原因**：
- 数据源已经是公开接口，不需要服务器端调
- Mac mini 24/7 在线，电费忽略
- 妈妈手机走内网穿透访问，不走公网
**备选**：如果团长有云服务器，Docker 一键部署。

### WDR-005: 认证

**MVP 不做认证**（局域网直接访问）。
**M3.2**：加微信 OAuth 或简单密码。
**原因**：先跑通核心功能，认证是锦上添花。

## 7. 实施计划

### 阶段 1：后端 API（M3.0-backend）

**工作量**：~1.5 天

| 任务 | 产出 |
|---|---|
| FastAPI app 工厂 + 依赖注入 | `web/app.py`, `web/deps.py` |
| REST: quotes / watchlist / signals / cache | `web/routes/*.py` |
| Pydantic 响应模型 | `web/schemas/*.py` |
| WebSocket: quotes / signals | `web/routes/ws.py` |
| 后台轮询 task | `web/background.py` |
| CLI: `mommy-web` 子命令 | `cli.py` 追加 |
| 单测（Mock adapter） | `tests/test_web/*.py` |

**验收标准**：
- `curl localhost:8000/api/quotes` 返回 JSON
- WebSocket 连接能收到报价推送
- ruff + mypy strict + pytest 全过

### 阶段 2：前端 MVP（M3.0-frontend）

**工作量**：~2-3 天

| 任务 | 产出 |
|---|---|
| Vite + Vue 3 + Vant 项目初始化 | `web/` 目录 |
| 布局 + 路由 | Dashboard / StockDetail / Signals / Settings |
| 行情表格组件（实时刷新） | `QuoteTable.vue` |
| K 线图（ECharts） | `KLineChart.vue` |
| 5 档盘口 + 资金流图 | `OrderBook.vue`, `MoneyFlowChart.vue` |
| 信号列表 | `Signals.vue` |
| 自选股管理（增删） | `Settings.vue` |
| WebSocket 连接 + 断线重连 | `useWebSocket.ts` |
| PWA 配置 | `manifest.json`, service worker |

**验收标准**：
- 手机浏览器打开 → 看到自选股行情
- 点股票 → K 线 + 盘口 + 资金流
- 后台触发信号 → 手机端秒级收到
- 加到桌面 → 像 App 一样打开

### 阶段 3：联调 + 优化（M3.0-polish）

**工作量**：~1 天

- 真实数据联调（东财 + 腾讯 + 缓存层 + WebSocket 全链路）
- Mobile 适配（iPhone / Android 各测一遍）
- 性能优化（首屏加载 <1s，行情刷新延迟 <3s）
- 错误处理（网络断 / 数据源挂时的前端展示）

**总计：~4-5 天**

## 8. 新增依赖

### Python（后端）

```toml
# pyproject.toml [project.optional-dependencies]
web = [
    "fastapi>=0.115",
    "uvicorn[standard]>=0.32",
    "pydantic>=2.9",  # FastAPI 内置，但显式声明版本
    "websockets>=13",  # uvicorn[standard] 已含
]
```

### Node.js（前端）

```json
{
  "dependencies": {
    "vue": "^3.5",
    "vue-router": "^4.4",
    "pinia": "^2.2",
    "vant": "^4.9",
    "echarts": "^5.5",
    "vue-echarts": "^7.0",
    "axios": "^1.7"
  },
  "devDependencies": {
    "vite": "^6.0",
    "@vitejs/plugin-vue": "^5.2",
    "typescript": "^5.6",
    "vite-plugin-pwa": "^0.21"
  }
}
```

## 9. 风险 & 待确认

| 风险 | 缓解 |
|---|---|
| Mac mini 不公网暴露，妈妈外出了怎么办？ | frp / Cloudflare Tunnel 内网穿透（团长有经验吗？） |
| efinance + tencent 都挂了？ | 前端展示「数据源暂时不可用」+ 最后缓存时间 |
| WebSocket 在微信内置浏览器可能不支持 | 降级为 SSE（Server-Sent Events）或 long polling |
| 前端 Node.js 环境 Mac mini 上有没有？ | 需要确认（团长 Mac mini 装了 Node.js 吗？） |

## 10. 团长确认点

在动手之前，请确认：

1. **技术栈**：FastAPI + Vue 3 + Vant + ECharts，行不行？
2. **部署**：Mac mini 本地跑，妈妈手机通过内网穿透访问？还是有云服务器？
3. **Node.js**：Mac mini 上有没有 Node.js？（前端构建要用）
4. **范围**：M3.0 MVP 先做这四页（Dashboard / 单股详情 / 信号中心 / 设置），行不行？
5. **优先级**：先做后端 API 还是先搭前端骨架？（我建议先后端，前端有 API 才好联调）
