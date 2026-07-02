"""自选股 ORM 模型。

设计：
- 单个 Watchlist（隐式，所有 group 共享一个池子，未来需要多池子再加 Watchlist 表）
- Group：分类（白酒/银行/...），name 全局唯一
- StockEntry：一只自选股，所属一个 Group
  - (code, group_id) 唯一约束：同一分组内不能重复
  - 不同分组可以重复（妈妈可能同时在「白酒」和「长线」里都加茅台）
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def _utcnow() -> datetime:
    return datetime.now(UTC)


class WatchlistBase(DeclarativeBase):
    """所有 watchlist ORM 的基类。"""


class Group(WatchlistBase):
    """自选分组。"""

    __tablename__ = "groups"

    id: Mapped[int] = mapped_column(primary_key=True)
    name: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )

    entries: Mapped[list[StockEntry]] = relationship(
        back_populates="group",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )

    def __repr__(self) -> str:
        n_entries = len(self.entries) if self.entries else 0
        return f"<Group {self.name} entries={n_entries}>"


class StockEntry(WatchlistBase):
    """一只自选股。"""

    __tablename__ = "stock_entries"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    # 名称首次添加时为 None，拉到行情后回填
    name: Mapped[str | None] = mapped_column(String(64))
    group_id: Mapped[int] = mapped_column(
        ForeignKey("groups.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )

    group: Mapped[Group] = relationship(back_populates="entries")

    __table_args__ = (
        UniqueConstraint("code", "group_id", name="uq_stock_code_group"),
        Index("ix_stock_code", "code"),
    )

    def __repr__(self) -> str:
        return f"<StockEntry {self.code} ({self.name or '?'}) group_id={self.group_id}>"
