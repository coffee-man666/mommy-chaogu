"""
bars.py — 数据加载与规范化

所有模块统一在一个简单的 Bar DataFrame 约定上工作：
    index: DatetimeIndex (tz-aware 建议, 但不强制)
    columns: open, high, low, close, volume (volume 可选, 缺省补 0)

设计说明
--------
刻意不引入自定义 Bar 类——指标计算全部向量化, 直接用 pandas。
库的输入只需要 OHLC(V), 与数据源解耦 (CSV / Yahoo / BATS 导出均可)。
"""

from __future__ import annotations

import pandas as pd

REQUIRED = ["open", "high", "low", "close"]


def load_csv(
    path: str, time_col: str = "time", tz: str | None = "America/New_York"
) -> pd.DataFrame:
    """加载 OHLC CSV。列名大小写不敏感, time 列解析为 DatetimeIndex。"""
    df = pd.read_csv(path)
    df.columns = [c.strip() for c in df.columns]
    lower = {c.lower(): c for c in df.columns}
    out = pd.DataFrame()
    for col in [*REQUIRED, "volume"]:
        if col in lower:
            out[col] = pd.to_numeric(df[lower[col]], errors="coerce")
    if "volume" not in out:
        out["volume"] = 0.0
    t = pd.to_datetime(df[time_col], utc=True)
    if tz:
        t = t.dt.tz_convert(tz)
    out.index = t
    out.index.name = "time"
    return validate(out)


def validate(df: pd.DataFrame) -> pd.DataFrame:
    """丢缺失、排序、去重, 返回干净 bars。"""
    missing = [c for c in REQUIRED if c not in df.columns]
    if missing:
        raise ValueError(f"missing columns: {missing}")
    df = df.dropna(subset=REQUIRED).sort_index()
    df = df[~df.index.duplicated(keep="last")]
    return df


def resample_bars(df: pd.DataFrame, rule: str) -> pd.DataFrame:
    """聚合到更粗周期 (如 30min→2h)。rule 用 pandas offset 别名。"""
    agg = {"open": "first", "high": "max", "low": "min", "close": "last", "volume": "sum"}
    out = df.resample(rule).agg({k: v for k, v in agg.items() if k in df.columns})
    return validate(out)
