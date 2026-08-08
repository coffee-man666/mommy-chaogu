"""
示例: 在 SOXX 30min 数据上运行完整监控系统
用法: python examples/run_on_soxx.py [csv_path]
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))  # 源码树内直接运行

from ma_suppression_monitor import (
    DualEngine,
    baseline,
    forward_returns,
    load_csv,
    score_events,
)

CSV = sys.argv[1] if len(sys.argv) > 1 else "data/SOXX_30min_bars_clean.csv"

bars = load_csv(CSV)
print(f"bars: {len(bars)}  {bars.index[0]} -> {bars.index[-1]}")

# ---------- 1. 双引擎全量计算 ----------
eng = DualEngine()
frame = eng.run(bars)

# ---------- 2. 当前监控读数 ----------
readout = eng.readout(bars)
print("\n=== 当前读数 ===")
for k, v in readout.items():
    print(f"  {k}: {v}")

# ---------- 3. 压制状态机事件 (近窗口) ----------
ev = eng.suppression_events_
print(f"\n=== 压制事件: 共 {len(ev)} 次 ===")
for e in ev[-5:]:
    print(
        f"  {e.t_confirmed}  第{e.count}次  深度{e.depth_atr:.2f}ATR  驻留{e.dwell_bars}b  收盘{e.confirm_close:.1f}"
    )

# ---------- 4. 底部评分事件回测 (无未来函数) ----------
H = [13, 26, 65]
ev_idx = score_events(frame["score"], on=65, off=35)
fr = forward_returns(bars, ev_idx, H)
bl = baseline(bars, H)
print(f"\n=== 底部评分>65 事件: {len(ev_idx)} 次 ===")
print(f"{'窗口':>6} {'事件均值%':>9} {'胜率%':>6} {'基准%':>7} {'超额%':>7}")
for h in H:
    s = fr[f"r{h}"].dropna()
    print(
        f"{h:>6} {s.mean():>9.2f} {100 * (s > 0).mean():>6.0f} {bl[h]:>7.2f} {s.mean() - bl[h]:>7.2f}"
    )
