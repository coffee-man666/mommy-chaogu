from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from mommy_chaogu.channels import process as gateway_process
from mommy_chaogu.channels.store import WeixinCredentials, WeixinStore


def _authorized_store(tmp_path: Path) -> WeixinStore:
    store = WeixinStore(tmp_path)
    store.save_credentials(
        WeixinCredentials(
            account_id="bot@im.bot",
            token="secret",
            base_url="https://ilink.example",
            owner_user_id="owner",
        )
    )
    return store


def test_start_gateway_process_detaches_and_records_pid(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = _authorized_store(tmp_path)
    child = MagicMock(pid=2468)
    child.poll.return_value = None
    popen = MagicMock(return_value=child)
    monkeypatch.setattr(gateway_process.subprocess, "Popen", popen)
    monkeypatch.setattr(gateway_process.time, "sleep", lambda _seconds: None)

    result = gateway_process.start_gateway_process(store)

    assert result.started is True
    assert result.pid == 2468
    assert (store.root / "gateway.pid").read_text(encoding="utf-8") == "2468\n"
    command = popen.call_args.args[0]
    assert command[1:3] == ["-m", "mommy_chaogu.channels.worker"]


def test_start_gateway_process_does_not_duplicate_live_worker(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = _authorized_store(tmp_path)
    (store.root / "gateway.pid").write_text("2468\n", encoding="utf-8")
    monkeypatch.setattr(gateway_process, "_pid_is_running", lambda _pid: True)
    popen = MagicMock()
    monkeypatch.setattr(gateway_process.subprocess, "Popen", popen)

    result = gateway_process.start_gateway_process(store)

    assert result == gateway_process.GatewayProcess(
        pid=2468,
        started=False,
        log_path=store.root / "gateway.log",
    )
    popen.assert_not_called()


def test_restart_gateway_process_waits_for_old_worker_and_starts_new_one(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = _authorized_store(tmp_path)
    restarted = gateway_process.GatewayProcess(
        pid=9753,
        started=True,
        log_path=store.root / "gateway.log",
    )
    pid = MagicMock(side_effect=[2468, None])
    stop = MagicMock(return_value=True)
    start = MagicMock(return_value=restarted)
    monkeypatch.setattr(gateway_process, "gateway_process_pid", pid)
    monkeypatch.setattr(gateway_process, "stop_gateway_process", stop)
    monkeypatch.setattr(gateway_process, "start_gateway_process", start)

    result = gateway_process.restart_gateway_process(store)

    assert result == restarted
    stop.assert_called_once_with(store)
    start.assert_called_once_with(store)


def test_gateway_process_pid_clears_stale_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store = _authorized_store(tmp_path)
    pid_path = store.root / "gateway.pid"
    pid_path.write_text("2468\n", encoding="utf-8")
    monkeypatch.setattr(gateway_process, "_pid_is_running", lambda _pid: False)

    assert gateway_process.gateway_process_pid(store) is None
    assert not pid_path.exists()
