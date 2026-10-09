"""阶段五：earnings 日频任务（pull + score + evaluate → Signal）单测。

离线：EarningsAdapter 用 fake（可控增速与披露日），preview 库用迷你 SQLite。
覆盖：
- 近期披露的 score → beat / miss 信号；超窗口的旧披露不再评估
- 披露临近（日历 + 前瞻预测）→ approaching 信号；日历为空不伪造
- 环境变量开关 / 空 codes 不触网络
- current_report_period 启发式
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

from mommy_chaogu.earnings.daily import (
    current_report_period,
    run_daily,
)
from mommy_chaogu.earnings.service import EarningsService
from mommy_chaogu.earnings.store import EarningsStore
from mommy_chaogu.earnings.types import (
    EarningsActual,
    EarningsCalendar,
    EarningsSource,
)
from mommy_chaogu.signals.custom_evaluation import MOMMY_ALERTS_BUILTIN_ONLY_ENV

TODAY = date(2026, 10, 1)


class FakeEarningsAdapter:
    """可控 fake：按 (code, period) 返回预设 actual，记录调用。"""

    name = "fake"

    def __init__(self, actuals: dict[tuple[str, str], EarningsActual]) -> None:
        self._actuals = actuals
        self.fetch_calls: list[tuple[str, str]] = []

    def fetch_actual(
        self,
        code: str,
        period: str,
        *,
        since: date | None = None,
    ) -> list[EarningsActual]:
        self.fetch_calls.append((code, period))
        actual = self._actuals.get((code, period))
        return [actual] if actual is not None else []

    def fetch_calendar(self, code: str, *, since: date | None = None) -> list[EarningsCalendar]:
        return []


def _actual(code: str, name: str, period: str, growth: str, disclosure: date) -> EarningsActual:
    growth_d = Decimal(growth)
    return EarningsActual(
        code=code,
        name=name,
        period=period,
        actual_value=Decimal("100000000") * (Decimal("1") + growth_d / Decimal("100")),
        growth_pct=growth_d,
        disclosure_date=disclosure,
        source=EarningsSource.REPORT,
        note="fake",
        fetched_at=datetime.now(UTC),
    )


def _preview_db(tmp_path: Path) -> Path:
    db_path = tmp_path / "preview.db"
    conn = sqlite3.connect(str(db_path))
    conn.executescript(
        """
        CREATE TABLE earnings_preview (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            code TEXT NOT NULL,
            name TEXT NOT NULL,
            sector TEXT,
            subsector TEXT,
            growth_low REAL NOT NULL,
            growth_high REAL NOT NULL,
            growth_mid REAL NOT NULL,
            growth_text TEXT,
            core_driver TEXT,
            highlight TEXT,
            report_period TEXT NOT NULL,
            report_source TEXT NOT NULL,
            report_date TEXT NOT NULL,
            watchlist_flag INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        INSERT INTO earnings_preview
            (code, name, sector, subsector, growth_low, growth_high, growth_mid,
             growth_text, core_driver, highlight,
             report_period, report_source, report_date)
        VALUES
            ('603662', '柯力传感', '传感器', '六维力',
             188.0, 217.0, 202.5, '+188%~+217%', '机器人/工业', '⭐',
             'H1 2026', '中信证券', '2026-07-02'),
            ('603986', '兆易创新', '半导体', '存储',
             1070.0, 1370.0, 1220.0, '+1070%~+1370%', 'AI/涨价', '...',
             'H1 2026', '中信证券', '2026-07-02');
        """
    )
    conn.commit()
    conn.close()
    return db_path


def _service(tmp_path: Path, adapter: FakeEarningsAdapter) -> EarningsService:
    store = EarningsStore(tmp_path / "actual.db")
    return EarningsService(adapter, store, _preview_db(tmp_path))


# ---------- current_report_period ----------


def test_current_report_period() -> None:
    assert current_report_period(date(2026, 10, 1)) == "Q3 2026"
    assert current_report_period(date(2026, 12, 31)) == "Q3 2026"
    assert current_report_period(date(2026, 7, 1)) == "H1 2026"
    assert current_report_period(date(2026, 9, 30)) == "H1 2026"
    assert current_report_period(date(2026, 1, 1)) == "FY 2025"
    assert current_report_period(date(2026, 6, 30)) == "FY 2025"


# ---------- list_preview_periods ----------


def test_list_preview_periods(tmp_path: Path) -> None:
    svc = _service(tmp_path, FakeEarningsAdapter({}))
    assert svc.list_preview_periods() == ["H1 2026"]


def test_list_preview_periods_missing_table(tmp_path: Path) -> None:
    empty = tmp_path / "empty.db"
    conn = sqlite3.connect(str(empty))
    conn.execute("CREATE TABLE other (x TEXT)")
    conn.commit()
    conn.close()
    store = EarningsStore(tmp_path / "actual.db")
    svc = EarningsService(FakeEarningsAdapter({}), store, empty)
    assert svc.list_preview_periods() == []


def test_load_prediction(tmp_path: Path) -> None:
    svc = _service(tmp_path, FakeEarningsAdapter({}))
    name, low, high = svc.load_prediction("603662", "H1 2026")  # type: ignore[misc]
    assert name == "柯力传感"
    assert low == Decimal("188.0")
    assert high == Decimal("217.0")
    assert svc.load_prediction("999999", "H1 2026") is None


# ---------- run_daily：score 类信号 ----------


def test_run_daily_super_beat_signal(tmp_path: Path) -> None:
    """当天披露 + 增速超预测上限 → earnings_beat CRITICAL 信号。"""
    adapter = FakeEarningsAdapter(
        {("603662", "H1 2026"): _actual("603662", "柯力传感", "H1 2026", "250", TODAY)}
    )
    svc = _service(tmp_path, adapter)

    signals = run_daily(svc, ["603662"], today=TODAY)

    beats = [s for s in signals if s.rule_id == "earnings_beat"]
    assert len(beats) == 1
    assert beats[0].code == "603662"
    assert beats[0].severity.value == "critical"
    # 拉取覆盖了 preview 期别 + 日期推断的当前期（Q3 2026）
    assert ("603662", "H1 2026") in adapter.fetch_calls
    assert ("603662", "Q3 2026") in adapter.fetch_calls


def test_run_daily_deep_miss_signal(tmp_path: Path) -> None:
    adapter = FakeEarningsAdapter(
        {("603662", "H1 2026"): _actual("603662", "柯力传感", "H1 2026", "100", TODAY)}
    )
    svc = _service(tmp_path, adapter)

    signals = run_daily(svc, ["603662"], today=TODAY)
    misses = [s for s in signals if s.rule_id == "earnings_miss"]
    assert len(misses) == 1
    assert misses[0].severity.value == "critical"


def test_run_daily_skips_old_disclosure(tmp_path: Path) -> None:
    """披露日超出回看窗口（>7 天）的旧 score 不再评估（防每日重复推送）。"""
    adapter = FakeEarningsAdapter(
        {("603662", "H1 2026"): _actual("603662", "柯力传感", "H1 2026", "250", date(2026, 7, 20))}
    )
    svc = _service(tmp_path, adapter)

    signals = run_daily(svc, ["603662"], today=TODAY)
    assert [
        s for s in signals if s.rule_id in ("earnings_beat", "earnings_miss", "earnings_meet")
    ] == []


# ---------- run_daily：approaching 类信号 ----------


def test_run_daily_approaching_from_calendar(tmp_path: Path) -> None:
    """日历里 3 天后披露 + 预测上限 >100% → earnings_approaching WARNING。"""
    adapter = FakeEarningsAdapter({})  # 603986 无 actual（未披露）
    svc = _service(tmp_path, adapter)
    svc.store.upsert_calendar(
        EarningsCalendar(
            code="603986",
            name="兆易创新",
            period="H1 2026",
            disclosure_date=TODAY.replace(day=4),
            is_estimated=False,
            source="test",
        )
    )

    signals = run_daily(svc, ["603986"], today=TODAY)
    approaching = [s for s in signals if s.rule_id == "earnings_approaching"]
    assert len(approaching) == 1
    assert approaching[0].code == "603986"
    assert approaching[0].severity.value == "warning"


def test_run_daily_empty_calendar_no_approaching(tmp_path: Path) -> None:
    """日历未维护 → approaching 自然不触发，不伪造披露日期。"""
    adapter = FakeEarningsAdapter({})
    svc = _service(tmp_path, adapter)
    signals = run_daily(svc, ["603986"], today=TODAY)
    assert [s for s in signals if s.rule_id == "earnings_approaching"] == []


# ---------- 开关与短路 ----------


def test_run_daily_env_switch_skips_everything(
    tmp_path: Path,
    monkeypatch,  # type: ignore[no-untyped-def]
) -> None:
    monkeypatch.setenv(MOMMY_ALERTS_BUILTIN_ONLY_ENV, "1")
    adapter = FakeEarningsAdapter(
        {("603662", "H1 2026"): _actual("603662", "柯力传感", "H1 2026", "250", TODAY)}
    )
    svc = _service(tmp_path, adapter)

    assert run_daily(svc, ["603662"], today=TODAY) == []
    assert adapter.fetch_calls == []


def test_run_daily_empty_codes_short_circuit(tmp_path: Path) -> None:
    adapter = FakeEarningsAdapter({})
    svc = _service(tmp_path, adapter)
    assert run_daily(svc, [], today=TODAY) == []
    assert adapter.fetch_calls == []
