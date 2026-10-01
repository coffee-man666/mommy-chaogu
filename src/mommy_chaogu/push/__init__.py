"""推送模块（Bark + 通用管道）。

设计原则（参考 docs/DESIGN.md）：
- 接口先行：Notifier / Pusher / Deduper 都是 Protocol，业务层零依赖具体实现
- 失败不致命：网络挂、key 错，BackgroundService 不会挂
- 优雅降级：未配置 key → 完全不推送，但服务正常运行
- 一码一规一天：dedup 防止 5 秒一次刷屏

使用：
    notifier = SignalNotifier(
        pusher=BarkPusher(device_key="..."),
        deduper=JsonFileDeduper(Path("data/pushed.json")),
    )
    pushed = notifier.notify(signals)  # 返回实际推了的
"""

from .bark import BarkPusher
from .base import Deduper, Pusher, SignalNotifier
from .deduper import JsonFileDeduper

__all__ = [
    "BarkPusher",
    "Deduper",
    "JsonFileDeduper",
    "Pusher",
    "SignalNotifier",
]
