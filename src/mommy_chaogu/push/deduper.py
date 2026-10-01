"""去重器：JSON 文件实现。

按 (code, rule_id, date) 去重——一码一规一天最多推一次。
每天新的一天会自动清空（不加载昨天的 key）——含常驻进程场景：
should_push / mark_pushed 首次发现跨天时自动翻转日期并重新加载当天 key
（此前 _today 冻结在构造时刻，常驻 web 跨天后昨天推过的 key 被永久抑制）。

存到 data/pushed.json。文件格式：
{
  "date": "2026-06-27",
  "pushed_keys": ["600519|main_flow_threshold|2026-06-27", ...]
}
"""

from __future__ import annotations

import json
import logging
from datetime import UTC, date, datetime
from pathlib import Path

from mommy_chaogu.signals.types import Signal

_log = logging.getLogger(__name__)


class JsonFileDeduper:
    """JSON 文件去重器（按日清空）。"""

    def __init__(self, db_path: Path) -> None:
        self.db_path = db_path
        self._today = date.today().isoformat()
        self._pushed: set[str] = set()
        self._load()

    def _key(self, signal: Signal) -> str:
        return f"{signal.code}|{signal.rule_id}|{self._today}"

    def _ensure_current_day(self) -> None:
        """跨天翻转（常驻进程必需）。

        ``_today`` 若冻结在构造时刻，常驻 web / monitor 跨天后，
        昨天推过的 code+rule 会生成同一条旧 key 而被永久抑制，
        直到进程重启。翻转时重新加载文件，顺带拾取同日其它进程
        （如 cron snapshot 与常驻 web 共用同一 pushed.json）写入的 key。
        """
        today = date.today().isoformat()
        if today != self._today:
            self._today = today
            self._load()

    def should_push(self, signal: Signal) -> bool:
        self._ensure_current_day()
        return self._key(signal) not in self._pushed

    def mark_pushed(self, signal: Signal) -> None:
        self._ensure_current_day()
        key = self._key(signal)
        self._pushed.add(key)
        self._save()

    def _load(self) -> None:
        if not self.db_path.exists():
            return
        try:
            raw = self.db_path.read_text(encoding="utf-8")
            if not raw.strip():
                return
            data = json.loads(raw)
            # 只加载当天的 key（昨天的就丢了）
            keys = data.get("pushed_keys", [])
            self._pushed = {k for k in keys if k.endswith(f"|{self._today}")}
            _log.debug("去重器加载 %d 条当日记录", len(self._pushed))
        except (json.JSONDecodeError, OSError) as e:
            _log.warning("去重器加载失败: %s", e)
            self._pushed = set()

    def _save(self) -> None:
        try:
            self.db_path.parent.mkdir(parents=True, exist_ok=True)
            payload = {
                "date": self._today,
                "updated_at": datetime.now(UTC).isoformat(),
                "pushed_keys": sorted(self._pushed),
            }
            tmp = self.db_path.with_suffix(".tmp")
            tmp.write_text(
                json.dumps(payload, ensure_ascii=False, indent=2),
                encoding="utf-8",
            )
            tmp.replace(self.db_path)
        except OSError as e:
            _log.warning("去重器保存失败: %s", e)

    def count(self) -> int:
        return len(self._pushed)

    def clear(self) -> None:
        """清空（主要用于测试）。"""
        self._pushed.clear()
        if self.db_path.exists():
            self.db_path.unlink()
