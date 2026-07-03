"""verify_engine 单测：降级验证引擎。"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path
from unittest.mock import MagicMock

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

    def test_neutral(self) -> None:
        status, score = _score_direction("neutral", 0.0)
        assert status == "hit"
        assert score == 0.5


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


# ---------- TestVerifyPending: Batch ----------


class TestVerifyPending:
    def test_batch_hit_and_missed(
        self,
        tmp_path: Path,
    ) -> None:
        from mommy_chaogu.agent.prediction_tracker import PredictionTracker

        tracker = PredictionTracker(tmp_path / "test.db")
        tracker.create(
            code="603662",
            name="柯力传感",
            prediction="看涨",
            direction="bullish",
            timeframe="1d",
        )
        tracker.create(
            code="000858",
            name="五粮液",
            prediction="看跌",
            direction="bearish",
            timeframe="1d",
        )

        # Make them immediately verifiable
        import sqlite3

        conn = sqlite3.connect(str(tmp_path / "test.db"))
        past = (datetime.now(UTC) - timedelta(hours=1)).isoformat()
        conn.execute("UPDATE predictions SET verify_after = ?", (past,))
        conn.commit()
        conn.close()

        adapter = MagicMock()

        def get_quote(code: str) -> MagicMock | None:
            if code == "603662":
                return make_quote(83.0, 3.75)  # bullish hit
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
    ) -> None:
        from mommy_chaogu.agent.prediction_tracker import PredictionTracker

        tracker = PredictionTracker(tmp_path / "test.db")
        tracker.create(
            code="603662",
            name="柯力传感",
            prediction="看涨",
            direction="bullish",
            timeframe="1d",
        )

        import sqlite3

        past = (datetime.now(UTC) - timedelta(hours=1)).isoformat()
        conn = sqlite3.connect(str(tmp_path / "test.db"))
        conn.execute("UPDATE predictions SET verify_after = ?", (past,))
        conn.commit()
        conn.close()

        adapter = MagicMock()
        adapter.get_quote.return_value = None  # 永远拿不到数据

        # 第一次：data_unavailable
        results = verify_pending(tracker, None, adapter, None, max_attempts=3)
        assert results["data_unavailable"] == 1

        # 手动把 attempts 设到 3
        conn = sqlite3.connect(str(tmp_path / "test.db"))
        conn.execute("UPDATE predictions SET verify_attempts = 3")
        conn.commit()
        conn.close()

        # 第二次：expired
        results = verify_pending(tracker, None, adapter, None, max_attempts=3)
        assert results["expired"] == 1
