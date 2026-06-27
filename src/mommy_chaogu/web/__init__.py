"""Web 后端：FastAPI + WebSocket。

设计原则（参考 docs/DESIGN.md）：
- P0 接口先行：业务层零依赖具体实现
- P2 数据库是唯一真相源：复用现有 cache / fallback 装饰器链
- P4 装饰器链：CachedMarketDataAdapter(FallbackAdapter([Efinance, Tencent]))
- 不动 market_data / watchlist / monitor / signals / cache 任何已有代码
"""
from mommy_chaogu.web.app import create_app

__all__ = ["create_app"]
