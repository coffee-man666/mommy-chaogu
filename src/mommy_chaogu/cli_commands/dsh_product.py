"""mommy dsh —— DSH 产品模式安装器（独立 DSH_HOME + profile 嫁接）。

与 ``mommy connect dsh``（增强模式：往用户 ``~/.dsh`` 合并一行 MCP）互补，
本模块把 mommy-chaogu 作为**产品**嫁接到 DSH 宿主：

1. 独立 ``DSH_HOME``（默认 ``<数据目录>/dsh-home``，不污染用户 ``~/.dsh``）；
2. ``profiles/mommy/`` 生成官方 profile manifest（dsh.profile.bundles =
   dsh-base + dsh-web-app + @mommy-chaogu/dsh-bundle）；
3. profile 私有 ``cordis.patch.yml`` 覆盖 bundle 行配置为**绝对路径**（MCP 行绑定
   当前解释器与解析后的数据库路径，桥行绑定 mommy CLI 与数据目录，agent-presets
   行绑定产品 preset root）——覆盖语义全键 restate，不改 bundle 包本身；
4. 产品 Skill（当前五个）装进 ``<DSH_HOME>/skills``（preset 的 skill-filesystem 发现根）。

preset 与审批闸门由 bundle 在宿主 boot 时自安装/自挂载（TS 侧），Python 侧只做
确定性落盘。bundle 源码在仓库 ``dsh/`` 子工程（pnpm workspace），安装前需构建。
"""

from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, NoReturn

import yaml

from mommy_chaogu.agent.research_tools import (
    allowed_base_tool_names,
    allowed_research_tool_names,
    normalize_mcp_profile,
)
from mommy_chaogu.coding_agents.base import (
    ConnectionSpec,
    connection_spec,
    directory_hash,
    install_skill,
    remove_managed_skills,
)

# dsh patch 的 YAML 可能含未知标签（用户层的 !!js 行）——复用 dsh adapter 的
# 保标签读写机器（同包内协作，语义见 coding_agents/dsh.py 头注）。
from mommy_chaogu.coding_agents.dsh import (
    _PatchDumper,
    _PatchLoader,
    dsh_version_check,
)
from mommy_chaogu.db_paths import default_data_dir

#: 产品 profile 名（``dsh --profile mommy``）。
PROFILE_NAME = "mommy"
#: 嫁接 bundle 的 npm 包名（patch 行与 profile 依赖的解析键）。
BUNDLE_PACKAGE = "@mommy-chaogu/dsh-bundle"
#: 与 dsh-bundle 依赖钉版一致的宿主验证基线（0.1.5-rc 系）。
PRODUCT_TESTED_DSH_VERSION = "0.1.5-rc.2"
#: preset 挂载的产品 Skill：三件套（persona 文本引用）+ 两个分析 Skill
#: （篮子均线分析 / 盘内观察循环——宿主可按 skill 脚本跑完整技术分析）。
PRODUCT_SKILL_NAMES: tuple[str, ...] = (
    "mommy-onboard",
    "mommy-research",
    "mommy-strategy",
    "basket-analysis",
    "market-watch-loop",
)

_WEB_BUNDLES: tuple[str, ...] = ("@deepseek-ai/dsh-base", "@deepseek-ai/dsh-web-app")
_HEADLESS_BUNDLES: tuple[str, ...] = ("@deepseek-ai/dsh-base", "@deepseek-ai/dsh-headless")


def product_home() -> Path:
    """产品 DSH_HOME：MOMMY_DSH_HOME 覆盖，否则数据目录下 dsh-home。"""
    override = os.environ.get("MOMMY_DSH_HOME", "").strip()
    if override:
        return Path(override).expanduser()
    return default_data_dir() / "dsh-home"


def product_preset_root() -> Path:
    """产品 preset root（与 dsh-bundle src/presets.ts defaultPresetRoot 同一解析）。"""
    return default_data_dir() / "dsh-presets"


def profile_dir(home: Path | None = None) -> Path:
    return (home or product_home()) / "profiles" / PROFILE_NAME


def locate_bundle() -> Path:
    """定位 dsh-bundle 源码目录：MOMMY_DSH_BUNDLE 覆盖 → 仓库内 dsh/ 子工程。"""
    override = os.environ.get("MOMMY_DSH_BUNDLE", "").strip()
    if override:
        path = Path(override).expanduser()
        if not path.is_dir():
            raise RuntimeError(f"MOMMY_DSH_BUNDLE 指向不存在的目录：{path}")
        return path
    current = Path(__file__).resolve()
    for parent in current.parents:
        candidate = parent / "dsh" / "packages" / "dsh-bundle"
        if (parent / "pyproject.toml").is_file() and candidate.is_dir():
            return candidate
    raise RuntimeError(
        "没有找到 dsh-bundle 源码目录。源码安装请确认仓库 dsh/ 子工程存在，"
        "或设置 MOMMY_DSH_BUNDLE 指向 @mommy-chaogu/dsh-bundle 包目录。"
    )


def bundle_built(bundle: Path) -> bool:
    """bundle 构建产物齐备（host 半 index.js + 浏览器半 client.js）。"""
    return (bundle / "lib" / "index.js").is_file() and (bundle / "lib" / "client.js").is_file()


def build_bundle(bundle: Path) -> None:
    """在 dsh/ 子工程跑 pnpm 构建（安装闭包 + 双半构建）。"""
    workspace = bundle.parents[1]
    pnpm = shutil.which("pnpm")
    if pnpm is None:
        raise RuntimeError(
            "没有找到 pnpm；请先安装 pnpm 或手动运行 `pnpm -C dsh install && pnpm -C dsh build`"
        )
    for args in (["install"], ["build"]):
        result = subprocess.run(
            [pnpm, *args, "--dir", str(workspace)],
            text=True,
            capture_output=True,
            check=False,
            timeout=600,
        )
        if result.returncode != 0:
            detail = (result.stderr or result.stdout or "").strip()[-800:]
            raise RuntimeError(f"pnpm {args[0]} 失败（{workspace}）：\n{detail}")
    if not bundle_built(bundle):
        raise RuntimeError(f"pnpm 构建完成但产物不齐备：{bundle / 'lib'}")


def profile_manifest(bundle: Path, *, web: bool) -> dict[str, Any]:
    """官方 profile manifest：bundles 层序 = 宿主模板 + 产品 bundle。"""
    layer = _WEB_BUNDLES if web else _HEADLESS_BUNDLES
    bundles = [*layer, BUNDLE_PACKAGE]
    return {
        "name": "mommy-chaogu-dsh-profile",
        "private": True,
        "dsh": {
            "profile": {
                "bundles": bundles,
                # 自定义 profile 默认 live（宿主 DEFAULT_PROFILE_PATCH_RELOAD 同款）
                "patchReload": "live",
            }
        },
        "dependencies": {
            BUNDLE_PACKAGE: f"file:{bundle.resolve()}",
        },
    }


def profile_patch_rows(
    spec: ConnectionSpec,
    *,
    data_dir: Path,
    preset_root: Path,
    mommy_cli: tuple[str, list[str]],
) -> list[dict[str, Any]]:
    """profile 层覆盖行（在所有 bundle 层之后应用，同 id 全键 restate）。"""
    mommy_command, mommy_args = mommy_cli
    return [
        {
            # MCP 行绑定当前解释器与解析后的数据库路径（build_spec 纪律：
            # 单独安装的 mommy-mcp 可能是旧版本，绝不混用）
            "id": "mommy-chaogu-mcp",
            "name": "@deepseek-ai/dsh-mcp-client",
            "config": {
                "transport": "stdio",
                "serverName": "mommy-chaogu",
                "command": spec.command,
                "args": list(spec.args),
                "env": dict(spec.env),
                "cwd": spec.cwd,
            },
        },
        {
            # preset 安装器目标 root 显式化：宿主进程里没有 MOMMY_DATA_DIR，
            # TS 侧默认解析（~/.local/share）可能与 agent-presets 挂载的 root
            # 分叉——boot 时自安装必须落在挂载的同一个 root。
            "id": "mommy-chaogu-preset-installer",
            "name": f"{BUNDLE_PACKAGE}/presets",
            "config": {"presetRoot": str(preset_root)},
        },
        {
            # 桥行绑定 mommy CLI（python -m 形态，与当前安装一致）与数据目录
            "id": "mommy-chaogu-bridge",
            "name": f"{BUNDLE_PACKAGE}/bridge",
            "config": {
                "mommyCommand": mommy_command,
                "mommyArgs": list(mommy_args),
                "dataDir": str(data_dir),
            },
        },
        {
            # preset root 绝对路径覆盖（bundle 层用 ~ 相对默认值）
            "id": "agent-presets",
            "name": "@deepseek-ai/dsh-agent-presets",
            "config": {
                "default": "mommy-investor",
                "roots": [{"path": str(preset_root), "trust": "user"}],
                "includeShippedRoot": True,
                "includeUserRoot": True,
            },
        },
    ]


def _write_atomic(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(text, encoding="utf-8")
    temp.replace(path)


def _merge_profile_patch(path: Path, rows: list[dict[str, Any]]) -> int:
    """profile patch 落盘：同 id 覆盖行替换，其余（用户自加行）原样保留。

    返回写入的覆盖行数。文件损坏/非数组时拒绝写入而不是猜（dsh adapter 同款）。
    """
    if path.is_file():
        loaded = yaml.load(path.read_text(encoding="utf-8"), Loader=_PatchLoader)
        if loaded is None:
            patches: list[Any] = []
        elif isinstance(loaded, list):
            patches = loaded
        else:
            raise RuntimeError(f"profile patch 必须是操作列表：{path}")
    else:
        patches = []
    ids = {row.get("id") for row in rows}
    patches = [op for op in patches if not (isinstance(op, dict) and op.get("id") in ids)]
    patches.extend(rows)
    header = (
        "# mommy-chaogu 产品 profile 的用户 patch 层（bundle 层之后应用）。\n"
        "# 本文件由 mommy dsh install 生成：只拥有 mommy-chaogu-mcp / mommy-chaogu-preset-installer /\n"
        "# mommy-chaogu-bridge / agent-presets 四个覆盖行，其余行是你自己的，升级时原样保留。\n"
    )
    _write_atomic(
        path, header + yaml.dump(patches, Dumper=_PatchDumper, allow_unicode=True, sort_keys=False)
    )
    return len(rows)


def _install_profile_node_modules(directory: Path) -> None:
    """按 profile package.json 安装依赖闭包（file: 链接 bundle 进 node_modules）。

    pnpm 对 file: 依赖按 lockfile 缓存，bundle 产物更新后不会自动刷新——先删
    旧副本再 install（dsh-trading「刷新 file: 副本」同款纪律）。
    """
    stale_scope = directory / "node_modules" / "@mommy-chaogu"
    if stale_scope.exists():
        shutil.rmtree(stale_scope, ignore_errors=True)
    pnpm_dir = directory / "node_modules" / ".pnpm"
    if pnpm_dir.is_dir():
        for entry in pnpm_dir.glob("@mommy-chaogu+*"):
            shutil.rmtree(entry, ignore_errors=True)
    if shutil.which("pnpm") is not None:
        command = ["pnpm", "install", "--dir", str(directory)]
    elif shutil.which("npm") is not None:
        command = ["npm", "install", "--prefix", str(directory)]
    else:
        raise RuntimeError(
            "没有找到 pnpm/npm，无法安装 profile 依赖闭包；"
            f"请手动在 {directory} 运行包管理器 install 后重试。"
        )
    result = subprocess.run(command, text=True, capture_output=True, check=False, timeout=600)
    if result.returncode != 0:
        detail = (result.stderr or result.stdout or "").strip()[-800:]
        raise RuntimeError(f"profile 依赖安装失败（{directory}）：\n{detail}")


def _bundled_skill_source(name: str) -> Path:
    from mommy_chaogu.plugins import bundled_plugin_dirs

    for source in bundled_plugin_dirs():
        if source.name == name:
            return source
    raise RuntimeError(f"没有找到 bundled Skill 源目录：{name}")


def install_dsh_product(
    *,
    home: Path | None = None,
    web: bool = True,
    build: bool = True,
    force: bool = False,
    mcp_profile: str = "market-only",
) -> dict[str, Any]:
    """安装/升级产品 profile。幂等：重复安装重生成 manifest 与自有覆盖行。"""
    resolved_home = (home or product_home()).resolve()
    bundle = locate_bundle()
    if not bundle_built(bundle):
        if build:
            build_bundle(bundle)
        else:
            raise RuntimeError(
                f"dsh-bundle 未构建（缺 lib/index.js 或 lib/client.js）：{bundle}\n"
                "请先运行 `pnpm -C dsh install && pnpm -C dsh build`，或去掉 --no-build。"
            )

    directory = profile_dir(resolved_home)
    directory.mkdir(parents=True, exist_ok=True)

    manifest = profile_manifest(bundle, web=web)
    _write_atomic(
        directory / "package.json", json.dumps(manifest, ensure_ascii=False, indent=2) + "\n"
    )
    _install_profile_node_modules(directory)

    spec = connection_spec(profile=mcp_profile)
    data_dir = default_data_dir().resolve()
    preset_root = product_preset_root().resolve()
    mommy_cli = (sys.executable, ["-m", "mommy_chaogu.cli"])
    rows = profile_patch_rows(spec, data_dir=data_dir, preset_root=preset_root, mommy_cli=mommy_cli)
    merged = _merge_profile_patch(directory / "cordis.patch.yml", rows)

    installed_skills: list[str] = []
    for name in PRODUCT_SKILL_NAMES:
        install_skill("dsh", _bundled_skill_source(name), None, force=force, home=resolved_home)
        installed_skills.append(name)

    return {
        "home": str(resolved_home),
        "profile": str(directory),
        "bundle": str(bundle),
        "web": web,
        "mcp_profile": mcp_profile,
        "patch_rows": merged,
        "skills": installed_skills,
        "launch": f"mommy dsh run（即 DSH_HOME={resolved_home} dsh --profile {PROFILE_NAME}）",
    }


def uninstall_dsh_product(*, home: Path | None = None) -> dict[str, Any]:
    """移除产品 profile 与未修改的托管 Skill；用户改过的 Skill 保留。"""
    resolved_home = (home or product_home()).resolve()
    directory = profile_dir(resolved_home)
    removed_profile = False
    if directory.is_dir():
        shutil.rmtree(directory)
        removed_profile = True
    # 合成托管记录（路径 + 期望 hash = bundled 源当前值）：只删未修改副本
    previous: dict[str, Any] = {"skills": {}}
    for name in PRODUCT_SKILL_NAMES:
        source = _bundled_skill_source(name)
        previous["skills"][name] = {
            "path": str(resolved_home / "skills" / name),
            "hash": directory_hash(source),
        }
    remove_managed_skills("dsh", previous, home=resolved_home)
    return {"home": str(resolved_home), "profile_removed": removed_profile}


def _detect_dsh() -> tuple[str | None, str | None]:
    """探测 dsh 可执行与版本（npx 形态探测不到版本，返回 None）。"""
    binary = shutil.which("dsh")
    if binary is None:
        return None, None
    try:
        result = subprocess.run(
            [binary, "--version"], text=True, capture_output=True, check=False, timeout=30
        )
    except (OSError, subprocess.SubprocessError):
        return binary, None
    version = (result.stdout or result.stderr or "").strip() or None
    return binary, version


def doctor_dsh_product(*, home: Path | None = None) -> dict[str, Any]:
    """逐项体检：dsh 探测、profile 文件、bundle 产物、Skill、覆盖行、MCP 档位。"""
    resolved_home = (home or product_home()).resolve()
    directory = profile_dir(resolved_home)
    checks: list[dict[str, Any]] = []

    binary, version = _detect_dsh()
    if binary is None:
        checks.append(
            {
                "name": "dsh_binary",
                "status": "warning",
                "message": "PATH 上没有 dsh 二进制（npx 运行形态探测不到）； mommy dsh run 会回退 npx @deepseek-ai/dsh。",
            }
        )
    else:
        checks.append(dsh_version_check(version, baseline=PRODUCT_TESTED_DSH_VERSION))

    manifest_path = directory / "package.json"
    if manifest_path.is_file():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        bundles = manifest.get("dsh", {}).get("profile", {}).get("bundles", [])
        if BUNDLE_PACKAGE in bundles:
            checks.append(
                {
                    "name": "profile_manifest",
                    "status": "ok",
                    "message": f"profile bundles 共 {len(bundles)} 层，含 {BUNDLE_PACKAGE}。",
                }
            )
        else:
            checks.append(
                {
                    "name": "profile_manifest",
                    "status": "error",
                    "message": f"profile manifest 缺 {BUNDLE_PACKAGE}，请重跑 mommy dsh install。",
                }
            )
    else:
        checks.append(
            {
                "name": "profile_manifest",
                "status": "error",
                "message": f"没有找到 {manifest_path}；先运行 mommy dsh install。",
            }
        )

    try:
        bundle = locate_bundle()
        checks.append(
            {
                "name": "bundle_built",
                "status": "ok" if bundle_built(bundle) else "error",
                "message": f"bundle 产物{'齐备' if bundle_built(bundle) else '缺失'}（{bundle / 'lib'}）。",
            }
        )
    except RuntimeError as exc:
        checks.append({"name": "bundle_built", "status": "error", "message": str(exc)})

    patch_path = directory / "cordis.patch.yml"
    if patch_path.is_file():
        patches = yaml.load(patch_path.read_text(encoding="utf-8"), Loader=_PatchLoader) or []
        ids = {op.get("id") for op in patches if isinstance(op, dict)}
        expected = {
            "mommy-chaogu-mcp",
            "mommy-chaogu-preset-installer",
            "mommy-chaogu-bridge",
            "agent-presets",
        }
        missing = expected - ids
        checks.append(
            {
                "name": "profile_patch",
                "status": "ok" if not missing else "error",
                "message": "覆盖行齐备。"
                if not missing
                else f"缺覆盖行：{sorted(missing)}；重跑 mommy dsh install。",
            }
        )
        # 档位检查：MCP 行 args 的 --profile 决定宿主 Agent 的工具面（切换
        # 档位 = 重跑 install + 重启宿主）。doctor 是唯一的档位探测面。
        mcp_row = next(
            (op for op in patches if isinstance(op, dict) and op.get("id") == "mommy-chaogu-mcp"),
            None,
        )
        profile_args: list[str] = []
        if isinstance(mcp_row, dict):
            raw_args = mcp_row.get("config", {}).get("args", [])
            if isinstance(raw_args, list):
                profile_args = [str(item) for item in raw_args]
        profile_value: str | None = None
        if "--profile" in profile_args:
            idx = profile_args.index("--profile")
            if idx + 1 < len(profile_args):
                profile_value = profile_args[idx + 1]
        if profile_value is None:
            checks.append(
                {
                    "name": "mcp_profile",
                    "status": "error",
                    "message": "MCP 覆盖行缺 --profile 参数；重跑 mommy dsh install。",
                }
            )
        else:
            try:
                profile = normalize_mcp_profile(profile_value)
            except ValueError:
                checks.append(
                    {
                        "name": "mcp_profile",
                        "status": "error",
                        "message": f"未知档位 {profile_value!r}（须为 market-only 或 personal）；重跑 mommy dsh install。",
                    }
                )
            else:
                n_base = len(allowed_base_tool_names(profile))
                n_research = len(allowed_research_tool_names(profile))
                if profile == "market-only":
                    message = (
                        f"market-only（公共行情档）：{n_base} 个基础工具 + "
                        f"{n_research} 个研究工作流；个人上下文与写操作不开放，"
                        "策略卡/记忆相关卡片不会渲染。"
                    )
                else:
                    message = (
                        f"personal（个人档）：{n_base} 个基础工具 + "
                        f"{n_research} 个研究工作流，含策略卡、记忆与持仓；"
                        "写操作经宿主审批闸逐次授权；个人数据对宿主 Agent 可见。"
                    )
                checks.append({"name": "mcp_profile", "status": "ok", "message": message})
    else:
        checks.append(
            {"name": "profile_patch", "status": "error", "message": f"没有找到 {patch_path}。"}
        )

    skills_missing = [
        name for name in PRODUCT_SKILL_NAMES if not (resolved_home / "skills" / name).is_dir()
    ]
    checks.append(
        {
            "name": "product_skills",
            "status": "ok" if not skills_missing else "error",
            "message": f"{len(PRODUCT_SKILL_NAMES)} 个产品 Skill 就位。"
            if not skills_missing
            else f"缺 Skill：{skills_missing}。",
        }
    )

    blocking = [c["name"] for c in checks if c["status"] == "error"]
    return {"home": str(resolved_home), "checks": checks, "ok": not blocking, "blocking": blocking}


def run_dsh(*, home: Path | None = None, extra_args: list[str] | None = None) -> NoReturn:
    """以产品 DSH_HOME 启动 dsh --profile mommy（替换当前进程）。

    extra_args 原样追加在宿主命令之后（如 ``--no-open`` 不自动开浏览器）。
    """
    resolved_home = (home or product_home()).resolve()
    directory = profile_dir(resolved_home)
    if not (directory / "package.json").is_file():
        raise RuntimeError(f"产品 profile 未安装（{directory}）；先运行 mommy dsh install。")
    passthrough = list(extra_args or [])
    binary = shutil.which("dsh")
    if binary is not None:
        command = [binary, "--profile", PROFILE_NAME, *passthrough]
    else:
        npx = shutil.which("npx")
        if npx is None:
            raise RuntimeError(
                "没有找到 dsh 或 npx；请先安装 DeepSeek Harness（npm i -g @deepseek-ai/dsh）。"
            )
        command = [npx, "-y", "@deepseek-ai/dsh", "--profile", PROFILE_NAME, *passthrough]
        if not passthrough:
            print(
                "⚠️  PATH 上无 dsh 二进制，npx 回退可能解析到缓存的旧版本；建议 npm i -g @deepseek-ai/dsh。"
            )
    env = {**os.environ, "DSH_HOME": str(resolved_home)}
    print(f"▶ {' '.join(command)}  (DSH_HOME={resolved_home})")
    os.execvpe(command[0], command, env)


# ============================================================
# CLI
# ============================================================


def cmd_dsh_install(args: argparse.Namespace) -> int:
    summary = install_dsh_product(
        web=not args.headless,
        build=not args.no_build,
        force=args.force,
        mcp_profile="personal" if args.personal else "market-only",
    )
    print(f"✅ mommy DSH 产品 profile 已安装：{summary['profile']}")
    print(f"   DSH_HOME   {summary['home']}")
    print(
        f"   MCP 档位   {summary['mcp_profile']}（market-only=公共行情；--personal 开个人上下文与写操作）"
    )
    print(
        f"   覆盖行     {summary['patch_rows']} 条（mcp / preset-installer / bridge / agent-presets）"
    )
    print(f"   Skill      {', '.join(summary['skills'])}")
    print(f"   启动       {summary['launch']}")
    return 0


def cmd_dsh_uninstall(_args: argparse.Namespace) -> int:
    summary = uninstall_dsh_product()
    print(
        f"🗑️  已移除产品 profile：{summary['home']}"
        if summary["profile_removed"]
        else "ℹ️ 产品 profile 本来就不存在。"
    )
    print("   未被修改的托管 Skill 已一并移除；你改过的 Skill 目录已保留。")
    return 0


def cmd_dsh_doctor(_args: argparse.Namespace) -> int:
    report = doctor_dsh_product()
    print(f" mommy DSH 产品体检（home={report['home']}）")
    for check in report["checks"]:
        icon = {"ok": "✅", "error": "❌", "warning": "⚠️ ", "not_checked": "ℹ️ "}.get(
            check["status"], "·"
        )
        print(f" {icon} {check['name']}: {check['message']}")
    if report["ok"]:
        print("\n结论：产品 profile 可用。")
        return 0
    print(f"\n结论：存在阻塞项（{', '.join(report['blocking'])}）；重跑 mommy dsh install 可修复。")
    return 1


def cmd_dsh_run(args: argparse.Namespace) -> int:
    extra: list[str] = ["--no-open"] if args.no_open else []
    extra.extend(args.dsh_args)
    run_dsh(extra_args=extra)
    return 0  # pragma: no cover — execvpe 成功后不再返回


def build_dsh_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="mommy-dsh",
        description="妈妈炒股 - DSH 产品模式（独立 DSH_HOME + profile 嫁接）",
        epilog=(
            "example:\n"
            "  mommy dsh install          安装/升级产品 profile（默认 web 宿主）\n"
            "  mommy dsh install --headless   无头宿主（无 GUI，工具面照常）\n"
            "  mommy dsh run              启动 dsh --profile mommy\n"
            "  mommy dsh run --no-open    启动但不自动开浏览器（透传底层 dsh）\n"
            "  mommy dsh doctor           逐项体检"
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    sub = p.add_subparsers(dest="cmd", required=True)

    p_i = sub.add_parser("install", help="安装/升级产品 profile（幂等）")
    p_i.add_argument("--headless", action="store_true", help="无头宿主（不装 dsh-web-app 层）")
    p_i.add_argument(
        "--no-build", action="store_true", help="不自动构建 dsh-bundle（产物需已存在）"
    )
    p_i.add_argument("--force", action="store_true", help="Skill 目标被用户修改过也覆盖")
    p_i.add_argument(
        "--personal", action="store_true", help="MCP 档位切 personal（默认 market-only）"
    )
    p_i.set_defaults(func=cmd_dsh_install)

    p_u = sub.add_parser("uninstall", help="移除产品 profile 与未修改的托管 Skill")
    p_u.set_defaults(func=cmd_dsh_uninstall)

    p_d = sub.add_parser("doctor", help="逐项体检")
    p_d.set_defaults(func=cmd_dsh_doctor)

    p_r = sub.add_parser("run", help="启动 dsh --profile mommy")
    p_r.add_argument(
        "--no-open", action="store_true", help="不自动打开浏览器（透传底层 dsh --no-open）"
    )
    p_r.add_argument(
        "dsh_args",
        nargs="*",
        help="额外透传给底层 dsh 的参数（用 -- 分隔，如 mommy dsh run -- --port 8080）",
    )
    p_r.set_defaults(func=cmd_dsh_run)

    return p


def main_dsh(argv: list[str] | None = None) -> int:
    parser = build_dsh_parser()
    args = parser.parse_args(argv)
    rc = args.func(args)
    return int(rc) if rc is not None else 0


if __name__ == "__main__":
    raise SystemExit(main_dsh())
