"""CacheStore：行情缓存 SQLite 存储。

所有数据带 fetched_at 时间戳，quote_cache 还带 quote_ts（数据自身时间）。
失败时保留旧数据 — 永远不让数据库"消失"一份已有数据。
"""

from __future__ import annotations

import json
from contextlib import contextmanager
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from sqlalchemy import text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import sessionmaker

from mommy_chaogu.cache.schema import SCHEMA_SQL
from mommy_chaogu.cache.serializer import quote_from_dict, quote_to_dict
from mommy_chaogu.db import EngineOwner, create_sqlite_engine
from mommy_chaogu.market_data.adapter import MarketDataAdapter
from mommy_chaogu.market_data.types import AdjustmentType, Bar, BarInterval, MoneyFlow


def _bar_to_dict(bar: Bar) -> dict[str, Any]:
    """Bar → JSON-safe dict（和 CachedMarketDataAdapter 读回格式一致）。"""
    return {
        "code": bar.code,
        "name": bar.name,
        "timestamp": bar.timestamp.isoformat(),
        "interval": bar.interval.value,
        "adjustment": bar.adjustment.value,
        "open": str(bar.open),
        "high": str(bar.high),
        "low": str(bar.low),
        "close": str(bar.close),
        "volume": bar.volume,
        "turnover": str(bar.turnover.amount),
        "change_pct": str(bar.change_pct) if bar.change_pct is not None else None,
        "turnover_rate": str(bar.turnover_rate) if bar.turnover_rate is not None else None,
        "amplitude": str(bar.amplitude) if bar.amplitude is not None else None,
    }


def _money_flow_to_dict(f: MoneyFlow) -> dict[str, Any]:
    """MoneyFlow → JSON-safe dict（和 CachedMarketDataAdapter 格式一致）。"""

    def _money(m: object) -> dict[str, str]:
        if isinstance(m, dict):
            return {"amount": str(m["amount"]), "currency": m.get("currency", "CNY")}
        return {"amount": str(m.amount), "currency": m.currency}  # type: ignore[attr-defined]

    return {
        "code": f.code,
        "name": f.name,
        "timestamp": f.timestamp.isoformat(),
        "main_net": _money(f.main_net),
        "small_net": _money(f.small_net),
        "medium_net": _money(f.medium_net),
        "large_net": _money(f.large_net),
        "super_large_net": _money(f.super_large_net),
        "main_net_ratio": str(f.main_net_ratio) if f.main_net_ratio is not None else None,
    }


def _utcnow() -> datetime:
    return datetime.now(UTC)


@dataclass(frozen=True, slots=True)
class QuoteCacheEntry:
    """quote_cache 表的单行。"""

    code: str
    quote: object  # Quote dataclass
    fetched_at: datetime
    quote_ts: datetime

    @property
    def age_seconds(self) -> float:
        return (_utcnow() - self.fetched_at).total_seconds()


class CacheStore(EngineOwner):
    """SQLite-backed 行情缓存。

    设计原则：
    - 拉新成功 → 覆盖旧数据
    - 拉新失败 → 旧数据保留，外部照常能读
    - 永远不主动删除 quote_cache 的旧数据（除非手动 clear）
    """

    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        db_path.parent.mkdir(parents=True, exist_ok=True)
        self.engine: Engine = create_sqlite_engine(db_path)
        self._manage_engine()
        with self.engine.begin() as conn:
            for stmt in SCHEMA_SQL.strip().split(";"):
                stmt = stmt.strip()
                if stmt:
                    conn.execute(text(stmt))
        self._Session = sessionmaker(self.engine, expire_on_commit=False)

    @contextmanager
    def session(self) -> object:  # type: ignore[no-untyped-def]
        s = self._Session()
        try:
            yield s
            s.commit()
        except Exception:
            s.rollback()
            raise
        finally:
            s.close()

    # ---------- Quote cache ----------

    def get_quote(self, code: str) -> QuoteCacheEntry | None:
        with self.session() as s:
            row = s.execute(
                text(
                    "SELECT code, quote_json, fetched_at, quote_ts FROM quote_cache WHERE code = :code"
                ),
                {"code": code},
            ).first()
            if row is None:
                return None
            quote_dict = json.loads(row[1])
            quote = quote_from_dict(quote_dict)
            return QuoteCacheEntry(
                code=row[0],
                quote=quote,
                fetched_at=row[2]
                if isinstance(row[2], datetime)
                else datetime.fromisoformat(row[2]),
                quote_ts=row[3] if isinstance(row[3], datetime) else datetime.fromisoformat(row[3]),
            )

    def set_quote(self, code: str, quote) -> None:
        """写入/覆盖 quote_cache。"""
        quote_dict = quote_to_dict(quote)
        quote_json = json.dumps(quote_dict, ensure_ascii=False)
        with self.session() as s:
            s.execute(
                text("""
                    INSERT INTO quote_cache (code, quote_json, fetched_at, quote_ts)
                    VALUES (:code, :json, :fetched, :quote_ts)
                    ON CONFLICT(code) DO UPDATE SET
                        quote_json = excluded.quote_json,
                        fetched_at = excluded.fetched_at,
                        quote_ts = excluded.quote_ts
                """),
                {
                    "code": code,
                    "json": quote_json,
                    "fetched": _utcnow(),
                    "quote_ts": quote.timestamp,
                },
            )

    def get_all_quote_codes(self) -> list[str]:
        with self.session() as s:
            rows = s.execute(text("SELECT code FROM quote_cache ORDER BY code")).all()
            return [r[0] for r in rows]

    def get_all_quote_entries(self) -> list[QuoteCacheEntry]:
        with self.session() as s:
            rows = s.execute(
                text(
                    "SELECT code, quote_json, fetched_at, quote_ts FROM quote_cache ORDER BY fetched_at DESC"
                )
            ).all()
            out: list[QuoteCacheEntry] = []
            for row in rows:
                quote_dict = json.loads(row[1])
                quote = quote_from_dict(quote_dict)
                out.append(
                    QuoteCacheEntry(
                        code=row[0],
                        quote=quote,
                        fetched_at=row[2]
                        if isinstance(row[2], datetime)
                        else datetime.fromisoformat(row[2]),
                        quote_ts=row[3]
                        if isinstance(row[3], datetime)
                        else datetime.fromisoformat(row[3]),
                    )
                )
            return out

    # ---------- Bar cache ----------

    def get_bars(
        self,
        code: str,
        interval: str,
        adj_type: str,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> list[dict[str, Any]] | None:
        """返回 [bar_dict, ...]（如果该 code 已有任何缓存）或 None。"""
        with self.session() as s:
            stmt = text("""
                SELECT trade_date, bar_json, fetched_at
                FROM bar_cache
                WHERE code = :code AND interval = :interval AND adj_type = :adj_type
                ORDER BY trade_date
            """)
            rows = s.execute(
                stmt,
                {
                    "code": code,
                    "interval": interval,
                    "adj_type": adj_type,
                },
            ).all()
            if not rows:
                return None
            out: list[dict] = []
            for trade_date, bar_json, _fetched in rows:
                if start_date and trade_date < start_date:
                    continue
                if end_date and trade_date > end_date:
                    continue
                bar_dict = json.loads(bar_json)
                out.append(bar_dict)
            return out

    def set_bar(self, code: str, interval: str, adj_type: str, trade_date: str, bar: dict) -> None:
        bar_json = json.dumps(bar, ensure_ascii=False)
        with self.session() as s:
            s.execute(
                text("""
                    INSERT INTO bar_cache (code, interval, adj_type, trade_date, bar_json, fetched_at)
                    VALUES (:code, :interval, :adj_type, :date, :json, :fetched)
                    ON CONFLICT(code, interval, adj_type, trade_date) DO UPDATE SET
                        bar_json = excluded.bar_json,
                        fetched_at = excluded.fetched_at
                """),
                {
                    "code": code,
                    "interval": interval,
                    "adj_type": adj_type,
                    "date": trade_date,
                    "json": bar_json,
                    "fetched": _utcnow(),
                },
            )

    # ---------- Money flow cache ----------

    def get_today_money_flow(self, code: str) -> list[dict[str, Any]] | None:
        with self.session() as s:
            row = s.execute(
                text(
                    "SELECT flows_json, fetched_at FROM today_money_flow_cache WHERE code = :code"
                ),
                {"code": code},
            ).first()
            if row is None:
                return None
            return json.loads(row[0])

    def set_today_money_flow(self, code: str, flows: list[dict]) -> None:
        flows_json = json.dumps(flows, ensure_ascii=False)
        with self.session() as s:
            s.execute(
                text("""
                    INSERT INTO today_money_flow_cache (code, flows_json, fetched_at)
                    VALUES (:code, :json, :fetched)
                    ON CONFLICT(code) DO UPDATE SET
                        flows_json = excluded.flows_json,
                        fetched_at = excluded.fetched_at
                """),
                {"code": code, "json": flows_json, "fetched": _utcnow()},
            )

    def get_money_flow_history(
        self, code: str, start_date: str | None = None
    ) -> list[dict[str, Any]] | None:
        with self.session() as s:
            stmt = text("""
                SELECT trade_date, flow_json, fetched_at
                FROM money_flow_cache
                WHERE code = :code
                ORDER BY trade_date
            """)
            rows = s.execute(stmt, {"code": code}).all()
            if not rows:
                return None
            out: list[dict] = []
            for trade_date, flow_json, _fetched in rows:
                if start_date and trade_date < start_date:
                    continue
                flows = json.loads(flow_json)
                # flow_json 存的是 list[dict]，用 wrapper 标记 trade_date
                out.append({"__trade_date__": trade_date, "flows": flows})
            return out

    def set_money_flow_history(self, code: str, trade_date: str, flows: list[dict]) -> None:
        flow_json = json.dumps(flows, ensure_ascii=False)
        with self.session() as s:
            s.execute(
                text("""
                    INSERT INTO money_flow_cache (code, trade_date, flow_json, fetched_at)
                    VALUES (:code, :date, :json, :fetched)
                    ON CONFLICT(code, trade_date) DO UPDATE SET
                        flow_json = excluded.flow_json,
                        fetched_at = excluded.fetched_at
                """),
                {"code": code, "date": trade_date, "json": flow_json, "fetched": _utcnow()},
            )

    # ---------- Backfill ----------

    def backfill_history(
        self, adapter: MarketDataAdapter, code: str, days: int = 30
    ) -> dict[str, Any]:
        """批量回填历史 K 线 + 资金流到缓存。

        从 adapter 拉取最近 *days* 天的日 K 线和历史资金流，逐条写入
        bar_cache / money_flow_cache。单条失败不影响其余写入。

        Returns:
            {"code", "days", "bars_written", "flows_written", "errors"}
        """
        result: dict[str, Any] = {
            "code": code,
            "days": days,
            "bars_written": 0,
            "flows_written": 0,
            "errors": [],
        }

        # ---- Bars ----
        interval = BarInterval.D1
        adjustment = AdjustmentType.FORWARD
        interval_str = interval.value
        adj_str = adjustment.value
        try:
            bars = adapter.get_bars(code, interval=interval, adjustment=adjustment, limit=days)
        except Exception as e:
            result["errors"].append(f"bars fetch: {e}")
            bars = []

        for bar in bars:
            try:
                trade_date = bar.timestamp.strftime("%Y-%m-%d")
                self.set_bar(code, interval_str, adj_str, trade_date, _bar_to_dict(bar))
                result["bars_written"] += 1
            except Exception as e:
                result["errors"].append(f"bar {bar.timestamp}: {e}")

        # ---- Money flow ----
        try:
            flows = adapter.get_history_money_flow(code, days=days)
        except Exception as e:
            result["errors"].append(f"money_flow fetch: {e}")
            flows = []

        by_date: dict[str, list[MoneyFlow]] = {}
        for f in flows:
            trade_date = f.timestamp.strftime("%Y-%m-%d")
            by_date.setdefault(trade_date, []).append(f)

        for trade_date, day_flows in by_date.items():
            try:
                flow_dicts = [_money_flow_to_dict(f) for f in day_flows]
                self.set_money_flow_history(code, trade_date, flow_dicts)
                result["flows_written"] += 1
            except Exception as e:
                result["errors"].append(f"flow {trade_date}: {e}")

        return result

    # ---------- Market snapshot cache (保留 N 份历史) ----------

    def save_market_snapshot(self, quotes: list[dict], quote_ts: datetime | None = None) -> int:
        """保存一份全市场快照，返回 id。"""
        quotes_json = json.dumps(quotes, ensure_ascii=False)
        with self.session() as s:
            result = s.execute(
                text("""
                    INSERT INTO market_snapshot_cache (fetched_at, quote_ts, quotes_json, n_codes)
                    VALUES (:fetched, :quote_ts, :json, :n)
                """),
                {
                    "fetched": _utcnow(),
                    "quote_ts": quote_ts,
                    "json": quotes_json,
                    "n": len(quotes),
                },
            )
            return result.lastrowid or 0

    def get_latest_market_snapshot(
        self,
    ) -> tuple[int, datetime, datetime | None, list[dict]] | None:
        """最新一份全市场快照。"""
        with self.session() as s:
            row = s.execute(
                text("""
                    SELECT id, fetched_at, quote_ts, quotes_json
                    FROM market_snapshot_cache
                    ORDER BY id DESC LIMIT 1
                """)
            ).first()
            if row is None:
                return None
            return (
                row[0],
                row[1] if isinstance(row[1], datetime) else datetime.fromisoformat(row[1]),
                row[2]
                if isinstance(row[2], datetime)
                else (datetime.fromisoformat(row[2]) if row[2] else None),
                json.loads(row[3]),
            )

    def list_market_snapshots(self, limit: int = 30) -> list[dict[str, Any]]:
        """列出最近 N 份快照的元信息。"""
        with self.session() as s:
            rows = s.execute(
                text("""
                    SELECT id, fetched_at, quote_ts, n_codes
                    FROM market_snapshot_cache
                    ORDER BY id DESC LIMIT :limit
                """),
                {"limit": limit},
            ).all()
            return [
                {
                    "id": r[0],
                    "fetched_at": r[1],
                    "quote_ts": r[2],
                    "n_codes": r[3],
                }
                for r in rows
            ]

    def trim_market_snapshots(self, keep: int) -> int:
        """保留最新 N 份，删除更早的。返回删除数。"""
        with self.session() as s:
            result = s.execute(
                text("""
                    DELETE FROM market_snapshot_cache
                    WHERE id NOT IN (
                        SELECT id FROM market_snapshot_cache ORDER BY id DESC LIMIT :keep
                    )
                """),
                {"keep": keep},
            )
            return result.rowcount or 0

    # ---------- Stats & clear ----------

    def stats(self) -> dict[str, Any]:
        """缓存统计。"""
        with self.session() as s:
            n_quotes = s.execute(text("SELECT COUNT(*) FROM quote_cache")).scalar() or 0
            n_bars = s.execute(text("SELECT COUNT(*) FROM bar_cache")).scalar() or 0
            n_flows_today = (
                s.execute(text("SELECT COUNT(*) FROM today_money_flow_cache")).scalar() or 0
            )
            n_flows_history = s.execute(text("SELECT COUNT(*) FROM money_flow_cache")).scalar() or 0
            n_snapshots = (
                s.execute(text("SELECT COUNT(*) FROM market_snapshot_cache")).scalar() or 0
            )
        return {
            "quotes": n_quotes,
            "bars": n_bars,
            "flows_today": n_flows_today,
            "flows_history": n_flows_history,
            "snapshots": n_snapshots,
        }

    def clear_quotes(self) -> int:
        with self.session() as s:
            return s.execute(text("DELETE FROM quote_cache")).rowcount or 0

    def clear_all(self) -> None:
        with self.session() as s:
            s.execute(text("DELETE FROM quote_cache"))
            s.execute(text("DELETE FROM bar_cache"))
            s.execute(text("DELETE FROM money_flow_cache"))
            s.execute(text("DELETE FROM today_money_flow_cache"))
            s.execute(text("DELETE FROM market_snapshot_cache"))
