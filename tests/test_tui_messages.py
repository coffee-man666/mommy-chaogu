"""TUI 消息协议单测。

tui/messages.py 目前只有 StepStatus 在实际使用（工作流步骤进度，
由 app._post_step 发送）；tier2 #9 已清理其余未落地的消息类。
"""

from __future__ import annotations

from mommy_chaogu.tui.messages import StepStatus


class TestStepStatus:
    def test_fields_assigned(self) -> None:
        msg = StepStatus(idx=2, state="running", detail="拉取行情")
        assert msg.idx == 2
        assert msg.state == "running"
        assert msg.detail == "拉取行情"

    def test_default_detail(self) -> None:
        msg = StepStatus(idx=0, state="ok")
        assert msg.detail == ""
