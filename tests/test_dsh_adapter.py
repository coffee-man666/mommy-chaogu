"""dsh adapter 的 YAML patch 合并专项测试。

契约测试（tests/test_coding_agent_adapters.py）覆盖连接/断开的通用行为；
这里集中验证 dsh 特有的部分：合并语义、用户 patch 保留、``!!js`` 标签
round-trip 和损坏文件拒绝写入。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import patch

import pytest
import yaml

from mommy_chaogu.coding_agents import adapter_for
from mommy_chaogu.coding_agents.base import ConnectionSpec
from mommy_chaogu.coding_agents.dsh import (
    TESTED_DSH_VERSION,
    _PatchLoader,
    dsh_version_check,
    parse_dsh_version,
)

USER_PATCHES = """\
# 用户自己的 patch（可能带注释）
- insert:
    - id: user-plugin
      name: someone/other-plugin
      config:
        cwd: !!js process.cwd()
- remove:
    - id: builtin-demo
"""


@pytest.fixture
def dsh_home(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    home = tmp_path / "dsh"
    monkeypatch.setenv("DSH_HOME", str(home))
    return home


def _spec(**overrides: Any) -> ConnectionSpec:
    values: dict[str, Any] = {
        "command": "/usr/bin/python3",
        "args": ["-m", "mommy_chaogu.agent.mcp_server", "--profile", "market-only"],
        "env": {"MOMMY_AGENT_DB": "/tmp/agent.db"},
        "cwd": "/tmp",
        "profile": "market-only",
    }
    values.update(overrides)
    return ConnectionSpec(**values)


def _adapter(previous: dict[str, Any] | None = None, *, force: bool = False) -> Any:
    return adapter_for("dsh", previous=previous, force=force, which=lambda name: "/bin/dsh")


def _load(path: Path) -> list[Any]:
    return yaml.load(path.read_text(encoding="utf-8"), Loader=_PatchLoader)


def _mommy_rows(patches: list[Any]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for op in patches:
        if isinstance(op, dict) and isinstance(op.get("insert"), list):
            for row in op["insert"]:
                if (
                    isinstance(row, dict)
                    and row.get("name") == "@deepseek-ai/dsh-mcp-client"
                    and isinstance(row.get("config"), dict)
                    and row["config"].get("serverName") == "mommy-chaogu"
                ):
                    rows.append(row)
    return rows


def test_register_appends_row_and_preserves_user_patches(dsh_home: Path) -> None:
    patch = dsh_home / "cordis.patch.yml"
    dsh_home.mkdir(parents=True)
    patch.write_text(USER_PATCHES, encoding="utf-8")

    _adapter().register_mcp(_spec())

    patches = _load(patch)
    assert len(patches) == 3  # 两个用户操作 + mommy 追加的一个
    assert patches[0]["insert"][0]["name"] == "someone/other-plugin"
    assert [op for op in patches if isinstance(op, dict) and "remove" in op]
    rows = _mommy_rows(patches)
    assert len(rows) == 1
    config = rows[0]["config"]
    assert config["transport"] == "stdio"
    assert config["command"] == "/usr/bin/python3"
    assert config["args"][-2:] == ["--profile", "market-only"]
    assert config["env"] == {"MOMMY_AGENT_DB": "/tmp/agent.db"}
    assert config["cwd"] == "/tmp"
    # 未知标签 !!js 原样保留（值与标签都在）。
    preserved = patches[0]["insert"][0]["config"]["cwd"]
    assert getattr(preserved, "tag", None) == "tag:yaml.org,2002:js"
    assert getattr(preserved, "value", None) == "process.cwd()"


def test_reregister_replaces_row_in_place(dsh_home: Path) -> None:
    patch = dsh_home / "cordis.patch.yml"
    first = _spec()
    _adapter().register_mcp(first)
    previous = {"profile": first.profile, "spec": first.as_dict()}
    second = _spec(env={"MOMMY_AGENT_DB": "/tmp/agent-2.db"})

    _adapter(previous).register_mcp(second)

    rows = _mommy_rows(_load(patch))
    assert len(rows) == 1
    assert rows[0]["config"]["env"] == {"MOMMY_AGENT_DB": "/tmp/agent-2.db"}


def test_disconnect_removes_only_managed_row_and_empty_op(dsh_home: Path) -> None:
    patch = dsh_home / "cordis.patch.yml"
    dsh_home.mkdir(parents=True)
    patch.write_text(USER_PATCHES, encoding="utf-8")
    spec = _spec()
    _adapter().register_mcp(spec)
    assert len(_mommy_rows(_load(patch))) == 1

    _adapter({"profile": spec.profile, "spec": spec.as_dict()}).disconnect()

    patches = _load(patch)
    assert _mommy_rows(patches) == []
    assert len(patches) == 2  # 用户的 insert + remove 操作原样保留
    assert patches[0]["insert"][0]["name"] == "someone/other-plugin"


def test_disconnect_writes_empty_list_when_no_user_patches(dsh_home: Path) -> None:
    patch = dsh_home / "cordis.patch.yml"
    spec = _spec()
    _adapter().register_mcp(spec)
    _adapter({"profile": spec.profile, "spec": spec.as_dict()}).disconnect()
    assert _load(patch) == []


def test_modified_managed_row_requires_force(dsh_home: Path) -> None:
    patch = dsh_home / "cordis.patch.yml"
    dsh_home.mkdir(parents=True)
    patch.write_text(
        "- insert:\n"
        "    - id: mcp-mommy-chaogu\n"
        "      name: '@deepseek-ai/dsh-mcp-client'\n"
        "      config:\n"
        "        serverName: mommy-chaogu\n"
        "        transport: stdio\n"
        "        command: edited-by-user\n",
        encoding="utf-8",
    )
    previous = {"profile": "market-only", "spec": _spec().as_dict()}
    with pytest.raises(RuntimeError, match="修改"):
        _adapter(previous).register_mcp(_spec())


def test_invalid_yaml_refuses_without_touching_file(dsh_home: Path) -> None:
    patch = dsh_home / "cordis.patch.yml"
    dsh_home.mkdir(parents=True)
    patch.write_text("- insert: [unclosed", encoding="utf-8")
    with pytest.raises(RuntimeError, match="不是有效 YAML"):
        _adapter().register_mcp(_spec())
    assert patch.read_text(encoding="utf-8") == "- insert: [unclosed"


def test_unknown_tag_on_mapping_refuses_to_merge(dsh_home: Path) -> None:
    patch = dsh_home / "cordis.patch.yml"
    dsh_home.mkdir(parents=True)
    patch.write_text(
        "- insert:\n"
        "    - id: user-plugin\n"
        "      name: someone/other-plugin\n"
        "      config: !!js { enabled: true }\n",
        encoding="utf-8",
    )
    with pytest.raises(RuntimeError, match="无法安全合并"):
        _adapter().register_mcp(_spec())


def test_not_installed_reports_hint(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("DSH_HOME", str(tmp_path / "missing"))
    adapter = adapter_for("dsh", which=lambda name: None)
    with pytest.raises(RuntimeError, match="没有找到 dsh"):
        adapter.register_mcp(_spec())


def test_parse_dsh_version_tolerates_release_candidate_and_prefix() -> None:
    assert parse_dsh_version("0.1.1-rc.2") == (0, 1, 1)
    assert parse_dsh_version("dsh/1.2.3 node-v22") == (1, 2, 3)
    assert parse_dsh_version("0.1.1") == (0, 1, 1)
    assert parse_dsh_version("") is None
    assert parse_dsh_version("not-a-version") is None
    assert parse_dsh_version(None) is None
    # 基线常量本身必须可解析，否则 doctor 的版本检查失去意义。
    assert parse_dsh_version(TESTED_DSH_VERSION) is not None


def test_dsh_version_check_reports_drift_as_non_blocking_warning() -> None:
    baseline = TESTED_DSH_VERSION
    assert dsh_version_check(baseline)["status"] == "ok"
    assert dsh_version_check("0.1.1-rc.9")["status"] == "ok"  # 同版本 RC 视为同一基线

    older = dsh_version_check("0.0.9")
    assert older["status"] == "warning"
    assert older["detected"] == "0.0.9"

    newer = dsh_version_check("0.2.0")
    assert newer["status"] == "warning"
    assert "破坏性变更" in newer["message"]

    unknown = dsh_version_check(None)
    assert unknown["status"] == "not_checked"
    assert "npx" in unknown["message"]

    unparseable = dsh_version_check("custom-build")
    assert unparseable["status"] == "warning"
    assert unparseable["detected"] == "custom-build"


def test_doctor_includes_dsh_version_check_without_blocking(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from mommy_chaogu.cli_commands import agent_managed

    monkeypatch.setenv("DSH_HOME", "/tmp/nonexistent-dsh-home")
    with (
        patch.object(agent_managed, "_resolve_host", return_value="dsh"),
        patch.object(agent_managed, "_state_connections", return_value={}),
        patch.object(
            agent_managed,
            "_host_status",
            return_value={"configured": False, "state": "配置缺失", "version": "0.0.9"},
        ),
    ):
        result = agent_managed.doctor_payload("dsh", timeout_seconds=20.0)

    by_name = {item["name"]: item for item in result["checks"]}
    assert by_name["dsh_version"]["status"] == "warning"
    assert by_name["dsh_version"]["detected"] == "0.0.9"
    # 版本漂移是告警不是失败：不进入 blocking_checks。
    assert "dsh_version" not in result["blocking_checks"]
