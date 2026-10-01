"""阶段四工具单测（全离线）：A 股指数通路 + regime 序列 + 叙事 scope/变化检测。

覆盖：
- get_index_bars：INDEX_LIST 白名单、防错源（裸 '000001' 拒绝且不打 adapter）、
  判定标的标注
- market_regime_series：服务接线 + 判定标的/探索性标注 + 防错源
- get_market_narrative：scope 参数暴露（narrative 层 scope 透传 + 降级路径过滤）
- detect_market_changes：LLM 路径与无 LLM 降级路径（两段原始事件）
"""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest

from mommy_chaogu.agent.episodic_memory import EpisodicMemory
from mommy_chaogu.agent.tools import ToolContext, ToolRegistry
from mommy_chaogu.market_data.types import AdjustmentType, Bar, BarInterval, Money


def _index_bar(code: str, day: int, close: str) -> Bar:
    return Bar(
        code=code,
        name="上证指数",
        interval=BarInterval.D1,
        adjustment=AdjustmentType.FORWARD,
        timestamp=datetime(2026, 7, 1) + timedelta(days=day),
        open=Decimal(close),
        high=Decimal(close),
        low=Decimal(close),
        close=Decimal(close),
        volume=1000,
        turnover=Money.from_yuan("1000"),
    )


def _bull_bars(code: str, n: int = 120) -> list[Bar]:
    closes = [100.0 * (1.004**i) for i in range(n)]
    return [_index_bar(code, i, f"{c:.2f}") for i, c in enumerate(closes)]


class FakeAdapter:
    name = "fake"

    def __init__(self, bars_by_code: dict[str, list[Bar]]) -> None:
        self._bars = bars_by_code
        self.calls: list[tuple[str, int | None]] = []

    def get_bars(
        self,
        code: str,
        interval: BarInterval = BarInterval.D1,
        adjustment: AdjustmentType = AdjustmentType.FORWARD,
        start: Any = None,
        end: Any = None,
        limit: int | None = None,
    ) -> list[Bar]:
        self.calls.append((code, limit))
        bars = self._bars.get(code, [])
        return list(bars[-limit:]) if limit is not None else list(bars)


def _registry(adapter: FakeAdapter, **ctx_kwargs: Any) -> tuple[ToolRegistry, FakeAdapter]:
    return ToolRegistry(ToolContext(adapter=adapter, **ctx_kwargs)), adapter


def _all_defs() -> list[dict[str, Any]]:
    return ToolRegistry(ToolContext(adapter=MagicMock())).definitions()


# ---------- get_index_bars ----------


class TestGetIndexBars:
    def test_passes_prefixed_index_code_and_annotates_subject(self) -> None:
        registry, adapter = _registry(FakeAdapter({"sh000001": _bull_bars("sh000001")}))

        result = registry.call("get_index_bars", {"code": "sh000001", "limit": 5})
        data = json.loads(result)

        # 透传的是带前缀的指数代码，不是 6 位个股码
        assert adapter.calls == [("sh000001", 5)]
        assert data["subject"] == "上证指数 sh000001"
        assert data["index_name"] == "上证指数"
        assert data["index_code"] == "sh000001"
        assert data["secid"] == "1.000001"
        assert data["note"] == "判定标的：上证指数 sh000001（东财 secid 1.000001）"
        assert data["count"] == 5
        assert data["bars"][0]["close"] > 0

    def test_bare_stock_code_rejected_without_adapter_call(self) -> None:
        """防错源（R10）：'000001' 是平安银行，必须拒绝而不是静默拉个股日 K。"""
        registry, adapter = _registry(FakeAdapter({"000001": _bull_bars("000001")}))

        result = registry.call("get_index_bars", {"code": "000001"})
        data = json.loads(result)

        assert "error" in data
        assert "平安银行" in data["hint"]
        assert "sh000001" in data["hint"]
        assert adapter.calls == []

    def test_resolves_by_name_and_secid(self) -> None:
        registry, adapter = _registry(FakeAdapter({"sz399006": _bull_bars("sz399006", 10)}))

        by_name = json.loads(registry.call("get_index_bars", {"code": "创业板指"}))
        by_secid = json.loads(registry.call("get_index_bars", {"code": "0.399006"}))

        assert by_name["subject"] == "创业板指 sz399006"
        assert by_secid["index_code"] == "sz399006"
        assert {call[0] for call in adapter.calls} == {"sz399006"}

    def test_empty_bars_returns_error_with_subject(self) -> None:
        registry, _ = _registry(FakeAdapter({}))
        data = json.loads(registry.call("get_index_bars", {"code": "sh000688"}))
        assert "error" in data
        assert data["subject"] == "科创50 sh000688"

    def test_definition_enum_only_index_codes(self) -> None:
        defs = {d["function"]["name"]: d for d in _all_defs()}
        code_prop = defs["get_index_bars"]["function"]["parameters"]["properties"]["code"]
        assert set(code_prop["enum"]) == {
            "sh000001",
            "sz399001",
            "sz399006",
            "sh000300",
            "sh000688",
            "sh000016",
        }


# ---------- market_regime_series ----------


class TestMarketRegimeSeries:
    def test_returns_series_with_subject_and_note(self) -> None:
        registry, _ = _registry(FakeAdapter({"sh000001": _bull_bars("sh000001")}))

        data = json.loads(
            registry.call("market_regime_series", {"index_code": "sh000001", "days": 20})
        )

        assert data["subject"] == "上证指数 sh000001"
        assert data["current_regime"] == "bull"
        assert data["counts"]["bull"] == 20
        assert len(data["series"]) == 20
        assert "探索性状态评估" in data["note"]
        assert "bull×20" in data["summary"]

    def test_bare_stock_code_rejected(self) -> None:
        registry, adapter = _registry(FakeAdapter({"000001": _bull_bars("000001")}))
        data = json.loads(registry.call("market_regime_series", {"index_code": "000001"}))
        assert "error" in data
        assert adapter.calls == []

    def test_registered_in_tool_names(self) -> None:
        names = ToolRegistry.tool_names()
        assert "get_index_bars" in names
        assert "market_regime_series" in names
        assert "detect_market_changes" in names


# ---------- get_market_narrative scope ----------


def _mock_client(response_text: str = "测试叙述文本") -> MagicMock:
    client = MagicMock()
    resp = MagicMock()
    resp.choices = [MagicMock()]
    resp.choices[0].message.content = response_text
    client.chat.completions.create.return_value = resp
    return client


class TestGetMarketNarrativeScope:
    def test_scope_passed_to_narrative_layer(self, tmp_path: Path) -> None:
        """只写 sector scope 的事件：scope 正确透传时 LLM 被调用，market 默认则无事件。"""
        db = tmp_path / "agent.db"
        em = EpisodicMemory(db)
        em.write(
            event_type="market_snapshot",
            scope="sector:半导体",
            summary="半导体板块主力大幅流入",
            data={},
        )
        client = _mock_client("半导体主线延续")

        ctx = ToolContext(adapter=MagicMock(), db_path=db, client=client, model="test-model")
        reg = ToolRegistry(ctx)

        with_scope = json.loads(
            reg.call("get_market_narrative", {"days": 7, "scope": "sector:半导体"})
        )
        assert with_scope["narrative"] == "半导体主线延续"
        assert with_scope["scope"] == "sector:半导体"
        client.chat.completions.create.assert_called_once()

        # 默认 market scope 下没有事件 → 不调 LLM、返回无记录提示
        default_scope = json.loads(reg.call("get_market_narrative", {"days": 7}))
        assert "没有" in default_scope["narrative"]
        assert default_scope["scope"] == "market"
        client.chat.completions.create.assert_called_once()  # 仍只有第一次

    def test_degraded_path_filters_events_by_scope(self, tmp_path: Path) -> None:
        db = tmp_path / "agent.db"
        em = EpisodicMemory(db)
        em.write(event_type="market_snapshot", scope="market", summary="全市场平稳", data={})
        em.write(event_type="market_snapshot", scope="sector:半导体", summary="半导体大涨", data={})

        ctx = ToolContext(adapter=MagicMock(), db_path=db)  # client=None → 降级
        reg = ToolRegistry(ctx)
        data = json.loads(reg.call("get_market_narrative", {"days": 7, "scope": "sector:半导体"}))

        assert data["degraded"] is True
        assert data["scope"] == "sector:半导体"
        assert len(data["events"]) == 1
        assert data["events"][0]["summary"] == "半导体大涨"

    def test_invalid_scope_rejected(self, tmp_path: Path) -> None:
        ctx = ToolContext(adapter=MagicMock(), db_path=tmp_path / "agent.db")
        data = json.loads(ToolRegistry(ctx).call("get_market_narrative", {"scope": "全市场"}))
        assert "error" in data


# ---------- detect_market_changes ----------


class TestDetectMarketChanges:
    def test_no_db_returns_error(self) -> None:
        registry = ToolRegistry(ToolContext(adapter=MagicMock()))
        assert "error" in json.loads(registry.call("detect_market_changes", {}))

    def test_llm_path_returns_changes_text(self, tmp_path: Path) -> None:
        db = tmp_path / "agent.db"
        em = EpisodicMemory(db)
        em.write(event_type="market_snapshot", scope="market", summary="风格切换", data={})
        client = _mock_client("[风格] 之前防守，现在进攻")

        ctx = ToolContext(adapter=MagicMock(), db_path=db, client=client, model="test-model")
        data = json.loads(ToolRegistry(ctx).call("detect_market_changes", {"scope": "market"}))

        assert data["changes"] == "[风格] 之前防守，现在进攻"
        assert data["scope"] == "market"
        client.chat.completions.create.assert_called_once()

    def test_degrades_to_event_lists_without_llm(self, tmp_path: Path) -> None:
        db = tmp_path / "agent.db"
        em = EpisodicMemory(db)
        em.write(event_type="market_snapshot", scope="market", summary="今天的事件", data={})
        # prior 窗口（之前 10 天）按 trade_date 过滤：写一条 trade_date=5 天前的事件
        em.write(
            event_type="market_snapshot",
            scope="market",
            summary="五天前的事件",
            data={},
            trade_date=(datetime.now(UTC) - timedelta(days=5)).strftime("%Y-%m-%d"),
        )

        ctx = ToolContext(adapter=MagicMock(), db_path=db)  # client=None → 降级
        data = json.loads(ToolRegistry(ctx).call("detect_market_changes", {}))

        assert data["degraded"] is True
        assert data["scope"] == "market"
        summaries_recent = [e["summary"] for e in data["recent_events"]]
        summaries_prior = [e["summary"] for e in data["prior_events"]]
        assert "今天的事件" in summaries_recent
        assert "五天前的事件" in summaries_prior

    def test_scope_filters_events(self, tmp_path: Path) -> None:
        db = tmp_path / "agent.db"
        em = EpisodicMemory(db)
        em.write(event_type="market_snapshot", scope="market", summary="市场事件", data={})
        em.write(event_type="market_snapshot", scope="stock:603662", summary="个股事件", data={})

        ctx = ToolContext(adapter=MagicMock(), db_path=db)
        data = json.loads(
            ToolRegistry(ctx).call("detect_market_changes", {"scope": "stock:603662"})
        )
        assert data["scope"] == "stock:603662"
        assert [e["summary"] for e in data["recent_events"]] == ["个股事件"]

    def test_invalid_scope_rejected(self, tmp_path: Path) -> None:
        ctx = ToolContext(adapter=MagicMock(), db_path=tmp_path / "agent.db")
        assert "error" in json.loads(
            ToolRegistry(ctx).call("detect_market_changes", {"scope": "sector"})
        )


# ---------- scope 参数的 DEFS 契约 ----------


class TestScopeDefs:
    @pytest.mark.parametrize(
        ("tool", "param"),
        [("get_market_narrative", "scope"), ("detect_market_changes", "scope")],
    )
    def test_scope_param_pattern_exposed(self, tool: str, param: str) -> None:
        defs = {d["function"]["name"]: d for d in _all_defs()}
        props = defs[tool]["function"]["parameters"]["properties"]
        assert props[param]["pattern"] == "^(market|sector:.+|stock:.+)$"
        assert props[param]["default"] == "market"
