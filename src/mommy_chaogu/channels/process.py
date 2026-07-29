"""Lifecycle helpers for the detached local Weixin gateway."""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import tempfile
import time
from contextlib import suppress
from dataclasses import dataclass
from pathlib import Path

from mommy_chaogu.channels.store import WeixinStore
from mommy_chaogu.channels.weixin import WeixinApiError


@dataclass(frozen=True, slots=True)
class GatewayProcess:
    """Result of starting or inspecting the local gateway process."""

    pid: int
    started: bool
    log_path: Path


def _pid_path(store: WeixinStore) -> Path:
    return store.root / "gateway.pid"


def gateway_log_path(store: WeixinStore) -> Path:
    """Return the private log used by the detached gateway."""
    return store.root / "gateway.log"


def _read_pid(store: WeixinStore) -> int | None:
    try:
        value = int(_pid_path(store).read_text(encoding="utf-8").strip())
    except (FileNotFoundError, OSError, ValueError):
        return None
    return value if value > 0 else None


def _pid_is_running(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _unlink_pid(store: WeixinStore) -> None:
    with suppress(FileNotFoundError):
        _pid_path(store).unlink()


def gateway_process_pid(store: WeixinStore) -> int | None:
    """Return a live gateway PID and discard a stale PID file."""
    pid = _read_pid(store)
    if pid is not None and _pid_is_running(pid):
        return pid
    if pid is not None:
        _unlink_pid(store)
    return None


def _write_pid(store: WeixinStore, pid: int) -> None:
    store.root.mkdir(parents=True, exist_ok=True, mode=0o700)
    with suppress(OSError):
        os.chmod(store.root, 0o700)
    fd, temp_name = tempfile.mkstemp(prefix=".gateway.pid.", dir=store.root)
    temp_path = Path(temp_name)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            handle.write(f"{pid}\n")
        os.chmod(temp_path, 0o600)
        os.replace(temp_path, _pid_path(store))
    finally:
        with suppress(FileNotFoundError):
            temp_path.unlink()


def start_gateway_process(store: WeixinStore) -> GatewayProcess:
    """Start the Weixin gateway detached from the onboarding terminal."""
    if store.load_credentials() is None:
        raise WeixinApiError("尚未连接微信，请先完成扫码授权")

    running_pid = gateway_process_pid(store)
    log_path = gateway_log_path(store)
    if running_pid is not None:
        return GatewayProcess(pid=running_pid, started=False, log_path=log_path)

    store.root.mkdir(parents=True, exist_ok=True, mode=0o700)
    log_fd = os.open(log_path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
    with os.fdopen(log_fd, "a", encoding="utf-8") as log_file:
        process = subprocess.Popen(
            [
                sys.executable,
                "-m",
                "mommy_chaogu.channels.worker",
                "--state-dir",
                str(store.root.parent),
            ],
            stdin=subprocess.DEVNULL,
            stdout=log_file,
            stderr=subprocess.STDOUT,
            start_new_session=True,
            close_fds=True,
        )
    _write_pid(store, process.pid)

    # Catch immediate startup failures (bad local config/import errors) instead
    # of claiming that Weixin is online when the child has already exited.
    time.sleep(0.15)
    if process.poll() is not None:
        _unlink_pid(store)
        raise WeixinApiError(f"微信网关启动失败，请查看日志：{log_path}")
    return GatewayProcess(pid=process.pid, started=True, log_path=log_path)


def stop_gateway_process(store: WeixinStore) -> bool:
    """Request a graceful stop of the detached gateway."""
    pid = gateway_process_pid(store)
    if pid is None:
        return False
    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        _unlink_pid(store)
        return False
    return True


def restart_gateway_process(store: WeixinStore, *, timeout: float = 15.0) -> GatewayProcess:
    """Restart a live worker so it reloads credentials and LLM configuration."""
    if gateway_process_pid(store) is None:
        return start_gateway_process(store)
    if not stop_gateway_process(store):
        raise WeixinApiError("微信网关重启失败：无法停止旧进程")

    deadline = time.monotonic() + timeout
    while gateway_process_pid(store) is not None:
        if time.monotonic() >= deadline:
            raise WeixinApiError("微信网关重启超时，请手动执行 stop 后再 start")
        time.sleep(0.05)
    return start_gateway_process(store)


def clear_gateway_pid(store: WeixinStore, *, expected_pid: int) -> None:
    """Remove the PID file only when it still belongs to this worker."""
    if _read_pid(store) == expected_pid:
        _unlink_pid(store)


__all__ = [
    "GatewayProcess",
    "clear_gateway_pid",
    "gateway_log_path",
    "gateway_process_pid",
    "restart_gateway_process",
    "start_gateway_process",
    "stop_gateway_process",
]
