"""Private local storage for Weixin channel credentials and cursors."""

from __future__ import annotations

import json
import os
import tempfile
from contextlib import suppress
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Any


def default_channel_state_dir() -> Path:
    """Resolve state outside the repository so credentials cannot be committed."""
    override = os.environ.get("MOMMY_CHANNEL_STATE_DIR", "").strip()
    if override:
        return Path(override).expanduser()
    return Path.home() / ".config" / "mommy-chaogu" / "channels"


@dataclass(frozen=True, slots=True)
class WeixinCredentials:
    account_id: str
    token: str = field(repr=False)
    base_url: str
    owner_user_id: str
    saved_at: str = field(default_factory=lambda: datetime.now(UTC).isoformat())

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> WeixinCredentials:
        names = ("account_id", "token", "base_url", "owner_user_id", "saved_at")
        fields = {name: str(raw.get(name, "")).strip() for name in names}
        required = ("account_id", "token", "base_url", "owner_user_id")
        if any(not fields[name] for name in required):
            raise ValueError("微信凭据文件缺少必要字段")
        if not fields["saved_at"]:
            fields["saved_at"] = datetime.now(UTC).isoformat()
        return cls(**fields)


@dataclass(slots=True)
class WeixinState:
    get_updates_buf: str = ""
    context_tokens: dict[str, str] = field(default_factory=dict)

    @classmethod
    def from_dict(cls, raw: dict[str, Any]) -> WeixinState:
        context_raw = raw.get("context_tokens", {})
        contexts = (
            {
                str(key): str(value)
                for key, value in context_raw.items()
                if isinstance(key, str) and isinstance(value, str) and key and value
            }
            if isinstance(context_raw, dict)
            else {}
        )
        return cls(get_updates_buf=str(raw.get("get_updates_buf", "")), context_tokens=contexts)


class WeixinStore:
    """Store one locally authorized Weixin bot account with restrictive permissions."""

    def __init__(self, root: Path | None = None) -> None:
        self.root = (root or default_channel_state_dir()) / "weixin"
        self.credentials_path = self.root / "credentials.json"
        self.state_path = self.root / "state.json"

    def load_credentials(self) -> WeixinCredentials | None:
        raw = self._read_json(self.credentials_path)
        return WeixinCredentials.from_dict(raw) if raw is not None else None

    def save_credentials(self, credentials: WeixinCredentials) -> None:
        self._write_private_json(self.credentials_path, asdict(credentials))

    def load_state(self) -> WeixinState:
        raw = self._read_json(self.state_path)
        return WeixinState.from_dict(raw) if raw is not None else WeixinState()

    def save_state(self, state: WeixinState) -> None:
        self._write_private_json(self.state_path, asdict(state))

    def clear(self) -> None:
        """Remove the local Weixin authorization and cursor state."""
        for path in (self.credentials_path, self.state_path):
            with suppress(FileNotFoundError):
                path.unlink()

    @staticmethod
    def _read_json(path: Path) -> dict[str, Any] | None:
        try:
            raw = json.loads(path.read_text(encoding="utf-8"))
        except FileNotFoundError:
            return None
        except (OSError, json.JSONDecodeError) as exc:
            raise ValueError(f"无法读取微信本地状态：{path}") from exc
        if not isinstance(raw, dict):
            raise ValueError(f"微信本地状态格式无效：{path}")
        return raw

    def _write_private_json(self, path: Path, value: object) -> None:
        self.root.mkdir(parents=True, exist_ok=True, mode=0o700)
        with suppress(OSError):
            os.chmod(self.root, 0o700)

        fd, temp_name = tempfile.mkstemp(prefix=f".{path.name}.", dir=self.root)
        temp_path = Path(temp_name)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(value, handle, ensure_ascii=False, indent=2)
                handle.write("\n")
            os.chmod(temp_path, 0o600)
            os.replace(temp_path, path)
        finally:
            with suppress(FileNotFoundError):
                temp_path.unlink()
