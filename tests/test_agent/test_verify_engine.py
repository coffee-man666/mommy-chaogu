"""verify_engine 单测：降级验证引擎。"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from mommy_chaogu.agent.episodic_memory import EpisodicMemory
from mommy_chaogu.agent.verify_engine import (
    _score_direction,
    _score_target,
    verify_one,
    verify_pending,
)

# ---------- fixtures ----------


def make_pred(
    code: str = "603662",
    direction: str = "bullish",
    target_price: float | None = None,
    entry_price: float = 80.0,
    timeframe: str = "5d",
    created_at: str | None = None,
) -> dict:
    """构造一个 pred dict。"""
    if created_at is None:
        created_at = (datetime.now(UTC) - timedelta(days=2)).isoformat()
    return {
        "id": 1,
        "code": code,
        "name": "柯力传感",
        "prediction": "底部反转",
        "direction": direction,
        "target_price": target_price,
        "entry_price": entry_price,
        "timeframe": timeframe,
        "created_at": created_at,
        "verify_attempts": 0,
    }


def make_quote(price: float, change_pct: float) -> MagicMock:
    """构造一个 mock quote。"""
    q = MagicMock()
    q.price = price
    q.change_pct = change_pct
    return q


def _create_aged_prediction(
    tracker: object,
    monkeypatch: pytest.MonkeyPatch,
    *,
    days_old: float,
    **kwargs: object,
) -> int:
    """以真实 created_at/verify_after 关系创建一条 days_old 天前的预测。

    通过猴子补丁 ``prediction_tracker._utcnow``，让 create() 算出的
    ``verify_after = created_at + timeframe`` 自然落在过去（已到期），
    而不是用裸 SQL 改写 verify_after——那是生产不可能出现的数据形状，
    恰好掩盖了"验证窗口宽度为零"的 bug。
    """
    import mommy_chaogu.agent.prediction_tracker as pt

    fake_now = datetime.now(UTC) - timedelta(days=days_old)
    with monkeypatch.context() as m:
        m.setattr(pt, "_utcnow", lambda: fake_now)
        return tracker.create(**kwargs)  # type: ignore[attr-defined]


# ---------- TestScoring ----------


class TestScoreDirection:
    def test_bullish_strong_hit(self) -> None:
        status, score = _score_direction("bullish", 5.0)
        assert status == "hit"
        assert score == 1.0

    def test_bullish_mild_hit(self) -> None:
        status, score = _score_direction("bullish", 1.0)
        assert status == "hit"
        assert score == 0.7

    def test_bullish_mild_missed(self) -> None:
        status, score = _score_direction("bullish", -1.0)
        assert status == "missed"
        assert score == 0.3

    def test_bullish_strong_missed(self) -> None:
        status, score = _score_direction("bullish", -5.0)
        assert status == "missed"
        assert score == 0.0

    def test_bearish_strong_hit(self) -> None:
        status, score = _score_direction("bearish", -5.0)
        assert status == "hit"
        assert score == 1.0

    def test_bearish_mild_hit(self) -> None:
        status, score = _score_direction("bearish", -1.0)
        assert status == "hit"
        assert score == 0.7

    def test_neutral_is_unverifiable(self) -> None:
        """neutral 无方向可验证 → unverifiable（不计 hit/missed，防命中率灌水）。"""
        status, score = _score_direction("neutral", 0.0)
        assert status == "unverifiable"
        assert score == 0.0


class TestScoreTarget:
    def test_exact_target(self) -> None:
        status, score = _score_target(84.49, 84.49, "bullish", 80.0)
        assert status == "hit"
        assert score == 1.0

    def test_close_to_target(self) -> None:
        # target 84.49, actual 81.5 → ~3.5% off, in 2-5% range
        status, score = _score_target(84.49, 81.5, "bullish", 80.0)
        assert status == "hit"
        assert score == 0.8

    def test_right_direction_not_reached(self) -> None:
        # target 84.49, entry 70.0, actual 75.0 → above entry (right direction)
        # but distance from target = |84.49-75|/84.49 = 11.2% → score 0.5
        status, score = _score_target(84.49, 75.0, "bullish", 70.0)
        assert status == "hit"
        assert score == 0.5

    def test_wrong_direction(self) -> None:
        status, score = _score_target(84.49, 78.0, "bullish", 80.0)
        assert status == "missed"
        assert score == 0.2


# ---------- TestVerifyOne: Quote ----------


class TestVerifyQuote:
    def test_bullish_hit(self) -> None:
        pred = make_pred()
        adapter = MagicMock()
        adapter.get_quote.return_value = make_quote(83.0, 3.75)

        result = verify_one(pred, adapter)
        assert result.status == "hit"
        assert result.price == 83.0
        assert result.score == 1.0

    def test_bullish_missed(self) -> None:
        pred = make_pred()
        adapter = MagicMock()
        adapter.get_quote.return_value = make_quote(76.0, -5.0)

        result = verify_one(pred, adapter)
        assert result.status == "missed"
        assert result.price == 76.0
        assert result.score == 0.0

    def test_bearish_hit(self) -> None:
        pred = make_pred(direction="bearish")
        adapter = MagicMock()
        adapter.get_quote.return_value = make_quote(76.0, -5.0)

        result = verify_one(pred, adapter)
        assert result.status == "hit"
        assert result.score == 1.0


# ---------- TestVerifyOne: Target Price ----------


class TestVerifyTargetPrice:
    def test_target_hit(self) -> None:
        pred = make_pred(target_price=84.49)
        adapter = MagicMock()
        adapter.get_quote.return_value = make_quote(84.49, 5.6)

        result = verify_one(pred, adapter)
        assert result.status == "hit"
        assert result.score == 1.0

    def test_target_wrong_direction(self) -> None:
        pred = make_pred(target_price=84.49)
        adapter = MagicMock()
        adapter.get_quote.return_value = make_quote(76.0, -5.0)

        result = verify_one(pred, adapter)
        assert result.status == "missed"


# ---------- TestVerifyOne: Degraded / Data Unavailable ----------


class TestVerifyDataUnavailable:
    def test_adapter_returns_none_no_cache(self) -> None:
        pred = make_pred()
        adapter = MagicMock()
        adapter.get_quote.return_value = None

        result = verify_one(pred, adapter, cache_store=None)
        assert result.status == "data_unavailable"
        assert "不可用" in result.reason

    def test_adapter_exception(self) -> None:
        pred = make_pred()
        adapter = MagicMock()
        adapter.get_quote.side_effect = Exception("timeout")

        result = verify_one(pred, adapter, cache_store=None)
        assert result.status == "data_unavailable"

    def test_stale_cache_fallback(self) -> None:
        pred = make_pred()
        adapter = MagicMock()
        adapter.get_quote.return_value = None

        cache_entry = MagicMock()
        cache_entry.quote = make_quote(82.0, 2.5)
        cache_store = MagicMock()
        cache_store.get_quote.return_value = cache_entry

        result = verify_one(pred, adapter, cache_store=cache_store)
        assert result.status == "hit"
        assert result.price == 82.0
        assert "stale_cache" in result.reason


# ---------- TestVerifyOne: 窗口口径 ----------


class TestVerifyWindowBasis:
    def test_window_change_pct_overrides_single_day(self) -> None:
        """方向判定用相对 entry_price 的窗口涨跌幅，而非验证当日单日 change_pct。

        单日 -3%（旧口径会判 bullish missed），但窗口 +5% → hit。
        """
        pred = make_pred(direction="bullish", entry_price=80.0)
        adapter = MagicMock()
        adapter.get_quote.return_value = make_quote(84.0, -3.0)

        result = verify_one(pred, adapter)
        assert result.status == "hit"
        assert result.score == 1.0
        # 记录的 actual_change_pct 是窗口涨跌幅
        assert result.change_pct == pytest.approx(5.0)
        assert "窗口涨跌幅" in result.reason

    def test_window_miss_despite_single_day_up(self) -> None:
        """单日 +4% 但窗口 -5% → bullish missed（旧口径会误判 hit）。"""
        pred = make_pred(direction="bullish", entry_price=80.0)
        adapter = MagicMock()
        adapter.get_quote.return_value = make_quote(76.0, 4.0)

        result = verify_one(pred, adapter)
        assert result.status == "missed"
        assert result.score == 0.0

    def test_fallback_to_single_day_without_entry_price(self) -> None:
        """entry_price 缺失时回退单日 change_pct 旧口径。"""
        pred = make_pred(direction="bullish", entry_price=None)
        adapter = MagicMock()
        adapter.get_quote.return_value = make_quote(83.0, 3.75)

        result = verify_one(pred, adapter)
        assert result.status == "hit"
        assert result.score == 1.0
        assert result.change_pct == 3.75
        assert "单日涨跌幅" in result.reason

    def test_neutral_prediction_is_unverifiable(self) -> None:
        """neutral 预测走 verify_one → unverifiable，不记 hit。"""
        pred = make_pred(direction="neutral")
        adapter = MagicMock()
        adapter.get_quote.return_value = make_quote(83.0, 3.75)

        result = verify_one(pred, adapter)
        assert result.status == "unverifiable"
        assert result.score == 0.0


# ---------- TestVerifyOne: Expired ----------


class TestVerifyExpired:
    def test_expired(self) -> None:
        old = (datetime.now(UTC) - timedelta(days=30)).isoformat()
        pred = make_pred(created_at=old, timeframe="5d")
        adapter = MagicMock()
        adapter.get_quote.return_value = make_quote(82.0, 2.5)

        result = verify_one(pred, adapter)
        assert result.status == "expired"

    def test_not_yet_expired(self) -> None:
        recent = (datetime.now(UTC) - timedelta(days=1)).isoformat()
        pred = make_pred(created_at=recent, timeframe="5d")
        adapter = MagicMock()
        adapter.get_quote.return_value = make_quote(82.0, 2.5)

        result = verify_one(pred, adapter)
        assert result.status in ("hit", "missed")

    def test_within_grace_window_is_verified(self) -> None:
        """到期后在宽限期内（verify_after + 1 个 timeframe 内）仍应验证，不判 expired。

        修复前过期判定用 created_at + timeframe（= verify_after），到期即过期，
        真实 created_at/verify_after 关系的预测永远不会被验证。
        """
        now = datetime.now(UTC)
        created_at = (now - timedelta(days=8)).isoformat()
        verify_after = (now - timedelta(days=3)).isoformat()  # 5d 预测，3 天前到期
        pred = make_pred(created_at=created_at, timeframe="5d")
        pred["verify_after"] = verify_after
        adapter = MagicMock()
        adapter.get_quote.return_value = make_quote(84.0, 1.0)

        result = verify_one(pred, adapter)
        assert result.status == "hit"  # 窗口 +5% → hit，而非 expired

    def test_beyond_grace_window_is_expired(self) -> None:
        """超过 verify_after + 一个 timeframe 宽限期才判 expired。"""
        now = datetime.now(UTC)
        created_at = (now - timedelta(days=11)).isoformat()
        verify_after = (now - timedelta(days=6)).isoformat()  # 6 天前到期，超过 5 天宽限
        pred = make_pred(created_at=created_at, timeframe="5d")
        pred["verify_after"] = verify_after
        adapter = MagicMock()
        adapter.get_quote.return_value = make_quote(84.0, 1.0)

        result = verify_one(pred, adapter)
        assert result.status == "expired"


# ---------- TestVerifyPending: Batch ----------


class TestVerifyPending:
    def test_due_prediction_with_real_relationship_gets_verified(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """真实 created_at/verify_after 关系的到期预测会被验证，而非直接 expired。

        回归 P2：6 天前创建的 5d 预测（1 天前到期，仍在 5 天宽限期内），
        修复前 now > created_at + 5d 恒成立 → 直接 expired，adapter 不被调用。
        """
        from mommy_chaogu.agent.prediction_tracker import PredictionTracker

        tracker = PredictionTracker(tmp_path / "test.db")
        pid = _create_aged_prediction(
            tracker,
            monkeypatch,
            days_old=6,
            code="603662",
            name="柯力传感",
            prediction="看涨",
            direction="bullish",
            timeframe="5d",
            entry_price=80.0,
        )

        adapter = MagicMock()
        adapter.get_quote.return_value = make_quote(84.0, 1.0)  # 窗口 +5%

        results = verify_pending(tracker, None, adapter, None)
        assert results["total"] == 1
        assert results["hit"] == 1
        assert results["expired"] == 0
        assert adapter.get_quote.called

        row = tracker.get_by_id(pid)
        assert row is not None
        assert row["status"] == "hit"
        assert row["actual_change_pct"] == pytest.approx(5.0)

    def test_neutral_counts_as_unverifiable_not_hit(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """neutral 预测验证后记 unverifiable，不进 hit_rate 分母。"""
        from mommy_chaogu.agent.prediction_tracker import PredictionTracker

        tracker = PredictionTracker(tmp_path / "test.db")
        _create_aged_prediction(
            tracker,
            monkeypatch,
            days_old=6,
            code="603662",
            name="柯力传感",
            prediction="震荡",
            direction="neutral",
            timeframe="5d",
        )

        adapter = MagicMock()
        adapter.get_quote.return_value = make_quote(84.0, 3.75)

        results = verify_pending(tracker, None, adapter, None)
        assert results["unverifiable"] == 1
        assert results["hit"] == 0
        assert results["missed"] == 0

        stats = tracker.stats()
        assert stats["unverifiable"] == 1
        assert stats["hit"] == 0
        assert stats["hit_rate"] == 0.0

    def test_batch_hit_and_missed(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from mommy_chaogu.agent.prediction_tracker import PredictionTracker

        tracker = PredictionTracker(tmp_path / "test.db")
        # 6 天前创建的 5d 预测：1 天前到期，仍在宽限期内（真实时间关系）
        _create_aged_prediction(
            tracker,
            monkeypatch,
            days_old=6,
            code="603662",
            name="柯力传感",
            prediction="看涨",
            direction="bullish",
            timeframe="5d",
        )
        _create_aged_prediction(
            tracker,
            monkeypatch,
            days_old=6,
            code="000858",
            name="五粮液",
            prediction="看跌",
            direction="bearish",
            timeframe="5d",
        )

        adapter = MagicMock()

        def get_quote(code: str) -> MagicMock | None:
            if code == "603662":
                return make_quote(83.0, 3.75)  # bullish hit（无 entry_price → 单日口径）
            if code == "000858":
                return make_quote(76.0, 5.0)  # bearish missed (price went up)

            return None

        adapter.get_quote.side_effect = get_quote

        results = verify_pending(tracker, None, adapter, None)
        assert results["total"] == 2
        assert results["hit"] == 1
        assert results["missed"] == 1

    def test_data_unavailable_then_expired(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from mommy_chaogu.agent.prediction_tracker import PredictionTracker

        tracker = PredictionTracker(tmp_path / "test.db")
        _create_aged_prediction(
            tracker,
            monkeypatch,
            days_old=6,
            code="603662",
            name="柯力传感",
            prediction="看涨",
            direction="bullish",
            timeframe="5d",
        )

        adapter = MagicMock()
        adapter.get_quote.return_value = None  # 永远拿不到数据

        # 第一次：data_unavailable
        results = verify_pending(tracker, None, adapter, None, max_attempts=3)
        assert results["data_unavailable"] == 1

        # 手动把 attempts 设到 3
        import sqlite3

        conn = sqlite3.connect(str(tmp_path / "test.db"))
        conn.execute("UPDATE predictions SET verify_attempts = 3")
        conn.commit()
        conn.close()

        # 第二次：expired
        results = verify_pending(tracker, None, adapter, None, max_attempts=3)
        assert results["expired"] == 1

    def test_verify_backfills_source_event_prediction_id(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """验证 hit/missed 后，源事件的 prediction_id 被回填。"""
        from mommy_chaogu.agent.prediction_tracker import PredictionTracker

        episodic = EpisodicMemory(tmp_path / "episodic.db")
        tracker = PredictionTracker(tmp_path / "test.db")

        # 先写一条 observation，拿到 event_id
        event_id = episodic.write(
            event_type="analysis_record",
            scope="stock:603662",
            code="603662",
            name="柯力传感",
            summary="底部反转",
            data={"price": 80.0},
        )
        # 源事件初始没有 prediction_id
        assert episodic.get_by_id(event_id)["prediction_id"] is None

        # 创建一条 prediction，关联源事件（6 天前的 5d 预测，真实时间关系）
        pred_id = _create_aged_prediction(
            tracker,
            monkeypatch,
            days_old=6,
            code="603662",
            name="柯力传感",
            prediction="看涨",
            direction="bullish",
            timeframe="5d",
            source_event_id=event_id,
        )

        adapter = MagicMock()
        adapter.get_quote.return_value = make_quote(83.0, 3.75)  # bullish hit

        results = verify_pending(tracker, episodic, adapter, None)
        assert results["hit"] == 1

        # 源事件的 prediction_id 应被回填
        source_event = episodic.get_by_id(event_id)
        assert source_event["prediction_id"] == pred_id
