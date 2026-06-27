# 进度总结 (PROGRESS.md)

> mommy-chaogu 当前在哪个位置？**做完什么**、**还差什么**、**接下来做什么**。

最后更新：2026-06-27 22:35

---

## TL;DR

| 维度 | 状态 |
|---|---|
| 项目阶段 | **M3.1 完成（Server酱 微信推送上线），M3.2 待启动** |
| 代码量 | **~10500 行**（Python src 7300 + tests 2270 + web 2000） |
| 测试 | **154 个**（145 离线通过 + 9 实时网络） |
| 代码质量 | ruff ✅ / mypy strict ✅ 0 errors |
| 文档 | DESIGN / LEDGER / PROGRESS / WEB-UI-PROPOSAL 4 份齐 |
| **实战验证** | ✅ **妈妈今天已能用 Web** — Server酱 推送等团长拿到 SendKey 测 |

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
        │  FastAPI (uvicorn :8765)    │        │
        │  ├─ /api/* REST (14 端点)   │        │
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
```

---

## 已完成的里程碑（git log 全部 10 个 commit）

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
| `8c9e38f` | Taro + Vue 3 + klinecharts（实验性，**已放弃**） | 踩坑：webpack 5.91 不兼容 / 加载器错位 / router 找不到页面实例 |
| `eb23fe5` | **Vite + Vue 3 切换 + 4 页通过实测** | 切换到 Vite，15 分钟跑通 K 线 + 盘口 |
| `22f4e8b` | UI 优化 for 妈妈 | 5档盘口修色 + 大字号 + 骨架屏 + 信号跳转 |

### ✅ 推送（M3.1，1 个 commit）
| commit | 标题 | 内容 |
|---|---|---|
| `3402e19` | **Server酱 微信推送 + JSON 文件去重** | Pusher/Deduper Protocol + 严重度阈值 + 集成 BackgroundService + 29 个单测 |

---

## 当前功能矩阵（M3.1）

| 能力 | 数据源 | 缓存 | Web UI | 信号 | 推送 |
|---|---|---|---|---|---|
| 实时报价 | ✅ efin+tencent | ✅ | ✅ 首页 + 详情 | ✅ | ✅ ⚠️→🚨 |
| 5 档盘口 | ✅ efin+tencent | ✅ | ✅ 详情页（卖=红 买=绿） | ❌ | — |
| K 线（日/周/月 + 5/15/30/60 分） | ✅ efinance | ✅ | ✅ klinecharts + MA 均线 | ❌ | — |
| 资金流（当日 + 历史） | ✅ efinance | ✅ | ⚠️ 仅显示主力净流入 | ✅ 主力阈值 | ✅ |
| 全市场快照 | ✅ efinance | ✅ | ⚠️ 自选股用 | ❌ | — |
| 自选股分组管理 | — | ✅ | ✅ 设置页 CRUD | ❌ | — |
| 信号告警（7 条规则） | — | — | ✅ 信号中心（可点击跳转） | ✅ 实时 | ✅ JSON 去重 |
| 数据新鲜度报告 | — | ✅ | ✅ 设置页 | ❌ | — |
| **微信推送（Server酱³）** | — | — | ⚠️ 设置页未集成入口 | ✅ 阈值过滤 | ✅ Markdown + 链接 |

🟢 妈妈能用 · 🟡 数据可达未深度集成 · ❌ 未实现

---

## M3.0 已交付（Web UI MVP）

### 后端（src/mommy_chaogu/web/）
- `app.py` — FastAPI 工厂 + lifespan 管理后台轮询 + notifier 注入
- `deps.py` — 依赖注入（单例 adapter / store / alerter / notifier）
- `background.py` — 单 asyncio task 后台轮询 + WS 广播 + 推送
- `schemas.py` — 14 个 Pydantic 模型（Decimal → str）
- `mappers.py` — dataclass → Pydantic 转换
- `routes/{quotes,watchlist,signals,cache,ws}.py` — 5 个路由文件
- CLI: `mommy-web --port 8765 --poll-interval 3`

### 前端（web/）
- Vite 6 + Vue 3 + TypeScript + vue-router
- 4 个页面 + 1 个 App.vue（带底部 Tab）
- klinecharts 9.8（金融图表专业库）
- API 客户端（5 个模块）+ WebSocket 客户端（断线重连 + 心跳）

### 实测（headless iPhone 14 viewport）
| 页面 | 数据 | K 线 / 盘口 / 信号 |
|---|---|---|
| 首页 | 5 只自选股 + 主力合计 + 涨跌统计 | A 股红涨绿跌 + 主力箭头 + 骨架屏 |
| 详情 | 完整报价 + 11 个数据点 | K 线 + MA5/10/30/60 + VOL MA + 5 档盘口 |
| 信号 | 8 条触发（5 CRIT + 1 WARN + 1 INFO） | 严重度 emoji + 点击跳 K 线 |
| 设置 | 服务状态 + 缓存 + 自选股 CRUD | 刷新按钮 + 缓存命中率 + 删除二次确认 |

---

## M3.1 已交付（Server酱 微信推送）

### 模块（src/mommy_chaogu/push/）
- `base.py` — `Pusher`/`Deduper` Protocol + `SignalNotifier` 顶层封装
  - 默认只推 `WARNING` + `CRITICAL`（INFO 太多刷屏）
  - 失败不致命（异常被吞，下次重试）
- `server_chan.py` — Server酱³ 实现
  - POST `https://sctapi.ftqq.com/{SendKey}.send`
  - 标题带 emoji（🚨 CRIT / ⚠️ WARN / ℹ️ INFO）
  - Markdown desp 含代码 / 时间 / 详情 / 触发值 / 阈值
  - K 线详情链接（拼 `web_base_url + code`）
- `deduper.py` — JSON 文件去重（按日清空）
  - key = `code|rule_id|date`
  - 每天自动清空昨天的（避免无限增长）
  - 原子写（tmp + rename）
  - 损坏文件容错

### 集成
- `BackgroundService` 接受可选 notifier
  - `_tick()` 在信号评估后调用 `notifier.notify_batch()`
  - 记录最近 100 条推送成功的信号（暴露给 API）
  - 推送异常被吞，不影响 WS 广播
- `create_app()` 接受 `server_chan_key` + `web_base_url`
  - 未配置 SendKey → 完全不推送，服务正常
  - 推送初始化失败 → 记日志但继续运行（graceful degradation）

### CLI
```bash
# 方式 1：命令行参数
mommy-web --server-chan-key SCT123xxx --web-base-url https://mommy.example.com

# 方式 2：环境变量（推荐生产）
export SERVER_CHAN_KEY="SCT123xxx"
export WEB_BASE_URL="https://mommy.example.com"
mommy-web --port 8765
```

### 测试（29 个）
- `test_server_chan.py` (10) — 成功/失败/网络异常/JSON 异常/web 链接/严重度 emoji
- `test_deduper.py` (10) — 首推/重推/不同 code/不同 rule/跨日/损坏文件/clear
- `test_notifier.py` (9) — 阈值过滤/去重/失败不标记/异常处理/batch

---

## 测试覆盖

```
src/mommy_chaogu/market_data/    13 dataclass + 11 efinance + 17 tencent (含 4 fallback 场景)
src/mommy_chaogu/watchlist/       17 CRUD
src/mommy_chaogu/monitor/         10 轮询（Mock adapter）
src/mommy_chaogu/signals/         31 规则（每条 3-5 case）
src/mommy_chaogu/cache/           26 命中/拉新/失败/节流/历史/Manager
src/mommy_chaogu/push/            29 server_chan + deduper + notifier  (NEW M3.1)
src/mommy_chaogu/web/             0  (TODO P0 — 后端单测)
                              ───
                              154 total（145 离线 + 9 live）
```

- `ruff`: All checks passed
- `mypy --strict`: 0 errors
- pytest: **154**（145 离线通过 + 9 实时网络）

**后端 web/ 模块还没单测** —— 等团长说补

---

## 已修复的 bug

1. **Decimal vs Money 误判**（mappers.py × 3）—— Bar.open/close、OrderBookLevel.price 是 Decimal 不是 Money
2. **5档盘口颜色反了** —— A 股约定：卖=红 买=绿
3. **Taro 4 H5 加载器错位** —— 切换到 Vite + Vue 3 解决
4. **FastAPI StaticFiles 抢路由** —— 移到最后注册
5. **Naive datetime vs aware** —— mappers 自动转 UTC
6. **Server酱 emoji 在标题里 markdown 化** —— desp 用 `\n\n` 分段 + 一行 trigger value
7. **JSON Decimal 序列化 NaN** —— Money/Decimal 一律转 str

---

## 已知限制

| 限制 | 影响 | 何时修 |
|---|---|---|
| Mac mini 内网 IP，妈妈出门不能访问 | 只能在 WiFi 下用 | 部署 frp / Cloudflare Tunnel |
| 后端 web/ 模块无单测 | 回归风险 | 团长说就补 |
| 没 PWA（不能加桌面） | 每次打开浏览器 | M3.2 加 |
| 没复盘报告 | 每天收盘后妈妈要自己 `mommy-monitor log` 看 | P1 |
| Server酱 免费版 5 条/天 | 严重信号 >5 时部分丢失 | 升级 VIP 或加钉钉/Telegram 双源 |
| 9 个 efinance live 测试偶发挂 | 凌晨东财挂时挂 | `pytest -m live` 标记 |
| 没 CI | 团长看不见我跑没跑测试 | 待加 GitHub Actions |

---

## 下一步候选（按团长优先级）

### 🟥 P0 — 该做但没做
1. **后端 web 单测**（FastAPI 路由 + WebSocket + mappers）—— 1 小时
2. **真实手机 + 微信推送实测** —— 等团长拿到 SendKey 测

### 🟧 P1 — 让妈妈更爽
3. **复盘报告**（收盘后自动生成 markdown）—— 半天
4. **风险提示规则**（涨停板 / 跌停板 / 单股异动）—— 半天
5. **Server酱 多渠道兜底**（加钉钉/Telegram/Bark 防单源挂）—— 1 小时

### 🟨 P2 — 体验升级
6. **CI 配置**（GitHub Actions：ruff + mypy + pytest）—— 半小时
7. **PWA 配置**（妈妈加到桌面像 App）—— 半天
8. **K 线标注**（支撑位 / 压力位 / 黄金分割）—— 1 天
9. **投资组合跟踪**（成本 / 盈亏 / 持仓占比）—— 2-3 天

### 🟦 P3 — 大件
10. **微信小程序**（基于 web/src 复用，Taro 重新跑）—— 3-5 天
11. **回测引擎**（验证信号规则历史表现）—— 1-2 周
12. **多用户支持**（妈妈 + 丈母娘 + 团长）—— 2-3 天
13. **内网穿透**（Cloudflare Tunnel，0 配置）—— 1 小时

---

## 给团长的话

**M3.1 推送已上线（代码完成）**：
- 信号触发 → 自动微信推妈妈
- 免费版 5 条/天，够核心信号用
- 没配置 SendKey 时优雅降级，不影响 Web 服务

**妈妈使用链路**：
1. 信号在行情里触发（主力净流入 > 阈值）
2. BackgroundService 评估 → JSON 去重
3. POST 到 Server酱 → 推微信「妈妈炒股的信号」
4. 妈妈微信里看到 ⚠️🚨 → 点链接看 K 线

**测试步骤**：
```bash
# 1. 注册 Server酱拿 SendKey: https://sct.ftqq.com/
# 2. 设置环境变量
export SERVER_CHAN_KEY="SCT123xxx"
export WEB_BASE_URL="http://192.168.10.84:8765"
# 3. 启动服务
mommy-web --port 8765
# 4. 等 5s 一个 tick，看妈妈微信是否收到
```

**现在最大的 gap 仍是「妈妈在户外看不到」**：
- 内网 IP（已 push 即时解决了一半，但 WiFi 外还是不行）
- 没自动复盘
- 没 CI

建议下一步做 **P1：复盘报告 + 后端 web 单测**——这两个做完，妈妈就真正「躺着用」+ 团长能放心改。

---

## 相关文档

- `docs/DESIGN.md` — 架构 + 5 份 ADR
- `docs/LEDGER.md` — 逐条时间线（commit 级别）
- `docs/WEB-UI-PROPOSAL.md` — Web UI 方案设计（GLM-5.2 vs 我的对比）
- `README.md` — 快速上手