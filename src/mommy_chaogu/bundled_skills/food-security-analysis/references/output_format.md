# 输出格式规范 · ZIP 结构 · 时间戳 · 报告头

> 同一份分析, 多个时间点跑, 都要能区分谁是"最终版"。
> 时间戳用**数据最新时间** (北京时间), 不用脚本执行时间。

---

## 1. 目录结构 (per-run, v1.1 = 5 deliverables)

```
deliverables/food-security/{YYYY-MM-DD}/{run_ts}/
├── report.md            (≥ 30 KB, 11 sections, 完整版报告)
├── strategy-card.md     (≥ 8 KB, draft, 不入库)
├── web.html             (self-contained, 11 modules, dark-mode + Chart.js + hover/click)
├── text.md              (v1.1 新增, 纯文字版, 零图, 贴微信/邮件/Notion)
└── data.json            (raw: basket flow + top-5 tech + top5_flow_ts + global context)
```

- `YYYY-MM-DD` = 交易日 (北京)
- `run_ts` = 这次运行的 UTC 时间戳, 格式 `YYYYMMDD-HHMMSS` (例如 `20260817-153022`)

---

## 2. ZIP 结构 (per-day, v1.1 = 5 files in daily-final)

```
deliverables/food-security/{YYYY-MM-DD}.zip
├── manifest.json
├── daily-final/                          # canonical final version
│   ├── report.md
│   ├── strategy-card.md
│   ├── web.html
│   ├── text.md                           # v1.1 新增
│   └── data.json
└── runs/
    ├── {run_ts_1}/                       # first run of the day
    │   ├── report.md
    │   ├── strategy-card.md
    │   ├── web.html
    │   ├── text.md
    │   └── data.json
    ├── {run_ts_2}/
    └── {latest_run}/                     # also the source of daily-final/
        ├── report.md
        ├── strategy-card.md
        ├── web.html
        └── data.json
```

### 多次同一天分析

- 每次跑都新建 `runs/{run_ts}/` (递增)
- `daily-final/` 始终指向**最新**的 run (除非用户强制标记)
- ZIP 重新生成, 旧 run 不会丢

### 最终版标记

- `daily-final/` = 这次 ZIP 里的最终版
- 用户可以强制标记: `python package_zip.py --final {run_ts}` 覆盖默认 "latest = final" 规则

---

## 3. 报告/网页头部 (时间戳)

每个 report / strategy-card / web 文件**头部**必须包含:

```markdown
# 报告标题
**数据截至**: {YYYY-MM-DD} {close|mid-day} (北京时间)
**生成时间**: {YYYY-MM-DDTHH:MM:SS+08:00} (北京时间, ISO8601)
**Skill**: food-security-analysis
**Session**: {session_id}
```

- `数据截至` = **数据本身的最新时间**, 不是脚本执行时间
  - A 股 15:00 后跑: `as of {today_bj} close (Beijing)`
  - A 股 9:30-15:00 跑: `as of {today_bj} mid-day (Beijing)`
  - 跨夜/盘前跑: `as of {previous_trading_day} close (Beijing)` + 标注
- `生成时间` = 脚本真实执行时间, 用于审计
- `Session` = Mavis session_id, 用于跨 session 关联

### HTML 网页头部对应

```html
<meta name="data-as-of" content="{today_bj} close (Beijing)">
<meta name="generated-at" content="{now_bj_iso}">
<meta name="session-id" content="{session_id}">
<meta name="skill" content="food-security-analysis">
```

并在 hero section 显示 "数据截至"。

---

## 4. manifest.json schema (v1.1 = 5 files)

```json
{
  "skill": "food-security-analysis",
  "session_id": "431666932195605",
  "skill_version": "1.1",
  "generated_at": "2026-08-17T15:30:22+08:00",
  "trading_day": "2026-08-17",
  "is_market_close": true,
  "data_as_of": "2026-08-17 15:00:00 (Beijing time, A股收盘)",
  "is_final": true,
  "basket_coverage": {
    "total": 35,
    "money_flow_pulled": 26,
    "kline_pulled_top5": 5
  },
  "files": [
    {
      "path": "daily-final/report.md",
      "type": "report",
      "size_bytes": 30376,
      "sha256": "abc123..."
    },
    {
      "path": "daily-final/strategy-card.md",
      "type": "strategy-card",
      "size_bytes": 9067,
      "sha256": "..."
    },
    {
      "path": "daily-final/web.html",
      "type": "web",
      "size_bytes": 246570,
      "sha256": "..."
    },
    {
      "path": "daily-final/text.md",
      "type": "text",
      "size_bytes": 6494,
      "sha256": "..."
    },
    {
      "path": "daily-final/data.json",
      "type": "data",
      "size_bytes": 268976,
      "sha256": "..."
    }
  ],
  "runs_in_zip": [
    {"ts": "20260817-153022", "is_final": true},
    {"ts": "20260817-143000", "is_final": false}
  ]
}
```

---

## 5. data.json schema (v1.1 includes top5_flow_ts for Chart.js)

```json
{
  "skill": "food-security-analysis",
  "skill_version": "1.1",
  "trading_day": "2026-08-17",
  "data_as_of": "2026-08-17 15:00:00 (Beijing time)",
  "basket_flow": {
    "000408": {"code":"000408","name":"藏格矿业","chain":"上游","subcategory":"化肥-钾肥","main_net":0.86e8, "samples":240, "last_ts":"2026-08-17T15:00:00", "close":79.41},
    ...
  },
  "top5_tech": {
    "002041": {"code":"002041","name":"登海种业","close":8.91,"ma5":8.70,"ma10":8.80,"ma20":8.67,"ma60":8.49,"trend":"bull","dev20":2.76,"pos20":72,"vol_ratio":2.81,"golden_cross_recent":false,"n_bars":60},
    ...
  },
  "top5_flow_ts": {                          // v1.1 — Chart.js time-series
    "002041": [{"time":"09:31","main_net_yi":0.01,...}, ..., {"time":"15:00","main_net_yi":-0.01}],
    "000408": [...],
    ...
  },
  "variable_history": {                      // v1.1 — 4-variable 6-month history
    "months": ["2026-03", ..., "2026-08E"],
    "fao_index": [127.4, ..., 131.6],
    "el_nino_strength": [1.2, ..., 2.5],
    "fpi_pe_pctile": [28, ..., 38],
    "ukraine_grain_yoy": [-25, ..., -38]
  },
  "global_context": {
    "fao_july_2026": 131.1,
    "fao_change_mom_pct": 0.6,
    "black_sea_yoy_pct": -40,
    "el_nino_status": "strong (70年最强)",
    "fpi_pe_percentile_10y": 36.5
  },
  "a_share_snapshot": {
    "indices": {
      "上证指数": {"price":3960.19,"change_pct":0.84},
      "深证成指": {"price":14534.46,"change_pct":1.26},
      "创业板指": {"price":3674.68,"change_pct":1.33}
    },
    "limit_up_sectors": [...],
    "laggard_sectors": [...]
  }
}
```

---

## 6. 文件大小基线 (健康检查, v1.1 = 5 files)

| 文件 | 最小大小 | 健康范围 | 备注 |
|---|---|---|---|
| report.md | ≥ 30 KB | 30-50 KB | 完整版 |
| strategy-card.md | ≥ 8 KB | 8-15 KB | 草稿 |
| web.html | ≥ 100 KB | 100-260 KB | 含 Chart.js + dark mode CSS + 240min × 5 只 JSON |
| text.md | ≥ 3 KB | 4-8 KB | 纯文字版 (新增) |
| data.json | ≥ 10 KB | 200-300 KB | 含 top5_flow_ts (1200 个 flow 点) |
| 总 ZIP | ≥ 150 KB | 150-350 KB | 5 文件 + manifest |

如果文件明显小于基线, 报告里标注 `⚠️ {file} size {n} KB < baseline {m} KB, 内容可能不完整`。

---

## 7. 命名约定

| 元素 | 格式 | 例子 |
|---|---|---|
| 报告 (in ZIP) | `report.md` | 简短, ZIP 内部用 |
| 报告 (in run dir) | `report-{ts}.md` | 跨 run 时区分 |
| 策略卡 (in ZIP) | `strategy-card.md` | — |
| 网页 (in ZIP) | `web.html` | — |
| 数据 (in ZIP) | `data.json` | — |
| ZIP 文件名 | `food-security-{YYYY-MM-DD}.zip` | 一天一个 |
| run 目录 | `{YYYYMMDD-HHMMSS}/` | 时间戳排序 |

---

## 8. 强制标注的免责声明

每个 report / strategy-card / web 文件**底部**必须有:

```markdown
> ⚠️ 本报告为研究/教学/个人投资参考, **不是投资建议, 不构成任何买卖推荐**.
> 任何"看好"判断都基于今天 ({data_as_of}) 的公开数据, 未来可能变化.
```

不能省略。
