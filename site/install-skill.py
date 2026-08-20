#!/usr/bin/env python3
"""Install a downloaded mommy-chaogu Skill bundle into a host's Skill directory.

The script is intentionally dependency-free so it can be downloaded next to a
ZIP/TAR.GZ from the static Skills store and inspected before execution.
"""

from __future__ import annotations

import argparse
import os
import re
import shutil
import sys
import tarfile
import tempfile
import uuid
import zipfile
from pathlib import Path, PurePosixPath


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="安装 mommy-chaogu Skills 归档（zip / tar.gz），默认目标为 Codex。"
    )
    parser.add_argument("archive", type=Path, help="下载的 .zip 或 .tar.gz 文件")
    parser.add_argument(
        "--target",
        choices=("codex", "claude", "kimi", "cline", "custom"),
        default="codex",
        help="目标宿主；custom 需要同时提供 --destination",
    )
    parser.add_argument(
        "--destination",
        type=Path,
        help="Skill 根目录；不传时使用目标宿主的默认目录",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="替换同名目录；不传时遇到已有目录会安全停止",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="只校验归档并打印目标路径，不写入文件",
    )
    return parser


def _default_destination(target: str) -> Path:
    if target == "custom":
        raise ValueError("--target custom 必须同时提供 --destination")
    home = Path.home()
    if target == "codex":
        configured = os.environ.get("CODEX_SKILLS_DIR", "").strip()
        return Path(configured).expanduser() if configured else home / ".agents" / "skills"
    if target == "claude":
        configured = os.environ.get("CLAUDE_CONFIG_DIR", "").strip()
        base = Path(configured).expanduser() if configured else home / ".claude"
        return base / "skills"
    if target == "kimi":
        configured = os.environ.get("KIMI_CODE_HOME", "").strip()
        base = Path(configured).expanduser() if configured else home / ".kimi-code"
        return base / "skills"
    configured = os.environ.get("CLINE_DATA_DIR", "").strip()
    base = Path(configured).expanduser() if configured else home / ".cline" / "data"
    return base / "settings" / "skills"


def _safe_member_name(name: str) -> PurePosixPath:
    normalized = PurePosixPath(name)
    if normalized.is_absolute() or ".." in normalized.parts:
        raise ValueError(f"归档包含不安全路径：{name}")
    return normalized


def _extract_zip(archive: Path, destination: Path) -> None:
    with zipfile.ZipFile(archive) as bundle:
        for member in bundle.infolist():
            _safe_member_name(member.filename)
            file_mode = (member.external_attr >> 16) & 0o170000
            if file_mode == 0o120000:
                raise ValueError(f"归档包含链接，为避免写入意外位置已停止：{member.filename}")
        bundle.extractall(destination)


def _extract_tar(archive: Path, destination: Path) -> None:
    with tarfile.open(archive, mode="r:*") as bundle:
        for member in bundle.getmembers():
            _safe_member_name(member.name)
            if member.issym() or member.islnk():
                raise ValueError(f"归档包含链接，为避免写入意外位置已停止：{member.name}")
        # The archive has already passed the traversal and link checks above.
        # Use the safer filter when available, while keeping compatibility
        # with the Python 3.9 runtime still present on some macOS machines.
        if sys.version_info >= (3, 12):
            bundle.extractall(destination, filter="data")
        else:
            bundle.extractall(destination)


def _extract(archive: Path, destination: Path) -> None:
    name = archive.name.lower()
    if name.endswith(".zip"):
        _extract_zip(archive, destination)
    elif name.endswith((".tar.gz", ".tgz", ".tar")):
        _extract_tar(archive, destination)
    else:
        raise ValueError("只支持 .zip、.tar.gz、.tgz 或 .tar 归档")


def _find_skill_root(extracted: Path) -> tuple[Path, str]:
    candidates = sorted(path.parent for path in extracted.rglob("SKILL.md") if path.is_file())
    if len(candidates) != 1:
        raise ValueError(f"归档应包含且只能包含一个 SKILL.md，实际找到 {len(candidates)} 个")
    root = candidates[0]
    content = (root / "SKILL.md").read_text(encoding="utf-8")
    match = re.search(r"^name:\s*([A-Za-z0-9][A-Za-z0-9._-]*)\s*$", content, re.MULTILINE)
    if match is None:
        raise ValueError("SKILL.md 缺少可识别的 frontmatter name")
    skill_name = match.group(1)
    if Path(skill_name).name != skill_name:
        raise ValueError(f"SKILL 名称不安全：{skill_name}")
    return root, skill_name


def _install(source: Path, destination_root: Path, skill_name: str, *, force: bool) -> Path:
    destination_root.mkdir(parents=True, exist_ok=True)
    destination = destination_root / skill_name
    if destination.is_symlink():
        raise ValueError(f"目标是符号链接，为避免写入意外位置已停止：{destination}")
    if destination.exists() and not force:
        raise FileExistsError(f"目标已存在：{destination}；升级时请显式使用 --force")

    staging = (
        Path(tempfile.mkdtemp(prefix=f".{skill_name}-staging-", dir=destination_root)) / skill_name
    )
    backup = destination_root / f".{skill_name}-backup-{uuid.uuid4().hex}"
    shutil.copytree(source, staging)
    had_destination = destination.is_dir()
    try:
        if had_destination:
            destination.rename(backup)
        staging.rename(destination)
    except Exception:
        if had_destination and backup.is_dir() and not destination.exists():
            backup.rename(destination)
        raise
    finally:
        shutil.rmtree(staging.parent, ignore_errors=True)
    if backup.is_dir():
        shutil.rmtree(backup)
    return destination


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    archive = args.archive.expanduser().resolve()
    if not archive.is_file():
        print(f"错误：找不到归档文件：{archive}", file=sys.stderr)
        return 2

    try:
        destination_root = (
            (args.destination or _default_destination(args.target)).expanduser().resolve()
        )
        with tempfile.TemporaryDirectory(prefix="mommy-skill-verify-") as temp_dir:
            extracted = Path(temp_dir)
            _extract(archive, extracted)
            skill_root, skill_name = _find_skill_root(extracted)
            destination = destination_root / skill_name
            print(f"已验证：{skill_name} ← {archive.name}")
            print(f"目标目录：{destination}")
            if not args.dry_run:
                installed = _install(skill_root, destination_root, skill_name, force=args.force)
                print(f"✅ 安装完成：{installed}")
    except (OSError, ValueError, tarfile.TarError, zipfile.BadZipFile) as exc:
        print(f"错误：{exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
