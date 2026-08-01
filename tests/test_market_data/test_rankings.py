"""Market ranking batching tests."""

from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from mommy_chaogu.market_data.rankings import fetch_indexes


def test_fetch_indexes_uses_one_batched_request(monkeypatch: pytest.MonkeyPatch) -> None:
    response = MagicMock()
    response.json.return_value = {
        "data": {
            "diff": [
                {"f12": "000001", "f13": 1, "f14": "上证指数", "f2": 3200, "f3": 1.2, "f18": 3162},
                {
                    "f12": "399001",
                    "f13": 0,
                    "f14": "深证成指",
                    "f2": 10500,
                    "f3": -0.3,
                    "f18": 10531,
                },
            ]
        }
    }
    get = MagicMock(return_value=response)
    monkeypatch.setattr("mommy_chaogu.market_data.rankings.requests.get", get)

    indexes = fetch_indexes()

    assert [item.name for item in indexes] == ["上证指数", "深证成指"]
    get.assert_called_once()
    assert get.call_args.kwargs["timeout"] == 2
    assert "1.000001" in get.call_args.kwargs["params"]["secids"]


def test_fetch_indexes_returns_empty_on_batch_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "mommy_chaogu.market_data.rankings.requests.get",
        MagicMock(side_effect=TimeoutError("offline")),
    )
    assert fetch_indexes() == []
