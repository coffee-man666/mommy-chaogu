"""PortfolioStore：持仓 CRUD + 盈亏计算。

和 WatchlistStore 同一个 SQLite 文件，独立表。
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from datetime import date
from decimal import Decimal
from pathlib import Path

from sqlalchemy import create_engine, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, selectinload, sessionmaker

from mommy_chaogu.portfolio.models import (
    PortfolioBase,
    Position,
    PositionAdjustment,
)


class PortfolioError(Exception):
    """portfolio 模块基础异常。"""


class PositionNotFoundError(PortfolioError):
    """持仓不存在。"""


class PortfolioStore:
    """SQLite-backed 持仓存储。

    用法：
        store = PortfolioStore(Path("data/portfolio.db"))
        pos = store.add_position("600519", "贵州茅台", Decimal("1800"), 100)
        summary = store.summary({"600519": Decimal("1850")})
    """

    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self.engine: Engine = create_engine(
            f"sqlite:///{db_path}",
            echo=False,
            future=True,
        )
        with self.engine.begin() as conn:
            from sqlalchemy import text

            conn.execute(text("PRAGMA foreign_keys = ON"))
        PortfolioBase.metadata.create_all(self.engine)
        self._Session = sessionmaker(self.engine, expire_on_commit=False)

    @contextmanager
    def session(self) -> Iterator[Session]:
        s = self._Session()
        try:
            yield s
            s.commit()
        except Exception:
            s.rollback()
            raise
        finally:
            s.close()

    # ---------- Position CRUD ----------

    def add_position(
        self,
        code: str,
        name: str | None,
        buy_price: Decimal,
        shares: int,
        buy_date: date | None = None,
        note: str | None = None,
    ) -> Position:
        """录入一笔新持仓。同 code 可有多笔（不同批次）。"""
        with self.session() as s:
            pos = Position(
                code=code,
                name=name,
                buy_price=str(buy_price),
                shares=shares,
                buy_date=buy_date,
                note=note,
            )
            s.add(pos)
            s.flush()
            s.refresh(pos)
            return pos

    def get_position(self, position_id: int) -> Position:
        """按 id 获取持仓（含 adjustments）。"""
        with self.session() as s:
            pos = s.execute(
                select(Position)
                .options(selectinload(Position.adjustments))
                .where(Position.id == position_id)
            ).scalar_one_or_none()
            if pos is None:
                raise PositionNotFoundError(f"持仓 id={position_id} 不存在")
            return pos

    def list_positions(self) -> list[Position]:
        """所有持仓（含 adjustments），按 code 排序。"""
        with self.session() as s:
            return list(
                s.execute(
                    select(Position)
                    .options(selectinload(Position.adjustments))
                    .order_by(Position.code)
                )
                .scalars()
                .all()
            )

    def remove_position(self, position_id: int) -> None:
        """删除持仓（级联删 adjustments）。"""
        with self.session() as s:
            pos = s.execute(select(Position).where(Position.id == position_id)).scalar_one_or_none()
            if pos is None:
                raise PositionNotFoundError(f"持仓 id={position_id} 不存在")
            s.delete(pos)

    def update_position_name(self, code: str, name: str) -> int:
        """行情拉到名字后回填，返回更新数。"""
        with self.session() as s:
            positions = s.execute(select(Position).where(Position.code == code)).scalars().all()
            for p in positions:
                if p.name is None:
                    p.name = name
            return len(positions)

    # ---------- Adjustment CRUD ----------

    def add_adjustment(
        self,
        position_id: int,
        action: str,
        price: Decimal,
        shares: int,
        note: str | None = None,
    ) -> PositionAdjustment:
        """添加加减仓记录。action: buy / sell / dividend。"""
        if action not in ("buy", "sell", "dividend"):
            raise PortfolioError(f"不支持的 action: {action!r}")
        if shares <= 0:
            raise PortfolioError("shares 必须为正数")

        with self.session() as s:
            pos = s.execute(select(Position).where(Position.id == position_id)).scalar_one_or_none()
            if pos is None:
                raise PositionNotFoundError(f"持仓 id={position_id} 不存在")

            adj = PositionAdjustment(
                position_id=position_id,
                action=action,
                price=str(price),
                shares=shares,
                note=note,
            )
            s.add(adj)

            # 同步更新 Position 的 shares（buy +, sell -）
            if action == "buy":
                pos.shares += shares
            elif action == "sell":
                pos.shares = max(0, pos.shares - shares)

            s.flush()
            s.refresh(adj)
            return adj

    def list_adjustments(self, position_id: int) -> list[PositionAdjustment]:
        """某持仓的所有调整记录。"""
        with self.session() as s:
            return list(
                s.execute(
                    select(PositionAdjustment)
                    .where(PositionAdjustment.position_id == position_id)
                    .order_by(PositionAdjustment.timestamp)
                )
                .scalars()
                .all()
            )

    # ---------- 计算 ----------

    def cost_basis(self, position: Position) -> tuple[Decimal, int]:
        """计算加权平均成本价和总股数。

        返回 (avg_cost, total_shares)。
        - 初始买入 + 所有 buy adjustments 计入成本
        - sell 减少股数但不改变总成本（已实现盈亏在卖出时锁定）
        - dividend 减少总成本（分红返还）
        """
        total_cost = Decimal(position.buy_price) * position.shares
        total_shares = position.shares

        for adj in position.adjustments:
            adj_price = Decimal(adj.price)
            if adj.action == "buy":
                total_cost += adj_price * adj.shares
                # total_shares 已在 add_adjustment 同步
            elif adj.action == "sell":
                # 减仓：按比例减少成本
                if total_shares > 0:
                    cost_per_share = total_cost / total_shares
                    total_cost -= cost_per_share * adj.shares
            elif adj.action == "dividend":
                total_cost -= adj_price * adj.shares

        # total_shares 从 position 拿（已同步）
        if total_shares <= 0:
            return Decimal("0"), 0

        avg_cost = total_cost / total_shares
        return avg_cost.quantize(Decimal("0.0001")), total_shares

    def summary(
        self,
        current_prices: dict[str, Decimal],
    ) -> dict[str, object]:
        """计算全局持仓概要。

        参数：
            current_prices: {code: 当前价格}

        返回：
            {
                "positions": [
                    {
                        "position": Position,
                        "avg_cost": Decimal,
                        "shares": int,
                        "current_price": Decimal | None,
                        "market_value": Decimal | None,
                        "total_cost": Decimal,
                        "unrealized_pnl": Decimal | None,
                        "unrealized_pnl_pct": Decimal | None,
                    },
                    ...
                ],
                "total_cost": Decimal,
                "total_market_value": Decimal,
                "total_unrealized_pnl": Decimal,
                "total_unrealized_pnl_pct": Decimal,
                "n_positions": int,
            }
        """
        positions_data: list[dict[str, object]] = []
        grand_cost = Decimal("0")
        grand_market = Decimal("0")
        has_market = False

        for pos in self.list_positions():
            avg_cost, shares = self.cost_basis(pos)
            total_cost = avg_cost * shares
            cur_price = current_prices.get(pos.code)
            if cur_price is not None and shares > 0:
                market_value = cur_price * shares
                pnl = market_value - total_cost
                pnl_pct = (pnl / total_cost * Decimal("100")) if total_cost > 0 else Decimal("0")
                grand_market += market_value
                has_market = True
            else:
                market_value = None
                pnl = None
                pnl_pct = None

            grand_cost += total_cost

            positions_data.append(
                {
                    "position": pos,
                    "avg_cost": avg_cost,
                    "shares": shares,
                    "current_price": cur_price,
                    "market_value": market_value,
                    "total_cost": total_cost,
                    "unrealized_pnl": pnl,
                    "unrealized_pnl_pct": pnl_pct,
                }
            )

        total_pnl = (grand_market - grand_cost) if has_market else None
        total_pnl_pct = (
            (total_pnl / grand_cost * Decimal("100"))
            if has_market and total_pnl is not None and grand_cost > 0
            else None
        )

        return {
            "positions": positions_data,
            "total_cost": grand_cost,
            "total_market_value": grand_market if has_market else None,
            "total_unrealized_pnl": total_pnl,
            "total_unrealized_pnl_pct": total_pnl_pct,
            "n_positions": len(positions_data),
        }
