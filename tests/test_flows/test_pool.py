"""flows.pool 单测 — 股票池抽象。

覆盖：
- CustomPool：去重、保序、trim、skip empty、name/codes/describe
- WatchlistPool / SemiconPool：mock store 验证 codes() 转发
- build_pool 工厂：三种池 + 错误分支
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from mommy_chaogu.flows.pool import (
    CustomPool,
    PoolSource,
    SemiconPool,
    WatchlistPool,
    build_pool,
)

# ========== CustomPool ==========


def test_custom_pool_name() -> None:
    assert CustomPool(["600519"]).name == "custom"


def test_custom_pool_codes_preserves_order() -> None:
    pool = CustomPool(["000001", "600519", "000002"])
    assert pool.codes() == ["000001", "600519", "000002"]


def test_custom_pool_codes_dedup() -> None:
    pool = CustomPool(["000001", "600519", "000001", "600519"])
    assert pool.codes() == ["000001", "600519"]


def test_custom_pool_strips_whitespace() -> None:
    pool = CustomPool(["  600519  ", " 000001"])
    assert pool.codes() == ["600519", "000001"]


def test_custom_pool_skips_empty() -> None:
    pool = CustomPool(["600519", "", "  ", "000001"])
    assert pool.codes() == ["600519", "000001"]


def test_custom_pool_codes_returns_copy() -> None:
    """codes() 返回的是副本，修改不影响内部状态。"""
    pool = CustomPool(["600519"])
    codes = pool.codes()
    codes.append("000001")
    assert pool.codes() == ["600519"]


def test_custom_pool_describe() -> None:
    pool = CustomPool(["600519", "000001"])
    desc = pool.describe()
    assert "custom" in desc
    assert "2" in desc


def test_custom_pool_satisfies_protocol() -> None:
    pool: PoolSource = CustomPool(["600519"])
    # Protocol 是结构性，调用接口方法即可验证
    assert pool.name == "custom"
    assert pool.codes() == ["600519"]
    assert isinstance(pool.describe(), str)


# ========== WatchlistPool ==========


def test_watchlist_pool_name() -> None:
    pool = WatchlistPool(Path("/tmp/fake.db"))
    assert pool.name == "watchlist"


@patch("mommy_chaogu.watchlist.WatchlistStore")
def test_watchlist_pool_codes(mock_store_cls: MagicMock) -> None:
    mock_instance = mock_store_cls.return_value
    mock_instance.get_all_codes.return_value = ["600519", "000001"]
    pool = WatchlistPool(Path("/tmp/fake.db"))
    assert pool.codes() == ["600519", "000001"]
    mock_instance.get_all_codes.assert_called_once()


@patch("mommy_chaogu.watchlist.WatchlistStore")
def test_watchlist_pool_describe(mock_store_cls: MagicMock) -> None:
    mock_instance = mock_store_cls.return_value
    mock_instance.get_all_codes.return_value = ["600519", "000001"]
    pool = WatchlistPool(Path("/tmp/fake.db"))
    desc = pool.describe()
    assert "watchlist" in desc
    assert "2" in desc
    assert "自选股" in desc


# ========== SemiconPool ==========


def test_semicon_pool_name() -> None:
    pool = SemiconPool(Path("/tmp/fake.db"))
    assert pool.name == "semicon"


@patch("mommy_chaogu.semicon.SemiconStore")
def test_semicon_pool_codes(mock_store_cls: MagicMock) -> None:
    mock_instance = mock_store_cls.return_value
    mock_instance.list_codes.return_value = ["300782", "688981"]
    pool = SemiconPool(Path("/tmp/fake.db"))
    assert pool.codes() == ["300782", "688981"]
    mock_instance.list_codes.assert_called_once()


@patch("mommy_chaogu.semicon.SemiconStore")
def test_semicon_pool_describe(mock_store_cls: MagicMock) -> None:
    mock_instance = mock_store_cls.return_value
    mock_instance.list_codes.return_value = ["300782", "688981"]
    pool = SemiconPool(Path("/tmp/fake.db"))
    desc = pool.describe()
    assert "semicon" in desc
    assert "2" in desc
    assert "产业链" in desc


# ========== build_pool 工厂 ==========


def test_build_pool_watchlist() -> None:
    pool = build_pool("watchlist", Path("/tmp/fake.db"))
    assert isinstance(pool, WatchlistPool)
    assert pool.name == "watchlist"


def test_build_pool_semicon() -> None:
    pool = build_pool("semicon", Path("/tmp/fake.db"))
    assert isinstance(pool, SemiconPool)
    assert pool.name == "semicon"


def test_build_pool_custom() -> None:
    pool = build_pool("custom", Path("/tmp/fake.db"), custom_codes=["600519"])
    assert isinstance(pool, CustomPool)
    assert pool.codes() == ["600519"]


def test_build_pool_custom_requires_codes() -> None:
    with pytest.raises(ValueError, match="--codes"):
        build_pool("custom", Path("/tmp/fake.db"))


def test_build_pool_custom_empty_codes_raises() -> None:
    with pytest.raises(ValueError, match="--codes"):
        build_pool("custom", Path("/tmp/fake.db"), custom_codes=[])


def test_build_pool_unknown_raises() -> None:
    with pytest.raises(ValueError, match="未知 pool"):
        build_pool("invalid", Path("/tmp/fake.db"))
