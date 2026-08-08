# ma-suppression-monitor — 均线压制与趋势通道监控工具箱

独立的量化监控工具箱：EMA 云带 / 枢轴通道 / 压制状态机 / 底部评分 / 双引擎编排。
适用于 30 分钟到日线级别的股票与 ETF OHLC 数据，所有阈值用 ATR 归一化，
跨品种、跨 regime 可比，无需人工调参。

> **核心惯例**：信号在 bar 收盘确认，成交价为**下一根 bar 的开盘价**。全链路无未来函数。

本目录是 mommy-chaogu 仓库内的**独立包**，与 `src/mommy_chaogu` 主程序完全解耦：
不引用主包代码，主包也不依赖它。可单独安装、单独测试。

## 安装

```bash
cd quant/ma-suppression-monitor
pip install -e .          # 仅需 pandas>=2.0, numpy>=1.24
```

## 快速上手

```python
from ma_suppression_monitor import DualEngine, load_csv, score_events, forward_returns

bars = load_csv("your_bars.csv")  # 任意含 time/open/high/low/close(/volume) 的 CSV
eng = DualEngine()
frame = eng.run(bars)  # 逐 bar 监控帧

print(eng.readout(bars))  # 当前时刻面板读数 (dict)

for e in eng.suppression_events_[-5:]:  # 压制确认事件
    print(e.t_confirmed, f"第{e.count}次", f"深度{e.depth_atr:.2f}ATR")

ev_idx = score_events(frame["score"], on=65, off=35)  # 底部评分事件
fr = forward_returns(bars, ev_idx, [13, 26, 65])  # 无未来函数前向收益
```

完整示例：`python examples/run_on_soxx.py <csv路径>`

## 模块地图

| 文件 | 内容 |
|---|---|
| `bars.py` | 数据加载与规范化（OHLCV 约定，与数据源解耦） |
| `indicators.py` | EMA 云带（55/89 斐波那契对）/ ATR / 枢轴点 / 回归通道 |
| `regime.py` | **模块一** 趋势状态机 BULL/BEAR + 云带几何量（ATR 归一化） |
| `channel.py` | **模块二** 枢轴通道（包含性约束 + 最大触碰拟合，复刻手绘通道） |
| `suppression.py` | **模块三** 压制三阶段状态机：预判 ARMED / 监控 ENGAGED / 确认 CONFIRMED |
| `bottom.py` | **模块四** 底部形态评分（四特征加权 0~100，含崩盘过滤器） |
| `engine.py` | 双引擎编排：做空引擎 × 底部评分调制 + 单一口径警报 |
| `backtest.py` | 无未来函数回测：前向收益 / B→S 成对交易 / 组合模拟 |
| `macro_channel.py`（顶层） | 大尺度通道（4H/日线），最大回撤段锚定，独立于 `channel.py` |

## 设计要点

1. **一切阈值 ATR 归一化** — 跨品种可比、跨 regime 自适应、统计含义稳定。
2. **EMA 用递推式（`adjust=False`）** — 与 TradingView `ta.ema` 完全一致（误差 < 0.001）。
3. **趋势状态保持二元** — 纠缠区信息由连续变量 `cloud_width` 承载，下游规则更干净。
4. **底部评分用固定仿射映射** — 样本内一次标定后不再动，样本外读数可直接比较。
5. **防闪烁三件套** — 滞后缓冲 / 一次反弹只出一枪 / 压制计数（"事不过三"分组）。

## 压制状态机

```
IDLE    --空头排列 且 价格逼近云带(≤1.5 ATR)--> ARMED
ARMED   --探入触发区间 且 深度≥0.2 ATR-------> ENGAGED
ARMED   --收盘站上云带上沿+缓冲--------------> IDLE   (预判失效)
ENGAGED --收盘跌回云带下沿之下---------------> CONFIRMED (发信号)
ENGAGED --收盘站上云带上沿-------------------> IDLE   (压制失败)
CONFIRMED--价格离开云带>1.0 ATR-------------> ARMED  (重新武装, 计数+1)
```

## 警报优先级（单一口径，面板直接可读）

```
CROSS (金叉/死叉, ≤3 bar) > RALLY_FADE (压制确认区) >
BOTTOM_WATCH (评分≥65) > TREND_LONG / FREE_FALL > —
```

## 测试

```bash
pip install pytest
pytest tests/             # 合成数据冒烟测试, 不访问网络
```

## 配置

全部默认值见 `engine.EngineConfig`（EMA 55/89、ATR 14、通道窗 60、
BOTTOM_WATCH 65、底部特征权重 0.30/0.30/0.25/0.15 等），均可注入覆盖：

```python
from ma_suppression_monitor import DualEngine, EngineConfig, SuppressionConfig

cfg = EngineConfig(
    ema_fast=21,
    ema_slow=55,
    suppression=SuppressionConfig(arm_dist=2.0, min_depth=0.5),
)
eng = DualEngine(cfg)
```
