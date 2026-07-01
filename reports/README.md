# reports/

> 妈妈炒股 · 资金流收盘报告（HTML 单文件实战产物）

## 这是什么

每个交易日收盘后，由 `mommy-report render` 把 `data/flows_report_{YYYY-MM-DD}.md`
解析成**单文件自包含 HTML**（无外部依赖），妈妈可以：

- 直接浏览器打开看（无 JS、无网都行）
- 发到微信让她手机看
- `mommy-report serve` 起 HTTP server 跨设备看（开发时用）

## 文件命名

| 文件 | 说明 |
|---|---|
| `{YYYY-MM-DD}.html` | 单日实战产物（每日 1 份）。**正式入仓** |
| `index.html` | 多日索引页（自动扫描目录下所有日期）。**临时生成，不入仓** |

## 为什么 `index.html` 不入仓

`index.html` 是 `mommy-report index` 动态扫描当前目录下所有 `{date}.html` 生成的，
每次跑都会重写。如果入仓：

- 每天都会多一个无意义的 commit
- 多人/多设备 sync 会有冲突
- 索引内容完全可以从单日文件重新派生，不需要版本化

要看索引？跑：

```bash
uv run mommy-report index --out reports/  # 重新生成
```

## 如何生成

```bash
# 1. 先跑资金流日报（data/flows_report_{today}.md）
uv run mommy-flows --pool semicon report --day today

# 2. 渲染单日 HTML
uv run mommy-report render --day today

# 3. 重新生成索引（可选）
uv run mommy-report index

# 4. 本地预览
uv run mommy-report serve  # 起 http server，预设端口 8765
```

## gitignore 规则

`reports/.gitignore` 排除：
- `index.html`（临时索引，每次重新生成）
- `*.tmp.html`（开发期临时文件）

## 历史

| 日期 | 备注 |
|---|---|
| 2026-06-29 | **首份实战**（半导体产业链 106 只）。上中下游温度 + 矛盾股清单 |
