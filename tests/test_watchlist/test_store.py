"""WatchlistStore CRUD 单测。"""

from __future__ import annotations

from decimal import Decimal
from pathlib import Path

import pytest

from mommy_chaogu.watchlist import WatchlistStore
from mommy_chaogu.watchlist.store import (
    GroupAlreadyExistsError,
    GroupNotFoundError,
    StockEntryNotFoundError,
)


@pytest.fixture
def store(tmp_path: Path) -> WatchlistStore:
    db = tmp_path / "test_watchlist.db"
    return WatchlistStore(db)


# ---------- Group CRUD ----------


def test_empty_store_has_no_groups(store: WatchlistStore) -> None:
    assert store.list_groups() == []
    assert store.list_entries() == []


def test_add_group(store: WatchlistStore) -> None:
    g = store.add_group("白酒", description="白酒板块")
    assert g.id > 0
    assert g.name == "白酒"
    assert g.description == "白酒板块"
    assert g.created_at is not None


def test_add_duplicate_group_raises(store: WatchlistStore) -> None:
    store.add_group("白酒")
    with pytest.raises(GroupAlreadyExistsError):
        store.add_group("白酒")


def test_get_or_create_group_idempotent(store: WatchlistStore) -> None:
    g1 = store.get_or_create_group("白酒")
    g2 = store.get_or_create_group("白酒")
    assert g1.id == g2.id


def test_remove_group_cascades_entries(store: WatchlistStore) -> None:
    store.add_group("白酒")
    store.add_entry("600519", "白酒")
    store.add_entry("000858", "白酒")
    store.remove_group("白酒")
    assert store.list_entries() == []
    assert store.list_groups() == []


def test_remove_missing_group_raises(store: WatchlistStore) -> None:
    with pytest.raises(GroupNotFoundError):
        store.remove_group("不存在")


def test_require_group(store: WatchlistStore) -> None:
    store.add_group("白酒")
    g = store.require_group("白酒")
    assert g.name == "白酒"
    with pytest.raises(GroupNotFoundError):
        store.require_group("不存在")


# ---------- StockEntry CRUD ----------


def test_add_entry(store: WatchlistStore) -> None:
    store.add_group("白酒")
    e = store.add_entry("600519", "白酒", note="妈妈长期持有")
    assert e.code == "600519"
    assert e.note == "妈妈长期持有"
    assert e.group.name == "白酒"


def test_add_entry_to_missing_group_raises(store: WatchlistStore) -> None:
    with pytest.raises(GroupNotFoundError):
        store.add_entry("600519", "不存在的分组")


def test_add_duplicate_in_same_group_idempotent(store: WatchlistStore) -> None:
    store.add_group("白酒")
    e1 = store.add_entry("600519", "白酒", note="first")
    e2 = store.add_entry("600519", "白酒", note="second")
    # 返回同一 entry，note 不变
    assert e1.id == e2.id
    assert e2.note == "first"


def test_same_code_different_groups_allowed(store: WatchlistStore) -> None:
    store.add_group("白酒")
    store.add_group("长线")
    e1 = store.add_entry("600519", "白酒")
    e2 = store.add_entry("600519", "长线")
    assert e1.id != e2.id
    entries = store.list_entries()
    assert len(entries) == 2


def test_remove_entry(store: WatchlistStore) -> None:
    store.add_group("白酒")
    store.add_entry("600519", "白酒")
    store.add_entry("000858", "白酒")
    store.remove_entry("600519", "白酒")
    entries = store.list_entries()
    assert len(entries) == 1
    assert entries[0].code == "000858"


def test_remove_missing_entry_raises(store: WatchlistStore) -> None:
    store.add_group("白酒")
    with pytest.raises(StockEntryNotFoundError):
        store.remove_entry("600519", "白酒")


def test_list_entries_by_group_returns_dict(store: WatchlistStore) -> None:
    store.add_group("白酒")
    store.add_group("银行")
    store.add_entry("600519", "白酒")
    store.add_entry("000858", "白酒")
    store.add_entry("000001", "银行")
    result = store.list_entries_by_group()
    assert set(result.keys()) == {"白酒", "银行"}
    assert [e.code for e in result["白酒"]] == ["000858", "600519"]
    assert [e.code for e in result["银行"]] == ["000001"]


def test_get_all_codes_dedup(store: WatchlistStore) -> None:
    """同一 code 跨多分组时只返回一次。"""
    store.add_group("白酒")
    store.add_group("长线")
    store.add_entry("600519", "白酒")
    store.add_entry("600519", "长线")
    codes = store.get_all_codes()
    assert codes == ["600519"]


def test_basket_preferences_are_persistent_and_partially_updated(
    store: WatchlistStore,
) -> None:
    created = store.set_basket_preference(
        "theme:semiconductor",
        followed=False,
        sort_order=3,
        reason="等待库存周期确认",
        update_reason=True,
    )
    assert created.followed is False
    assert created.sort_order == 3

    updated = store.set_basket_preference("theme:semiconductor", hidden=True)
    assert updated.followed is False
    assert updated.hidden is True
    assert updated.reason == "等待库存周期确认"

    preferences = store.list_basket_preferences()
    assert list(preferences) == ["theme:semiconductor"]


def test_basket_member_weight_can_be_set_and_cleared(store: WatchlistStore) -> None:
    store.set_basket_member_weight("theme:semiconductor", "600519", Decimal("25.50"))
    assert store.list_basket_member_weights() == {
        ("theme:semiconductor", "600519"): Decimal("25.5000")
    }

    store.set_basket_member_weight("theme:semiconductor", "600519", None)
    assert store.list_basket_member_weights() == {}


def test_removing_custom_basket_or_member_cleans_preferences(
    store: WatchlistStore,
) -> None:
    group = store.add_group("观察")
    store.add_entry("600519", group.name)
    basket_id = f"group:{group.id}"
    store.set_basket_preference(basket_id, followed=False)
    store.set_basket_member_weight(basket_id, "600519", Decimal("50"))

    store.remove_entry("600519", group.name)
    assert store.list_basket_member_weights() == {}

    store.set_basket_member_weight(basket_id, "600001", Decimal("25"))
    store.remove_group(group.name)
    assert store.list_basket_preferences() == {}
    assert store.list_basket_member_weights() == {}


def test_backfill_name_updates_all_entries_of_code(store: WatchlistStore) -> None:
    store.add_group("白酒")
    store.add_group("长线")
    store.add_entry("600519", "白酒")
    store.add_entry("600519", "长线")
    n = store.backfill_name("600519", "贵州茅台")
    assert n == 2
    for e in store.list_entries():
        assert e.name == "贵州茅台"


def test_stats(store: WatchlistStore) -> None:
    store.add_group("白酒")
    store.add_group("银行")
    store.add_entry("600519", "白酒")
    store.add_entry("000858", "白酒")
    store.add_entry("000001", "银行")
    st = store.stats()
    assert st == {"groups": 2, "entries": 3, "codes": 3}


# ---------- User preferences (singleton) ----------


def test_get_user_preferences_defaults_without_row(store: WatchlistStore) -> None:
    prefs = store.get_user_preferences()
    assert prefs["style"] == "balanced"
    assert prefs["holding_period"] == "swing"
    assert prefs["drawdown_sensitivity"] == "medium"
    assert prefs["notify_min_severity"] == "warning"
    assert prefs["watched_rules"] == []
    assert prefs["reminder_windows"] == []
    assert prefs["updated_at"] is None


def test_update_user_preferences_upserts_singleton(store: WatchlistStore) -> None:
    updated = store.update_user_preferences({"style": "conservative"})
    assert updated["style"] == "conservative"
    assert updated["holding_period"] == "swing"  # 未更新字段回落默认
    assert updated["updated_at"] is not None

    again = store.update_user_preferences({"holding_period": "long"})
    assert again["style"] == "conservative"  # 上次写入保留（单例行 upsert）
    assert again["holding_period"] == "long"


def test_update_user_preferences_whitelists_columns(store: WatchlistStore) -> None:
    prefs = store.update_user_preferences({"style": "aggressive", "unknown_field": "x", "id": 99})
    assert prefs["style"] == "aggressive"
    assert "unknown_field" not in prefs


def test_update_user_preferences_json_columns(store: WatchlistStore) -> None:
    prefs = store.update_user_preferences(
        {
            "watched_rules": ["rule_a", "rule_b"],
            "reminder_windows": [{"start": "09:30", "end": "15:00"}],
        }
    )
    assert prefs["watched_rules"] == ["rule_a", "rule_b"]
    assert prefs["reminder_windows"] == [{"start": "09:30", "end": "15:00"}]
    # 重新读取（新 session）仍是持久化值
    reread = store.get_user_preferences()
    assert reread["watched_rules"] == ["rule_a", "rule_b"]
    assert reread["reminder_windows"] == [{"start": "09:30", "end": "15:00"}]


def test_reset_user_preferences_restores_defaults(store: WatchlistStore) -> None:
    store.update_user_preferences({"style": "aggressive", "watched_rules": ["rule_a"]})
    prefs = store.reset_user_preferences()
    assert prefs["style"] == "balanced"
    assert prefs["watched_rules"] == []
    assert prefs["updated_at"] is None
    # reset 后再读也是默认值
    assert store.get_user_preferences()["style"] == "balanced"


def test_reset_user_preferences_idempotent(store: WatchlistStore) -> None:
    prefs = store.reset_user_preferences()
    assert prefs["style"] == "balanced"
    assert prefs["updated_at"] is None
