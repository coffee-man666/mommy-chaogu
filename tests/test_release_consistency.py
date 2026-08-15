"""发布一致性绊网：打包 exclude 列表必须与捆绑 Skills 对齐。

回归背景：market-watch-loop 曾被误加入 ``[tool.hatch.build] exclude``，导致
安装版（wheel）里 ``bundled_skills/`` 缺目录，而 ``connect.py`` 的
``_bundled_skill_dirs()`` 仍然硬编码引用它 —— ``mommy agent connect`` 在
安装环境下对不存在的路径算 hash / 复制，集成在任何真实探针之前就断了。
这里同时锁定两个方向：

1. 磁盘上每个捆绑 Skill 目录（本地实验目录 market-monitoring-test 除外）
   都不得出现在 exclude 列表里；
2. ``connect.py`` 引用的 Skill 名字集合必须存在于源码树的
   ``bundled_skills/`` 目录中（import 级检查，防 wheel 空指针复发）。
"""

from __future__ import annotations

import re
import tomllib
from pathlib import Path

from mommy_chaogu.cli_commands.connect import _bundled_skill_dirs

_REPO_ROOT = Path(__file__).resolve().parents[1]
_BUNDLED_SKILLS_DIR = _REPO_ROOT / "src" / "mommy_chaogu" / "bundled_skills"
_SKILL_EXCLUDE_RE = re.compile(r"^/src/mommy_chaogu/bundled_skills/(?P<name>[^/]+)/\*\*$")

# 本地实验性 Skill 目录：确实不应进入发布产物（白名单）。
_EXCLUDED_SKILL_WHITELIST = frozenset({"market-monitoring-test"})


def _hatch_exclude_patterns() -> set[str]:
    config = tomllib.loads((_REPO_ROOT / "pyproject.toml").read_text(encoding="utf-8"))
    excluded = config["tool"]["hatch"]["build"]["exclude"]
    if not isinstance(excluded, list):
        raise AssertionError("[tool.hatch.build] exclude 应为字符串列表")
    return {str(pattern) for pattern in excluded}


def _excluded_skill_names(patterns: set[str]) -> set[str]:
    names = set()
    for pattern in patterns:
        match = _SKILL_EXCLUDE_RE.match(pattern)
        if match:
            names.add(match.group("name"))
    return names


def _bundled_skill_dir_names() -> set[str]:
    return {path.name for path in _BUNDLED_SKILLS_DIR.iterdir() if path.is_dir()}


def test_runtime_output_stays_excluded_from_release_artifacts() -> None:
    excluded = _hatch_exclude_patterns()

    assert "/output/**" in excluded


def test_every_shipping_bundled_skill_is_not_excluded() -> None:
    on_disk = _bundled_skill_dir_names()
    excluded = _excluded_skill_names(_hatch_exclude_patterns())

    assert on_disk, "bundled_skills/ 不应为空目录"
    # 被排除的 Skill 只允许是显式白名单里的本地实验目录。
    assert excluded <= _EXCLUDED_SKILL_WHITELIST, (
        f"新增被排除的 Skill {sorted(excluded - _EXCLUDED_SKILL_WHITELIST)} "
        "必须先加入白名单并确认不是应当发布的捆绑 Skill"
    )
    shipping = on_disk - _EXCLUDED_SKILL_WHITELIST
    missing = shipping & excluded
    assert not missing, (
        f"捆绑 Skill {sorted(missing)} 被打进了 exclude 列表：安装版 wheel 会缺这些目录，"
        "mommy agent connect 将引用不存在的路径（2026-08-15 审计的 wheel 空指针问题）"
    )


def test_connector_skill_references_exist_in_bundled_package() -> None:
    on_disk = _bundled_skill_dir_names()
    referenced = {path.name for path in _bundled_skill_dirs()}

    assert referenced, "_bundled_skill_dirs() 不应返回空集合"
    dangling = referenced - on_disk
    assert not dangling, (
        f"connect.py _bundled_skill_dirs() 引用了 bundled_skills/ 中不存在的目录 "
        f"{sorted(dangling)}；安装版会在 agent connect 时踩到空指针"
    )
    for path in _bundled_skill_dirs():
        assert path.is_dir(), f"捆绑 Skill 路径不存在: {path}"
