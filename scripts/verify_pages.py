"""Validate the static GitHub Pages bundle and its downloadable artifacts."""

from __future__ import annotations

import json
import re
import tarfile
import zipfile
from pathlib import Path, PurePosixPath

ROOT = Path(__file__).resolve().parents[1]
SITE = ROOT / "site"


def _require(path: Path) -> None:
    if not path.is_file():
        raise AssertionError(f"missing site asset: {path}")


def _archive_has_skill(path: Path) -> None:
    if path.suffix == ".zip":
        with zipfile.ZipFile(path) as bundle:
            names = bundle.namelist()
    elif path.name.endswith((".tar.gz", ".tgz", ".tar")):
        with tarfile.open(path, mode="r:*") as bundle:
            names = bundle.getnames()
    else:
        raise AssertionError(f"unsupported archive: {path}")
    skill_files = [name for name in names if PurePosixPath(name).name == "SKILL.md"]
    if len(skill_files) != 1:
        raise AssertionError(f"{path.name} should contain one SKILL.md, found {skill_files}")


def _check_links() -> None:
    index = (SITE / "index.html").read_text(encoding="utf-8")
    links = re.findall(r"(?:href|src)=[\"']([^\"']+)[\"']", index)
    for link in links:
        if link.startswith(("#", "http:", "https:", "mailto:", "data:")):
            continue
        local = link.split("?", 1)[0].split("#", 1)[0]
        if not local:
            continue
        candidate = (SITE / local.lstrip("./")).resolve()
        if SITE not in candidate.parents and candidate != SITE:
            raise AssertionError(f"site link escapes site/: {link}")
        _require(candidate)


def main() -> int:
    for relative in (
        "index.html",
        "styles.css",
        "app.js",
        "install-skill.py",
        "plugins.json",
        "README.md",
    ):
        _require(SITE / relative)

    catalog = json.loads((SITE / "plugins.json").read_text(encoding="utf-8"))
    expected_plugins = (
        "mommy-onboard",
        "mommy-research",
        "mommy-strategy",
        "market-watch-loop",
        "basket-analysis",
        "food-security-analysis",
    )
    if catalog.get("store") != "mommy-chaogu plugins store":
        raise AssertionError("plugins.json store name is incorrect")
    actual_plugins = tuple(plugin["name"] for plugin in catalog.get("plugins", []))
    if actual_plugins != expected_plugins:
        raise AssertionError(f"Plugins Store catalog drift: {actual_plugins}")

    for archive in sorted((SITE / "skills").iterdir()):
        _archive_has_skill(archive)
    for plugin in catalog["plugins"]:
        archive = plugin.get("archive")
        if archive:
            archive_path = (SITE / archive).resolve()
            if SITE not in archive_path.parents:
                raise AssertionError(f"plugin archive escapes site/: {archive}")
            _require(archive_path)
            _archive_has_skill(archive_path)
    sample = SITE / "samples" / "2026-08-19"
    for relative in ("2026-08-19.zip", "web.html", "report.md", "strategy-card.md", "data.json"):
        _require(sample / relative)
    with zipfile.ZipFile(sample / "2026-08-19.zip") as bundle:
        required = {
            "manifest.json",
            "daily-final/report.md",
            "daily-final/strategy-card.md",
            "daily-final/web.html",
            "daily-final/data.json",
        }
        missing = sorted(required - set(bundle.namelist()))
        if missing:
            raise AssertionError(f"sample archive missing: {missing}")
    _check_links()
    print("GitHub Pages assets: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
