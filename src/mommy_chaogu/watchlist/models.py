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
from decimal import Decimal

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    Numeric,
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


class BasketPreference(WatchlistBase):
    """用户对统一主题/篮子的展示偏好。

    ``basket_id`` 使用稳定命名空间：内置主题为 ``theme:<id>``，自选分组为
    ``group:<database id>``。定义数据仍由主题文件和自选分组持有，本表只保存
    用户偏好，避免复制成分股。
    """

    __tablename__ = "basket_preferences"

    basket_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    followed: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    hidden: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    sort_order: Mapped[int | None] = mapped_column(Integer)
    reason: Mapped[str | None] = mapped_column(Text)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False
    )


class BasketMemberPreference(WatchlistBase):
    """Optional user-defined member weight for a canonical basket."""

    __tablename__ = "basket_member_preferences"

    basket_id: Mapped[str] = mapped_column(String(128), primary_key=True)
    code: Mapped[str] = mapped_column(String(16), primary_key=True)
    weight: Mapped[Decimal] = mapped_column(Numeric(10, 4), nullable=False)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False
    )
