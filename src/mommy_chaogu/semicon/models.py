"""半导体产业链股票 ORM 模型。

一张表 semicon_stocks：
- id 主键
- code 股票代码（unique）
- name 中文名
- chain_position 主位置：上游 / 中游 / 下游 / 末端
- subcategory 子分类：EDA / IP / 设备 / 材料 / 存储 / ... / 分销
- product 具体产品（如「介质刻蚀」「ArF 光刻胶」「DDR 内存接口」）
- board 板块：主板 / 创业板 / 科创板 / 北交所
- note 备注（可空，跨分类公司的「兼：xxx」写在这里）
- created_at / updated_at

字段长度都按实际数据上限放大，没做严格枚举约束（subcategory 故意放开，
方便后续增补新分类时不需要改 schema）。
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import DateTime, Index, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


def _utcnow() -> datetime:
    return datetime.now(UTC)


class SemiconBase(DeclarativeBase):
    """所有 semicon ORM 的基类。"""


class SemiconStock(SemiconBase):
    """半导体产业链内的一只 A 股。"""

    __tablename__ = "semicon_stocks"

    id: Mapped[int] = mapped_column(primary_key=True)

    code: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(64), nullable=False)

    # 主位置：上游 / 中游 / 下游 / 末端
    chain_position: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    # 子分类：EDA / IP / 设备 / 材料 / 存储 / MCU / 处理器 / 模拟 /
    #        射频 / 功率 / 传感器 / FPGA / 制造 / 封测 / 分销
    subcategory: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    # 具体产品（可空）：介质刻蚀 / ArF 光刻胶 / NOR Flash ...
    product: Mapped[str | None] = mapped_column(String(64))

    # 板块：主板 / 创业板 / 科创板 / 北交所
    board: Mapped[str] = mapped_column(String(16), nullable=False)

    # 备注：跨分类、龙头标识等（如「CIS 全球前三 豪威」）
    note: Mapped[str | None] = mapped_column(Text)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        default=_utcnow,
        onupdate=_utcnow,
        nullable=False,
    )

    __table_args__ = (
        UniqueConstraint("code", name="uq_semicon_code"),
        # 联合索引，方便 (chain_position, subcategory) 分组查询
        Index("ix_semicon_chain_sub", "chain_position", "subcategory"),
    )

    def __repr__(self) -> str:
        return f"<SemiconStock {self.code} {self.name} {self.chain_position}/{self.subcategory}>"
