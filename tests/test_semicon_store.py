"""SemiconStore 行为测试：覆盖单条 CRUD / 批量 upsert / 查询 / 统计 / 异常路径。

约定：
- 每个用例用 tmp_path 临时数据库，互不污染
- 直接断言返回的 ORM 对象字段，不走真实 reference.db
- 异常用 pytest.raises 断言类型与 message 片段
"""

from __future__ import annotations

from pathlib import Path

import pytest

from mommy_chaogu.semicon.models import SemiconStock
from mommy_chaogu.semicon.store import (
    Board,
    ChainPosition,
    SemiconError,
    SemiconStore,
    StockAlreadyExistsError,
    StockNotFoundError,
    Subcategory,
)

# ---------- fixtures ----------


@pytest.fixture
def store(tmp_path: Path) -> SemiconStore:
    """每个用例独立的临时 store。"""
    with SemiconStore(tmp_path / "semicon_test.db") as s:
        yield s


def _row(
    code: str = "600519",
    name: str = "贵州茅台",
    chain_position: str = ChainPosition.DOWNSTREAM,
    subcategory: str = Subcategory.DISTRIBUTION,
    product: str | None = None,
    board: str = Board.MAIN,
    note: str | None = None,
) -> tuple[str, str, str, str, str | None, str, str | None]:
    """造一行 bulk_upsert 用的 7 元组。"""
    return (code, name, chain_position, subcategory, product, board, note)


# ---------- init ----------


def test_init_creates_parent_directory_and_db_file(tmp_path: Path) -> None:
    """init 应该自动 mkdir 父目录并创建 DB 文件。"""
    nested = tmp_path / "nested" / "deep" / "semicon.db"
    s = SemiconStore(nested)
    try:
        assert nested.parent.exists()
        # 触发一次建表后文件应该存在
        assert nested.exists()
        # 空库统计应该是 0
        assert s.stats()["total"] == 0
    finally:
        s.close()


def test_init_is_idempotent_on_existing_file(tmp_path: Path) -> None:
    """重复打开同一 DB 文件不应报错，已有数据应保留。"""
    path = tmp_path / "reuse.db"
    with SemiconStore(path) as s1:
        s1.add("000001", "平安银行", ChainPosition.DOWNSTREAM, Subcategory.DISTRIBUTION)
    # 再开一次，旧数据还在
    with SemiconStore(path) as s2:
        assert s2.stats()["total"] == 1
        assert s2.get("000001") is not None


# ---------- add ----------


def test_add_returns_stock_with_defaults(store: SemiconStore) -> None:
    """add 默认 board=主板，product/note=None。"""
    stock = store.add(
        "600519",
        "贵州茅台",
        ChainPosition.DOWNSTREAM,
        Subcategory.DISTRIBUTION,
    )
    assert isinstance(stock, SemiconStock)
    assert stock.code == "600519"
    assert stock.name == "贵州茅台"
    assert stock.chain_position == "下游"
    assert stock.subcategory == "分销"
    # 默认值
    assert stock.board == "主板"
    assert stock.product is None
    assert stock.note is None
    # id 自增、时间戳已填
    assert stock.id is not None
    assert stock.created_at is not None
    assert stock.updated_at is not None


def test_add_with_optional_fields(store: SemiconStore) -> None:
    stock = store.add(
        "688981",
        "中芯国际",
        ChainPosition.MIDSTREAM,
        Subcategory.FOUNDRY,
        product="晶圆代工",
        board=Board.STAR,
        note="大陆龙头代工厂",
    )
    assert stock.product == "晶圆代工"
    assert stock.board == "科创板"
    assert stock.note == "大陆龙头代工厂"


def test_add_duplicate_raises(store: SemiconStore) -> None:
    store.add("600519", "贵州茅台", ChainPosition.DOWNSTREAM, Subcategory.DISTRIBUTION)
    # 同 code 再加应该报错
    with pytest.raises(StockAlreadyExistsError, match="600519"):
        store.add(
            "600519",
            "另一个名字",
            ChainPosition.UPSTREAM,
            Subcategory.EDA,
        )
    # 数据没被覆盖：原记录仍在
    again = store.require("600519")
    assert again.name == "贵州茅台"
    assert again.chain_position == "下游"


def test_add_duplicate_does_not_partial_commit(store: SemiconStore) -> None:
    """重复 add 失败时事务应该回滚，不会留下第二条。"""
    store.add("000001", "平安银行", ChainPosition.DOWNSTREAM, Subcategory.DISTRIBUTION)
    with pytest.raises(StockAlreadyExistsError):
        store.add("000001", "x", ChainPosition.UPSTREAM, Subcategory.EDA)
    assert store.stats()["total"] == 1


def test_add_is_visible_to_subsequent_get(store: SemiconStore) -> None:
    store.add("300999", "测试股", ChainPosition.UPSTREAM, Subcategory.EDA)
    fetched = store.get("300999")
    assert fetched is not None
    assert fetched.name == "测试股"


# ---------- get / require ----------


def test_get_missing_returns_none(store: SemiconStore) -> None:
    assert store.get("not-exist") is None


def test_get_returns_detached_object(store: SemiconStore) -> None:
    """get 返回的对象在 session 关闭后字段仍可访问（expire_on_commit=False）。"""
    store.add("600519", "贵州茅台", ChainPosition.DOWNSTREAM, Subcategory.DISTRIBUTION)
    stock = store.get("600519")
    assert stock is not None
    # 在 session 之外访问字段不应触发 DetachedInstanceError
    assert stock.name == "贵州茅台"
    assert stock.code == "600519"


def test_require_missing_raises(store: SemiconStore) -> None:
    with pytest.raises(StockNotFoundError, match="not-exist"):
        store.require("not-exist")


def test_require_returns_stock(store: SemiconStore) -> None:
    store.add("600519", "贵州茅台", ChainPosition.DOWNSTREAM, Subcategory.DISTRIBUTION)
    stock = store.require("600519")
    assert stock.code == "600519"


def test_not_found_and_already_exist_are_semicon_errors() -> None:
    """两个异常都继承 SemiconError，便于上层统一捕获。"""
    assert issubclass(StockNotFoundError, SemiconError)
    assert issubclass(StockAlreadyExistsError, SemiconError)


# ---------- remove ----------


def test_remove_deletes_stock(store: SemiconStore) -> None:
    store.add("600519", "贵州茅台", ChainPosition.DOWNSTREAM, Subcategory.DISTRIBUTION)
    assert store.get("600519") is not None
    store.remove("600519")
    assert store.get("600519") is None
    assert store.stats()["total"] == 0


def test_remove_missing_raises(store: SemiconStore) -> None:
    with pytest.raises(StockNotFoundError, match="404xxx"):
        store.remove("404xxx")


def test_remove_returns_none(store: SemiconStore) -> None:
    store.add("600519", "贵州茅台", ChainPosition.DOWNSTREAM, Subcategory.DISTRIBUTION)
    assert store.remove("600519") is None


def test_remove_does_not_affect_other_rows(store: SemiconStore) -> None:
    store.add("000001", "A", ChainPosition.DOWNSTREAM, Subcategory.DISTRIBUTION)
    store.add("000002", "B", ChainPosition.DOWNSTREAM, Subcategory.DISTRIBUTION)
    store.remove("000001")
    assert store.require("000002").name == "B"


# ---------- update ----------


def test_update_changes_specified_fields(store: SemiconStore) -> None:
    store.add(
        "600519",
        "原名",
        ChainPosition.DOWNSTREAM,
        Subcategory.DISTRIBUTION,
        product="原产品",
        note="原备注",
    )
    updated = store.update(
        "600519",
        name="新名",
        chain_position=ChainPosition.UPSTREAM,
        subcategory=Subcategory.EDA,
        product="EDA 工具",
        board=Board.STAR,
        note="新备注",
    )
    assert updated.name == "新名"
    assert updated.chain_position == "上游"
    assert updated.subcategory == "EDA"
    assert updated.product == "EDA 工具"
    assert updated.board == "科创板"
    assert updated.note == "新备注"
    # 持久化生效
    fresh = store.require("600519")
    assert fresh.name == "新名"
    assert fresh.product == "EDA 工具"


def test_update_none_fields_are_ignored(store: SemiconStore) -> None:
    """显式传 None 的字段不应被改写。"""
    store.add(
        "600519",
        "贵州茅台",
        ChainPosition.DOWNSTREAM,
        Subcategory.DISTRIBUTION,
        product="白酒",
        note="龙头",
    )
    updated = store.update(
        "600519",
        name=None,
        chain_position=None,
        subcategory=None,
        product=None,
        board=None,
        note=None,
    )
    # 全部 None → 字段保持原值
    assert updated.name == "贵州茅台"
    assert updated.chain_position == "下游"
    assert updated.subcategory == "分销"
    assert updated.product == "白酒"
    assert updated.board == "主板"
    assert updated.note == "龙头"


def test_update_partial_fields(store: SemiconStore) -> None:
    store.add(
        "600519",
        "贵州茅台",
        ChainPosition.DOWNSTREAM,
        Subcategory.DISTRIBUTION,
        product="白酒",
        board=Board.MAIN,
    )
    # 只改 name 和 board
    updated = store.update("600519", name="茅台股份", board=Board.STAR)
    assert updated.name == "茅台股份"
    assert updated.board == "科创板"
    # 其他字段不动
    assert updated.chain_position == "下游"
    assert updated.subcategory == "分销"
    assert updated.product == "白酒"


def test_update_can_clear_optional_via_empty_string(store: SemiconStore) -> None:
    """product/note 是 nullable，但传 None 表示「不改」。
    要清空得传空串（这是 update 的语义边界，本用例锁定该行为）。"""
    store.add(
        "600519",
        "贵州茅台",
        ChainPosition.DOWNSTREAM,
        Subcategory.DISTRIBUTION,
        product="白酒",
    )
    updated = store.update("600519", product="")
    assert updated.product == ""


def test_update_missing_raises(store: SemiconStore) -> None:
    with pytest.raises(StockNotFoundError, match="404"):
        store.update("404", name="x")


def test_update_bumps_updated_at(store: SemiconStore) -> None:
    """update 应触发 onupdate=utcnow，让 updated_at 推进。"""
    import time

    store.add("600519", "贵州茅台", ChainPosition.DOWNSTREAM, Subcategory.DISTRIBUTION)
    before = store.require("600519").updated_at
    # onupdate 的精度是秒级，睡一下确保时间推进
    time.sleep(1.05)
    store.update("600519", name="新名")
    after = store.require("600519").updated_at
    assert after > before


# ---------- bulk_upsert ----------


def test_bulk_upsert_inserts_new_rows(store: SemiconStore) -> None:
    rows = [
        _row("000001", "平安银行", ChainPosition.DOWNSTREAM, Subcategory.DISTRIBUTION),
        _row(
            "688981",
            "中芯国际",
            ChainPosition.MIDSTREAM,
            Subcategory.FOUNDRY,
            product="晶圆代工",
            board=Board.STAR,
        ),
        _row(
            "688012",
            "中微公司",
            ChainPosition.UPSTREAM,
            Subcategory.EQUIPMENT,
            product="介质刻蚀",
            board=Board.STAR,
            note="龙头",
        ),
    ]
    result = store.bulk_upsert(rows)
    assert result == {"inserted": 3, "updated": 0, "skipped": 0}
    assert store.stats()["total"] == 3
    assert set(store.list_codes()) == {"000001", "688012", "688981"}


def test_bulk_upsert_skips_existing_without_overwrite(store: SemiconStore) -> None:
    store.add(
        "688981",
        "原名",
        ChainPosition.DOWNSTREAM,
        Subcategory.DISTRIBUTION,
        product="原产品",
        board=Board.MAIN,
        note="原备注",
    )
    rows = [
        _row(
            "688981",
            "新名",
            ChainPosition.MIDSTREAM,
            Subcategory.FOUNDRY,
            product="晶圆代工",
            board=Board.STAR,
            note="新备注",
        ),
        _row("000001", "平安银行", ChainPosition.DOWNSTREAM, Subcategory.DISTRIBUTION),
    ]
    result = store.bulk_upsert(rows, overwrite=False)
    assert result == {"inserted": 1, "updated": 0, "skipped": 1}
    # 跳过的那条没被改动
    kept = store.require("688981")
    assert kept.name == "原名"
    assert kept.chain_position == "下游"
    assert kept.product == "原产品"
    assert kept.board == "主板"
    assert kept.note == "原备注"


def test_bulk_upsert_overwrites_when_overwrite_true(store: SemiconStore) -> None:
    store.add(
        "688981",
        "原名",
        ChainPosition.DOWNSTREAM,
        Subcategory.DISTRIBUTION,
        product="原产品",
        board=Board.MAIN,
    )
    rows = [
        _row(
            "688981",
            "中芯国际",
            ChainPosition.MIDSTREAM,
            Subcategory.FOUNDRY,
            product="晶圆代工",
            board=Board.STAR,
            note="新备注",
        ),
        _row("000001", "平安银行", ChainPosition.DOWNSTREAM, Subcategory.DISTRIBUTION),
    ]
    result = store.bulk_upsert(rows, overwrite=True)
    assert result == {"inserted": 1, "updated": 1, "skipped": 0}
    overwritten = store.require("688981")
    assert overwritten.name == "中芯国际"
    assert overwritten.chain_position == "中游"
    assert overwritten.subcategory == "制造"
    assert overwritten.product == "晶圆代工"
    assert overwritten.board == "科创板"
    assert overwritten.note == "新备注"


def test_bulk_upsert_empty_list_is_noop(store: SemiconStore) -> None:
    result = store.bulk_upsert([])
    assert result == {"inserted": 0, "updated": 0, "skipped": 0}
    assert store.stats()["total"] == 0


def test_bulk_upsert_mixed_scenario(store: SemiconStore) -> None:
    """混合：1 条已存在（skip）+ 1 条已存在（overwrite）+ 2 条新增。"""
    store.add("A001", "keep-me", ChainPosition.DOWNSTREAM, Subcategory.DISTRIBUTION)
    store.add("A002", "to-overwrite", ChainPosition.DOWNSTREAM, Subcategory.DISTRIBUTION)

    rows = [
        # A001: skip（无 overwrite）
        _row("A001", "should-be-skipped", ChainPosition.UPSTREAM, Subcategory.EDA),
        # A002: 在 overwrite=True 的批次里会被覆盖
        _row(
            "A002",
            "overwritten",
            ChainPosition.MIDSTREAM,
            Subcategory.FOUNDRY,
        ),
        # 两条全新
        _row("A003", "new1", ChainPosition.UPSTREAM, Subcategory.MATERIAL),
        _row("A004", "new2", ChainPosition.UPSTREAM, Subcategory.EQUIPMENT),
    ]
    result = store.bulk_upsert(rows, overwrite=True)
    assert result == {"inserted": 2, "updated": 2, "skipped": 0}
    # A001 在 overwrite=True 下也会被覆盖（不是 skip）
    assert store.require("A001").name == "should-be-skipped"
    assert store.require("A002").name == "overwritten"


def test_bulk_upsert_preserves_none_product_and_note(store: SemiconStore) -> None:
    rows = [
        _row(
            "A001",
            "no-prod",
            ChainPosition.UPSTREAM,
            Subcategory.EDA,
            product=None,
            board=Board.MAIN,
            note=None,
        ),
    ]
    store.bulk_upsert(rows)
    stock = store.require("A001")
    assert stock.product is None
    assert stock.note is None


# ---------- list_all / list_by_chain / list_by_subcategory ----------


def _seed_catalog(store: SemiconStore) -> None:
    """塞一个有多种位置/子分类的小目录。"""
    rows = [
        # 下游 / 分销
        _row("D002", "B行", ChainPosition.DOWNSTREAM, Subcategory.DISTRIBUTION),
        _row("D001", "A行", ChainPosition.DOWNSTREAM, Subcategory.DISTRIBUTION),
        # 上游 / EDA
        _row("U001", "EDA甲", ChainPosition.UPSTREAM, Subcategory.EDA, product="仿真"),
        # 上游 / 材料
        _row("U100", "材料甲", ChainPosition.UPSTREAM, Subcategory.MATERIAL),
        # 中游 / 制造
        _row("M001", "代工厂", ChainPosition.MIDSTREAM, Subcategory.FOUNDRY),
    ]
    store.bulk_upsert(rows)


def test_list_all_sorted_by_chain_subcategory_code(store: SemiconStore) -> None:
    _seed_catalog(store)
    result = store.list_all()
    codes = [s.code for s in result]
    # 中文按 unicode 排序：上游(4E0A) < 下游(4E0B) < 中游(4E2D) < 末端
    # 上游里：EDA(U001) < 材料(U100)（子分类升序）
    # 下游里：D001 < D002（code 升序）
    assert codes == ["U001", "U100", "D001", "D002", "M001"]


def test_list_all_empty(store: SemiconStore) -> None:
    assert store.list_all() == []


def test_list_by_chain(store: SemiconStore) -> None:
    _seed_catalog(store)
    upstream = store.list_by_chain(ChainPosition.UPSTREAM)
    assert [s.code for s in upstream] == ["U001", "U100"]
    # 内部排序按 (subcategory, code)
    assert upstream[0].subcategory == "EDA"
    assert upstream[1].subcategory == "材料"

    downstream = store.list_by_chain("下游")
    assert [s.code for s in downstream] == ["D001", "D002"]


def test_list_by_chain_empty_match(store: SemiconStore) -> None:
    _seed_catalog(store)
    assert store.list_by_chain(ChainPosition.TERMINAL) == []


def test_list_by_subcategory(store: SemiconStore) -> None:
    _seed_catalog(store)
    eda = store.list_by_subcategory(Subcategory.EDA)
    assert len(eda) == 1
    assert eda[0].code == "U001"

    dist = store.list_by_subcategory("分销")
    assert {s.code for s in dist} == {"D001", "D002"}
    # 按 code 升序
    assert [s.code for s in dist] == ["D001", "D002"]


def test_list_by_subcategory_crosses_chain(store: SemiconStore) -> None:
    """同一 subcategory 可分布在多个 chain 下，应全部返回。"""
    store.bulk_upsert(
        [
            _row("X001", "a", ChainPosition.UPSTREAM, Subcategory.EDA),
            _row("X002", "b", ChainPosition.MIDSTREAM, Subcategory.EDA),
            _row("X003", "c", ChainPosition.DOWNSTREAM, Subcategory.EDA),
        ]
    )
    result = store.list_by_subcategory(Subcategory.EDA)
    assert {s.code for s in result} == {"X001", "X002", "X003"}


# ---------- list_codes ----------


def test_list_codes_sorted_alphabetically(store: SemiconStore) -> None:
    store.bulk_upsert(
        [
            _row("C003", "c", ChainPosition.UPSTREAM, Subcategory.EDA),
            _row("C001", "a", ChainPosition.UPSTREAM, Subcategory.EDA),
            _row("C002", "b", ChainPosition.UPSTREAM, Subcategory.EDA),
        ]
    )
    assert store.list_codes() == ["C001", "C002", "C003"]


def test_list_codes_empty(store: SemiconStore) -> None:
    assert store.list_codes() == []


def test_list_codes_returns_strings(store: SemiconStore) -> None:
    store.bulk_upsert([_row("A001", "a", ChainPosition.UPSTREAM, Subcategory.EDA)])
    codes = store.list_codes()
    assert len(codes) == 1
    assert isinstance(codes[0], str)


# ---------- count_by_chain / count_by_subcategory ----------


def test_count_by_chain(store: SemiconStore) -> None:
    _seed_catalog(store)
    counts = dict(store.count_by_chain())
    # 中文 unicode 排序：上游 < 下游 < 中游
    assert counts == {
        "上游": 2,
        "下游": 2,
        "中游": 1,
    }


def test_count_by_chain_returns_tuples(store: SemiconStore) -> None:
    _seed_catalog(store)
    rows = store.count_by_chain()
    assert all(isinstance(r, tuple) and len(r) == 2 for r in rows)
    # 每个 count 都是 int
    assert all(isinstance(n, int) for _, n in rows)


def test_count_by_chain_empty(store: SemiconStore) -> None:
    assert store.count_by_chain() == []


def test_count_by_subcategory(store: SemiconStore) -> None:
    _seed_catalog(store)
    counts = store.count_by_subcategory()
    # 期望按 (chain_position, subcategory) 排序；中文 unicode：上游 < 下游 < 中游
    expected = [
        ("上游", "EDA", 1),
        ("上游", "材料", 1),
        ("下游", "分销", 2),
        ("中游", "制造", 1),
    ]
    assert counts == expected


def test_count_by_subcategory_returns_triples(store: SemiconStore) -> None:
    _seed_catalog(store)
    rows = store.count_by_subcategory()
    assert all(isinstance(r, tuple) and len(r) == 3 for r in rows)
    assert all(isinstance(n, int) for _, _, n in rows)


def test_count_by_subcategory_empty(store: SemiconStore) -> None:
    assert store.count_by_subcategory() == []


# ---------- search ----------


def test_search_matches_name(store: SemiconStore) -> None:
    store.bulk_upsert(
        [
            _row("A001", "中芯国际", ChainPosition.MIDSTREAM, Subcategory.FOUNDRY),
            _row("A002", "中微公司", ChainPosition.UPSTREAM, Subcategory.EQUIPMENT),
            _row("A003", "北方华创", ChainPosition.UPSTREAM, Subcategory.EQUIPMENT),
        ]
    )
    result = store.search("中")
    assert {s.code for s in result} == {"A001", "A002"}


def test_search_matches_product(store: SemiconStore) -> None:
    store.bulk_upsert(
        [
            _row("A001", "中微", ChainPosition.UPSTREAM, Subcategory.EQUIPMENT, product="介质刻蚀"),
            _row(
                "A002",
                "北方华创",
                ChainPosition.UPSTREAM,
                Subcategory.EQUIPMENT,
                product="薄膜沉积",
            ),
        ]
    )
    result = store.search("刻蚀")
    assert [s.code for s in result] == ["A001"]


def test_search_matches_note(store: SemiconStore) -> None:
    store.bulk_upsert(
        [
            _row("A001", "中芯", ChainPosition.MIDSTREAM, Subcategory.FOUNDRY, note="大陆龙头"),
            _row("A002", "华虹", ChainPosition.MIDSTREAM, Subcategory.FOUNDRY, note="特色工艺"),
        ]
    )
    result = store.search("龙头")
    assert [s.code for s in result] == ["A001"]


def test_search_matches_code(store: SemiconStore) -> None:
    store.bulk_upsert(
        [
            _row("688981", "中芯国际", ChainPosition.MIDSTREAM, Subcategory.FOUNDRY),
            _row("000001", "平安银行", ChainPosition.DOWNSTREAM, Subcategory.DISTRIBUTION),
        ]
    )
    result = store.search("688")
    assert [s.code for s in result] == ["688981"]


def test_search_is_case_insensitive_for_ascii(store: SemiconStore) -> None:
    """SQLite LIKE 默认 ASCII 大小写不敏感。"""
    store.bulk_upsert(
        [
            _row("A001", "EDA公司甲", ChainPosition.UPSTREAM, Subcategory.EDA),
            _row("A002", "eda公司乙", ChainPosition.UPSTREAM, Subcategory.EDA),
        ]
    )
    result = store.search("eda")
    assert {s.code for s in result} == {"A001", "A002"}


def test_search_results_sorted_by_code(store: SemiconStore) -> None:
    store.bulk_upsert(
        [
            _row("Z001", "中芯", ChainPosition.MIDSTREAM, Subcategory.FOUNDRY),
            _row("A001", "中微", ChainPosition.UPSTREAM, Subcategory.EQUIPMENT),
            _row("M001", "中环", ChainPosition.UPSTREAM, Subcategory.MATERIAL),
        ]
    )
    result = store.search("中")
    assert [s.code for s in result] == ["A001", "M001", "Z001"]


def test_search_no_match(store: SemiconStore) -> None:
    _seed_catalog(store)
    assert store.search("不存在的关键字xyz") == []


def test_search_empty_keyword_matches_all(store: SemiconStore) -> None:
    """空关键字 → LIKE '%%' → 全表。锁定该行为。"""
    _seed_catalog(store)
    result = store.search("")
    assert len(result) == 5


# ---------- stats ----------


def test_stats_empty_store(store: SemiconStore) -> None:
    stats = store.stats()
    assert stats == {
        "total": 0,
        "chains": 0,
        "subcategories": 0,
        "boards": 0,
    }


def test_stats_counts_distinct_values(store: SemiconStore) -> None:
    _seed_catalog(store)
    stats = store.stats()
    assert stats["total"] == 5
    # 上游 / 中游 / 下游
    assert stats["chains"] == 3
    # EDA / 材料 / 制造 / 分销
    assert stats["subcategories"] == 4
    # 全部默认主板
    assert stats["boards"] == 1


def test_stats_counts_distinct_boards(store: SemiconStore) -> None:
    store.bulk_upsert(
        [
            _row("A001", "a", ChainPosition.UPSTREAM, Subcategory.EDA, board=Board.MAIN),
            _row("A002", "b", ChainPosition.UPSTREAM, Subcategory.IP, board=Board.STAR),
            _row("A003", "c", ChainPosition.UPSTREAM, Subcategory.MCU, board=Board.CHINEXT),
            _row("A004", "d", ChainPosition.UPSTREAM, Subcategory.FPGA, board=Board.BSE),
        ]
    )
    stats = store.stats()
    assert stats["boards"] == 4
    assert stats["subcategories"] == 4
    assert stats["chains"] == 1


# ---------- integration: end-to-end workflow ----------


def test_full_workflow_add_update_search_remove(store: SemiconStore) -> None:
    """端到端：add → update → search → remove → 验证。"""
    # 1. 批量 seed
    store.bulk_upsert(
        [
            _row(
                "688981",
                "中芯国际",
                ChainPosition.MIDSTREAM,
                Subcategory.FOUNDRY,
                product="晶圆代工",
                board=Board.STAR,
                note="大陆龙头",
            ),
            _row(
                "688012",
                "中微公司",
                ChainPosition.UPSTREAM,
                Subcategory.EQUIPMENT,
                product="介质刻蚀",
                board=Board.STAR,
            ),
        ]
    )

    # 2. 单条 add
    store.add("000001", "平安银行", ChainPosition.DOWNSTREAM, Subcategory.DISTRIBUTION)

    # 3. update 补 product
    store.update("000001", product="银行服务", note="金融龙头")

    # 4. search 验证
    leaders = store.search("龙头")
    assert {s.code for s in leaders} == {"688981", "000001"}

    # 5. remove 一条
    store.remove("000001")
    assert store.get("000001") is None

    # 6. 最终 stats
    stats = store.stats()
    assert stats["total"] == 2
    assert stats["chains"] == 2  # 上游 + 中游
    assert stats["boards"] == 1  # 只剩 STAR
