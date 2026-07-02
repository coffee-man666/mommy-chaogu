"""dataclass ↔ JSON 序列化器。

针对 market_data.types 的 dataclass：
- Quote / Bar / Tick / MoneyFlow / OrderBook / Board
- 所有 Money / Decimal / datetime / Enum 字段都要正确转换
"""

from __future__ import annotations

import json
from datetime import datetime
from decimal import Decimal
from typing import Any


class Serializer:
    """JSON 序列化器（Decimal / datetime / Enum 安全）。"""

    @staticmethod
    def dumps(obj: Any) -> str:
        return json.dumps(obj, default=_json_default, ensure_ascii=False)

    @staticmethod
    def loads(s: str) -> Any:
        return json.loads(s, object_hook=_json_object_hook)


def _json_default(obj: Any) -> Any:  # type: ignore[no-untyped-def]
    return _default(obj)


def _default(obj: Any) -> Any:
    if isinstance(obj, Decimal):
        return {"__decimal__": str(obj)}
    if isinstance(obj, datetime):
        return {"__datetime__": obj.isoformat()}
    # StrEnum 自动继承 str，json.dumps 本身能处理
    raise TypeError(f"Object of type {type(obj).__name__} is not JSON serializable")


def _json_object_hook(d: dict[str, Any]) -> Any:  # type: ignore[no-untyped-def]
    return _hook(d)


def _hook(d: dict[str, Any]) -> Any:
    if "__decimal__" in d:
        return Decimal(d["__decimal__"])
    if "__datetime__" in d:
        return datetime.fromisoformat(d["__datetime__"])
    return d


# ---------- 单个 dataclass 的 encode/decode ----------


def quote_to_dict(q: Any) -> dict[str, Any]:
    """Quote dataclass → JSON-safe dict。

    所有 Decimal 转 str，datetime 转 ISO str，enum 转 .value，Money 拆 amount/currency。
    """

    def _money(m) -> dict[str, Any] | None:
        if m is None:
            return None
        return {"amount": str(m.amount), "currency": m.currency}

    return {
        "code": q.code,
        "name": q.name,
        "market": q.market.value,
        "quote_type": q.quote_type.value,
        "price": str(q.price),
        "open": str(q.open),
        "high": str(q.high),
        "low": str(q.low),
        "prev_close": str(q.prev_close),
        "change": str(q.change),
        "change_pct": str(q.change_pct),
        "volume": q.volume,
        "turnover": _money(q.turnover),
        "turnover_rate": str(q.turnover_rate) if q.turnover_rate is not None else None,
        "volume_ratio": str(q.volume_ratio) if q.volume_ratio is not None else None,
        "pe_dynamic": str(q.pe_dynamic) if q.pe_dynamic is not None else None,
        "total_market_cap": _money(q.total_market_cap),
        "circulating_market_cap": _money(q.circulating_market_cap),
        "timestamp": q.timestamp.isoformat() if isinstance(q.timestamp, datetime) else q.timestamp,
        "quote_id": q.quote_id,
        "extra": q.extra,
    }


def quote_from_dict(d: dict[str, Any]) -> Any:
    """dict → Quote dataclass。"""
    from mommy_chaogu.market_data.types import MarketType, Money, Quote, QuoteType

    def _money(m: Any) -> Money | None:
        if m is None:
            return None
        if isinstance(m, dict):
            return Money(Decimal(str(m["amount"])), m.get("currency", "CNY"))
        return Money(Decimal(str(m)), "CNY")

    def _ts(v: Any) -> datetime:
        if isinstance(v, datetime):
            return v
        return datetime.fromisoformat(v)

    return Quote(
        code=d["code"],
        name=d["name"],
        market=MarketType(d["market"]),
        quote_type=QuoteType(d["quote_type"]),
        price=Decimal(str(d["price"])),
        open=Decimal(str(d["open"])),
        high=Decimal(str(d["high"])),
        low=Decimal(str(d["low"])),
        prev_close=Decimal(str(d["prev_close"])),
        change=Decimal(str(d["change"])),
        change_pct=Decimal(str(d["change_pct"])),
        volume=d["volume"],
        turnover=_money(d.get("turnover")) or Money(Decimal("0"), "CNY"),
        turnover_rate=_dec_or_none(d.get("turnover_rate")),
        volume_ratio=_dec_or_none(d.get("volume_ratio")),
        pe_dynamic=_dec_or_none(d.get("pe_dynamic")),
        total_market_cap=_money(d.get("total_market_cap")),
        circulating_market_cap=_money(d.get("circulating_market_cap")),
        timestamp=_ts(d["timestamp"]),
        quote_id=d.get("quote_id"),
        extra=d.get("extra", {}),
    )


def _dec_or_none(v: Any) -> Decimal | None:  # type: ignore[no-untyped-def]
    if v is None:
        return None
    return Decimal(str(v))
