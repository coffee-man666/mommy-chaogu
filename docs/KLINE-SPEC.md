# K 线技术规格（KLINE-SPEC）

> mommy-chaogu K 线模块完整技术文档
> 最后更新：2026-06-28

---

## 1. 架构总览

```
用户手机浏览器
    │
    │ ① 点击「详情」→ detail/index.vue
    │
    ↓
┌──────────────────────────────────┐
│  前端（Vue 3 + TypeScript）       │
│  ├─ API client: getBars()         │ ② GET /api/quotes/{code}/bars?interval=1d&limit=250
│  ├─ klinecharts 9.8 渲染引擎      │
│  └─ 7 个周期 Tab（5分~月K）       │
└──────────────┬───────────────────┘
               │
               ↓
┌──────────────────────────────────┐
│  FastAPI 后端                     │
│  ├─ routes/quotes.py              │ ③ 路由层：参数校验 + mapper
│  └─ CachedMarketDataAdapter       │ ④ 缓存层：SQLite 永久缓存
│      └─ FallbackAdapter           │ ⑤ 兜底：主源挂→备源
│          ├─ EfinanceAdapter (主)   │ ⑥ 东方财富 push2his.eastmoney.com
│          └─ TencentAdapter  (备)   │    腾讯 qt.gtimg.cn
└──────────────────────────────────┘
```

### 数据流一句话

**前端请求 → FastAPI 路由 → 缓存命中直接返回 → miss 走 efinance 拉新 → 拉到后写 SQLite + 返回 → 前端 klinecharts 渲染**

---

## 2. 数据模型

### 2.1 后端 `Bar` dataclass

**位置**：`src/mommy_chaogu/market_data/types.py:150`

```python
@dataclass(frozen=True, slots=True)
class Bar:
    code: str                    # 股票代码（如 "600519"）
    name: str                    # 股票名称
    interval: BarInterval        # 周期枚举（M5/M15/M30/M60/D1/W1/M）
    adjustment: AdjustmentType   # 复权方式（NONE/FORWARD/BACKWARD）
    timestamp: datetime          # K 线开始时间
    open: Decimal                # 开盘价
    high: Decimal                # 最高价
    low: Decimal                 # 最低价
    close: Decimal               # 收盘价
    volume: int                  # 成交量（股）
    turnover: Money              # 成交额（Decimal + CNY）
    change_pct: Decimal | None   # 涨跌幅 %
    turnover_rate: Decimal | None  # 换手率 %
    amplitude: Decimal | None    # 振幅 %
```

**设计决策**：
- `frozen=True` + `slots=True`：行情数据不可变 + 内存优化
- `Decimal` 而非 `float`：金融场景杜绝精度漂移
- `Money` 类型：`Decimal amount` + `currency`（默认 CNY）

### 2.2 前端 `Bar` 接口

**位置**：`web/src/api/types.ts`

```typescript
export interface Bar {
  timestamp: string    // ISO 8601（后端 Decimal → str 传递）
  open: string         // 前端用 Number() 转换
  high: string
  low: string
  close: string
  volume: number       // 整数直接用 number
  turnover: string
}
```

### 2.3 API 响应 `BarOut`（Pydantic）

```python
class BarOut(BaseModel):
    timestamp: datetime
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    volume: int
    turnover: Decimal
```

---

## 3. 周期与复权

### 3.1 支持的 K 线周期

| 周期 | 枚举值 | API 参数 | 东财 klt 值 | 说明 |
|---|---|---|---|---|
| 1 分钟 | `M1` | `1m` | 1 | 盘中分钟级 |
| 5 分钟 | `M5` | `5m` | 5 | ✅ 前端 Tab |
| 15 分钟 | `M15` | `15m` | 15 | ✅ 前端 Tab |
| 30 分钟 | `M30` | `30m` | 30 | ✅ 前端 Tab |
| 60 分钟 | `M60` | `60m` | 60 | ✅ 前端 Tab |
| 日 K | `D1` | `1d` | 101 | ✅ 前端 Tab（默认） |
| 周 K | `W1` | `1w` | 102 | ✅ 前端 Tab |
| 月 K | `M` | `1M` | 103 | ✅ 前端 Tab |

**枚举定义**：`src/mommy_chaogu/market_data/types.py:43` (`BarInterval`, StrEnum)

### 3.2 复权方式

| 方式 | 枚举值 | 东财 fqt 值 | 说明 |
|---|---|---|---|
| 不复权 | `NONE` | 0 | 原始价格 |
| **前复权** | `FORWARD` | 1 | ✅ 默认，连续价格 |
| 后复权 | `BACKWARD` | 2 | 适合长期回测 |

**API 默认**：`adjustment=forward`

---

## 4. 后端实现详解

### 4.1 API 端点

```
GET /api/quotes/{code}/bars?interval=1d&limit=250&adjustment=forward
```

**位置**：`src/mommy_chaogu/web/routes/quotes.py:53`

**参数**：
| 参数 | 类型 | 默认 | 约束 |
|---|---|---|---|
| `code` | path | — | 6 位股票代码 |
| `interval` | query | `1d` | 枚举（见上表） |
| `limit` | query | `120` | 1~500 |
| `adjustment` | query | `forward` | none/forward/backward |

**响应**：`list[BarOut]`，按时间升序

### 4.2 装饰器链（核心架构）

K 线请求经过三层装饰器，从外到内：

```
CachedMarketDataAdapter        ← 第 1 层：SQLite 缓存
  └─ FallbackAdapter           ← 第 2 层：主备切换
      ├─ EfinanceAdapter       ← 主源：东方财富
      └─ TencentAdapter        ← 备源：腾讯财经
```

#### 第 1 层：CachedMarketDataAdapter

**位置**：`src/mommy_chaogu/cache/adapter.py`

策略：**按日期永久缓存**

- 首次请求 → miss → 向下游拉取 → 每根 Bar 按日期存 SQLite
- 再次请求 → 命中缓存 → 直接从 SQLite 返回（零网络）
- 分钟线缓存粒度：按 `trade_date` 存储（同一天共享）

缓存 key：`(code, interval, adj_type, trade_date)`，主键唯一。

**节流策略**：同 code+interval+adj 的请求在 5 秒内只拉一次新数据（`_fetched_keys` set）。

#### 第 2 层：FallbackAdapter

**位置**：`src/mommy_chaogu/market_data/fallback.py`

- 依次调用主源 → 失败（异常/空）→ 自动切备源
- `get_bars()` 只走了 efinance（腾讯不支持历史 K 线）
- `get_quote()` / `get_order_book()` 双源兜底

#### 第 3 层：EfinanceAdapter

**位置**：`src/mommy_chaogu/market_data/efinance_adapter.py:287`

核心调用：

```python
ef.stock.get_quote_history(
    code,           # "600519"
    klt=101,        # K线周期（101=日K）
    fqt=1,          # 复权（1=前复权）
    beg="20220101", # 起始日期 YYYYMMDD
    end="20260628", # 结束日期 YYYYMMDD
)
```

**防坑设计**：

1. **日期范围自动收缩**（`_resolve_kline_range()`）
   - efinance 默认请求 1900-2050 全量数据 → 东财接口必断
   - 根据 `interval` + `limit` 自动推算合理时间范围
   - 日线：250 交易日/年 → limit=250 → 取最近 ~1 年
   - 分钟线：240 根/天 → limit=240 → 取最近 ~1 天

2. **重试 3 次带退避**
   - 失败后 sleep 0.5s × (attempt+1) 再重试
   - 全部失败返回空列表（不抛异常）

3. **字段映射**
   - 东财返回中文列名（`日期`/`开盘`/`最高`/`最低`/`收盘`/`成交量`/`成交额`/`涨跌幅`/`换手率`/`振幅`）
   - adapter 层映射到英文 `Bar` 字段
   - `_to_dec()` / `_to_int()` / `_to_money()` 安全转换

### 4.3 SQLite 缓存表结构

```sql
-- 位置：src/mommy_chaogu/cache/schema.py:21
CREATE TABLE IF NOT EXISTS bar_cache (
    code       TEXT NOT NULL,
    interval   TEXT NOT NULL,    -- "1d" / "5m" / ...
    adj_type   TEXT NOT NULL,    -- "forward" / "none" / ...
    trade_date TEXT NOT NULL,    -- "2024-03-15"
    bar_json   TEXT NOT NULL,    -- JSON: {open, high, low, close, volume, ...}
    fetched_at TIMESTAMP NOT NULL,
    PRIMARY KEY (code, interval, adj_type, trade_date)
);

CREATE INDEX IF NOT EXISTS ix_bar_cache_code
    ON bar_cache(code, interval, adj_type);
```

**设计**：
- 主键 = `(code, interval, adj_type, trade_date)`：同一股同周期同复权，每个日期只存一条
- `ON CONFLICT DO UPDATE`：重新拉取时自动覆盖（upsert）
- JSON 存储完整 Bar 数据，灵活扩展字段

---

## 5. 前端实现详解

### 5.1 图表库选型

**klinecharts 9.8**（`web/package.json`）

| 维度 | 选择理由 |
|---|---|
| 体积 | gzip 后 ~53KB（含 Vue 运行时） |
| 专业性 | 金融 K 线专用，内置 MA / VOL / MACD 等指标 |
| 框架无关 | 纯 JS，可以和 Vue 3 无缝集成 |
| 移动端 | 触摸手势支持（缩放/拖拽/十字线） |
| 开源 | Apache-2.0，无商业限制 |

### 5.2 详情页 K 线实现

**位置**：`web/src/pages/detail/index.vue`

#### 数据加载流程

```
1. 用户进入详情页（router push code=600519）
2. onMounted() → loadBars()
3. GET /api/quotes/600519/bars?interval=1d&limit=250&adjustment=forward
4. 后端缓存命中 → 毫秒级返回
5. bars.value = [Bar, Bar, ...]
6. await nextTick() → DOM 更新完成
7. drawKLine() → klinecharts 渲染
```

#### K 线渲染核心代码

```typescript
async function drawKLine() {
  // 1. 懒加载 klinecharts（首次才 import，减少首屏体积）
  if (!klineChart.value) {
    const klinecharts = await import('klinecharts')
    const el = document.getElementById('kline') as HTMLElement
    klineChart.value = klinecharts.init(el)
  }

  const chart = klineChart.value

  // 2. A 股配色（红涨绿跌，和欧美相反）
  chart.setStyles({
    candle: {
      bar: {
        upColor: '#c83e3e',    // 涨=红
        downColor: '#2d8e3d',  // 跌=绿
        noChangeColor: '#999'
      }
    }
  })

  // 3. 技术指标：MA 均线 + 成交量
  chart.createIndicator('MA', false, { id: 'candle_pane' })
  chart.createIndicator('VOL')

  // 4. 数据喂进去
  const dataList = bars.value.map(b => ({
    timestamp: new Date(b.timestamp).getTime(),
    open: Number(b.open),
    high: Number(b.high),
    low: Number(b.low),
    close: Number(b.close),
    volume: Number(b.volume)
  }))
  chart.applyNewData(dataList)
}
```

#### 关键交互

- **周期切换**：点击 Tab（5分/15分/30分/60分/日K/周K/月K）
  - `changeInterval(key)` → 更新 `interval.value` → `loadBars()` → 重绘
  - 日K/周K 取 250 根，分钟线取 200 根

- **图表销毁**：`onUnmounted()` → `klineChart.value.dispose()` 释放内存

- **跨页面保留**：详情页 watch(code) → 切换股票时重新加载 bars + 重绘

### 5.3 技术指标

| 指标 | 位置 | 默认参数 |
|---|---|---|
| MA（移动平均线） | 主图叠加 | MA5 / MA10 / MA30 / MA60 |
| VOL（成交量） | 副图 | MA5 / MA10 |

MA 均线由 klinecharts 自动计算并绘制，后端只返回原始 OHLCV 数据。

---

## 6. 性能优化

### 6.1 三级缓存

| 层级 | 位置 | 命中场景 | 延迟 |
|---|---|---|---|
| L1：浏览器内存 | Vue ref | 同页面切换周期 | ~0ms |
| L2：SQLite 永久缓存 | 后端 | 换股回来 / 二次进入 | ~5ms |
| L3：东方财富 API | 远程 | 首次请求 / 新交易日 | 200-800ms |

### 6.2 请求优化

- **日期范围收缩**：避免请求全量数据（1900-2050 → 最近 1-4 年）
- **limit 控制返回量**：日线 250 根 ≈ 1 年，够看趋势
- **5 秒节流**：同 code+interval 短时间内只拉一次

### 6.3 前端优化

- **懒加载**：`await import('klinecharts')` → 首页不加载图表库
- **dispose 释放**：离开详情页时销毁图表实例
- **nextTick 等渲染**：确保 DOM 存在再画图

---

## 7. 坑点与解决方案

| 坑 | 原因 | 解法 |
|---|---|---|
| efinance 请求全量超时 | `beg=19000101` 请求 150 年 | `_resolve_kline_range()` 自动收缩 |
| 东财中午高峰断连 | push2his.eastmoney.com 过载 | 重试 3 次 + TencentAdapter 兜底 |
| Naive datetime 比较 | efinance 返回无时区 | mapper 层统一补 UTC |
| Decimal JSON 序列化 | Pydantic 不自动转 | schemas 里 Decimal → str |
| 分钟线缓存膨胀 | 5m K 线一天 48 根 | 按日期合并 JSON 存储 |
| klinecharts 内存泄漏 | SPA 不销毁图表 | `onUnmounted` → `dispose()` |

---

## 8. 文件索引

| 文件 | 职责 |
|---|---|
| `src/mommy_chaogu/market_data/types.py` | Bar / BarInterval / AdjustmentType 定义 |
| `src/mommy_chaogu/market_data/efinance_adapter.py` | 东方财富 K 线拉取 + 日期范围算法 |
| `src/mommy_chaogu/market_data/fallback.py` | 主备源切换 |
| `src/mommy_chaogu/cache/adapter.py` | K 线缓存装饰器 |
| `src/mommy_chaogu/cache/store.py` | bar_cache SQLite CRUD |
| `src/mommy_chaogu/cache/schema.py` | bar_cache DDL |
| `src/mommy_chaogu/web/routes/quotes.py` | `/api/quotes/{code}/bars` 端点 |
| `src/mommy_chaogu/web/mappers.py` | Bar → BarOut 转换 |
| `src/mommy_chaogu/web/schemas.py` | BarOut Pydantic 模型 |
| `web/src/pages/detail/index.vue` | K 线详情页 + klinecharts 渲染 |
| `web/src/api/index.ts` | `getBars()` API client |
| `web/src/api/types.ts` | Bar TS 接口 |

---

## 9. 未来扩展方向

- [ ] **MACD / KDJ / BOLL** 指标（klinecharts 内置，加一行 `createIndicator` 即可）
- [ ] **K 线标注**：在图上标记买卖点 / 信号触发位置
- [ ] **十字线 + 详情浮窗**：klinecharts 内置，需开启配置
- [ ] **画线工具**：支撑线 / 压力线 / 黄金分割
- [ ] **实时更新**：WebSocket 推送最新分钟 Bar → `chart.updateData()`
- [ ] **多股对比**：同一图表叠加两只股票的归一化 K 线
