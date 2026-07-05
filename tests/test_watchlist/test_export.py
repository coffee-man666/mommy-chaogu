"""WatchlistStore.export_to_json / build_export_payload 单测。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from mommy_chaogu.watchlist import WatchlistStore
from mommy_chaogu.watchlist.store import EXPORT_SCHEMA_VERSION


@pytest.fixture
def store(tmp_path: Path) -> WatchlistStore:
    db = tmp_path / "test_watchlist.db"
    return WatchlistStore(db)


def _seed(store: WatchlistStore) -> None:
    store.add_group("白酒", description="白酒板块")
    store.add_group("长线", description="长期持有")
    store.add_entry("600519", "白酒", note="妈妈长期持有")
    store.add_entry("000858", "白酒")
    store.add_entry("600519", "长线", note="同一只跨组")


# ---------- build_export_payload ----------


def test_build_payload_schema_shape(store: WatchlistStore) -> None:
    _seed(store)
    payload = store.build_export_payload()

    assert set(payload.keys()) == {"meta", "groups"}
    meta = payload["meta"]
    assert meta["schema_version"] == EXPORT_SCHEMA_VERSION
    assert isinstance(meta["stats"], dict)
    assert meta["stats"]["groups"] == 2
    assert meta["stats"]["entries"] == 3
    assert meta["stats"]["codes"] == 2  # 600519 跨两组
    assert "db_path" not in meta
    # 不应包含日期字段（配置式快照，git log 负责时间记录）
    assert "exported_at" not in meta


def test_build_payload_no_date_fields(store: WatchlistStore) -> None:
    """配置式快照：不包含任何日期字段。"""
    _seed(store)
    payload = store.build_export_payload()

    # meta 无日期
    assert "exported_at" not in payload["meta"]
    # group 无 created_at
    for g in payload["groups"]:
        assert "created_at" not in g
        # entries 无 created_at
        for e in g["entries"]:
            assert "created_at" not in e


def test_build_payload_entry_keys(store: WatchlistStore) -> None:
    """entry 只含 code/name/note 三个字段（配置式）。"""
    _seed(store)
    payload = store.build_export_payload()
    bj = next(g for g in payload["groups"] if g["name"] == "白酒")
    et = next(e for e in bj["entries"] if e["code"] == "600519")
    assert set(et.keys()) == {"code", "name", "note"}


def test_build_payload_group_keys(store: WatchlistStore) -> None:
    """group 只含 name/description/entries 三个字段（配置式）。"""
    _seed(store)
    payload = store.build_export_payload()
    g = payload["groups"][0]
    assert set(g.keys()) == {"name", "description", "entries"}


def test_build_payload_meta_keys(store: WatchlistStore) -> None:
    """meta 只含 schema_version/stats。"""
    _seed(store)
    payload = store.build_export_payload()
    assert set(payload["meta"].keys()) == {"schema_version", "stats"}


def test_build_payload_groups_sorted(store: WatchlistStore) -> None:
    """分组按字母/中文 unicode 排序，与 list_entries_by_group 一致。"""
    _seed(store)
    payload = store.build_export_payload()
    names = [g["name"] for g in payload["groups"]]
    assert names == sorted(names)


def test_build_payload_entries_sorted_by_code(store: WatchlistStore) -> None:
    _seed(store)
    payload = store.build_export_payload()
    for g in payload["groups"]:
        codes = [e["code"] for e in g["entries"]]
        assert codes == sorted(codes)


def test_build_payload_entry_fields(store: WatchlistStore) -> None:
    _seed(store)
    payload = store.build_export_payload()
    # 找到白酒组的 600519 entry
    bj = next(g for g in payload["groups"] if g["name"] == "白酒")
    et = next(e for e in bj["entries"] if e["code"] == "600519")
    assert et["name"] == "贵州茅台" or et["name"] is None  # 可能已 backfill
    assert et["note"] == "妈妈长期持有"


def test_build_payload_empty_store(store: WatchlistStore) -> None:
    payload = store.build_export_payload()
    assert payload["groups"] == []
    assert payload["meta"]["stats"] == {"groups": 0, "entries": 0, "codes": 0}


def test_build_payload_group_without_entries(store: WatchlistStore) -> None:
    """空 group（只有名没股票）也能导出，不能崩。"""
    store.add_group("空分组", description="还没加股")
    store.add_group("实股组")
    store.add_entry("600519", "实股组")
    payload = store.build_export_payload()
    names = {g["name"] for g in payload["groups"]}
    assert names == {"空分组", "实股组"}
    empty = next(g for g in payload["groups"] if g["name"] == "空分组")
    assert empty["entries"] == []
    assert empty["description"] == "还没加股"


def test_build_payload_unicode_preserved(store: WatchlistStore) -> None:
    store.add_group("人形机器人", description="六维力传感器/伺服")
    store.add_entry("603662", "人形机器人", note="机器人概念核心标的")
    payload = store.build_export_payload()
    g = payload["groups"][0]
    assert g["name"] == "人形机器人"
    assert g["description"] == "六维力传感器/伺服"
    assert g["entries"][0]["note"] == "机器人概念核心标的"


# ---------- export_to_json ----------


def test_export_writes_to_default_path(store: WatchlistStore) -> None:
    _seed(store)
    written = store.export_to_json()
    assert written == store.db_path.parent / "watchlist.json"
    assert written.exists()
    assert written.parent == store.db_path.parent


def test_export_writes_to_custom_path(store: WatchlistStore, tmp_path: Path) -> None:
    _seed(store)
    out = tmp_path / "sub" / "watchlist.json"
    written = store.export_to_json(out)
    assert written == out.resolve()
    assert written.exists()


def test_export_writes_valid_json(store: WatchlistStore, tmp_path: Path) -> None:
    _seed(store)
    out = tmp_path / "w.json"
    store.export_to_json(out)
    parsed = json.loads(out.read_text(encoding="utf-8"))
    assert parsed["meta"]["stats"]["groups"] == 2


def test_export_preserves_chinese_by_default(store: WatchlistStore, tmp_path: Path) -> None:
    store.add_group("人形机器人")
    out = tmp_path / "w.json"
    store.export_to_json(out)
    text = out.read_text(encoding="utf-8")
    # ensure_ascii=False 时，JSON 内应保留中文字符
    assert "人形机器人" in text
    # 验证 ASCII 字符不是 \uXXXX 形式
    assert "\\u4eba" not in text


def test_export_ensure_ascii_true_escapes(store: WatchlistStore, tmp_path: Path) -> None:
    store.add_group("人形机器人")
    out = tmp_path / "w.json"
    store.export_to_json(out, ensure_ascii=True)
    text = out.read_text(encoding="utf-8")
    assert "\\u4eba" in text  # 人 → \u4eba


def test_export_custom_indent(store: WatchlistStore, tmp_path: Path) -> None:
    store.add_group("g")
    out = tmp_path / "w.json"
    store.export_to_json(out, indent=4)
    assert "\n    " in out.read_text(encoding="utf-8")


def test_export_is_atomic_via_overwrite(store: WatchlistStore, tmp_path: Path) -> None:
    """先 export 一次，再 export 一次不会污染旧数据。"""
    _seed(store)
    out = tmp_path / "w.json"
    p1 = store.export_to_json(out)
    p2 = store.export_to_json(out)
    assert p1 == p2
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["meta"]["stats"]["groups"] == 2


# ---------- 端到端：与 stats 一致 ----------


def test_export_consistent_with_stats(store: WatchlistStore) -> None:
    _seed(store)
    payload = store.build_export_payload()
    stats = store.stats()
    assert payload["meta"]["stats"] == stats
