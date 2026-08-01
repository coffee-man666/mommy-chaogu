"""Unified built-in-theme and user-watchlist basket service."""

from __future__ import annotations

import logging
from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any, Literal, TypedDict

from mommy_chaogu.market_data import MarketDataAdapter
from mommy_chaogu.market_data.types import Quote
from mommy_chaogu.services.theme_service import ThemeService
from mommy_chaogu.watchlist import BasketPreference, WatchlistStore

_log = logging.getLogger(__name__)

BasketKind = Literal["theme", "custom"]


class BasketMember(TypedDict):
    code: str
    name: str
    weight: Decimal | None
    note: str


class BasketDefinition(TypedDict):
    id: str
    source_id: str
    kind: BasketKind
    name: str
    description: str
    total_stocks: int
    members: list[BasketMember]
    followed: bool
    hidden: bool
    sort_order: int
    reason: str


class BasketService:
    """Join static themes, watchlist groups, user preferences, and live quotes."""

    def __init__(
        self,
        store: WatchlistStore,
        adapter: MarketDataAdapter | None = None,
        *,
        quote_overrides: Mapping[str, Quote] | None = None,
    ) -> None:
        self._store = store
        self._adapter = adapter
        self._quote_overrides = quote_overrides or {}

    def list_baskets(self, *, include_hidden: bool = True) -> list[BasketDefinition]:
        preferences = self._store.list_basket_preferences()
        member_weights = self._store.list_basket_member_weights()
        definitions: list[BasketDefinition] = []

        for index, theme in enumerate(ThemeService().list_theme_details()):
            source_id = str(theme["id"])
            basket_id = f"theme:{source_id}"
            members = [
                BasketMember(
                    code=str(stock.get("code", "")),
                    name=str(stock.get("name", "")),
                    weight=_decimal_or_none(stock.get("weight")),
                    note=str(stock.get("role") or stock.get("highlight") or ""),
                )
                for stock in theme.get("stocks", [])
                if stock.get("code")
            ]
            definitions.append(
                self._with_preference(
                    BasketDefinition(
                        id=basket_id,
                        source_id=source_id,
                        kind="theme",
                        name=str(theme["name"]),
                        description=str(theme.get("description", "")),
                        total_stocks=len(members),
                        members=members,
                        followed=index < 4,
                        hidden=False,
                        sort_order=index,
                        reason="",
                    ),
                    preferences.get(basket_id),
                )
            )

        entries_by_group = self._store.list_entries_by_group()
        group_offset = len(definitions)
        for index, (group, count) in enumerate(self._store.list_groups()):
            basket_id = f"group:{group.id}"
            members = [
                BasketMember(
                    code=entry.code,
                    name=entry.name or entry.code,
                    weight=None,
                    note=entry.note or "",
                )
                for entry in entries_by_group.get(group.name, [])
            ]
            definitions.append(
                self._with_preference(
                    BasketDefinition(
                        id=basket_id,
                        source_id=str(group.id),
                        kind="custom",
                        name=group.name,
                        description=group.description or "",
                        total_stocks=count,
                        members=members,
                        followed=True,
                        hidden=False,
                        sort_order=group_offset + index,
                        reason="",
                    ),
                    preferences.get(basket_id),
                )
            )

        for definition in definitions:
            for member in definition["members"]:
                override = member_weights.get((definition["id"], member["code"]))
                if override is not None:
                    member["weight"] = override

        definitions.sort(key=lambda item: (item["sort_order"], item["name"], item["id"]))
        if include_hidden:
            return definitions
        return [item for item in definitions if not item["hidden"]]

    def get_basket(self, basket_id: str) -> BasketDefinition | None:
        return next((item for item in self.list_baskets() if item["id"] == basket_id), None)

    def summarize(self, basket: BasketDefinition) -> dict[str, Any]:
        return self.summarize_many([basket])[basket["id"]]

    def summarize_many(self, baskets: list[BasketDefinition]) -> dict[str, dict[str, Any]]:
        """Fetch all missing member quotes in one adapter call, then summarize in memory."""
        quote_map = dict(self._quote_overrides)
        missing_codes = sorted(
            {
                member["code"]
                for basket in baskets
                for member in basket["members"]
                if member["code"] not in quote_map
            }
        )
        if missing_codes and self._adapter is not None:
            try:
                quote_map.update(
                    {quote.code: quote for quote in self._adapter.get_quotes(missing_codes)}
                )
            except Exception as exc:
                _log.warning("basket batch quote fetch failed: %s", exc)
        return {basket["id"]: self._summarize_with_quotes(basket, quote_map) for basket in baskets}

    @staticmethod
    def _summarize_with_quotes(
        basket: BasketDefinition,
        quote_map: Mapping[str, Quote],
    ) -> dict[str, Any]:
        rows: list[tuple[BasketMember, Quote]] = []
        missing = 0
        for member in basket["members"]:
            quote = quote_map.get(member["code"])
            if quote is None:
                missing += 1
                continue
            rows.append((member, quote))

        if not rows:
            return {
                "change_pct": None,
                "leader": None,
                "laggard": None,
                "anomaly": "暂无可用行情" if basket["members"] else None,
                "as_of": None,
                "status": "unavailable" if basket["members"] else "ok",
                "message": "成分股行情暂不可用" if basket["members"] else "篮子为空",
            }

        total_weight = sum(
            (member["weight"] for member, _quote in rows if member["weight"] is not None),
            Decimal("0"),
        )
        all_weighted = all(member["weight"] is not None for member, _quote in rows)
        if all_weighted and total_weight > 0:
            change_pct = (
                sum(
                    (
                        quote.change_pct * (member["weight"] or Decimal("0"))
                        for member, quote in rows
                    ),
                    Decimal("0"),
                )
                / total_weight
            )
        else:
            change_pct = sum((quote.change_pct for _member, quote in rows), Decimal("0")) / len(
                rows
            )

        leader_member, leader_quote = max(rows, key=lambda row: row[1].change_pct)
        laggard_member, laggard_quote = min(rows, key=lambda row: row[1].change_pct)
        timestamps = [
            quote.timestamp
            if quote.timestamp.tzinfo is not None
            else quote.timestamp.replace(tzinfo=UTC)
            for _member, quote in rows
            if quote.timestamp is not None
        ]
        as_of: datetime | None = min(timestamps) if timestamps else None
        dispersion = leader_quote.change_pct - laggard_quote.change_pct
        anomaly: str | None = None
        if abs(leader_quote.change_pct) >= Decimal("5"):
            anomaly = f"{leader_member['name']}波动 {leader_quote.change_pct:+.2f}%"
        elif abs(laggard_quote.change_pct) >= Decimal("5"):
            anomaly = f"{laggard_member['name']}波动 {laggard_quote.change_pct:+.2f}%"
        elif dispersion >= Decimal("5"):
            anomaly = f"成分分化 {dispersion:.2f} 个百分点"

        stale_by_age = False
        if as_of is not None:
            aware_as_of = as_of if as_of.tzinfo is not None else as_of.replace(tzinfo=UTC)
            stale_by_age = datetime.now(UTC) - aware_as_of > timedelta(minutes=15)
        status = "stale" if missing or stale_by_age else "ok"
        message = None
        if missing:
            message = f"{missing} 只成分股行情未获取"
        elif stale_by_age:
            message = "行情数据较旧"

        return {
            "change_pct": change_pct.quantize(Decimal("0.01")),
            "leader": {
                "code": leader_member["code"],
                "name": leader_member["name"],
                "change_pct": leader_quote.change_pct,
            },
            "laggard": {
                "code": laggard_member["code"],
                "name": laggard_member["name"],
                "change_pct": laggard_quote.change_pct,
            },
            "anomaly": anomaly,
            "as_of": as_of,
            "status": status,
            "message": message,
        }

    @staticmethod
    def _with_preference(
        definition: BasketDefinition,
        preference: BasketPreference | None,
    ) -> BasketDefinition:
        if preference is None:
            return definition
        definition["followed"] = bool(preference.followed)
        definition["hidden"] = bool(preference.hidden)
        if preference.sort_order is not None:
            definition["sort_order"] = int(preference.sort_order)
        definition["reason"] = str(preference.reason or "")
        return definition


def _decimal_or_none(value: object) -> Decimal | None:
    if value in (None, ""):
        return None
    try:
        return Decimal(str(value))
    except Exception:
        return None
