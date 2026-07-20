"""工具层：把现有数据接口包装成 function-calling tools。

包结构：
- base.py: ToolDef / ToolContext / ToolHandler + JSON 序列化辅助
- quote / sector / flows / bars / holdings / intel / alerts / memory / themes:
  按域划分的工具定义（DEFS）与实现（HANDLERS）
- registry.py: ToolRegistry（聚合各域模块，查找 + 调用）

所有 handler 是同步函数，内部直接调 adapter（已被 CachedMarketDataAdapter 包装）。
AgentService 负责用 asyncio.to_thread 包装。
"""

from mommy_chaogu.agent.tools.base import ToolContext, ToolDef, ToolHandler
from mommy_chaogu.agent.tools.registry import ToolRegistry

__all__ = [
    "ToolContext",
    "ToolDef",
    "ToolHandler",
    "ToolRegistry",
]
