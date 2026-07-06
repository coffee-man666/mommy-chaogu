"""TokenTracker 单测：LLM token 用量追踪（SQLite 持久化）。"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from types import SimpleNamespace

import pytest

from mommy_chaogu.agent.token_tracker import (
    DEFAULT_PRICING,
    TokenTracker,
)


@pytest.fixture
def tracker(tmp_path: Path) -> TokenTracker:
    return TokenTracker(tmp_path / "test_tokens.db")


def _make_usage(
    prompt: int,
    completion: int,
    total: int | None = None,
    cached: int | None = None,
    reasoning: int | None = None,
) -> SimpleNamespace:
    """构造一个类 OpenAI usage 对象。"""
    prompt_details = SimpleNamespace(cached_tokens=cached) if cached is not None else None
    completion_details = (
        SimpleNamespace(reasoning_tokens=reasoning) if reasoning is not None else None
    )
    return SimpleNamespace(
        prompt_tokens=prompt,
        completion_tokens=completion,
        total_tokens=total if total is not None else prompt + completion,
        prompt_tokens_details=prompt_details,
        completion_tokens_details=completion_details,
    )


def _make_response(usage: SimpleNamespace) -> SimpleNamespace:
    return SimpleNamespace(usage=usage, choices=[])


# ======================================================================
# 写入
# ======================================================================


class TestTokenRecord:
    def test_record_returns_id(self, tracker: TokenTracker) -> None:
        """record 返回自增 id。"""
        id1 = tracker.record(
            model="deepseek-chat",
            prompt_tokens=100,
            completion_tokens=50,
        )
        id2 = tracker.record(
            model="deepseek-chat",
            prompt_tokens=200,
            completion_tokens=30,
        )
        assert id1 > 0
        assert id2 == id1 + 1

    def test_record_auto_total(self, tracker: TokenTracker) -> None:
        """total_tokens 为空时自动按 prompt+completion 计算。"""
        pid = tracker.record(
            model="deepseek-chat",
            prompt_tokens=120,
            completion_tokens=80,
        )
        rows = tracker.recent(limit=1)
        assert len(rows) == 1
        assert rows[0]["id"] == pid
        assert rows[0]["total_tokens"] == 200
        assert rows[0]["prompt_tokens"] == 120
        assert rows[0]["completion_tokens"] == 80
        assert rows[0]["cached_tokens"] == 0
        assert rows[0]["reasoning_tokens"] == 0

    def test_record_explicit_total(self, tracker: TokenTracker) -> None:
        """显式传入 total_tokens 时按原值存。"""
        tracker.record(
            model="deepseek-chat",
            prompt_tokens=100,
            completion_tokens=50,
            total_tokens=999,
        )
        rows = tracker.recent(limit=1)
        assert rows[0]["total_tokens"] == 999

    def test_record_with_all_fields(self, tracker: TokenTracker) -> None:
        """record 写入 model/phase/request_id + 缓存/推理 token。"""
        pid = tracker.record(
            model="deepseek-reasoner",
            prompt_tokens=300,
            completion_tokens=200,
            cached_tokens=100,
            reasoning_tokens=80,
            phase="agent",
            request_id="req-1",
        )
        assert pid > 0
        rows = tracker.recent(limit=1)
        row = rows[0]
        assert row["model"] == "deepseek-reasoner"
        assert row["phase"] == "agent"
        assert row["request_id"] == "req-1"
        assert row["cached_tokens"] == 100
        assert row["reasoning_tokens"] == 80

    def test_record_from_response_basic(self, tracker: TokenTracker) -> None:
        """record_from_response 从 OpenAI response 对象提取 usage。"""
        resp = _make_response(_make_usage(prompt=500, completion=120))
        pid = tracker.record_from_response(resp, model="deepseek-chat", phase="agent")
        assert pid > 0
        row = tracker.recent(limit=1)[0]
        assert row["prompt_tokens"] == 500
        assert row["completion_tokens"] == 120
        assert row["total_tokens"] == 620
        assert row["cached_tokens"] == 0

    def test_record_from_response_with_cache_and_reasoning(self, tracker: TokenTracker) -> None:
        """record_from_response 提取 cached_tokens + reasoning_tokens。"""
        resp = _make_response(
            _make_usage(
                prompt=1000,
                completion=400,
                cached=600,
                reasoning=150,
            )
        )
        tracker.record_from_response(
            resp, model="deepseek-reasoner", phase="backtest", request_id="run-42"
        )
        row = tracker.recent(limit=1)[0]
        assert row["prompt_tokens"] == 1000
        assert row["completion_tokens"] == 400
        assert row["total_tokens"] == 1400
        assert row["cached_tokens"] == 600
        assert row["reasoning_tokens"] == 150
        assert row["request_id"] == "run-42"
        assert row["phase"] == "backtest"

    def test_record_from_response_without_details(self, tracker: TokenTracker) -> None:
        """usage 没有 *_details 字段时 cached/reasoning 记为 0。"""
        usage = SimpleNamespace(
            prompt_tokens=200,
            completion_tokens=50,
            total_tokens=250,
            prompt_tokens_details=None,
            completion_tokens_details=None,
        )
        resp = _make_response(usage)
        tracker.record_from_response(resp, model="gpt-4o-mini")
        row = tracker.recent(limit=1)[0]
        assert row["cached_tokens"] == 0
        assert row["reasoning_tokens"] == 0

    def test_record_from_response_missing_usage_raises(self, tracker: TokenTracker) -> None:
        """response 无 usage 时抛 ValueError。"""
        resp = SimpleNamespace(usage=None)
        with pytest.raises(ValueError):
            tracker.record_from_response(resp, model="deepseek-chat")


# ======================================================================
# 聚合
# ======================================================================


class TestTokenTotals:
    def test_totals_all(self, tracker: TokenTracker) -> None:
        """totals 汇总全部记录。"""
        tracker.record(model="deepseek-chat", prompt_tokens=100, completion_tokens=50)
        tracker.record(model="deepseek-chat", prompt_tokens=200, completion_tokens=80)
        t = tracker.totals()
        assert t["calls"] == 2
        assert t["prompt_tokens"] == 300
        assert t["completion_tokens"] == 130
        assert t["total_tokens"] == 430

    def test_totals_by_model(self, tracker: TokenTracker) -> None:
        """totals 按 model 过滤。"""
        tracker.record(model="deepseek-chat", prompt_tokens=100, completion_tokens=50)
        tracker.record(model="gpt-4o-mini", prompt_tokens=300, completion_tokens=100)
        t = tracker.totals(model="gpt-4o-mini")
        assert t["calls"] == 1
        assert t["prompt_tokens"] == 300
        assert t["completion_tokens"] == 100

    def test_totals_by_phase(self, tracker: TokenTracker) -> None:
        """totals 按 phase 过滤。"""
        tracker.record(
            model="deepseek-chat", prompt_tokens=100, completion_tokens=50, phase="agent"
        )
        tracker.record(
            model="deepseek-chat", prompt_tokens=500, completion_tokens=200, phase="extraction"
        )
        tracker.record(model="deepseek-chat", prompt_tokens=50, completion_tokens=20, phase="agent")
        t_agent = tracker.totals(phase="agent")
        assert t_agent["calls"] == 2
        assert t_agent["prompt_tokens"] == 150
        assert t_agent["completion_tokens"] == 70

    def test_totals_by_request_id(self, tracker: TokenTracker) -> None:
        """totals 按 request_id 分组（一次对话多轮 LLM 调用）。"""
        tracker.record(
            model="deepseek-chat", prompt_tokens=100, completion_tokens=50, request_id="r1"
        )
        tracker.record(
            model="deepseek-chat", prompt_tokens=200, completion_tokens=100, request_id="r1"
        )
        tracker.record(
            model="deepseek-chat", prompt_tokens=300, completion_tokens=150, request_id="r2"
        )
        t = tracker.totals(request_id="r1")
        assert t["calls"] == 2
        assert t["total_tokens"] == 450

    def test_totals_empty(self, tracker: TokenTracker) -> None:
        """空库 totals 返回全 0。"""
        t = tracker.totals()
        assert t["calls"] == 0
        assert t["prompt_tokens"] == 0
        assert t["completion_tokens"] == 0
        assert t["total_tokens"] == 0
        assert t["cached_tokens"] == 0
        assert t["reasoning_tokens"] == 0

    def test_totals_includes_cached_and_reasoning(self, tracker: TokenTracker) -> None:
        """totals 汇总 cached / reasoning token。"""
        tracker.record(
            model="deepseek-reasoner",
            prompt_tokens=400,
            completion_tokens=200,
            cached_tokens=100,
            reasoning_tokens=80,
        )
        t = tracker.totals()
        assert t["cached_tokens"] == 100
        assert t["reasoning_tokens"] == 80


# ======================================================================
# 查询
# ======================================================================


class TestTokenRecent:
    def test_recent_ordered_desc(self, tracker: TokenTracker) -> None:
        """recent 按 created_at 降序。"""
        id1 = tracker.record(model="deepseek-chat", prompt_tokens=10, completion_tokens=5)
        id2 = tracker.record(model="deepseek-chat", prompt_tokens=20, completion_tokens=8)
        rows = tracker.recent(limit=10)
        assert len(rows) == 2
        assert rows[0]["id"] == id2  # 后写的排前面
        assert rows[1]["id"] == id1

    def test_recent_limit(self, tracker: TokenTracker) -> None:
        """recent 受 limit 限制。"""
        for i in range(5):
            tracker.record(model="deepseek-chat", prompt_tokens=i, completion_tokens=1)
        rows = tracker.recent(limit=2)
        assert len(rows) == 2

    def test_recent_filter_model(self, tracker: TokenTracker) -> None:
        """recent 按 model 过滤。"""
        tracker.record(model="deepseek-chat", prompt_tokens=10, completion_tokens=5)
        tracker.record(model="gpt-4o-mini", prompt_tokens=20, completion_tokens=8)
        rows = tracker.recent(limit=10, model="gpt-4o-mini")
        assert len(rows) == 1
        assert rows[0]["model"] == "gpt-4o-mini"

    def test_recent_filter_phase(self, tracker: TokenTracker) -> None:
        """recent 按 phase 过滤。"""
        tracker.record(model="deepseek-chat", prompt_tokens=10, completion_tokens=5, phase="agent")
        tracker.record(
            model="deepseek-chat", prompt_tokens=20, completion_tokens=8, phase="extraction"
        )
        rows = tracker.recent(limit=10, phase="agent")
        assert len(rows) == 1
        assert rows[0]["phase"] == "agent"


# ======================================================================
# 分组聚合
# ======================================================================


class TestTokenGroupBy:
    def test_by_model(self, tracker: TokenTracker) -> None:
        """by_model 按 model 聚合，按 total_tokens 降序。"""
        tracker.record(model="gpt-4o-mini", prompt_tokens=100, completion_tokens=50)
        tracker.record(model="deepseek-chat", prompt_tokens=300, completion_tokens=200)
        tracker.record(model="deepseek-chat", prompt_tokens=200, completion_tokens=100)
        groups = tracker.by_model()
        assert len(groups) == 2
        # deepseek-chat 总 token 800 > gpt-4o-mini 150，排前面
        assert groups[0]["model"] == "deepseek-chat"
        assert groups[0]["total_tokens"] == 800
        assert groups[0]["calls"] == 2
        assert groups[1]["model"] == "gpt-4o-mini"
        assert groups[1]["total_tokens"] == 150

    def test_by_phase(self, tracker: TokenTracker) -> None:
        """by_phase 聚合，NULL 归入 'unknown'。"""
        tracker.record(
            model="deepseek-chat", prompt_tokens=100, completion_tokens=50, phase="agent"
        )
        tracker.record(
            model="deepseek-chat", prompt_tokens=50, completion_tokens=20, phase="extraction"
        )
        tracker.record(model="deepseek-chat", prompt_tokens=30, completion_tokens=10)  # phase=None
        groups = tracker.by_phase()
        phases = {g["phase"] for g in groups}
        assert "agent" in phases
        assert "extraction" in phases
        assert "unknown" in phases

    def test_by_day(self, tracker: TokenTracker) -> None:
        """by_day 按日期分组。"""
        tracker.record(model="deepseek-chat", prompt_tokens=100, completion_tokens=50)
        rows = tracker.by_day()
        assert len(rows) == 1
        day = rows[0]["day"]
        # day 形如 YYYY-MM-DD，可被 strptime 解析
        assert datetime.strptime(day, "%Y-%m-%d") is not None
        assert rows[0]["calls"] == 1
        assert rows[0]["total_tokens"] == 150


# ======================================================================
# 成本估算
# ======================================================================


class TestTokenCost:
    def test_cost_estimate_basic(self, tracker: TokenTracker) -> None:
        """cost_estimate 按定价表估算成本（无缓存）。"""
        # deepseek-chat: input 0.27/M, output 1.10/M
        tracker.record(
            model="deepseek-chat",
            prompt_tokens=1_000_000,
            completion_tokens=1_000_000,
        )
        cost = tracker.cost_estimate()
        assert cost["total_usd"] == pytest.approx(0.27 + 1.10, rel=1e-6)
        assert cost["by_model"]["deepseek-chat"]["usd"] == pytest.approx(1.37, rel=1e-6)

    def test_cost_estimate_with_cache(self, tracker: TokenTracker) -> None:
        """缓存命中的 prompt token 按 input_cached 价计算。"""
        # 1M prompt 中 600K 命中缓存
        # 成本 = 400K * 0.27/M + 600K * 0.07/M + 1M * 1.10/M
        tracker.record(
            model="deepseek-chat",
            prompt_tokens=1_000_000,
            completion_tokens=1_000_000,
            cached_tokens=600_000,
        )
        cost = tracker.cost_estimate()
        expected = 0.4 * 0.27 + 0.6 * 0.07 + 1.0 * 1.10
        assert cost["total_usd"] == pytest.approx(expected, rel=1e-6)

    def test_cost_estimate_multiple_models(self, tracker: TokenTracker) -> None:
        """多模型分别计费。"""
        tracker.record(model="deepseek-chat", prompt_tokens=1_000_000, completion_tokens=0)
        tracker.record(model="gpt-4o-mini", prompt_tokens=1_000_000, completion_tokens=0)
        cost = tracker.cost_estimate()
        assert "deepseek-chat" in cost["by_model"]
        assert "gpt-4o-mini" in cost["by_model"]
        # deepseek input 0.27 > gpt-4o-mini input 0.15
        assert cost["by_model"]["deepseek-chat"]["usd"] > cost["by_model"]["gpt-4o-mini"]["usd"]

    def test_cost_estimate_custom_pricing(self, tracker: TokenTracker) -> None:
        """自定义定价表覆盖默认。"""
        tracker.record(model="my-model", prompt_tokens=2_000_000, completion_tokens=0)
        custom = {"my-model": {"input": 1.0, "input_cached": 1.0, "output": 2.0}}
        cost = tracker.cost_estimate(pricing=custom)
        assert cost["total_usd"] == pytest.approx(2.0, rel=1e-6)

    def test_cost_estimate_unknown_model_zero(self, tracker: TokenTracker) -> None:
        """未知模型（定价表无匹配）成本为 0。"""
        tracker.record(
            model="totally-unknown-xyz", prompt_tokens=1_000_000, completion_tokens=1_000_000
        )
        cost = tracker.cost_estimate()
        assert cost["total_usd"] == 0.0

    def test_cost_estimate_prefix_match(self, tracker: TokenTracker) -> None:
        """模型名带版本后缀时按前缀匹配定价。"""
        tracker.record(
            model="deepseek-chat-002",
            prompt_tokens=1_000_000,
            completion_tokens=0,
        )
        cost = tracker.cost_estimate()
        # 匹配 deepseek-chat 前缀
        assert cost["total_usd"] == pytest.approx(0.27, rel=1e-6)

    def test_cost_estimate_filter_phase(self, tracker: TokenTracker) -> None:
        """cost_estimate 可按 phase 过滤。"""
        tracker.record(
            model="deepseek-chat",
            prompt_tokens=1_000_000,
            completion_tokens=0,
            phase="agent",
        )
        tracker.record(
            model="deepseek-chat",
            prompt_tokens=500_000,
            completion_tokens=0,
            phase="extraction",
        )
        cost_agent = tracker.cost_estimate(phase="agent")
        assert cost_agent["total_usd"] == pytest.approx(0.27, rel=1e-6)
        assert list(cost_agent["by_model"].keys()) == ["deepseek-chat"]

    def test_cost_estimate_empty(self, tracker: TokenTracker) -> None:
        """空库成本为 0。"""
        cost = tracker.cost_estimate()
        assert cost["total_usd"] == 0.0
        assert cost["by_model"] == {}

    def test_default_pricing_table_populated(self) -> None:
        """默认定价表包含已知模型。"""
        assert "deepseek-chat" in DEFAULT_PRICING
        ds = DEFAULT_PRICING["deepseek-chat"]
        assert "input" in ds
        assert "input_cached" in ds
        assert "output" in ds
        # 缓存价应低于未缓存价
        assert ds["input_cached"] <= ds["input"]


# ======================================================================
# 维护
# ======================================================================


class TestTokenMaintenance:
    def test_reset_clears_and_returns_count(self, tracker: TokenTracker) -> None:
        """reset 清空记录并返回删除行数。"""
        for _ in range(3):
            tracker.record(model="deepseek-chat", prompt_tokens=10, completion_tokens=5)
        assert tracker.count() == 3
        deleted = tracker.reset()
        assert deleted == 3
        assert tracker.count() == 0
        assert tracker.totals()["calls"] == 0

    def test_count(self, tracker: TokenTracker) -> None:
        """count 返回记录总数。"""
        assert tracker.count() == 0
        tracker.record(model="deepseek-chat", prompt_tokens=10, completion_tokens=5)
        tracker.record(model="deepseek-chat", prompt_tokens=20, completion_tokens=8)
        assert tracker.count() == 2

    def test_reset_empty(self, tracker: TokenTracker) -> None:
        """空库 reset 返回 0。"""
        assert tracker.reset() == 0


# ======================================================================
# 持久化
# ======================================================================


class TestTokenPersistence:
    def test_persists_across_instances(self, tmp_path: Path) -> None:
        """同一 db 文件多个 TokenTracker 实例共享数据。"""
        db = tmp_path / "persist.db"
        t1 = TokenTracker(db)
        t1.record(model="deepseek-chat", prompt_tokens=100, completion_tokens=50)
        assert t1.count() == 1

        t2 = TokenTracker(db)
        assert t2.count() == 1
        assert t2.totals()["prompt_tokens"] == 100

    def test_creates_parent_dir(self, tmp_path: Path) -> None:
        """db 父目录不存在时自动创建。"""
        db = tmp_path / "nested" / "deep" / "tokens.db"
        TokenTracker(db)
        assert db.exists()

    def test_schema_idempotent(self, tmp_path: Path) -> None:
        """重复实例化同一 db 不报错（CREATE IF NOT EXISTS）。"""
        db = tmp_path / "idem.db"
        t1 = TokenTracker(db)
        t1.record(model="deepseek-chat", prompt_tokens=10, completion_tokens=5)
        t2 = TokenTracker(db)
        assert t2.count() == 1
