"""阶段二·左侧→右侧纪律闭环测试：stage/confirmed_at 列与正交状态机。

覆盖（docs/plans/trading-method-landing.md §2 阶段二）：
- predictions 表加 stage / confirmed_at 列的 SQLite 迁移向后兼容
  （旧库加列、旧记录取默认、旧查询不受影响）；
- stage 与 status 正交：verify 回填 hit 不升 confirmed；
  missed / expired 且 stage 仍 candidate 时一并 retired；
- update_stage 状态机（confirmed 记 confirmed_at、依据留痕 verify_log）；
- update_prediction_stage 工具（DEFS/HANDLERS 注册 + basis 必填 + 错误形态）；
- get_prediction_history 输出 stage / confirmed_at；
- 左侧入口承接（不写专用胶水）：screen_inflow_stocks 输出 →
  extractor.store_extraction 自动抽取 → stage=candidate 落库。

全部离线：adapter 用 MagicMock / SimpleNamespace，无网络依赖。
"""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from mommy_chaogu.agent.episodic_memory import EpisodicMemory
from mommy_chaogu.agent.extractor import store_extraction
from mommy_chaogu.agent.prediction_tracker import PredictionTracker
from mommy_chaogu.agent.tools import ToolContext, ToolRegistry
from mommy_chaogu.agent.tools import analysis as analysis_tools
from mommy_chaogu.agent.verify_engine import verify_pending
from mommy_chaogu.market_data.types import Money, MoneyFlow

# 阶段二之前的旧表结构（无 stage / confirmed_at 列）——迁移测试用它建旧库。
_OLD_SCHEMA = """
CREATE TABLE predictions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    created_at TEXT NOT NULL,
    code TEXT NOT NULL,
    name TEXT,
    prediction TEXT NOT NULL,
    direction TEXT NOT NULL,
    rationale TEXT,
    target_price REAL,
    entry_price REAL,
    stop_loss REAL,
    change_pct_at_creation REAL,
    timeframe TEXT NOT NULL,
    verify_after TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',
    verified_at TEXT,
    actual_price REAL,
    actual_change_pct REAL,
    accuracy_score REAL,
    verify_attempts INTEGER DEFAULT 0,
    verify_log TEXT,
    data_coverage_at_creation TEXT,
    data_coverage_at_verify TEXT,
    source_event_id INTEGER,
    insight_event_id INTEGER,
    idempotency_key TEXT
)
"""


@pytest.fixture
def tracker(tmp_path: Path) -> PredictionTracker:
    return PredictionTracker(tmp_path / "test_predictions.db")


@pytest.fixture
def registry() -> ToolRegistry:
    """无 db 的注册表（agent_db 为 None → 工具返回配置错误形态）。"""
    return ToolRegistry(ToolContext(adapter=MagicMock()))


def _create_aged(
    tracker: PredictionTracker,
    monkeypatch: pytest.MonkeyPatch,
    *,
    days_old: float,
    **kwargs: object,
) -> int:
    """以真实 created_at/verify_after 关系创建一条 days_old 天前的预测。

    复用 test_verify_engine 的猴子补丁模式：让 create() 算出的
    verify_after 自然落在过去（已到期）。
    """
    import mommy_chaogu.agent.prediction_tracker as pt

    fake_now = datetime.now(UTC) - timedelta(days=days_old)
    with monkeypatch.context() as m:
        m.setattr(pt, "_utcnow", lambda: fake_now)
        return tracker.create(**kwargs)  # type: ignore[arg-type]


def _quote(price: str, change_pct: float = 1.0) -> SimpleNamespace:
    return SimpleNamespace(price=Decimal(price), change_pct=change_pct)


def _flow(code: str, ratio_pct: str) -> MoneyFlow:
    return MoneyFlow(
        code=code,
        name=f"股票{code}",
        timestamp=datetime(2026, 9, 30, 15),
        main_net=Money.from_yuan("100000000"),
        small_net=Money.from_yuan("0"),
        medium_net=Money.from_yuan("0"),
        large_net=Money.from_yuan("0"),
        super_large_net=Money.from_yuan("0"),
        main_net_ratio=Decimal(ratio_pct),
    )


# ---------- 迁移向后兼容 ----------


class TestStageColumnMigration:
    def test_old_rows_get_defaults_and_old_queries_keep_working(self, tmp_path: Path) -> None:
        """旧库（无 stage/confirmed_at）打开即迁移：旧记录取默认值，旧查询不受影响。"""
        db = tmp_path / "agent.db"
        conn = sqlite3.connect(db)
        conn.execute(_OLD_SCHEMA)
        conn.execute(
            """
            INSERT INTO predictions (
                created_at, code, name, prediction, direction,
                timeframe, verify_after, status, verified_at, actual_price
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                "2026-07-01T15:00:00+00:00",
                "600519",
                "贵州茅台",
                "看涨",
                "up",
                "5d",
                "2026-07-06T15:00:00+00:00",
                "hit",
                "2026-07-06T15:30:00+00:00",
                1800.0,
            ),
        )
        conn.commit()
        conn.close()

        opened = PredictionTracker(db)  # __init__ 触发加列迁移
        row = opened.get_by_id(1)
        assert row is not None
        assert row["stage"] == "candidate"  # 旧记录自动取默认
        assert row["confirmed_at"] is None
        assert row["status"] == "hit"  # 旧字段不受影响
        assert row["actual_price"] == 1800.0
        # 旧查询路径不受影响
        assert opened.get_pending(datetime.now(UTC).isoformat()) == []
        assert len(opened.all()) == 1
        assert opened.stats()["hit"] == 1

        # 迁移幂等：重开同一库不报错、值不丢
        reopened = PredictionTracker(db)
        assert reopened.get_by_id(1) is not None
        assert reopened.get_by_id(1)["stage"] == "candidate"

    def test_new_db_create_defaults_to_candidate(self, tracker: PredictionTracker) -> None:
        """新库 create 的记录 stage 默认 candidate、confirmed_at 为空。"""
        pid = tracker.create(
            code="600519",
            name="贵州茅台",
            prediction="看涨",
            direction="up",
            timeframe="1d",
        )
        row = tracker.get_by_id(pid)
        assert row is not None
        assert row["stage"] == "candidate"
        assert row["confirmed_at"] is None


# ---------- stage 与 status 正交（update_status 联动规则） ----------


class TestStageStatusOrthogonal:
    def test_missed_retires_candidate(self, tracker: PredictionTracker) -> None:
        pid = tracker.create(
            code="600519", name="x", prediction="看涨", direction="up", timeframe="1d"
        )
        tracker.update_status(pid, status="missed", actual_price=70.0)
        row = tracker.get_by_id(pid)
        assert row is not None
        assert row["status"] == "missed"
        assert row["stage"] == "retired"  # 右侧迟迟不确认则退出

    def test_expired_retires_candidate(self, tracker: PredictionTracker) -> None:
        pid = tracker.create(
            code="600519", name="x", prediction="看涨", direction="up", timeframe="1d"
        )
        tracker.update_status(pid, status="expired")
        row = tracker.get_by_id(pid)
        assert row is not None
        assert row["stage"] == "retired"

    def test_hit_keeps_candidate(self, tracker: PredictionTracker) -> None:
        """价格对了 ≠ 右侧确认：status=hit 时 stage 不自动升 confirmed。"""
        pid = tracker.create(
            code="600519", name="x", prediction="看涨", direction="up", timeframe="1d"
        )
        tracker.update_status(pid, status="hit", actual_price=90.0)
        row = tracker.get_by_id(pid)
        assert row is not None
        assert row["status"] == "hit"
        assert row["stage"] == "candidate"
        assert row["confirmed_at"] is None

    def test_unverifiable_keeps_candidate(self, tracker: PredictionTracker) -> None:
        pid = tracker.create(
            code="600519", name="x", prediction="横盘", direction="flat", timeframe="1d"
        )
        tracker.update_status(pid, status="unverifiable")
        row = tracker.get_by_id(pid)
        assert row is not None
        assert row["stage"] == "candidate"

    def test_missed_does_not_demote_confirmed(self, tracker: PredictionTracker) -> None:
        """已确认的记录 verify 回填 missed 时不被降级（stage 非 candidate 不动）。"""
        pid = tracker.create(
            code="600519", name="x", prediction="看涨", direction="up", timeframe="1d"
        )
        tracker.update_stage(pid, "confirmed", note="high_20_breakout 命中")
        tracker.update_status(pid, status="missed", actual_price=70.0)
        row = tracker.get_by_id(pid)
        assert row is not None
        assert row["status"] == "missed"
        assert row["stage"] == "confirmed"
        assert row["confirmed_at"] is not None


# ---------- update_stage 状态机 ----------


class TestUpdateStage:
    def test_confirmed_sets_confirmed_at_and_logs_basis(self, tracker: PredictionTracker) -> None:
        pid = tracker.create(
            code="600519", name="贵州茅台", prediction="看涨", direction="up", timeframe="5d"
        )
        before = datetime.now(UTC)
        row = tracker.update_stage(
            pid, "confirmed", note="high_20_breakout：收盘 105 > 20日高点 100"
        )
        assert row is not None
        assert row["stage"] == "confirmed"
        assert row["confirmed_at"] is not None
        confirmed_at = datetime.fromisoformat(row["confirmed_at"])
        assert confirmed_at >= before - timedelta(seconds=1)
        # 确认依据留痕 verify_log（不新增 schema 列）
        log = json.loads(row["verify_log"])
        assert log[-1]["stage"] == "confirmed"
        assert "high_20_breakout" in log[-1]["note"]

    def test_retired_keeps_confirmed_at_none(self, tracker: PredictionTracker) -> None:
        pid = tracker.create(
            code="600519", name="x", prediction="看涨", direction="up", timeframe="5d"
        )
        row = tracker.update_stage(pid, "retired", note="用户显式放弃")
        assert row is not None
        assert row["stage"] == "retired"
        assert row["confirmed_at"] is None

    def test_candidate_is_not_a_transition_target(self, tracker: PredictionTracker) -> None:
        pid = tracker.create(
            code="600519", name="x", prediction="看涨", direction="up", timeframe="5d"
        )
        with pytest.raises(ValueError, match="confirmed / retired"):
            tracker.update_stage(pid, "candidate")

    def test_invalid_stage_raises(self, tracker: PredictionTracker) -> None:
        pid = tracker.create(
            code="600519", name="x", prediction="看涨", direction="up", timeframe="5d"
        )
        with pytest.raises(ValueError):
            tracker.update_stage(pid, "bogus")

    def test_missing_id_returns_none(self, tracker: PredictionTracker) -> None:
        assert tracker.update_stage(9999, "confirmed", note="x") is None

    def test_without_note_no_log_entry(self, tracker: PredictionTracker) -> None:
        pid = tracker.create(
            code="600519", name="x", prediction="看涨", direction="up", timeframe="5d"
        )
        row = tracker.update_stage(pid, "retired")
        assert row is not None
        assert row["stage"] == "retired"
        assert not row["verify_log"]

    def test_basis_note_coexists_with_verify_attempts(self, tracker: PredictionTracker) -> None:
        """stage 记录与 increment_attempts 的 attempt 记录在同一致 verify_log 并存。"""
        pid = tracker.create(
            code="600519", name="x", prediction="看涨", direction="up", timeframe="5d"
        )
        tracker.increment_attempts(pid, "no data")
        tracker.update_stage(pid, "confirmed", note="price_above_ma20 命中")
        tracker.increment_attempts(pid, "no data again")
        row = tracker.get_by_id(pid)
        assert row is not None
        log = json.loads(row["verify_log"])
        assert len(log) == 3
        assert log[0]["attempt"] == 1
        assert log[1]["stage"] == "confirmed"
        assert log[2]["attempt"] == 2
        assert row["verify_attempts"] == 2


# ---------- verify_engine 联动（引擎侧永不写 confirmed） ----------


class TestVerifyEngineStageInteraction:
    def test_hit_leaves_stage_candidate(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """verify 判 hit 但右侧信号从未出现 → status=hit 且 stage 仍 candidate。"""
        tr = PredictionTracker(tmp_path / "test.db")
        pid = _create_aged(
            tr,
            monkeypatch,
            days_old=6,
            code="603662",
            name="柯力传感",
            prediction="看涨",
            direction="up",
            timeframe="5d",
            entry_price=80.0,
        )
        adapter = MagicMock()
        adapter.get_quote.return_value = MagicMock(price=84.0, change_pct=5.0)  # 窗口 +5%

        results = verify_pending(tr, None, adapter, None)
        assert results["hit"] == 1

        row = tr.get_by_id(pid)
        assert row is not None
        assert row["status"] == "hit"
        assert row["stage"] == "candidate"  # verify_engine 永不写 confirmed
        assert row["confirmed_at"] is None

    def test_missed_retires_via_verify_pending(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """verify 回填 missed 且 stage 仍 candidate → 一并 retired（自动退出归档）。"""
        tr = PredictionTracker(tmp_path / "test.db")
        pid = _create_aged(
            tr,
            monkeypatch,
            days_old=6,
            code="603662",
            name="柯力传感",
            prediction="看涨",
            direction="up",
            timeframe="5d",
            entry_price=80.0,
        )
        adapter = MagicMock()
        adapter.get_quote.return_value = MagicMock(price=70.0, change_pct=-12.5)  # 窗口 -12.5%

        results = verify_pending(tr, None, adapter, None)
        assert results["missed"] == 1

        row = tr.get_by_id(pid)
        assert row is not None
        assert row["status"] == "missed"
        assert row["stage"] == "retired"


# ---------- agent 工具 ----------


class TestUpdatePredictionStageTool:
    def test_registered_in_registry(self) -> None:
        assert "update_prediction_stage" in ToolRegistry.tool_names()

    def test_definition_shape(self, registry: ToolRegistry) -> None:
        defs = {d["function"]["name"]: d for d in registry.definitions()}
        assert "update_prediction_stage" in defs
        fn = defs["update_prediction_stage"]["function"]
        assert fn["parameters"]["required"] == ["prediction_id", "stage", "basis"]
        assert set(fn["parameters"]["properties"]["stage"]["enum"]) == {"confirmed", "retired"}

    def test_confirm_via_tool(self, tmp_path: Path) -> None:
        db = tmp_path / "agent.db"
        tr = PredictionTracker(db)
        pid = tr.create(
            code="600519", name="贵州茅台", prediction="看涨", direction="up", timeframe="5d"
        )
        ctx = ToolContext(adapter=MagicMock(), db_path=db)
        reg = ToolRegistry(ctx)

        result = json.loads(
            reg.call(
                "update_prediction_stage",
                {
                    "prediction_id": pid,
                    "stage": "confirmed",
                    "basis": "high_20_breakout 命中：收盘 105 > 20日高点 100",
                },
            )
        )
        assert "error" not in result
        assert result["id"] == pid
        assert result["stage"] == "confirmed"
        assert result["status"] == "pending"  # stage 变更不动 status
        assert result["confirmed_at"]

        row = tr.get_by_id(pid)
        assert row is not None
        assert row["stage"] == "confirmed"
        assert "high_20_breakout" in json.loads(row["verify_log"])[-1]["note"]

    def test_retire_via_tool(self, tmp_path: Path) -> None:
        db = tmp_path / "agent.db"
        PredictionTracker(db).create(
            code="600519", name="x", prediction="看涨", direction="up", timeframe="5d"
        )
        ctx = ToolContext(adapter=MagicMock(), db_path=db)
        result = json.loads(
            ToolRegistry(ctx).call(
                "update_prediction_stage",
                {"prediction_id": 1, "stage": "retired", "basis": "用户放弃"},
            )
        )
        assert result["stage"] == "retired"

    def test_missing_basis_returns_error(self, tmp_path: Path) -> None:
        db = tmp_path / "agent.db"
        PredictionTracker(db).create(
            code="600519", name="x", prediction="看涨", direction="up", timeframe="5d"
        )
        ctx = ToolContext(adapter=MagicMock(), db_path=db)
        result = json.loads(
            ToolRegistry(ctx).call(
                "update_prediction_stage", {"prediction_id": 1, "stage": "confirmed", "basis": ""}
            )
        )
        assert "error" in result
        assert "basis" in result["error"]

    def test_unknown_id_returns_error(self, tmp_path: Path) -> None:
        ctx = ToolContext(adapter=MagicMock(), db_path=tmp_path / "agent.db")
        result = json.loads(
            ToolRegistry(ctx).call(
                "update_prediction_stage",
                {"prediction_id": 999, "stage": "confirmed", "basis": "x"},
            )
        )
        assert "error" in result

    def test_invalid_stage_returns_error(self, tmp_path: Path) -> None:
        db = tmp_path / "agent.db"
        PredictionTracker(db).create(
            code="600519", name="x", prediction="看涨", direction="up", timeframe="5d"
        )
        ctx = ToolContext(adapter=MagicMock(), db_path=db)
        result = json.loads(
            ToolRegistry(ctx).call(
                "update_prediction_stage",
                {"prediction_id": 1, "stage": "candidate", "basis": "x"},
            )
        )
        assert "error" in result

    def test_no_db_returns_error(self, registry: ToolRegistry) -> None:
        result = json.loads(
            registry.call(
                "update_prediction_stage",
                {"prediction_id": 1, "stage": "confirmed", "basis": "x"},
            )
        )
        assert "error" in result


class TestGetPredictionHistoryStageOutput:
    def test_output_includes_stage_and_confirmed_at(self, tmp_path: Path) -> None:
        db = tmp_path / "agent.db"
        tr = PredictionTracker(db)
        confirmed_id = tr.create(
            code="600519", name="贵州茅台", prediction="看涨", direction="up", timeframe="5d"
        )
        tr.create(
            code="000001", name="平安银行", prediction="看跌", direction="down", timeframe="5d"
        )
        tr.update_stage(confirmed_id, "confirmed", note="右侧确认")

        ctx = ToolContext(adapter=MagicMock(), db_path=db)
        data = json.loads(ToolRegistry(ctx).call("get_prediction_history", {}))
        assert len(data) == 2
        by_code = {item["code"]: item for item in data}
        assert by_code["600519"]["stage"] == "confirmed"
        assert by_code["600519"]["confirmed_at"]
        assert by_code["000001"]["stage"] == "candidate"
        assert by_code["000001"]["confirmed_at"] is None


# ---------- 左侧入口承接（screen → extractor → candidate，零专用胶水） ----------


class TestLeftSideChainThroughExtractor:
    def test_screen_output_flows_to_candidate_prediction(self, tmp_path: Path) -> None:
        """screen_inflow_stocks 输出经对话抽取自动承接为 candidate 预测。

        链路（阶段二任务 2，v1.3 明确不写专用胶水）：
        screen 输出进入对话上下文 → extractor.store_extraction 创建预测
        （rationale 承接资金依据、entry_price 自动填）→ stage 走 schema
        默认 candidate。
        """
        adapter = MagicMock()
        adapter.get_today_money_flow.side_effect = lambda code: [
            _flow(code, "2.5" if code == "600000" else "0.4")
        ]
        adapter.get_quote.return_value = _quote("12.34", change_pct=1.5)

        # 左侧筛选：600000 占比 2.5%（250bp）过阈值，000001 40bp 被滤掉
        screen = json.loads(
            analysis_tools._handle_screen_inflow_stocks(
                ToolContext(adapter=adapter),
                {"codes": ["000001", "600000"], "threshold_bp": 50},
            )
        )
        assert screen["count"] == 1
        top = screen["results"][0]
        assert top["code"] == "600000"

        # agent 回复进入对话上下文后，extractor 自动抽取（资金依据成为理由）
        extraction = {
            "observations": [],
            "predictions": [
                {
                    "code": "600000",
                    "name": top["name"],
                    "prediction": "主力净流入占比居池内首位，短期看涨",
                    "direction": "up",
                    "timeframe": "5d",
                    "rationale": (
                        f"screen_inflow_stocks 左侧候选：主力净流入占比 "
                        f"{top['main_net_ratio']}%（{top['ratio_bp']}bp）居池内首位"
                    ),
                }
            ],
        }
        episodic = EpisodicMemory(tmp_path / "agent.db")
        tr = PredictionTracker(tmp_path / "agent.db")
        created = store_extraction(extraction, episodic, tr, adapter)
        assert len(created) == 1

        row = tr.get_by_id(created[0]["id"])
        assert row is not None
        assert row["code"] == "600000"
        assert row["stage"] == "candidate"  # 左侧入口默认候选（schema 默认）
        assert row["status"] == "pending"
        assert row["entry_price"] == Decimal("12.34")  # extractor 自动填 entry_price
        assert "2.5" in (row["rationale"] or "")  # 资金依据承接进理由
