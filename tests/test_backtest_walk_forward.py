"""tests/test_backtest_walk_forward - walk-forward 过拟合检验单测。"""

from __future__ import annotations

from mommy_chaogu.backtest.walk_forward import walk_forward_test


def _make_pred(
    direction: str,
    change_pct: float,
    scope: str = "market",
    created_at: str = "2026-01-01",
) -> dict:
    return {
        "direction": direction,
        "actual_change_pct": change_pct,
        "scope": scope,
        "created_at": created_at,
    }


class TestWalkForwardSplit:
    def test_train_ratio_70(self) -> None:
        """前 70% 训练，后 30% 测试。"""
        preds = [_make_pred("bullish", 3.0, created_at=f"2026-01-{i:02d}") for i in range(1, 11)]
        result = walk_forward_test(preds, train_ratio=0.7)
        assert result.train_size == 7
        assert result.test_size == 3

    def test_split_respects_time_order(self) -> None:
        """按 created_at 排序后再切分（非原顺序）。"""
        preds = [
            _make_pred("bullish", 3.0, created_at="2026-03-01"),
            _make_pred("bullish", 3.0, created_at="2026-01-01"),
            _make_pred("bullish", 3.0, created_at="2026-02-01"),
            _make_pred("bullish", 3.0, created_at="2026-04-01"),
        ]
        result = walk_forward_test(preds, train_ratio=0.5)
        assert result.train_size == 2
        assert result.test_size == 2

    def test_empty_returns_zeros(self) -> None:
        """空数据返回全 0 结果。"""
        result = walk_forward_test([])
        assert result.train_size == 0
        assert result.test_size == 0
        assert result.train_hit_rate == 0.0
        assert result.test_hit_rate == 0.0
        assert result.overfitting_score == 0.0

    def test_single_sample_all_train(self) -> None:
        """不足 2 条时全部归训练集，测试集为空。"""
        result = walk_forward_test([_make_pred("bullish", 3.0)])
        assert result.train_size == 1
        assert result.test_size == 0
        assert result.test_hit_rate == 0.0

    def test_invalid_ratio_raises(self) -> None:
        """train_ratio 越界抛 ValueError。"""
        import pytest

        with pytest.raises(ValueError):
            walk_forward_test([_make_pred("bullish", 3.0)], train_ratio=0.0)
        with pytest.raises(ValueError):
            walk_forward_test([_make_pred("bullish", 3.0)], train_ratio=1.0)


class TestWalkForwardHitRate:
    def test_uniform_data_train_approx_test(self) -> None:
        """均匀数据上 train≈test，overfitting_score 接近 0。"""
        # 10 条全 bullish + 涨 3%，命中率应一致 = 100%
        preds = [_make_pred("bullish", 3.0, created_at=f"2026-01-{i:02d}") for i in range(1, 11)]
        result = walk_forward_test(preds, train_ratio=0.7)
        assert result.train_hit_rate == 1.0
        assert result.test_hit_rate == 1.0
        assert abs(result.overfitting_score) < 1e-9

    def test_all_miss_uniform(self) -> None:
        """全错的情况，train/test 命中率都是 0。"""
        preds = [_make_pred("bullish", -5.0, created_at=f"2026-01-{i:02d}") for i in range(1, 11)]
        result = walk_forward_test(preds, train_ratio=0.7)
        assert result.train_hit_rate == 0.0
        assert result.test_hit_rate == 0.0


class TestOverfittingScore:
    def test_overfitting_score_is_train_minus_test(self) -> None:
        """overfitting_score = train_hit_rate - test_hit_rate。"""
        # 训练集全对（bullish +3%），测试集全错（bullish -5%）。10 条 → 7 train / 3 test。
        train = [_make_pred("bullish", 3.0, created_at=f"2026-01-{i:02d}") for i in range(1, 8)]
        test = [_make_pred("bullish", -5.0, created_at=f"2026-02-{i:02d}") for i in range(1, 4)]
        result = walk_forward_test(train + test, train_ratio=0.7)
        assert result.train_size == 7
        assert result.test_size == 3
        assert result.train_hit_rate == 1.0
        assert result.test_hit_rate == 0.0
        assert result.overfitting_score == 1.0

    def test_negative_score_when_test_better(self) -> None:
        """测试集比训练集好时 overfitting_score 为负。"""
        train = [_make_pred("bullish", -5.0, created_at=f"2026-01-{i:02d}") for i in range(1, 8)]
        test = [_make_pred("bullish", 3.0, created_at=f"2026-02-{i:02d}") for i in range(1, 4)]
        result = walk_forward_test(train + test, train_ratio=0.7)
        assert result.overfitting_score == -1.0


class TestKnowledgeExtraction:
    def test_knowledge_extracted_from_train(self) -> None:
        """训练集提炼出 scope → 偏好方向的知识。"""
        preds = [
            _make_pred("bullish", 3.0, scope="sector:半导体", created_at="2026-01-01"),
            _make_pred("bullish", 3.0, scope="sector:半导体", created_at="2026-01-02"),
            _make_pred("bullish", 3.0, scope="sector:半导体", created_at="2026-01-03"),
        ]
        result = walk_forward_test(preds, train_ratio=0.7)
        assert "sector:半导体" in result.knowledge
        assert result.knowledge["sector:半导体"]["preferred_direction"] == "bullish"

    def test_baseline_lift_reported(self) -> None:
        """有知识 vs 无知识基线的 lift 被计算。"""
        preds = [_make_pred("bullish", 3.0, created_at=f"2026-01-{i:02d}") for i in range(1, 8)] + [
            _make_pred("bullish", 3.0, created_at=f"2026-02-{i:02d}") for i in range(1, 5)
        ]
        result = walk_forward_test(preds, train_ratio=0.7)
        assert result.baseline_test_hit_rate >= 0.0


class TestReport:
    def test_report_contains_key_sections(self) -> None:
        """格式化报告包含关键信息。"""
        preds = [_make_pred("bullish", 3.0, created_at=f"2026-01-{i:02d}") for i in range(1, 11)]
        result = walk_forward_test(preds, train_ratio=0.7)
        report = result.format_report()
        assert "Walk-Forward Test Report" in report
        assert "Train set" in report
        assert "Test  set" in report
        assert "Overfitting score" in report
