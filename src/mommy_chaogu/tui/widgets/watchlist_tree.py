"""自选股树（TreeView）。

从 data_service.get_watchlist_stocks() 构建分组树。
选中股票节点 → 发 StockSelected 消息通知 QuoteTable 切换。
"""

from __future__ import annotations

import logging

from textual.message import Message
from textual.widgets import Tree
from textual.widgets.tree import TreeNode

_log = logging.getLogger(__name__)


class StockNode:
    """树节点数据：一只自选股。"""

    __slots__ = ("code", "name")

    def __init__(self, code: str, name: str) -> None:
        self.code = code
        self.name = name

    def __repr__(self) -> str:
        return f"{self.code} {self.name}"


class WatchlistTree(Tree[StockNode]):
    """自选股分组树。

    Messages:
        StockSelected: 选中某只股票时触发
    """

    class StockSelected(Message):
        """选中股票节点。"""

        def __init__(self, code: str, name: str) -> None:
            super().__init__()
            self.code = code
            self.name = name

    DEFAULT_CSS = """
    WatchlistTree {
        width: 1fr;
        height: 100%;
        border: round $panel;
        background: $surface;
        padding: 0 1;
    }
    """

    def __init__(self, id: str | None = None) -> None:
        super().__init__("自选股", id=id)
        self._loaded = False
        self._load_task: object = None

    def on_mount(self) -> None:
        """挂载时加载数据。"""
        self.load_data()

    def load_data(self) -> None:
        """从 data_service 重新加载自选股树。"""
        self.clear()
        self.root.set_label("📁 自选股")

        try:
            app = self.app
            data_service = getattr(app, "data_service", None)
            if data_service is None:
                self.root.add_leaf("（数据服务未就绪）", data=None)
                return

            import asyncio

            loop = asyncio.get_event_loop()

            async def _load() -> None:
                grouped = await data_service.get_watchlist_stocks()
                if not grouped:
                    self.root.add_leaf("（暂无自选股）", data=None)
                    self.root.expand()
                    return

                for group_name, stocks in grouped.items():
                    group_node = self.root.add(f"📂 {group_name} ({len(stocks)})")
                    for s in stocks:
                        node = StockNode(s["code"], s["name"])
                        group_node.add_leaf(f"{s['code']} {s['name']}", data=node)
                    group_node.expand()

                self.root.expand()
                self._loaded = True

            self._load_task = loop.create_task(_load())
        except Exception as e:
            _log.warning("加载自选股失败: %s", e)
            self.root.add_leaf(f"（加载失败: {e}）", data=None)
            self.root.expand()

    def on_tree_node_selected(self, event: Tree.NodeSelected) -> None:
        """选中节点时，如果是股票叶子节点，发消息。"""
        node: TreeNode[StockNode] = event.node
        if node.data is not None and isinstance(node.data, StockNode):
            self.post_message(self.StockSelected(code=node.data.code, name=node.data.name))

    def action_refresh(self) -> None:
        """手动刷新（绑定快捷键 R）。"""
        self.load_data()
