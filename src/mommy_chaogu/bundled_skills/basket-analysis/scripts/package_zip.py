#!/usr/bin/env python3
"""Package basket-analysis (any theme) into a per-day ZIP archive.

Per the output_format spec:
  deliverables/{theme.name_en}/{YYYY-MM-DD}.zip
    manifest.json
    daily-final/                  (canonical final version, latest run or --final)
    runs/{run_ts}/                 (all runs of the day, by timestamp)
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import sys
import zipfile
from datetime import datetime, timezone, timedelta
from pathlib import Path
from typing import Any

BJ = timezone(timedelta(hours=8))


def now_bj() -> datetime:
    return datetime.now(BJ)


def fmt_bj_iso(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%dT%H:%M:%S%z")[:-2] + ":" + dt.strftime("%z")[-2:]


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def find_runs_for_day(day_dir: Path) -> list[Path]:
    """Find all run directories under day_dir, sorted by name (timestamp)."""
    if not day_dir.exists():
        return []
    runs = [p for p in day_dir.iterdir() if p.is_dir() and re.match(r"^\d{8}-\d{6}$", p.name)]
    return sorted(runs, key=lambda p: p.name)


def build_manifest(run_dir: Path, day_dir: Path, all_runs: list[Path], is_final: bool, session_id: str = "n/a") -> dict[str, Any]:
    files = []
    for f in ["report.md", "report.html", "report.pdf", "strategy-card.md", "strategy-card.html", "strategy-card.pdf", "web.html", "text.md", "data.json"]:
        p = run_dir / f
        if p.exists():
            files.append({
                "path": f"daily-final/{f}",
                "type": f.split(".")[0],
                "size_bytes": p.stat().st_size,
                "sha256": sha256_file(p),
            })
    runs_meta = []
    for r in all_runs:
        runs_meta.append({
            "ts": r.name,
            "is_final": (r == run_dir),
        })
    # v1.2 fix: read is_market_close + data_as_of from data.json (was hardcoded)
    data_json_path = run_dir / "data.json"
    is_market_close = True
    data_as_of = f"{day_dir.name} close (Beijing time, A股收盘)"
    theme_name = "粮食安全/危机"
    theme_name_en = "food-security"
    if data_json_path.exists():
        try:
            with open(data_json_path, "r", encoding="utf-8") as fj:
                d = json.load(fj)
            is_market_close = d.get("is_market_close", True)
            data_as_of = d.get("data_as_of", data_as_of)
            theme_meta = d.get("theme") or {}
            theme_name = theme_meta.get("name", theme_name)
            theme_name_en = theme_meta.get("name_en", theme_name_en)
        except Exception:
            pass
    return {
        "skill": "basket-analysis",
        "theme": {"name": theme_name, "name_en": theme_name_en},
        "session_id": session_id,
        "skill_version": "1.2",
        "generated_at": fmt_bj_iso(now_bj()),
        "trading_day": day_dir.name,
        "is_market_close": is_market_close,
        "data_as_of": data_as_of,
        "is_final": is_final,
        "basket_coverage": {
            "total": 35,
            "money_flow_pulled": 0,
            "kline_pulled_top5": 0,
        },
        "files": files,
        "runs_in_zip": runs_meta,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Package food-security analysis into per-day ZIP")
    parser.add_argument("--run-dir", required=True, help="Path to this run's output directory")
    parser.add_argument("--final", help="Force mark this run directory (within the same day) as final, by name")
    parser.add_argument("--session", default="n/a", help="Mavis session id")
    args = parser.parse_args()

    run_dir = Path(args.run_dir).resolve()
    if not run_dir.exists():
        print(f"  ❌ run dir not found: {run_dir}", file=sys.stderr)
        return 1

    # run_dir is deliverables/food-security/{YYYY-MM-DD}/{run_ts}
    day_dir = run_dir.parent
    if not re.match(r"^\d{4}-\d{2}-\d{2}$", day_dir.name):
        print(f"  ❌ run dir must be under deliverables/food-security/{{YYYY-MM-DD}}/, got: {day_dir}", file=sys.stderr)
        return 1

    all_runs = find_runs_for_day(day_dir)
    if run_dir not in all_runs:
        print(f"  ⚠️ run_dir {run_dir.name} not in known runs {all_runs}, appending")
        all_runs.append(run_dir)
        all_runs = sorted(all_runs, key=lambda p: p.name)

    # Determine the "final" run
    if args.final:
        target = day_dir / args.final
        if not target.exists():
            print(f"  ❌ --final run not found: {target}", file=sys.stderr)
            return 1
        final_run = target
    else:
        final_run = all_runs[-1]  # latest by name (timestamp)

    is_final = (final_run == run_dir)

    # Build manifest
    manifest = build_manifest(run_dir, day_dir, all_runs, is_final, session_id=args.session)

    # Update basket_coverage from data.json if available
    data_path = run_dir / "data.json"
    if data_path.exists():
        try:
            with open(data_path, "r", encoding="utf-8") as f:
                run_data = json.load(f)
            bf = run_data.get("basket_flow", {})
            t5 = run_data.get("top5_tech", {})
            theme_meta = run_data.get("theme") or {}
            total = (theme_meta.get("basket") or {}).get("size") or 35
            manifest["basket_coverage"] = {
                "total": total,
                "money_flow_pulled": len([v for v in bf.values() if v.get("main_net") is not None]),
                "kline_pulled_top5": len(t5),
            }
        except Exception as e:
            print(f"  ⚠️ could not parse data.json for coverage: {e}")

    # Create ZIP
    zip_path = day_dir.with_suffix(".zip")
    print(f"  📦 Creating ZIP: {zip_path}")
    if zip_path.exists():
        zip_path.unlink()

    with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_DEFLATED) as zf:
        # 1. manifest.json
        zf.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=2))
        print(f"    + manifest.json")

        # 2. daily-final/ from final_run
        for f in ["report.md", "report.html", "report.pdf", "strategy-card.md", "strategy-card.html", "strategy-card.pdf", "web.html", "text.md", "data.json"]:
            src = final_run / f
            if src.exists():
                zf.write(src, arcname=f"daily-final/{f}")
                print(f"    + daily-final/{f} ({src.stat().st_size} bytes)")

        # 3. runs/{run_ts}/
        for r in all_runs:
            for f in ["report.md", "report.html", "report.pdf", "strategy-card.md", "strategy-card.html", "strategy-card.pdf", "web.html", "text.md", "data.json"]:
                src = r / f
                if src.exists():
                    arc = f"runs/{r.name}/{f}"
                    if r == final_run:
                        # Skip — already in daily-final/, but keep in runs/ for archive
                        pass
                    zf.write(src, arcname=arc)
            print(f"    + runs/{r.name}/")

    print(f"  ✅ ZIP: {zip_path} ({zip_path.stat().st_size} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
