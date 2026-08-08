"""确定性指标内核。

设计约束（RFC §6.2）：
- 只基于本地 OHLCV 统一计算，不依赖上游供应商口径；
- 纯函数、无 IO、无随机性，同一输入永远得到同一输出；
- 所有序列与输入等长，warm-up 期间为 None，绝不向前填充；
- 任何「当天是否触发」的判断只允许使用截至前一天已确认的数据，
  通道类指标默认按 shift(1) 处理，避免用当日高点定义当日突破（look-ahead）。
"""

from __future__ import annotations

from collections import deque


def _check_window(window: int) -> None:
    if window < 1:
        raise ValueError("window 必须 >= 1")


def sma(values: list[float], window: int) -> list[float | None]:
    """简单移动平均。前 window - 1 个位置为 None。"""
    _check_window(window)
    out: list[float | None] = [None] * len(values)
    acc = 0.0
    q: deque[float] = deque()
    for i, v in enumerate(values):
        q.append(v)
        acc += v
        if len(q) > window:
            acc -= q.popleft()
        if len(q) == window:
            out[i] = acc / window
    return out


def ema(values: list[float], window: int) -> list[float | None]:
    """指数移动平均，以前 window 个值的 SMA 作为种子（与主流口径一致）。

    种子之前为 None；从第 window 个值起按 k = 2 / (window + 1) 递推。
    """
    _check_window(window)
    out: list[float | None] = [None] * len(values)
    if len(values) < window:
        return out
    k = 2.0 / (window + 1)
    seed = sum(values[:window]) / window
    out[window - 1] = seed
    prev = seed
    for i in range(window, len(values)):
        prev = values[i] * k + prev * (1 - k)
        out[i] = prev
    return out


def price_channel(
    highs: list[float], lows: list[float], window: int
) -> list[tuple[float, float] | None]:
    """价格通道（唐奇安通道），返回 (上轨, 下轨)。

    位置 i 的通道由区间 [i - window, i) 决定——即不包含当日，
    保证「当日突破通道」的判断不存在未来函数。前 window 个位置为 None。
    """
    _check_window(window)
    if len(highs) != len(lows):
        raise ValueError("highs 与 lows 长度必须一致")
    out: list[tuple[float, float] | None] = [None] * len(highs)
    # 单调队列维护窗口最大/最小值，O(n)
    max_q: deque[int] = deque()
    min_q: deque[int] = deque()
    for i in range(len(highs)):
        j = i - 1  # 纳入窗口的最新 bar 是前一天
        if j >= 0:
            while max_q and highs[max_q[-1]] <= highs[j]:
                max_q.pop()
            max_q.append(j)
            while min_q and lows[min_q[-1]] >= lows[j]:
                min_q.pop()
            min_q.append(j)
        lo = i - window
        while max_q and max_q[0] < lo:
            max_q.popleft()
        while min_q and min_q[0] < lo:
            min_q.popleft()
        if i >= window and max_q and min_q:
            out[i] = (highs[max_q[0]], lows[min_q[0]])
    return out


def atr(
    highs: list[float], lows: list[float], closes: list[float], window: int
) -> list[float | None]:
    """平均真实波幅（Wilder 平滑）。前 window 个位置为 None。"""
    _check_window(window)
    n = len(highs)
    if not (len(lows) == len(closes) == n):
        raise ValueError("highs/lows/closes 长度必须一致")
    out: list[float | None] = [None] * n
    if n <= window:
        return out
    trs: list[float] = []
    for i in range(1, n):
        tr = max(
            highs[i] - lows[i],
            abs(highs[i] - closes[i - 1]),
            abs(lows[i] - closes[i - 1]),
        )
        trs.append(tr)
    # trs[k] 对应原序列第 k + 1 根 bar
    seed = sum(trs[:window]) / window
    out[window] = seed
    prev = seed
    for k in range(window, len(trs)):
        prev = (prev * (window - 1) + trs[k]) / window
        out[k + 1] = prev
    return out


def rsi(closes: list[float], window: int = 14) -> list[float | None]:
    """相对强弱指数（Wilder 平滑）。前 window 个位置为 None。"""
    _check_window(window)
    n = len(closes)
    out: list[float | None] = [None] * n
    if n <= window:
        return out
    gains: list[float] = []
    losses: list[float] = []
    for i in range(1, n):
        diff = closes[i] - closes[i - 1]
        gains.append(max(diff, 0.0))
        losses.append(max(-diff, 0.0))
    avg_gain = sum(gains[:window]) / window
    avg_loss = sum(losses[:window]) / window
    out[window] = _rsi_value(avg_gain, avg_loss)
    for k in range(window, len(gains)):
        avg_gain = (avg_gain * (window - 1) + gains[k]) / window
        avg_loss = (avg_loss * (window - 1) + losses[k]) / window
        out[k + 1] = _rsi_value(avg_gain, avg_loss)
    return out


def _rsi_value(avg_gain: float, avg_loss: float) -> float:
    if avg_loss == 0:
        return 100.0 if avg_gain > 0 else 50.0
    rs = avg_gain / avg_loss
    return 100.0 - 100.0 / (1.0 + rs)


def volume_sma(volumes: list[float], window: int) -> list[float | None]:
    """成交量均值。放量判断由调用方用 volume / volume_sma 完成。"""
    return sma(volumes, window)


def relative_strength(
    closes: list[float], benchmark_closes: list[float], window: int
) -> list[float | None]:
    """标的相对基准的强度：window 日内标的收益 − 基准收益（小数）。

    两序列必须按同一交易日历对齐且等长。前 window 个位置为 None。
    """
    _check_window(window)
    if len(closes) != len(benchmark_closes):
        raise ValueError("closes 与 benchmark_closes 长度必须一致")
    out: list[float | None] = [None] * len(closes)
    for i in range(window, len(closes)):
        base_t = closes[i - window]
        base_b = benchmark_closes[i - window]
        if base_t <= 0 or base_b <= 0:
            continue
        out[i] = (closes[i] / base_t - 1.0) - (benchmark_closes[i] / base_b - 1.0)
    return out
