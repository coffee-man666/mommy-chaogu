"""AgentMonitor 单测：Mock LLM + adapter 测试扫描循环。"""

from __future__ import annotations

import json
from datetime import datetime
from decimal import Decimal
from unittest.mock import MagicMock

import pytest

from mommy_chaogu.agent.monitor import (
    AgentAlert,
    AgentMonitor,
    _calc_bp,
)
from mommy_chaogu.market_data.types import (
    MarketType,
    Money,
    MoneyFlow,
    Quote,
    QuoteType,
)

# ---------- fixtures ----------


def _make_quote(code: str = "600519", name: str = "贵州茅台", pct: float = 1.82) -> Quote:
    return Quote(
        code=code,
        name=name,
        market=MarketType.SH,
        quote_type=QuoteType.STOCK,
        price=Decimal("1680.00"),
        open=Decimal("1660.00"),
        high=Decimal("1690.00"),
        low=Decimal("1655.00"),
        prev_close=Decimal("1650.00"),
        change=Decimal("30.00"),
        change_pct=Decimal(str(pct)),
        volume=12345678,
        turnover=Money.from_yuan("9999999999"),
        turnover_rate=Decimal("0.98"),
        volume_ratio=Decimal("1.23"),
        pe_dynamic=Decimal("25.5"),
        total_market_cap=Money.from_yuan("2100000000000"),
        circulating_market_cap=Money.from_yuan("2100000000000"),
        timestamp=datetime(2026, 7, 1, 15, 0, 0),
    )


def _make_flow(code: str = "600519", main_net: float = 50000000) -> MoneyFlow:
    return MoneyFlow(
        code=code,
        name="贵州茅台",
        timestamp=datetime(2026, 7, 1, 15, 0, 0),
        main_net=Money.from_yuan(str(main_net)),
        small_net=Money.from_yuan("-10000000"),
        medium_net=Money.from_yuan("-5000000"),
        large_net=Money.from_yuan("20000000"),
        super_large_net=Money.from_yuan("30000000"),
        main_net_ratio=Decimal("2.5"),
    )


@pytest.fixture
def mock_agent() -> MagicMock:
    agent = MagicMock()
    agent._model = "deepseek-chat"
    agent._client = MagicMock()
    return agent


@pytest.fixture
def mock_adapter() -> MagicMock:
    adp = MagicMock()
    adp.get_quotes.return_value = [_make_quote(), _make_quote("000001", "平安银行", -2.3)]
    adp.get_today_money_flow.return_value = [_make_flow()]
    return adp


@pytest.fixture
def mock_watchlist() -> MagicMock:
    wl = MagicMock()
    wl.get_all_codes.return_value = ["600519", "000001"]
    return wl


@pytest.fixture
def monitor(
    mock_agent: MagicMock,
    mock_adapter: MagicMock,
    mock_watchlist: MagicMock,
) -> AgentMonitor:
    return AgentMonitor(
        agent=mock_agent,  # type: ignore[arg-type]
        adapter=mock_adapter,  # type: ignore[arg-type]
        watchlist_store=mock_watchlist,  # type: ignore[arg-type]
        notifier=None,
    )


# ---------- 数据收集测试 ----------


class TestCollectData:
    def test_collects_stocks(self, monitor: AgentMonitor) -> None:
        data = monitor._collect_data()
        assert data["stock_count"] == 2
        assert len(data["stocks"]) == 2
        assert data["stocks"][0]["code"] == "600519"
        assert data["stocks"][0]["price"] == 1680.0
        assert data["stocks"][0]["change_pct"] == 1.82
        # main_net_wan = 50000000 / 10000 = 5000
        assert data["stocks"][0]["main_net_wan"] == 5000.0

    def test_empty_watchlist(self, mock_adapter: MagicMock, mock_agent: MagicMock) -> None:
        wl = MagicMock()
        wl.get_all_codes.return_value = []
        mon = AgentMonitor(
            agent=mock_agent,  # type: ignore[arg-type]
            adapter=mock_adapter,  # type: ignore[arg-type]
            watchlist_store=wl,  # type: ignore[arg-type]
        )
        data = mon._collect_data()
        assert data["stock_count"] == 0
        assert data["stocks"] == []


class TestCalcBp:
    def test_normal_case(self) -> None:
        bp = _calc_bp(Decimal("50000000"), Decimal("100000000000"))
        assert bp is not None
        # 50000000 / 100000000000 * 10000 = 5.0
        assert bp == 5.0

    def test_none_main_net(self) -> None:
        assert _calc_bp(None, Decimal("100000000000")) is None

    def test_zero_market_cap(self) -> None:
        assert _calc_bp(Decimal("50000000"), Decimal("0")) is None

    def test_both_none(self) -> None:
        assert _calc_bp(None, None) is None


# ---------- JSON 解析测试 ----------


class TestParseScanResponse:
    def test_with_alerts(self, monitor: AgentMonitor) -> None:
        text = json.dumps(
            {
                "alerts": [
                    {
                        "code": "600519",
                        "name": "贵州茅台",
                        "severity": "warning",
                        "message": "主力流入",
                    },
                    {
                        "code": "000001",
                        "name": "平安银行",
                        "severity": "critical",
                        "message": "暴跌",
                    },
                ],
                "summary": "2 只异动",
            }
        )
        alerts, summary = monitor._parse_scan_response(text)
        assert len(alerts) == 2
        assert alerts[0].code == "600519"
        assert alerts[0].severity == "warning"
        assert alerts[1].severity == "critical"
        assert summary == "2 只异动"

    def test_no_alerts(self, monitor: AgentMonitor) -> None:
        text = json.dumps({"alerts": [], "summary": "行情平淡"})
        alerts, summary = monitor._parse_scan_response(text)
        assert len(alerts) == 0
        assert summary == "行情平淡"

    def test_invalid_json(self, monitor: AgentMonitor) -> None:
        alerts, summary = monitor._parse_scan_response("not json at all")
        assert len(alerts) == 0
        assert "格式异常" in summary

    def test_invalid_severity_defaults_to_warning(self, monitor: AgentMonitor) -> None:
        text = json.dumps(
            {
                "alerts": [
                    {"code": "600519", "name": "茅台", "severity": "invalid", "message": "test"},
                ],
            }
        )
        alerts, _ = monitor._parse_scan_response(text)
        assert alerts[0].severity == "warning"


# ---------- scan_once 测试 ----------


class TestScanOnce:
    def test_no_alerts(self, monitor: AgentMonitor, mock_agent: MagicMock) -> None:
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = json.dumps(
            {
                "alerts": [],
                "summary": "行情平淡",
            }
        )
        mock_agent._client.chat.completions.create.return_value = mock_response

        result = monitor.scan_once()

        assert result.n_stocks == 2
        assert len(result.alerts) == 0
        assert result.summary == "行情平淡"

    def test_with_alerts(self, monitor: AgentMonitor, mock_agent: MagicMock) -> None:
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = json.dumps(
            {
                "alerts": [
                    {
                        "code": "600519",
                        "name": "贵州茅台",
                        "severity": "warning",
                        "message": "主力流入",
                    },
                ],
                "summary": "1 只异动",
            }
        )
        mock_agent._client.chat.completions.create.return_value = mock_response

        result = monitor.scan_once()

        assert result.n_stocks == 2
        assert len(result.alerts) == 1
        assert result.alerts[0].code == "600519"

    def test_empty_watchlist_returns_early(
        self, mock_agent: MagicMock, mock_adapter: MagicMock
    ) -> None:
        wl = MagicMock()
        wl.get_all_codes.return_value = []
        mon = AgentMonitor(
            agent=mock_agent,  # type: ignore[arg-type]
            adapter=mock_adapter,  # type: ignore[arg-type]
            watchlist_store=wl,  # type: ignore[arg-type]
        )
        result = mon.scan_once()
        assert result.n_stocks == 0
        # agent should NOT be called
        mock_agent._client.chat.completions.create.assert_not_called()

    def test_llm_exception_handled(self, monitor: AgentMonitor, mock_agent: MagicMock) -> None:
        mock_agent._client.chat.completions.create.side_effect = RuntimeError("API down")

        result = monitor.scan_once()

        assert result.n_stocks == 2
        assert len(result.alerts) == 0
        assert "失败" in result.summary


# ---------- 推送测试 ----------


class TestPushAlerts:
    def test_no_notifier_returns_empty(self, monitor: AgentMonitor) -> None:
        # monitor fixture has notifier=None
        alerts = [AgentAlert("600519", "茅台", "warning", "test")]
        pushed = monitor._push_alerts(alerts)
        assert pushed == []

    def test_with_notifier(
        self, mock_agent: MagicMock, mock_adapter: MagicMock, mock_watchlist: MagicMock
    ) -> None:
        notifier = MagicMock()
        notifier.notify_one.return_value = True

        mon = AgentMonitor(
            agent=mock_agent,  # type: ignore[arg-type]
            adapter=mock_adapter,  # type: ignore[arg-type]
            watchlist_store=mock_watchlist,  # type: ignore[arg-type]
            notifier=notifier,  # type: ignore[arg-type]
        )
        alerts = [
            AgentAlert("600519", "茅台", "warning", "主力流入"),
            AgentAlert("000001", "平安银行", "critical", "暴跌"),
        ]
        pushed = mon._push_alerts(alerts)
        assert len(pushed) == 2
        assert "600519" in pushed
        assert "000001" in pushed
        assert notifier.notify_one.call_count == 2

    def test_notifier_returns_false_on_dedup(
        self, mock_agent: MagicMock, mock_adapter: MagicMock, mock_watchlist: MagicMock
    ) -> None:
        notifier = MagicMock()
        notifier.notify_one.return_value = False  # 去重跳过

        mon = AgentMonitor(
            agent=mock_agent,  # type: ignore[arg-type]
            adapter=mock_adapter,  # type: ignore[arg-type]
            watchlist_store=mock_watchlist,  # type: ignore[arg-type]
            notifier=notifier,  # type: ignore[arg-type]
        )
        alerts = [AgentAlert("600519", "茅台", "warning", "test")]
        pushed = mon._push_alerts(alerts)
        assert pushed == []
