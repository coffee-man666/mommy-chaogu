"""SemiconStore：半导体产业链参考库 CRUD + 查询。

设计原则（与 watchlist.store 对齐）：
- 接收/返回 ORM 对象，不暴露 Session
- 用 context manager 管理事务
- 「按 code 找」的查询：要么返回对象要么抛 NotFound
- bulk_upsert 做幂等 seed

字段是字符串而非 enum（chain_position / subcategory / board），
是因为这玩意儿是人工维护的 reference，频繁加新分类的话 enum 反而累赘。
不过为了 IDE 提示和打字安全，下面用 ChainPosition / Subcategory 给个常量集合。
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from enum import StrEnum
from pathlib import Path

from sqlalchemy import create_engine, func, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker

from mommy_chaogu.semicon.models import SemiconBase, SemiconStock

# ---------- 常量集合 ----------


class ChainPosition(StrEnum):
    """产业链主位置。"""

    UPSTREAM = "上游"
    MIDSTREAM = "中游"
    DOWNSTREAM = "下游"
    TERMINAL = "末端"


class Subcategory(StrEnum):
    """子分类。允许后续扩展（StrEnum 不限制）。"""

    EDA = "EDA"
    IP = "IP"
    EQUIPMENT = "设备"
    MATERIAL = "材料"
    MEMORY = "存储"
    PROCESSOR = "处理器"
    MCU = "MCU"
    ANALOG = "模拟"
    RF = "射频"
    POWER = "功率"
    SENSOR = "传感器"
    FPGA = "FPGA"
    FOUNDRY = "制造"
    OSAT = "封测"
    DISTRIBUTION = "分销"


class Board(StrEnum):
    """A 股板块。"""

    MAIN = "主板"
    CHINEXT = "创业板"
    STAR = "科创板"
    BSE = "北交所"


# ---------- 异常 ----------


class SemiconError(Exception):
    """semicon 模块基础异常。"""


class StockNotFoundError(SemiconError):
    """指定 code 不存在。"""


class StockAlreadyExistsError(SemiconError):
    """code 重复（仅在严格模式下抛）。"""


# ---------- Store ----------


class SemiconStore:
    """SQLite-backed 半导体产业链参考库。

    用法：
        store = SemiconStore(Path("data/semicon.db"))
        store.bulk_upsert(SEED_STOCKS)
        for s in store.list_by_chain("上游"):
            print(s.code, s.name, s.subcategory)
    """

    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self.engine: Engine = create_engine(
            f"sqlite:///{db_path}",
            echo=False,
            future=True,
        )
        SemiconBase.metadata.create_all(self.engine)
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

    # ---------- 单条 CRUD ----------

    def add(
        self,
        code: str,
        name: str,
        chain_position: str,
        subcategory: str,
        *,
        product: str | None = None,
        board: str = "主板",
        note: str | None = None,
    ) -> SemiconStock:
        """新增一只股票，code 已存在时抛 StockAlreadyExistsError。"""
        with self.session() as s:
            existing = s.execute(
                select(SemiconStock).where(SemiconStock.code == code)
            ).scalar_one_or_none()
            if existing is not None:
                raise StockAlreadyExistsError(f"股票 {code} 已存在")
            row = SemiconStock(
                code=code,
                name=name,
                chain_position=chain_position,
                subcategory=subcategory,
                product=product,
                board=board,
                note=note,
            )
            s.add(row)
            s.flush()
            s.refresh(row)
            return row

    def get(self, code: str) -> SemiconStock | None:
        with self.session() as s:
            return s.execute(
                select(SemiconStock).where(SemiconStock.code == code)
            ).scalar_one_or_none()

    def require(self, code: str) -> SemiconStock:
        row = self.get(code)
        if row is None:
            raise StockNotFoundError(f"股票 {code} 不存在")
        return row

    def remove(self, code: str) -> None:
        with self.session() as s:
            row = s.execute(
                select(SemiconStock).where(SemiconStock.code == code)
            ).scalar_one_or_none()
            if row is None:
                raise StockNotFoundError(f"股票 {code} 不存在")
            s.delete(row)

    def update(
        self,
        code: str,
        *,
        name: str | None = None,
        chain_position: str | None = None,
        subcategory: str | None = None,
        product: str | None = None,
        board: str | None = None,
        note: str | None = None,
    ) -> SemiconStock:
        """更新字段（None 表示不改）。"""
        with self.session() as s:
            row = s.execute(
                select(SemiconStock).where(SemiconStock.code == code)
            ).scalar_one_or_none()
            if row is None:
                raise StockNotFoundError(f"股票 {code} 不存在")
            if name is not None:
                row.name = name
            if chain_position is not None:
                row.chain_position = chain_position
            if subcategory is not None:
                row.subcategory = subcategory
            if product is not None:
                row.product = product
            if board is not None:
                row.board = board
            if note is not None:
                row.note = note
            s.flush()
            s.refresh(row)
            return row

    # ---------- 批量 ----------

    def bulk_upsert(
        self,
        rows: list[tuple[str, str, str, str, str | None, str, str | None]],
        *,
        overwrite: bool = False,
    ) -> dict[str, int]:
        """批量插入/更新。

        Args:
            rows: [(code, name, chain_position, subcategory, product, board, note), ...]
            overwrite: True 时已存在 code 会全字段覆盖；False 时跳过并计入 skipped

        Returns:
            {"inserted": N, "updated": K, "skipped": M}
        """
        inserted = updated = skipped = 0
        with self.session() as s:
            for code, name, cp, sub, prod, board, note in rows:
                existing = s.execute(
                    select(SemiconStock).where(SemiconStock.code == code)
                ).scalar_one_or_none()
                if existing is None:
                    s.add(
                        SemiconStock(
                            code=code,
                            name=name,
                            chain_position=cp,
                            subcategory=sub,
                            product=prod,
                            board=board,
                            note=note,
                        )
                    )
                    inserted += 1
                elif overwrite:
                    existing.name = name
                    existing.chain_position = cp
                    existing.subcategory = sub
                    existing.product = prod
                    existing.board = board
                    existing.note = note
                    updated += 1
                else:
                    skipped += 1
        return {"inserted": inserted, "updated": updated, "skipped": skipped}

    # ---------- 查询 ----------

    def list_all(self) -> list[SemiconStock]:
        """所有股票，按 (chain_position, subcategory, code) 排序。"""
        with self.session() as s:
            stmt = select(SemiconStock).order_by(
                SemiconStock.chain_position,
                SemiconStock.subcategory,
                SemiconStock.code,
            )
            return list(s.execute(stmt).scalars().all())

    def list_by_chain(self, chain_position: str) -> list[SemiconStock]:
        """按主位置过滤。"""
        with self.session() as s:
            stmt = (
                select(SemiconStock)
                .where(SemiconStock.chain_position == chain_position)
                .order_by(SemiconStock.subcategory, SemiconStock.code)
            )
            return list(s.execute(stmt).scalars().all())

    def list_by_subcategory(self, subcategory: str) -> list[SemiconStock]:
        with self.session() as s:
            stmt = (
                select(SemiconStock)
                .where(SemiconStock.subcategory == subcategory)
                .order_by(SemiconStock.code)
            )
            return list(s.execute(stmt).scalars().all())

    def list_codes(self) -> list[str]:
        """所有股票代码（按字母序）。"""
        with self.session() as s:
            rows = s.execute(select(SemiconStock.code).order_by(SemiconStock.code)).scalars().all()
            return list(rows)

    def count_by_chain(self) -> list[tuple[str, int]]:
        """[(chain_position, n), ...]，按主位置分组计数。"""
        with self.session() as s:
            stmt = (
                select(SemiconStock.chain_position, func.count(SemiconStock.id))
                .group_by(SemiconStock.chain_position)
                .order_by(SemiconStock.chain_position)
            )
            return [(cp, n) for cp, n in s.execute(stmt).all()]

    def count_by_subcategory(self) -> list[tuple[str, str, int]]:
        """[(chain_position, subcategory, n), ...]，按 (主位置, 子分类) 分组计数。"""
        with self.session() as s:
            stmt = (
                select(
                    SemiconStock.chain_position,
                    SemiconStock.subcategory,
                    func.count(SemiconStock.id),
                )
                .group_by(SemiconStock.chain_position, SemiconStock.subcategory)
                .order_by(SemiconStock.chain_position, SemiconStock.subcategory)
            )
            return [(cp, sub, n) for cp, sub, n in s.execute(stmt).all()]

    def search(self, keyword: str) -> list[SemiconStock]:
        """按关键字模糊匹配 name / product / note。"""
        like = f"%{keyword}%"
        with self.session() as s:
            stmt = (
                select(SemiconStock)
                .where(
                    SemiconStock.name.like(like)
                    | SemiconStock.product.like(like)
                    | SemiconStock.note.like(like)
                    | SemiconStock.code.like(like)
                )
                .order_by(SemiconStock.code)
            )
            return list(s.execute(stmt).scalars().all())

    # ---------- 统计 ----------

    def stats(self) -> dict[str, int]:
        with self.session() as s:
            n_total = s.execute(select(func.count(SemiconStock.id))).scalar_one()
            n_chain = s.execute(
                select(func.count(func.distinct(SemiconStock.chain_position)))
            ).scalar_one()
            n_sub = s.execute(
                select(func.count(func.distinct(SemiconStock.subcategory)))
            ).scalar_one()
            n_board = s.execute(select(func.count(func.distinct(SemiconStock.board)))).scalar_one()
        return {
            "total": int(n_total),
            "chains": int(n_chain),
            "subcategories": int(n_sub),
            "boards": int(n_board),
        }
