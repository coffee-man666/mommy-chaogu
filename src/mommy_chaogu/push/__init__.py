"""微信推送模块（Server酱）。

设计原则（参考 docs/DESIGN.md）：
- 接口先行：Notifier / Pusher / Deduper 都是 Protocol，业务层零依赖具体实现
- 失败不致命：网络挂、SendKey 错，BackgroundService 不会挂
- 优雅降级：未配置 SendKey → 完全不推送，但服务正常运行
- 一码一规一天：dedup 防止 5 秒一次刷屏

使用：
    notifier = SignalNotifier(
        pusher=ServerChanPusher(send_key="SCT..."),
        deduper=JsonFileDeduper(Path("data/pushed.json")),
    )
    pushed = notifier.notify(signals)  # 返回实际推了的
"""

from .base import Deduper, Pusher, SignalNotifier
from .deduper import JsonFileDeduper
from .server_chan import ServerChanPusher

__all__ = [
    "Deduper",
    "JsonFileDeduper",
    "Pusher",
    "ServerChanPusher",
    "SignalNotifier",
]
