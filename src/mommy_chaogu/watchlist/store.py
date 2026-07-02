"""WatchlistStore：自选池 CRUD。

API 设计原则：
- 接收/返回 dataclass 友好的对象（Group / StockEntry），不暴露 SQLAlchemy Session
- 用 context manager 管理事务
- 所有"按 name/code 找"的查询，要么返回对象要么抛 NotFound，让调用方决定怎么处理
- 重复 add 静默返回已有对象（幂等），方便 CLI 反复执行
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import create_engine, select
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, joinedload, sessionmaker

from mommy_chaogu.watchlist.models import Group, StockEntry, WatchlistBase


class WatchlistError(Exception):
    """watchlist 模块基础异常。"""


class GroupNotFoundError(WatchlistError):
    """分组不存在。"""


class GroupAlreadyExistsError(WatchlistError):
    """分组重名。"""


class StockEntryNotFoundError(WatchlistError):
    """自选股不存在。"""


class WatchlistStore:
    """SQLite-backed 自选池存储。

    用法：
        store = WatchlistStore(Path("data/watchlist.db"))
        store.add_group("白酒", description="白酒板块")
        store.add_entry("600519", "白酒", note="妈妈长期持有")
        for entry in store.list_entries():
            print(entry.code, entry.group.name)
    """

    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self.engine: Engine = create_engine(
            f"sqlite:///{db_path}",
            echo=False,
            future=True,
        )
        # SQLite 外键默认关，开一下
        with self.engine.begin() as conn:
            from sqlalchemy import text

            conn.execute(text("PRAGMA foreign_keys = ON"))
        # 创建表
        WatchlistBase.metadata.create_all(self.engine)
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

    # ---------- Group CRUD ----------

    def add_group(self, name: str, description: str | None = None) -> Group:
        """新建分组。重名时抛 GroupAlreadyExistsError。"""
        with self.session() as s:
            existing = s.execute(select(Group).where(Group.name == name)).scalar_one_or_none()
            if existing is not None:
                raise GroupAlreadyExistsError(f"分组已存在: {name!r}")
            g = Group(name=name, description=description)
            s.add(g)
            s.flush()
            s.refresh(g)
            return g

    def get_or_create_group(self, name: str, description: str | None = None) -> Group:
        """查找分组，没有则新建（幂等）。"""
        with self.session() as s:
            existing = s.execute(select(Group).where(Group.name == name)).scalar_one_or_none()
            if existing is not None:
                return existing
            g = Group(name=name, description=description)
            s.add(g)
            s.flush()
            s.refresh(g)
            return g

    def get_group(self, name: str) -> Group | None:
        with self.session() as s:
            return s.execute(select(Group).where(Group.name == name)).scalar_one_or_none()

    def require_group(self, name: str) -> Group:
        g = self.get_group(name)
        if g is None:
            raise GroupNotFoundError(f"分组不存在: {name!r}")
        return g

    def list_groups(self) -> list[tuple[Group, int]]:
        """返回 [(Group, entry_count), ...]，按组名排序。"""
        with self.session() as s:
            from sqlalchemy import func

            stmt = (
                select(Group, func.count(StockEntry.id).label("n_entries"))
                .outerjoin(StockEntry, StockEntry.group_id == Group.id)
                .group_by(Group.id)
                .order_by(Group.name)
            )
            return [(g, n_entries) for g, n_entries in s.execute(stmt).all()]

    def remove_group(self, name: str) -> None:
        """删除分组（级联删 entry）。"""
        with self.session() as s:
            g = s.execute(select(Group).where(Group.name == name)).scalar_one_or_none()
            if g is None:
                raise GroupNotFoundError(f"分组不存在: {name!r}")
            s.delete(g)

    # ---------- StockEntry CRUD ----------

    def add_entry(self, code: str, group_name: str, note: str | None = None) -> StockEntry:
        """添加自选股到指定分组。

        - 分组不存在抛 GroupNotFoundError
        - 同一分组内重复添加返回已有 entry（幂等）
        - 不同分组可以重复添加
        - 返回的 entry 已 eagerly 加载 group 属性（session 关闭后仍可访问）
        """
        with self.session() as s:
            g = s.execute(select(Group).where(Group.name == group_name)).scalar_one_or_none()
            if g is None:
                raise GroupNotFoundError(f"分组不存在: {group_name!r}")
            existing = s.execute(
                select(StockEntry)
                .options(joinedload(StockEntry.group))
                .where(StockEntry.group_id == g.id, StockEntry.code == code)
            ).scalar_one_or_none()
            if existing is not None:
                return existing
            entry = StockEntry(code=code, group_id=g.id, note=note)
            s.add(entry)
            s.flush()
            s.refresh(entry)
            # 重新查询并 joinedload group
            result = s.execute(
                select(StockEntry)
                .options(joinedload(StockEntry.group))
                .where(StockEntry.id == entry.id)
            ).scalar_one()
            return result

    def remove_entry(self, code: str, group_name: str) -> None:
        """从指定分组删除自选股。"""
        with self.session() as s:
            g = s.execute(select(Group).where(Group.name == group_name)).scalar_one_or_none()
            if g is None:
                raise GroupNotFoundError(f"分组不存在: {group_name!r}")
            entry = s.execute(
                select(StockEntry).where(StockEntry.group_id == g.id, StockEntry.code == code)
            ).scalar_one_or_none()
            if entry is None:
                raise StockEntryNotFoundError(f"自选股 {code} 不在分组 {group_name!r}")
            s.delete(entry)

    def list_entries(self, group_name: str | None = None) -> list[StockEntry]:
        """列出所有（或指定分组）自选股，按 (group.name, code) 排序。

        joinedload(Group) 确保 session 关闭后 entry.group 仍可访问。
        """
        with self.session() as s:
            stmt = (
                select(StockEntry)
                .join(Group)
                .options(joinedload(StockEntry.group))
                .order_by(Group.name, StockEntry.code)
            )
            if group_name is not None:
                stmt = stmt.where(Group.name == group_name)
            return list(s.execute(stmt).scalars().unique().all())

    def list_entries_by_group(self) -> dict[str, list[StockEntry]]:
        """按分组返回 {group_name: [entries]}，按组名排序。"""
        with self.session() as s:
            groups = list(s.execute(select(Group).order_by(Group.name)).scalars().all())
            result: dict[str, list[StockEntry]] = {}
            for g in groups:
                result[g.name] = list(
                    s.execute(
                        select(StockEntry)
                        .options(joinedload(StockEntry.group))
                        .where(StockEntry.group_id == g.id)
                        .order_by(StockEntry.code)
                    )
                    .scalars()
                    .unique()
                    .all()
                )
            return result

    def get_all_codes(self) -> list[str]:
        """所有自选股的 code 列表（去重）。"""
        with self.session() as s:
            rows = s.execute(select(StockEntry.code).distinct()).scalars().all()
            return list(rows)

    # ---------- Backfill name ----------

    def backfill_name(self, code: str, name: str) -> int:
        """拉取行情后回填 name 字段，返回更新的 entry 数。"""
        with self.session() as s:
            entries = s.execute(select(StockEntry).where(StockEntry.code == code)).scalars().all()
            for e in entries:
                e.name = name
            return len(entries)

    # ---------- Stats ----------

    def stats(self) -> dict[str, int]:
        """汇总统计：分组数 / 自选股数 / 唯一股票数。"""
        with self.session() as s:
            from sqlalchemy import func

            n_groups = s.execute(select(func.count(Group.id))).scalar_one()
            n_entries = s.execute(select(func.count(StockEntry.id))).scalar_one()
            n_distinct = s.execute(select(func.count(func.distinct(StockEntry.code)))).scalar_one()
        return {
            "groups": n_groups,
            "entries": n_entries,
            "codes": n_distinct,
        }
