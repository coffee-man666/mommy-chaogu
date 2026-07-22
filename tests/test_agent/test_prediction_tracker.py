"""PredictionTracker 单测：SQLite 持久化预测追踪。"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from mommy_chaogu.agent.prediction_tracker import PredictionTracker


@pytest.fixture
def tracker(tmp_path: Path) -> PredictionTracker:
    return PredictionTracker(tmp_path / "test_predictions.db")


class TestPredictionCRUD:
    def test_create_returns_id(self, tracker: PredictionTracker) -> None:
        """create 返回自增 id。"""
        id1 = tracker.create(
            code="600519",
            name="贵州茅台",
            prediction="看涨",
            direction="up",
            timeframe="1d",
        )
        id2 = tracker.create(
            code="000858",
            name="五粮液",
            prediction="看跌",
            direction="down",
            timeframe="5d",
        )
        assert id1 > 0
        assert id2 == id1 + 1

    def test_create_and_get_by_id(self, tracker: PredictionTracker) -> None:
        """create 后 get_by_id 能取到全部字段，含 JSON 解析。"""
        coverage = {"kline": True, "minute": False, "news": True}
        pid = tracker.create(
            code="600519",
            name="贵州茅台",
            prediction="短线看涨",
            direction="up",
            timeframe="5d",
            rationale="放量突破",
            target_price=1800.0,
            entry_price=1700.0,
            stop_loss=1650.0,
            change_pct_at_creation=2.5,
            data_coverage=coverage,
            source_event_id=42,
        )
        row = tracker.get_by_id(pid)
        assert row is not None
        assert row["id"] == pid
        assert row["code"] == "600519"
        assert row["name"] == "贵州茅台"
        assert row["prediction"] == "短线看涨"
        assert row["direction"] == "up"
        assert row["rationale"] == "放量突破"
        assert row["target_price"] == 1800.0
        assert row["entry_price"] == 1700.0
        assert row["stop_loss"] == 1650.0
        assert row["change_pct_at_creation"] == 2.5
        assert row["timeframe"] == "5d"
        assert row["status"] == "pending"
        assert row["source_event_id"] == 42
        assert row["verified_at"] is None
        # JSON 解析
        assert json.loads(row["data_coverage_at_creation"]) == coverage
        # created_at 可被 fromisoformat 解析
        assert datetime.fromisoformat(row["created_at"]) is not None

    def test_get_by_id_not_found(self, tracker: PredictionTracker) -> None:
        """不存在的 id 返回 None。"""
        assert tracker.get_by_id(9999) is None

    def test_create_sets_verify_after(self, tracker: PredictionTracker) -> None:
        """create 设置的 verify_after 在未来。"""
        before = datetime.now(UTC)
        pid = tracker.create(
            code="600519",
            name="贵州茅台",
            prediction="看涨",
            direction="up",
            timeframe="5d",
        )
        row = tracker.get_by_id(pid)
        assert row is not None
        verify_after = datetime.fromisoformat(row["verify_after"])
        # 5d → +5 天，应在 before 之后
        assert verify_after > before


class TestPredictionGetPending:
    def test_get_pending_returns_due(self, tracker: PredictionTracker) -> None:
        """到期的 pending 预测能被取到。"""
        tracker.create(
            code="600519",
            name="贵州茅台",
            prediction="看涨",
            direction="up",
            timeframe="1d",
        )
        # verify_after ≈ now + 1d，用未来时间查询
        future = (datetime.now() + timedelta(days=10)).isoformat()
        pending = tracker.get_pending(future)
        assert len(pending) == 1
        assert pending[0]["code"] == "600519"

    def test_get_pending_excludes_not_yet_due(self, tracker: PredictionTracker) -> None:
        """未到期的 pending 不返回。"""
        tracker.create(
            code="600519",
            name="贵州茅台",
            prediction="看涨",
            direction="up",
            timeframe="60d",
        )
        now = datetime.now().isoformat()
        pending = tracker.get_pending(now)
        assert pending == []

    def test_get_pending_excludes_already_verified(self, tracker: PredictionTracker) -> None:
        """已验证（status != pending）的不返回。"""
        pid = tracker.create(
            code="600519",
            name="贵州茅台",
            prediction="看涨",
            direction="up",
            timeframe="1d",
        )
        tracker.update_status(pid, status="hit", actual_price=1800.0)
        future = (datetime.now() + timedelta(days=10)).isoformat()
        pending = tracker.get_pending(future)
        assert pending == []

    def test_get_pending_empty(self, tracker: PredictionTracker) -> None:
        """空库时返回空列表。"""
        assert tracker.get_pending(datetime.now().isoformat()) == []

    def test_get_pending_ordered_by_verify_after(self, tracker: PredictionTracker) -> None:
        """get_pending 按 verify_after 升序。"""
        tracker.create(
            code="600519",
            name="贵州茅台",
            prediction="看涨",
            direction="up",
            timeframe="20d",
        )
        tracker.create(
            code="000858",
            name="五粮液",
            prediction="看涨",
            direction="up",
            timeframe="1d",
        )
        future = (datetime.now() + timedelta(days=100)).isoformat()
        pending = tracker.get_pending(future)
        assert len(pending) == 2
        # 1d (+1天) 应排在 20d (+20天) 之前
        assert pending[0]["code"] == "000858"
        assert pending[1]["code"] == "600519"


class TestPredictionUpdateStatus:
    def test_update_to_hit(self, tracker: PredictionTracker) -> None:
        """update_status 设为 hit 后能查到。"""
        pid = tracker.create(
            code="600519",
            name="贵州茅台",
            prediction="看涨",
            direction="up",
            timeframe="1d",
        )
        tracker.update_status(
            pid,
            status="hit",
            actual_price=1800.0,
            actual_change_pct=5.8,
            accuracy_score=0.9,
            data_coverage={"kline": True},
        )
        row = tracker.get_by_id(pid)
        assert row is not None
        assert row["status"] == "hit"
        assert row["actual_price"] == 1800.0
        assert row["actual_change_pct"] == 5.8
        assert row["accuracy_score"] == 0.9
        assert json.loads(row["data_coverage_at_verify"]) == {"kline": True}

    def test_update_to_missed(self, tracker: PredictionTracker) -> None:
        """update_status 设为 missed 后能查到。"""
        pid = tracker.create(
            code="600519",
            name="贵州茅台",
            prediction="看涨",
            direction="up",
            timeframe="1d",
        )
        tracker.update_status(pid, status="missed", actual_price=1600.0)
        row = tracker.get_by_id(pid)
        assert row is not None
        assert row["status"] == "missed"
        assert row["actual_price"] == 1600.0

    def test_update_sets_verified_at(self, tracker: PredictionTracker) -> None:
        """update_status 设置 verified_at。"""
        pid = tracker.create(
            code="600519",
            name="贵州茅台",
            prediction="看涨",
            direction="up",
            timeframe="1d",
        )
        before = datetime.now(UTC)
        tracker.update_status(pid, status="hit", actual_price=1800.0)
        row = tracker.get_by_id(pid)
        assert row is not None
        assert row["verified_at"] is not None
        verified_at = datetime.fromisoformat(row["verified_at"])
        # 允许 1 秒容差（SQLite TIMESTAMP 精度可能是秒级）
        assert (verified_at - before).total_seconds() >= -1


class TestPredictionIncrementAttempts:
    def test_increment_attempts(self, tracker: PredictionTracker) -> None:
        """increment_attempts 递增 verify_attempts。"""
        pid = tracker.create(
            code="600519",
            name="贵州茅台",
            prediction="看涨",
            direction="up",
            timeframe="1d",
        )
        tracker.increment_attempts(pid, "no data")
        tracker.increment_attempts(pid, "still no data")
        row = tracker.get_by_id(pid)
        assert row is not None
        assert row["verify_attempts"] == 2

    def test_increment_attempts_appends_log(self, tracker: PredictionTracker) -> None:
        """increment_attempts 向 verify_log 追加 JSON 记录。"""
        pid = tracker.create(
            code="600519",
            name="贵州茅台",
            prediction="看涨",
            direction="up",
            timeframe="1d",
        )
        tracker.increment_attempts(pid, "first failure")
        tracker.increment_attempts(pid, "second failure")
        row = tracker.get_by_id(pid)
        assert row is not None
        log = json.loads(row["verify_log"])
        assert len(log) == 2
        assert log[0]["attempt"] == 1
        assert log[0]["reason"] == "first failure"
        assert log[1]["attempt"] == 2
        assert log[1]["reason"] == "second failure"
        assert "time" in log[0]


class TestPredictionRecentVerified:
    def test_recent_verified(self, tracker: PredictionTracker) -> None:
        """recent_verified 返回已验证的预测，按 verified_at 降序。"""
        p1 = tracker.create(
            code="600519",
            name="贵州茅台",
            prediction="看涨",
            direction="up",
            timeframe="1d",
        )
        p2 = tracker.create(
            code="000858",
            name="五粮液",
            prediction="看跌",
            direction="down",
            timeframe="1d",
        )
        tracker.update_status(p1, status="hit", actual_price=1800.0)
        tracker.update_status(p2, status="missed", actual_price=1600.0)
        recent = tracker.recent_verified(limit=5)
        assert len(recent) == 2
        # p2 后验证，应排前面
        assert recent[0]["code"] == "000858"
        assert recent[1]["code"] == "600519"

    def test_recent_verified_empty(self, tracker: PredictionTracker) -> None:
        """无已验证记录时返回空列表。"""
        tracker.create(
            code="600519",
            name="贵州茅台",
            prediction="看涨",
            direction="up",
            timeframe="1d",
        )
        assert tracker.recent_verified() == []

    def test_recent_verified_excludes_pending(self, tracker: PredictionTracker) -> None:
        """recent_verified 不包含 pending 状态。"""
        tracker.create(
            code="600519",
            name="贵州茅台",
            prediction="看涨",
            direction="up",
            timeframe="1d",
        )
        assert tracker.recent_verified() == []


class TestPredictionStats:
    def test_stats_with_data(self, tracker: PredictionTracker) -> None:
        """stats 返回正确的计数。"""
        p1 = tracker.create(
            code="600519",
            name="贵州茅台",
            prediction="看涨",
            direction="up",
            timeframe="1d",
        )
        p2 = tracker.create(
            code="000858",
            name="五粮液",
            prediction="看涨",
            direction="up",
            timeframe="1d",
        )
        tracker.create(
            code="002594",
            name="比亚迪",
            prediction="看涨",
            direction="up",
            timeframe="1d",
        )
        tracker.update_status(p1, status="hit", actual_price=1800.0)
        tracker.update_status(p2, status="missed", actual_price=1600.0)
        # 第三条 pending

        s = tracker.stats()
        assert s["total"] == 3
        assert s["pending"] == 1
        assert s["hit"] == 1
        assert s["missed"] == 1
        assert s["expired"] == 0
        assert s["unverifiable"] == 0
        # hit_rate = hit / (hit + missed) = 0.5
        assert s["hit_rate"] == 0.5

    def test_stats_empty(self, tracker: PredictionTracker) -> None:
        """空库 stats 全 0。"""
        s = tracker.stats()
        assert s["total"] == 0
        assert s["pending"] == 0
        assert s["hit"] == 0
        assert s["missed"] == 0
        assert s["expired"] == 0
        assert s["unverifiable"] == 0
        assert s["hit_rate"] == 0.0

    def test_hit_rate_excludes_expired(self, tracker: PredictionTracker) -> None:
        """hit_rate = hit/(hit+missed)，不包含 expired。"""
        p1 = tracker.create(
            code="600519",
            name="贵州茅台",
            prediction="看涨",
            direction="up",
            timeframe="1d",
        )
        p2 = tracker.create(
            code="000858",
            name="五粮液",
            prediction="看涨",
            direction="up",
            timeframe="1d",
        )
        p3 = tracker.create(
            code="002594",
            name="比亚迪",
            prediction="看涨",
            direction="up",
            timeframe="1d",
        )
        tracker.update_status(p1, status="hit", actual_price=1800.0)
        tracker.update_status(p2, status="expired")
        tracker.update_status(p3, status="unverifiable")

        s = tracker.stats()
        # hit_rate = 1 / (1 + 0) = 1.0，不被 expired/unverifiable 影响
        assert s["hit"] == 1
        assert s["missed"] == 0
        assert s["expired"] == 1
        assert s["unverifiable"] == 1
        assert s["hit_rate"] == 1.0


class TestPredictionCleanupOld:
    def test_cleanup_removes_old_verified(self, tracker: PredictionTracker) -> None:
        """已验证的旧预测被清理。"""
        from datetime import UTC, datetime, timedelta

        from sqlalchemy import text

        pid = tracker.create(
            code="600519",
            name="贵州茅台",
            prediction="看涨",
            direction="up",
            timeframe="1d",
        )
        tracker.update_status(pid, status="hit", actual_price=1800.0)
        # 把 created_at / verified_at 改到 100 天前
        old_ts = (datetime.now(UTC) - timedelta(days=100)).isoformat()
        with tracker.engine.begin() as conn:
            conn.execute(
                text("UPDATE predictions SET created_at = :ts, verified_at = :ts WHERE id = :id"),
                {"ts": old_ts, "id": pid},
            )

        deleted = tracker.cleanup_old(days=90)
        assert deleted == 1
        assert tracker.get_by_id(pid) is None

    def test_cleanup_preserves_pending(self, tracker: PredictionTracker) -> None:
        """pending 预测永远不被清理。"""
        from datetime import UTC, datetime, timedelta

        from sqlalchemy import text

        pid = tracker.create(
            code="600519",
            name="贵州茅台",
            prediction="看涨",
            direction="up",
            timeframe="1d",
        )
        old_ts = (datetime.now(UTC) - timedelta(days=200)).isoformat()
        with tracker.engine.begin() as conn:
            conn.execute(
                text("UPDATE predictions SET created_at = :ts WHERE id = :id"),
                {"ts": old_ts, "id": pid},
            )

        deleted = tracker.cleanup_old(days=90)
        assert deleted == 0
        assert tracker.get_by_id(pid) is not None

    def test_cleanup_preserves_recent_verified(self, tracker: PredictionTracker) -> None:
        """近期验证的预测不被清理。"""
        pid = tracker.create(
            code="600519",
            name="贵州茅台",
            prediction="看涨",
            direction="up",
            timeframe="1d",
        )
        tracker.update_status(pid, status="hit", actual_price=1800.0)
        deleted = tracker.cleanup_old(days=90)
        assert deleted == 0
        assert tracker.get_by_id(pid) is not None

    def test_cleanup_removes_expired(self, tracker: PredictionTracker) -> None:
        """expired 状态的旧预测被清理。"""
        from datetime import UTC, datetime, timedelta

        from sqlalchemy import text

        pid = tracker.create(
            code="600519",
            name="贵州茅台",
            prediction="看涨",
            direction="up",
            timeframe="1d",
        )
        tracker.update_status(pid, status="expired")
        old_ts = (datetime.now(UTC) - timedelta(days=100)).isoformat()
        with tracker.engine.begin() as conn:
            conn.execute(
                text("UPDATE predictions SET created_at = :ts WHERE id = :id"),
                {"ts": old_ts, "id": pid},
            )

        deleted = tracker.cleanup_old(days=90)
        assert deleted == 1

    def test_cleanup_empty_db(self, tracker: PredictionTracker) -> None:
        """空库 cleanup 返回 0。"""
        assert tracker.cleanup_old(days=90) == 0

    def test_cleanup_returns_count(self, tracker: PredictionTracker) -> None:
        """cleanup 返回删除条数。"""
        from datetime import UTC, datetime, timedelta

        from sqlalchemy import text

        old_ts = (datetime.now(UTC) - timedelta(days=100)).isoformat()
        for i in range(3):
            pid = tracker.create(
                code=f"60051{i}",
                name="test",
                prediction="看涨",
                direction="up",
                timeframe="1d",
            )
            tracker.update_status(pid, status="hit", actual_price=100.0)
            with tracker.engine.begin() as conn:
                conn.execute(
                    text(
                        "UPDATE predictions SET created_at = :ts, verified_at = :ts WHERE id = :id"
                    ),
                    {"ts": old_ts, "id": pid},
                )

        deleted = tracker.cleanup_old(days=90)
        assert deleted == 3


class TestTimeframeUnification:
    """timeframe 映射统一：prediction_tracker 和 verify_engine 用同一套天数。"""

    def test_timeframe_mapping_is_unified(self) -> None:
        """两个模块引用同一个 _TIMEFRAME_DAYS 常量。"""
        from mommy_chaogu.agent import prediction_tracker, verify_engine

        assert prediction_tracker._TIMEFRAME_DAYS is verify_engine._TIMEFRAME_DAYS

    def test_timeframe_mapping_values(self) -> None:
        """统一映射为日历天。"""
        from mommy_chaogu.agent.prediction_tracker import _TIMEFRAME_DAYS

        assert _TIMEFRAME_DAYS["1d"] == 1
        assert _TIMEFRAME_DAYS["3d"] == 3
        assert _TIMEFRAME_DAYS["5d"] == 5
        assert _TIMEFRAME_DAYS["10d"] == 10
        assert _TIMEFRAME_DAYS["20d"] == 20
        assert _TIMEFRAME_DAYS["60d"] == 60

    def test_verify_after_and_is_expired_use_same_days(self) -> None:
        """_is_expired 以 verify_after + 一个 timeframe 宽限期为界（同一天数映射）。

        5d 预测：created+5d 到期可验证，此后留 5 天验证窗口，
        超过 verify_after+5d 才判 expired。
        """
        from datetime import UTC, datetime, timedelta

        from mommy_chaogu.agent.prediction_tracker import _compute_verify_after
        from mommy_chaogu.agent.verify_engine import _is_expired

        # 模拟 created_at = now，timeframe="5d"
        now = datetime.now(UTC)
        # _compute_verify_after 用真实 _utcnow()，所以取现在附近的时间
        verify_after_iso = _compute_verify_after("5d")
        verify_after = datetime.fromisoformat(verify_after_iso)

        # verify_after 应在 now+5d 附近（允许 1 分钟误差）
        assert abs((verify_after - now - timedelta(days=5)).total_seconds()) < 60

        # 到期后宽限期内：未过期（到期当天 / +4 天）
        assert _is_expired(verify_after_iso, "5d", now=verify_after) is False
        assert _is_expired(verify_after_iso, "5d", now=verify_after + timedelta(days=4)) is False
        # 超过宽限期（verify_after + 5d + 1s）：过期
        assert (
            _is_expired(verify_after_iso, "5d", now=verify_after + timedelta(days=5, seconds=1))
            is True
        )

    def test_compute_verify_after_5d_is_5_days(self, tracker: PredictionTracker) -> None:
        """create("5d") 的 verify_after 距 created_at 正好 5 天。"""
        before = datetime.now(UTC)
        pid = tracker.create(
            code="600519",
            name="贵州茅台",
            prediction="看涨",
            direction="up",
            timeframe="5d",
        )
        row = tracker.get_by_id(pid)
        assert row is not None
        verify_after = datetime.fromisoformat(row["verify_after"])
        created_at = datetime.fromisoformat(row["created_at"])
        # 间隔应为 5 天（允许几秒误差）
        delta = verify_after - created_at
        assert timedelta(days=5) <= delta <= timedelta(days=5, seconds=30)
        assert verify_after > before
