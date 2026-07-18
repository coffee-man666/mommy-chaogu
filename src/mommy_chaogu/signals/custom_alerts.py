"""用户自定义价格/涨跌幅告警。

设计：
- CustomAlert 是不可变 dataclass（frozen + slots），作为公开 API 的返回值
- CustomAlertStore 用 SQLAlchemy ORM 管理 SQLite 持久化，内部转换成 dataclass
- evaluate 是纯静态方法，接收 CustomAlert + Quote，返回是否触发
- 和 watchlist/portfolio 共用同一份 data/portfolio.db，独立表 custom_alerts
"""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal
from pathlib import Path

from sqlalchemy import (
    Boolean,
    DateTime,
    Integer,
    String,
    select,
)
from sqlalchemy.engine import Engine
from sqlalchemy.orm import (
    DeclarativeBase,
    Mapped,
    Session,
    mapped_column,
    sessionmaker,
)

from mommy_chaogu.db import EngineOwner, create_sqlite_engine
from mommy_chaogu.market_data.types import Quote

# ---------- 常量 ----------

VALID_CONDITIONS: tuple[str, ...] = (
    "price_above",
    "price_below",
    "change_pct_above",
    "change_pct_below",
)


# ---------- 公开 dataclass ----------


@dataclass(frozen=True, slots=True)
class CustomAlert:
    """一条用户自定义告警。"""

    code: str
    name: str
    condition: str  # price_above / price_below / change_pct_above / change_pct_below
    threshold: Decimal
    enabled: bool = True
    id: int | None = None  # None 表示尚未持久化


# ---------- ORM 模型 ----------


def _utcnow() -> datetime:
    return datetime.now(UTC)


class CustomAlertBase(DeclarativeBase):
    """自定义告警 ORM 基类。"""


class _CustomAlertModel(CustomAlertBase):
    """custom_alerts 表 ORM 模型（内部用）。"""

    __tablename__ = "custom_alerts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    code: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    condition: Mapped[str] = mapped_column(String(32), nullable=False)
    threshold: Mapped[str] = mapped_column(String(32), nullable=False)  # Decimal as text
    enabled: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=_utcnow, nullable=False
    )

    def to_dataclass(self) -> CustomAlert:
        return CustomAlert(
            id=self.id,
            code=self.code,
            name=self.name,
            condition=self.condition,
            threshold=Decimal(self.threshold),
            enabled=self.enabled,
        )


# ---------- 异常 ----------


class CustomAlertError(Exception):
    """custom_alerts 模块基础异常。"""


class CustomAlertNotFoundError(CustomAlertError):
    """告警不存在。"""


class InvalidConditionError(CustomAlertError):
    """不支持的 condition 类型。"""


# ---------- Store ----------


class CustomAlertStore(EngineOwner):
    """SQLite-backed 自定义告警存储。

    用法：
        store = CustomAlertStore(Path("data/portfolio.db"))
        store.add("600519", "贵州茅台", "price_below", Decimal("1600"))
        for a in store.list_all():
            print(a)
    """

    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self.engine: Engine = create_sqlite_engine(db_path)
        self._manage_engine()
        CustomAlertBase.metadata.create_all(self.engine)
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

    def add(
        self,
        code: str,
        name: str,
        condition: str,
        threshold: Decimal,
    ) -> CustomAlert:
        """添加一条告警。condition 不合法时抛 InvalidConditionError。"""
        if condition not in VALID_CONDITIONS:
            raise InvalidConditionError(
                f"不支持的 condition: {condition!r}，可选: {VALID_CONDITIONS}"
            )
        with self.session() as s:
            row = _CustomAlertModel(
                code=code,
                name=name,
                condition=condition,
                threshold=str(threshold),
                enabled=True,
            )
            s.add(row)
            s.flush()
            s.refresh(row)
            return row.to_dataclass()

    def remove(self, alert_id: int) -> None:
        """按 id 删除告警。不存在时抛 CustomAlertNotFoundError。"""
        with self.session() as s:
            row = s.execute(
                select(_CustomAlertModel).where(_CustomAlertModel.id == alert_id)
            ).scalar_one_or_none()
            if row is None:
                raise CustomAlertNotFoundError(f"告警 id={alert_id} 不存在")
            s.delete(row)

    def list_all(self) -> list[CustomAlert]:
        """列出所有告警，按 id 排序。"""
        with self.session() as s:
            rows = (
                s.execute(select(_CustomAlertModel).order_by(_CustomAlertModel.id)).scalars().all()
            )
            return [r.to_dataclass() for r in rows]

    def list_for_code(self, code: str) -> list[CustomAlert]:
        """列出某只股票的所有告警，按 id 排序。"""
        with self.session() as s:
            rows = (
                s.execute(
                    select(_CustomAlertModel)
                    .where(_CustomAlertModel.code == code)
                    .order_by(_CustomAlertModel.id)
                )
                .scalars()
                .all()
            )
            return [r.to_dataclass() for r in rows]

    @staticmethod
    def evaluate(alert: CustomAlert, quote: Quote) -> bool:
        """检查告警是否被当前报价触发。

        - price_above:     quote.price > threshold
        - price_below:     quote.price < threshold
        - change_pct_above:  quote.change_pct > threshold
        - change_pct_below:  quote.change_pct < threshold

        disabled 的告警永远返回 False。
        """
        if not alert.enabled:
            return False
        if alert.condition == "price_above":
            return quote.price > alert.threshold
        elif alert.condition == "price_below":
            return quote.price < alert.threshold
        elif alert.condition == "change_pct_above":
            return quote.change_pct > alert.threshold
        elif alert.condition == "change_pct_below":
            return quote.change_pct < alert.threshold
        return False
