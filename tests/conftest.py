"""tests 根 conftest：跨目录共享的测试夹具。"""

from __future__ import annotations

import os
from collections.abc import Iterator

import pytest


@pytest.fixture(autouse=True)
def _restore_environ() -> Iterator[None]:
    """每条测试结束后恢复 os.environ 快照，保证测试间环境隔离。

    背景：``mommy_chaogu.config.load_config`` 会把 .env 里的 provider /
    model / API key 写进 ``os.environ``（CLI 运行时的设计行为）。在 pytest
    单进程里，第一个触发它的测试会把真实 key 泄漏给后续所有测试——曾导致
    ``test_no_key_agent_none_executor_usable`` 在配置过 key 的开发机上
    全量跑失败、单跑通过（顺序依赖的假象）。这里统一在每条测试后恢复。
    """
    snapshot = dict(os.environ)
    try:
        yield
    finally:
        os.environ.clear()
        os.environ.update(snapshot)
