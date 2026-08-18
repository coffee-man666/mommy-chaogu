"""create_app(--db) 的路径覆盖传播回归测试。

旧实现直接替换 deps.get_db_path 模块属性并清缓存，但 store 工厂重建时
读的是 get_portfolio_db() 默认值——mommy-web --db 对自选/持仓静默失效。
"""

from __future__ import annotations

from pathlib import Path

from mommy_chaogu.db_paths import PORTFOLIO_DB
from mommy_chaogu.web import create_app, deps


def test_create_app_db_path_propagates_to_user_stores(tmp_path: Path) -> None:
    custom = tmp_path / "custom-portfolio.db"

    create_app(db_path=custom)

    assert deps.get_portfolio_db() == custom
    assert deps.get_db_path() == custom
    # 关键断言：store 单例重建后真的落在自定义路径上（旧实现做不到）
    assert deps.get_watchlist_store().db_path == custom


def test_create_app_without_db_path_resets_override(tmp_path: Path) -> None:
    create_app(db_path=tmp_path / "a.db")
    assert deps.get_portfolio_db() == tmp_path / "a.db"

    # 无参 create_app 复位覆盖，测试之间不泄漏
    create_app()
    assert deps.get_portfolio_db() == PORTFOLIO_DB
