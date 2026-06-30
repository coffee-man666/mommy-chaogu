"""持仓 ORM 模型。

设计：
- Position 记录一只股票的持仓（买入价 + 股数）
- PositionAdjustment 记录后续加减仓 / 分红
- 平均成本价 = 加权平均（含 adjustments）
- 和 watchlist.StockEntry 同一个 SQLite，独立表（不 FK 到 stock_entries，
  因为持仓可以在加入自选池之前就录入）
"""
from __future__ import annotations

from datetime import UTC, date, datetime

from sqlalchemy import (
    Date,
    DateTime,
    ForeignKey,
    Index,
    String,
    Text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship


def _utcnow() -> datetime:
    return datetime.now(UTC)


class PortfolioBase(DeclarativeBase):
    """所有 portfolio ORM 的基类。"""


class Position(PortfolioBase):
    """一笔持仓。"""

    __tablename__ = "positions"

    id: Mapped[int] = mapped_column(primary_key=True)
    code: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    name: Mapped[str | None] = mapped_column(String(64))
    # 初始买入价（首次录入）
    buy_price: Mapped[str] = mapped_column(String(32), nullable=False)
    # 初始股数
    shares: Mapped[int] = mapped_column(nullable=False)
    # 买入日期
    buy_date: Mapped[date | None] = mapped_column(Date)
    note: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, onupdate=_utcnow, nullable=False
    )

    adjustments: Mapped[list[PositionAdjustment]] = relationship(
        back_populates="position",
        cascade="all, delete-orphan",
        passive_deletes=True,
        order_by="PositionAdjustment.timestamp",
    )

    __table_args__ = (
        Index("ix_position_code", "code"),
    )

    def __repr__(self) -> str:
        return f"<Position {self.code} ({self.name or '?'}) shares={self.shares}>"


class PositionAdjustment(PortfolioBase):
    """加减仓 / 分红记录。"""

    __tablename__ = "position_adjustments"

    id: Mapped[int] = mapped_column(primary_key=True)
    position_id: Mapped[int] = mapped_column(
        ForeignKey("positions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    # buy=加仓, sell=减仓, dividend=分红
    action: Mapped[str] = mapped_column(String(16), nullable=False)
    price: Mapped[str] = mapped_column(String(32), nullable=False)
    shares: Mapped[int] = mapped_column(nullable=False)  # 正数
    timestamp: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )
    note: Mapped[str | None] = mapped_column(Text)

    position: Mapped[Position] = relationship(back_populates="adjustments")

    def __repr__(self) -> str:
        return f"<PositionAdjustment {self.action} {self.shares} @ {self.price}>"
