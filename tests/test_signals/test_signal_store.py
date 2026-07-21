"""SignalStore 单测（PLAN 三档 #10）：结构化信号历史存储。

覆盖：
- 建表幂等（重复构造不报错）
- insert + list（升降序、字段完整、Decimal TEXT 精度）
- rule_id / code 过滤
- count
- row_to_signal 转换
"""

from __future__ import annotations

from datetime import datetime
from decimal import Decimal
from pathlib import Path

import pytest

from mommy_chaogu.signals.store import SignalStore
from mommy_chaogu.signals.types import Signal, SignalSeverity


def _make_signal(
    code: str = "600519",
    name: str = "贵州茅台",
    rule_id: str = "price_change",
    severity: SignalSeverity = SignalSeverity.WARNING,
    ts: datetime | None = None,
) -> Signal:
    return Signal(
        timestamp=ts or datetime(2026, 7, 1, 10, 30, 0),
        code=code,
        name=name,
        rule_id=rule_id,
        severity=severity,
        title=f"{name} 涨超 5%",
        detail="现价 1850 涨 6.2%",
        trigger_value=Decimal("6.2"),
        threshold_value=Decimal("5.0"),
        metrics={"change_pct": 6.2},
    )


@pytest.fixture
def store(tmp_path: Path) -> SignalStore:
    return SignalStore(tmp_path / "test_market.db")


class TestSignalStoreSchema:
    def test_idempotent_creation(self, tmp_path: Path) -> None:
        """重复构造同一个 db 不报错（CREATE TABLE IF NOT EXISTS）。"""
        db = tmp_path / "market.db"
        s1 = SignalStore(db)
        s2 = SignalStore(db)
        assert s1.count() == 0
        assert s2.count() == 0
        s1.close()
        s2.close()


class TestSignalStoreInsert:
    def test_insert_and_list(self, store: SignalStore) -> None:
        signals = [_make_signal(code="600519"), _make_signal(code="000001")]
        count = store.insert(signals)
        assert count == 2
        assert store.count() == 2

    def test_empty_insert(self, store: SignalStore) -> None:
        assert store.insert([]) == 0
        assert store.count() == 0

    def test_list_returns_desc_by_timestamp(self, store: SignalStore) -> None:
        early = _make_signal(ts=datetime(2026, 7, 1, 10, 0, 0))
        late = _make_signal(ts=datetime(2026, 7, 2, 14, 0, 0))
        store.insert([early, late])

        rows = store.list(limit=10)
        assert len(rows) == 2
        # 降序：late 在前
        assert rows[0]["timestamp"] >= rows[1]["timestamp"]


class TestSignalStoreQuery:
    def test_filter_by_rule_id(self, store: SignalStore) -> None:
        store.insert(
            [
                _make_signal(rule_id="price_change"),
                _make_signal(rule_id="volume_surge"),
            ]
        )
        rows = store.list(rule_id="price_change")
        assert len(rows) == 1
        assert rows[0]["rule_id"] == "price_change"

    def test_filter_by_code(self, store: SignalStore) -> None:
        store.insert(
            [
                _make_signal(code="600519"),
                _make_signal(code="000001"),
            ]
        )
        rows = store.list(code="600519")
        assert len(rows) == 1
        assert rows[0]["code"] == "600519"

    def test_limit(self, store: SignalStore) -> None:
        signals = [_make_signal(code=f"60000{i}") for i in range(5)]
        store.insert(signals)
        rows = store.list(limit=3)
        assert len(rows) == 3

    def test_decimal_precision_preserved(self, store: SignalStore) -> None:
        store.insert([_make_signal()])
        rows = store.list()
        assert rows[0]["trigger_value"] == Decimal("6.2")
        assert rows[0]["threshold_value"] == Decimal("5.0")

    def test_all_fields_populated(self, store: SignalStore) -> None:
        store.insert([_make_signal()])
        rows = store.list()
        r = rows[0]
        assert r["code"] == "600519"
        assert r["name"] == "贵州茅台"
        assert r["rule_id"] == "price_change"
        assert r["severity"] == "warning"
        assert r["title"] == "贵州茅台 涨超 5%"
        assert r["detail"] == "现价 1850 涨 6.2%"


class TestRowToSignal:
    def test_roundtrip(self, store: SignalStore) -> None:
        original = _make_signal()
        store.insert([original])
        rows = store.list()
        restored = SignalStore.row_to_signal(rows[0])
        assert restored.code == original.code
        assert restored.name == original.name
        assert restored.severity == original.severity
        assert restored.trigger_value == original.trigger_value


class TestAlerterDoubleWrite:
    """Alerter 双写：SignalStore + 旧文本日志兼容。"""

    def test_write_to_store(self, tmp_path: Path) -> None:
        from mommy_chaogu.signals import Alerter

        store = SignalStore(tmp_path / "market.db")
        alerter = Alerter(rules=[], signal_store=store)
        signals = [_make_signal()]

        alerter.write_signals_log(signals)

        assert store.count() == 1
        store.close()

    def test_store_failure_falls_back_to_log(self, tmp_path: Path) -> None:
        from mommy_chaogu.signals import Alerter

        log_path = tmp_path / "signals.log"
        store = SignalStore(tmp_path / "market.db")
        store.close()  # 关闭后 insert 会失败
        alerter = Alerter(rules=[], log_path=log_path, signal_store=store)

        alerter.write_signals_log([_make_signal()])

        # 库写入失败 → 回退文本日志
        assert log_path.exists()
        assert "贵州茅台" in log_path.read_text(encoding="utf-8")

    def test_empty_signals_noop(self, tmp_path: Path) -> None:
        from mommy_chaogu.signals import Alerter

        store = SignalStore(tmp_path / "market.db")
        alerter = Alerter(rules=[], signal_store=store)

        alerter.write_signals_log([])

        assert store.count() == 0
        store.close()
