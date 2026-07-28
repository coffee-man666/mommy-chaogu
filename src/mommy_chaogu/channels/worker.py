"""Detached process entry point for the local Weixin gateway."""

from __future__ import annotations

import argparse
import os
import signal
from pathlib import Path

from mommy_chaogu.channels.process import clear_gateway_pid
from mommy_chaogu.channels.store import WeixinStore
from mommy_chaogu.channels.weixin import WeixinClient
from mommy_chaogu.cli_commands.channel import _run_gateway


def _stop_on_signal(_signum: int, _frame: object) -> None:
    """Interrupt blocking polling so its normal cleanup path can run."""
    raise KeyboardInterrupt


def main() -> None:
    parser = argparse.ArgumentParser(add_help=False)
    parser.add_argument("--state-dir", type=Path, required=True)
    args = parser.parse_args()
    store = WeixinStore(args.state_dir)
    signal.signal(signal.SIGTERM, _stop_on_signal)
    try:
        _run_gateway(store, WeixinClient(), once=False)
    except KeyboardInterrupt:
        pass
    finally:
        clear_gateway_pid(store, expected_pid=os.getpid())


if __name__ == "__main__":
    main()
