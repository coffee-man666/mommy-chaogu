# retry.py — 数据获取重试工具

basket-analysis skill 跑在受限沙盒环境里, 几个数据源会偶发失败:
- **efinance** (mommy money flow 上游) — 频繁 rate-limit, 一次只能拿到 70-80% 的股票
- **Tencent K-line API** — 偶发 SSL handshake 失败 / timeout
- **chrome --print-to-pdf** — 偶发 dbus / GPU / 沙盒噪音
- **web_search** — 偶发 429 rate limit

`retry.py` 提供统一的指数退避重试, 让所有数据获取点行为一致.

## API

### `retry_with_backoff(fn, ...)`
通用重试装饰器. 任何函数都可包装.

```python
from retry import retry_with_backoff

def fetch_url(url):
    # raise on transient failure
    with urllib.request.urlopen(url, timeout=15) as r:
        return r.read()

data = retry_with_backoff(
    fetch_url, args=(url,),
    max_attempts=3,          # 最多 3 次
    initial_delay=2.0,       # 第一次重试前等 2s
    backoff_factor=2.0,      # 每次等的时间 × 2
    max_delay=30.0,          # 最多等 30s
    jitter=0.3,              # ±30% 随机扰动, 避免同步重试
    retriable_exceptions=(URLError, TimeoutError, ConnectionError),
)
```

可重试的异常 (默认): `URLError`, `HTTPError`, `TimeoutError`, `ConnectionError`, `ConnectionResetError`, `ConnectionRefusedError`, `OSError`, `subprocess.TimeoutExpired`.

不可重试的异常 (立即抛出): `KeyError`, `ValueError`, `TypeError` 等 — 这些是程序错误, 重试也没用.

### `retry_money_flow(codes, ...)`
best-effort 拉一组代码的当日资金流, 自动找 `mommy` 二进制, 用 DB cache 决定哪些还需要重试.

```python
from retry import retry_money_flow

result = retry_money_flow(
    ["300189", "600313", "600127", ...],   # 35 只粮食股
    db_path="/workspace/.home/.local/share/mommy-chaogu/portfolio.db",
    max_attempts=2,
    initial_delay=5.0,
)
# → {"300189": True, "600313": True, ..., "002258": False, ...}
# → 26/35 (74%) 即使 2 次都失败了, 也会继续跑后续流程
```

特点:
- 跳过已经缓存的代码 (idempotent)
- 自动找 `mommy` binary (PATH 或常见位置)
- 失败不抛异常, 返回 dict 让上层继续

### `retry_kline(code, days=60, max_attempts=3)`
单只股票 K-line, 返回 closes 列表 (oldest→newest) 或 None.

```python
from retry import retry_kline

closes = retry_kline("300189", days=60, max_attempts=3)
# → [4.21, 4.18, 4.30, ..., 6.24]   (60 个收盘价)
# → None                              (3 次都失败)
```

### `retry_web_search(search_fn, query, ...)`
包装 `Mavis` 的 `web_search` 工具, 处理 429 / 5xx.

```python
from retry import retry_web_search
from mavis.tools import web_search  # 实际是 Mavis tool

# 通常不在脚本里直接用, 而是在 agent 的 plan 里提到
```

## 在 skill 里的接入点

| 数据源 | 接入方式 | 默认 | 启用 |
|---|---|---|---|
| 资金流 (mommy) | `BASKET_RETRY=1` env | 0 (单次) | retry 2 次, 5s+10s backoff |
| K-line (Tencent) | 调用 `retry_kline()` | 已 retry | retry 3 次, 2s+4s+8s backoff |
| PDF (chrome) | `_chrome_to_pdf()` 内部 | 已 retry | retry 2 次, 3s backoff |
| Web search | `retry_web_search()` | 已 retry | retry 3 次, 3s+6s+12s backoff |
| DB 读 (`_pull_top5_flow_ts`) | N/A | N/A | 纯本地, 不需要 retry |

## 设计原则

1. **Best-effort, not strict** — 失败时返回 None / 0 标记, 继续后续流程
2. **Idempotent** — 同一只股票可被多次重试, 不破坏 cache
3. **Bounded** — 最多 3 次, 最多 30s 间隔, 不让 retry 拖死整个 pipeline
4. **Observable** — 每次重试都打 `⟳ retry N/M` 日志, 让 agent 看到
5. **Per-exception** — 网络错重试, 程序错立刻抛, 不滥用 retry
6. **Jittered** — ±30% 随机, 避免 sandbox 多脚本同步重试

## 测试

```bash
cd /workspace/.skills/basket-analysis/scripts
/workspace/.home/.local/share/uv/tools/mommy-chaogu/bin/python -c "
import sys; sys.path.insert(0, '.')
from retry import retry_with_backoff, retry_money_flow, retry_kline
# 1) 立即成功
assert retry_with_backoff(lambda: 'ok') == 'ok'
# 2) 失败 2 次后成功
n = [0]
def f():
    n[0] += 1
    if n[0] < 3: raise ConnectionError()
    return 'ok'
assert retry_with_backoff(f, max_attempts=3, initial_delay=0.1) == 'ok'
print('  ✅ all unit tests passed')
"
```
