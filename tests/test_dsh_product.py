"""DSH 产品模式安装器（mommy dsh）离线测试。

只测确定性文件生成与合并语义；不跑 pnpm/npm（安装闭包步骤在用例里被
monkeypatch 掉），不依赖 dsh 二进制。
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from types import SimpleNamespace
from typing import Any

import pytest
import yaml

from mommy_chaogu.cli_commands import dsh_product
from mommy_chaogu.cli_commands.dsh_product import (
    BUNDLE_PACKAGE,
    PRODUCT_SKILL_NAMES,
    _merge_profile_patch,
    build_dsh_parser,
    cmd_dsh_run,
    doctor_dsh_product,
    install_dsh_product,
    locate_bundle,
    product_home,
    profile_dir,
    profile_manifest,
    profile_patch_rows,
    uninstall_dsh_product,
)
from mommy_chaogu.coding_agents.base import ConnectionSpec, connection_spec


@pytest.fixture()
def fake_env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, Path]:
    """独立数据目录 + 跳过 pnpm/npm + 跳过 bundle 构建的安装环境。"""
    data_dir = tmp_path / "data"
    home = data_dir / "dsh-home"
    monkeypatch.setenv("MOMMY_DATA_DIR", str(data_dir))
    monkeypatch.setattr(dsh_product, "_install_profile_node_modules", lambda _dir: None)
    monkeypatch.setattr(dsh_product, "bundle_built", lambda _bundle: True)
    return {"data_dir": data_dir, "home": home}


class TestPaths:
    def test_product_home_follows_data_dir(self, fake_env: dict[str, Path]) -> None:
        assert product_home() == fake_env["home"]
        assert profile_dir() == fake_env["home"] / "profiles" / "mommy"

    def test_locate_bundle_repo_walkup(self, fake_env: dict[str, Path]) -> None:
        bundle = locate_bundle()
        assert (bundle / "cordis.patch.yml").is_file()
        assert bundle.name == "dsh-bundle"


class TestRunPassthrough:
    """run 子命令的参数透传（--no-open 显式 + -- 分隔的任意参数）。"""

    def test_run_plain_has_no_extra_args(self) -> None:
        args = build_dsh_parser().parse_args(["run"])
        assert args.no_open is False
        assert args.dsh_args == []

    def test_run_no_open_flag(self) -> None:
        args = build_dsh_parser().parse_args(["run", "--no-open"])
        assert args.no_open is True
        assert args.dsh_args == []

    def test_run_double_dash_passthrough(self) -> None:
        args = build_dsh_parser().parse_args(["run", "--", "--port", "8080"])
        assert args.dsh_args == ["--port", "8080"]

    def test_cmd_run_assembles_extra_args(self, monkeypatch: pytest.MonkeyPatch) -> None:
        captured: dict[str, list[str]] = {}

        def fake_run_dsh(**kwargs: Any) -> None:
            captured.update(kwargs)

        monkeypatch.setattr(dsh_product, "run_dsh", fake_run_dsh)
        rc = cmd_dsh_run(
            build_dsh_parser().parse_args(["run", "--no-open", "--", "--port", "8080"])
        )
        assert rc == 0
        assert captured["extra_args"] == ["--no-open", "--port", "8080"]


class TestProfileManifest:
    def test_web_bundles_layering(self, tmp_path: Path) -> None:
        manifest = profile_manifest(tmp_path, web=True)
        bundles = manifest["dsh"]["profile"]["bundles"]
        assert bundles[:2] == ["@deepseek-ai/dsh-base", "@deepseek-ai/dsh-web-app"]
        assert bundles[-1] == BUNDLE_PACKAGE
        assert manifest["dsh"]["profile"]["patchReload"] == "live"
        assert manifest["dependencies"][BUNDLE_PACKAGE] == f"file:{tmp_path.resolve()}"

    def test_headless_bundles(self, tmp_path: Path) -> None:
        manifest = profile_manifest(tmp_path, web=False)
        bundles = manifest["dsh"]["profile"]["bundles"]
        assert "@deepseek-ai/dsh-web-app" not in bundles
        assert "@deepseek-ai/dsh-headless" in bundles


class TestProfilePatchRows:
    def test_three_override_rows_full_restate(self, fake_env: dict[str, Path]) -> None:
        spec = connection_spec(profile="market-only")
        rows = profile_patch_rows(
            spec,
            data_dir=fake_env["data_dir"],
            preset_root=fake_env["data_dir"] / "dsh-presets",
            mommy_cli=(sys.executable, ["-m", "mommy_chaogu.cli"]),
        )
        by_id = {row["id"]: row for row in rows}
        assert set(by_id) == {
            "mommy-chaogu-mcp",
            "mommy-chaogu-preset-installer",
            "mommy-chaogu-bridge",
            "agent-presets",
        }
        assert by_id["mommy-chaogu-preset-installer"]["config"]["presetRoot"].endswith(
            "dsh-presets"
        )

        mcp = by_id["mommy-chaogu-mcp"]["config"]
        # 覆盖语义全键 restate：bundle 层的每个键都在（缺键丢配置的坑）
        assert set(mcp) >= {"transport", "serverName", "command", "args", "env", "cwd"}
        assert mcp["serverName"] == "mommy-chaogu"
        assert mcp["command"] == spec.command and mcp["args"] == spec.args

        bridge = by_id["mommy-chaogu-bridge"]["config"]
        assert bridge["mommyCommand"] == sys.executable
        assert bridge["mommyArgs"] == ["-m", "mommy_chaogu.cli"]
        assert Path(bridge["dataDir"]).is_absolute()

        presets = by_id["agent-presets"]["config"]
        assert presets["default"] == "mommy-investor"
        assert presets["roots"][0]["path"].startswith(str(fake_env["data_dir"]))
        assert presets["includeShippedRoot"] is True and presets["includeUserRoot"] is True


class TestMergeProfilePatch:
    def test_fresh_write_then_idempotent(self, tmp_path: Path) -> None:
        path = tmp_path / "cordis.patch.yml"
        row = {
            "id": "mommy-chaogu-mcp",
            "name": "@deepseek-ai/dsh-mcp-client",
            "config": {"serverName": "mommy-chaogu"},
        }
        assert _merge_profile_patch(path, [dict(row)]) == 1
        assert _merge_profile_patch(path, [dict(row)]) == 1
        loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
        assert loaded == [row]

    def test_foreign_rows_preserved_and_own_rows_replaced(self, tmp_path: Path) -> None:
        path = tmp_path / "cordis.patch.yml"
        foreign = {"insert": [{"id": "user-own-row", "name": "some-plugin"}]}
        old = {
            "id": "mommy-chaogu-bridge",
            "name": f"{BUNDLE_PACKAGE}/bridge",
            "config": {"mommyCommand": "old"},
        }
        path.write_text(yaml.safe_dump([foreign, old]), encoding="utf-8")
        new = {
            "id": "mommy-chaogu-bridge",
            "name": f"{BUNDLE_PACKAGE}/bridge",
            "config": {"mommyCommand": "new"},
        }
        _merge_profile_patch(path, [new])
        loaded = yaml.safe_load(path.read_text(encoding="utf-8"))
        assert foreign in loaded
        assert new in loaded
        assert old not in loaded

    def test_refuses_non_array_patch(self, tmp_path: Path) -> None:
        path = tmp_path / "cordis.patch.yml"
        path.write_text("key: value\n", encoding="utf-8")
        with pytest.raises(RuntimeError, match="操作列表"):
            _merge_profile_patch(path, [])


class TestInstallLifecycle:
    def test_install_creates_profile_and_skills(self, fake_env: dict[str, Path]) -> None:
        summary = install_dsh_product(web=True)
        directory = profile_dir(fake_env["home"])
        manifest = json.loads((directory / "package.json").read_text(encoding="utf-8"))
        assert manifest["dsh"]["profile"]["bundles"][-1] == BUNDLE_PACKAGE
        patch = yaml.safe_load((directory / "cordis.patch.yml").read_text(encoding="utf-8"))
        assert {row["id"] for row in patch} == {
            "mommy-chaogu-mcp",
            "mommy-chaogu-preset-installer",
            "mommy-chaogu-bridge",
            "agent-presets",
        }
        for name in PRODUCT_SKILL_NAMES:
            assert (fake_env["home"] / "skills" / name / "SKILL.md").is_file()
        assert summary["web"] is True

    def test_install_is_idempotent(self, fake_env: dict[str, Path]) -> None:
        install_dsh_product()
        directory = profile_dir(fake_env["home"])
        marker = directory / "package.json"
        first = marker.read_text(encoding="utf-8")
        install_dsh_product()
        assert marker.read_text(encoding="utf-8") == first

    def test_modified_skill_blocks_reinstall_without_force(self, fake_env: dict[str, Path]) -> None:
        install_dsh_product()
        skill = fake_env["home"] / "skills" / PRODUCT_SKILL_NAMES[0]
        (skill / "USER-NOTE.md").write_text("user edit", encoding="utf-8")
        with pytest.raises(RuntimeError, match="用户修改"):
            install_dsh_product()
        install_dsh_product(force=True)
        assert not (skill / "USER-NOTE.md").exists()

    def test_uninstall_removes_profile_keeps_modified_skill(
        self, fake_env: dict[str, Path]
    ) -> None:
        install_dsh_product()
        skill = fake_env["home"] / "skills" / PRODUCT_SKILL_NAMES[1]
        (skill / "USER-NOTE.md").write_text("user edit", encoding="utf-8")
        result = uninstall_dsh_product()
        assert result["profile_removed"] is True
        assert not profile_dir(fake_env["home"]).exists()
        assert skill.is_dir() and (skill / "USER-NOTE.md").is_file()
        # 未修改的 Skill 一并移除
        assert not (fake_env["home"] / "skills" / PRODUCT_SKILL_NAMES[0]).exists()

    def test_install_requires_built_bundle(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("MOMMY_DATA_DIR", str(tmp_path / "data"))
        monkeypatch.setattr(dsh_product, "_install_profile_node_modules", lambda _dir: None)
        monkeypatch.setattr(dsh_product, "bundle_built", lambda _bundle: False)
        monkeypatch.setattr(dsh_product, "build_bundle", lambda _bundle: None)
        with pytest.raises(RuntimeError, match="未构建"):
            install_dsh_product(build=False)


class TestDoctor:
    def test_doctor_ok_after_install(self, fake_env: dict[str, Path]) -> None:
        install_dsh_product()
        report = doctor_dsh_product()
        statuses = {check["name"]: check["status"] for check in report["checks"]}
        assert report["ok"] is True
        for name in ("profile_manifest", "profile_patch", "bundle_built", "product_skills"):
            assert statuses[name] == "ok", check_message(report, name)

    def test_doctor_flags_missing_install(self, fake_env: dict[str, Path]) -> None:
        report = doctor_dsh_product()
        assert report["ok"] is False
        assert "profile_manifest" in report["blocking"]
        assert "product_skills" in report["blocking"]

    def test_doctor_version_check_uses_product_baseline(
        self, fake_env: dict[str, Path], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # 回归背景：doctor 曾用 adapter 基线（0.1.1-rc.2）做真实比较、再把文案
        # 字符串替换成产品基线（0.1.5-rc.2）——真实宿主版本永远对着错误基线判。
        # 探测到 0.1.5-rc.2 必须判 ok，且 tested 字段就是产品基线。
        from mommy_chaogu.coding_agents.dsh import parse_dsh_version

        assert parse_dsh_version(dsh_product.PRODUCT_TESTED_DSH_VERSION) is not None
        monkeypatch.setattr(
            dsh_product, "_detect_dsh", lambda: ("/usr/local/bin/dsh", "0.1.5-rc.2")
        )
        report = doctor_dsh_product()
        version_check = next(c for c in report["checks"] if c["name"] == "dsh_version")
        assert version_check["status"] == "ok"
        assert version_check["tested"] == dsh_product.PRODUCT_TESTED_DSH_VERSION
        assert "0.1.5-rc.2" in version_check["message"]


def check_message(report: dict[str, Any], name: str) -> str:
    return next(check["message"] for check in report["checks"] if check["name"] == name)


class TestWatchlistJson:
    def test_list_json_is_machine_readable(
        self, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        from mommy_chaogu.cli_commands.watchlist import build_watchlist_parser
        from mommy_chaogu.watchlist.store import WatchlistStore

        store = WatchlistStore(tmp_path / "portfolio.db")
        store.add_group("白酒")
        store.add_entry("600519", "白酒", note="核心持仓")

        parser = build_watchlist_parser()
        args = parser.parse_args(["--db", str(tmp_path / "portfolio.db"), "list", "--json"])
        rc = args.func(args)
        assert rc == 0
        payload = json.loads(capsys.readouterr().out)
        assert payload == [{"code": "600519", "name": None, "group": "白酒", "note": "核心持仓"}]


class TestSpecBinding:
    def test_connection_spec_binds_current_interpreter(self) -> None:
        spec = connection_spec(profile="personal")
        assert spec.command == sys.executable
        assert "--profile" in spec.args and "personal" in spec.args
        assert "MOMMY_PORTFOLIO_DB" in spec.env
        assert isinstance(spec, ConnectionSpec)


class _FakeMoney:
    def __init__(self, amount: str) -> None:
        self.amount = amount


def _fake_quote(code: str) -> Any:
    from datetime import datetime

    return SimpleNamespace(
        code=code,
        name=f"股票{code}",
        price="12.34",
        change_pct="1.23",
        change="0.15",
        open="12.19",
        high="12.40",
        low="12.10",
        prev_close="12.19",
        volume=1000,
        turnover=_FakeMoney("12340"),
        turnover_rate="0.5",
        volume_ratio="1.1",
        pe_dynamic="25.0",
        total_market_cap=_FakeMoney("1e10"),
        circulating_market_cap=_FakeMoney("8e9"),
        timestamp=datetime(2026, 9, 13, 10, 0, 0),
    )


class TestQuoteCli:
    def test_quote_outputs_source_and_quotes(
        self, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
    ) -> None:
        from mommy_chaogu.cli_commands import quote as quote_cli

        # 回归背景：曾有 bug 是 CLI 直接用裸适配器链（无 format_source_label），
        # source 恒为空串，而本测试 fake 在链上补了该方法照样绿——测试对象
        # 必须是 CLI 真实使用的适配器构造（缓存层），而非裸链。
        class FakeCachedAdapter:
            def get_quotes(self, codes: list[str]) -> list[Any]:
                return [_fake_quote(code) for code in codes]

            def format_source_label(self) -> str:
                return "测试源"

        monkeypatch.setattr(quote_cli, "_build_quote_adapter", lambda: FakeCachedAdapter())
        rc = quote_cli.main_quote(["600519", "000001"])
        assert rc == 0
        payload = json.loads(capsys.readouterr().out)
        assert payload["source"] == "测试源"
        assert [q["code"] for q in payload["quotes"]] == ["600519", "000001"]
        assert payload["quotes"][0]["price"] == 12.34

    def test_quote_rejects_over_limit(self, capsys: pytest.CaptureFixture[str]) -> None:
        from mommy_chaogu.cli_commands import quote as quote_cli

        codes = [str(600000 + i) for i in range(51)]
        rc = quote_cli.main_quote(codes)
        assert rc == 2
        assert "50" in capsys.readouterr().err


class TestDoctorMcpProfile:
    """doctor 必须如实报告 MCP 档位与对应的工具面（档位探测面只有 doctor）。"""

    def test_market_only_default_reports_public_surface(self, fake_env: dict[str, Path]) -> None:
        install_dsh_product()
        report = doctor_dsh_product()
        check = next(c for c in report["checks"] if c["name"] == "mcp_profile")
        assert check["status"] == "ok"
        assert "market-only" in check["message"]
        assert "19 个基础工具" in check["message"]
        assert "5 个研究工作流" in check["message"]

    def test_personal_reports_full_surface_and_boundary(self, fake_env: dict[str, Path]) -> None:
        install_dsh_product(mcp_profile="personal")
        report = doctor_dsh_product()
        check = next(c for c in report["checks"] if c["name"] == "mcp_profile")
        assert check["status"] == "ok"
        assert "personal" in check["message"]
        assert "37 个基础工具" in check["message"]
        assert "7 个研究工作流" in check["message"]
        assert "审批闸" in check["message"]

    def test_unknown_profile_is_error(self, fake_env: dict[str, Path]) -> None:
        install_dsh_product()
        patch = dsh_product.profile_dir() / "cordis.patch.yml"
        text = patch.read_text(encoding="utf-8").replace("market-only", "yolo")
        patch.write_text(text, encoding="utf-8")
        report = doctor_dsh_product()
        check = next(c for c in report["checks"] if c["name"] == "mcp_profile")
        assert check["status"] == "error"
        assert "mcp_profile" in report["blocking"]
