"""Deterministic no-network adapter used only by tests."""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from mommy_chaogu.market_data.types import (
    AdjustmentType,
    Bar,
    BarInterval,
    Board,
    MarketType,
    Money,
    MoneyFlow,
    OrderBook,
    Quote,
    QuoteType,
    Tick,
)


class OfflineMarketDataAdapter:
    """Stable local evidence source; it never opens a network connection."""

    name = "offline-fixture"

    def _quote(self, code: str) -> Quote:
        now = datetime.now(UTC)
        price = Decimal("1800.00")
        return Quote(
            code=code,
            name="离线测试标的",
            market=MarketType.SH,
            quote_type=QuoteType.STOCK,
            price=price,
            open=Decimal("1790.00"),
            high=Decimal("1810.00"),
            low=Decimal("1785.00"),
            prev_close=Decimal("1795.00"),
            change=Decimal("5.00"),
            change_pct=Decimal("0.2786"),
            volume=1000000,
            turnover=Money(Decimal("1800000000")),
            turnover_rate=Decimal("1.2"),
            volume_ratio=Decimal("1.1"),
            pe_dynamic=Decimal("20"),
            total_market_cap=Money(Decimal("1000000000000")),
            circulating_market_cap=Money(Decimal("800000000000")),
            timestamp=now,
        )

    def get_quote(self, code: str) -> Quote:
        return self._quote(code)

    def get_quotes(self, codes: list[str]) -> list[Quote]:
        return [self._quote(code) for code in dict.fromkeys(codes)]

    def list_market_quotes(self) -> list[Quote]:
        return [self._quote("600519")]

    def get_order_book(self, code: str) -> OrderBook | None:
        return None

    def get_bars(
        self,
        code: str,
        interval: BarInterval = BarInterval.D1,
        adjustment: AdjustmentType = AdjustmentType.FORWARD,
        start: date | None = None,
        end: date | None = None,
        limit: int | None = None,
    ) -> list[Bar]:
        now = datetime.now(UTC).replace(hour=0, minute=0, second=0, microsecond=0)
        count = min(limit or 20, 60)
        out: list[Bar] = []
        for index in range(count):
            close = Decimal("1800") + Decimal(index)
            out.append(
                Bar(
                    code=code,
                    name="离线测试标的",
                    interval=interval,
                    adjustment=adjustment,
                    timestamp=now - timedelta(days=count - index),
                    open=close - Decimal("5"),
                    high=close + Decimal("8"),
                    low=close - Decimal("8"),
                    close=close,
                    volume=1000000 + index,
                    turnover=Money(close * Decimal("1000000")),
                    change_pct=Decimal("0.1"),
                )
            )
        return out

    def get_ticks(self, code: str, limit: int | None = None) -> list[Tick]:
        return []

    def _flow(self, code: str) -> MoneyFlow:
        return MoneyFlow(
            code=code,
            name="离线测试标的",
            timestamp=datetime.now(UTC),
            main_net=Money(Decimal("1000000")),
            small_net=Money(Decimal("-100000")),
            medium_net=Money(Decimal("-200000")),
            large_net=Money(Decimal("500000")),
            super_large_net=Money(Decimal("500000")),
            main_net_ratio=Decimal("0.1"),
        )

    def get_today_money_flow(self, code: str) -> list[MoneyFlow]:
        return [self._flow(code)]

    def get_history_money_flow(self, code: str, days: int = 30) -> list[MoneyFlow]:
        return [self._flow(code) for _ in range(min(days, 60))]

    def get_belonging_boards(self, code: str) -> list[Board]:
        return []

    def health_check(self) -> bool:
        return True
