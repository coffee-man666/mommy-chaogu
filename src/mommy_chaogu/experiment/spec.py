"""ExperimentSpec：可证伪投资实验的序列化表示。

与 workflow.spec.WorkflowSpec 分离：
- WorkflowSpec 表达「先调用什么工具，再调用什么工具」的通用编排；
- ExperimentSpec 表达「在什么标的、用什么特征、按什么规则进出场、如何验证」
  的完整投资实验语义。

第一版为 Golden Scenario Spike 服务（docs/GOLDEN-SCENARIO-SPIKE.md），
字段刻意保持最小集合，只锁定 spike 验证过确实必要的部分。

规则（entry_rule / exit_rule）采用结构化 condition + params，
不发明自由表达式 DSL：condition 必须是运行时认识的预定义类型，
保证 spec 可由另一个 Coding Agent 无歧义重放。
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Any, Literal

SPEC_VERSION = 1

Market = Literal["US", "CN"]
Frequency = Literal["1d"]

# 第一版认识的特征类型（确定性指标内核，见 indicators.py）
FEATURE_TYPES = frozenset(
    {
        "sma",
        "ema",
        "price_channel",
        "atr",
        "rsi",
        "volume_sma",
        "relative_strength",
    }
)

# 第一版认识的规则 condition（由实验运行时解释）
ENTRY_CONDITIONS = frozenset({"false_breakdown_reclaim"})
EXIT_CONDITIONS = frozenset({"composite_exit"})

_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_\-]*$")


@dataclass(frozen=True)
class DateRange:
    """实验数据区间，闭区间，YYYY-MM-DD。"""

    start: str
    end: str

    def to_dict(self) -> dict[str, Any]:
        return {"start": self.start, "end": self.end}

    @classmethod
    def from_dict(cls, raw: Any) -> DateRange:
        if not isinstance(raw, dict):
            raise ValueError("DateRange 必须是对象")
        start, end = str(raw.get("start", "")), str(raw.get("end", ""))
        if not _is_iso_date(start) or not _is_iso_date(end):
            raise ValueError("date_range.start/end 必须是 YYYY-MM-DD")
        if start >= end:
            raise ValueError("date_range.start 必须早于 end")
        return cls(start=start, end=end)


@dataclass(frozen=True)
class FeatureSpec:
    """一个确定性特征，如 20 日 SMA 或 20 日价格通道。"""

    type: str
    window: int
    params: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {"type": self.type, "window": self.window, "params": dict(self.params)}

    @classmethod
    def from_dict(cls, raw: Any) -> FeatureSpec:
        if not isinstance(raw, dict):
            raise ValueError("FeatureSpec 必须是对象")
        ftype = str(raw.get("type", ""))
        if ftype not in FEATURE_TYPES:
            raise ValueError(
                f"FeatureSpec.type 不支持: {ftype!r}（可选: {sorted(FEATURE_TYPES)}）"
            )
        window = int(raw.get("window", 0))
        if window < 1:
            raise ValueError("FeatureSpec.window 必须 >= 1")
        params = raw.get("params", {})
        if not isinstance(params, dict):
            raise ValueError("FeatureSpec.params 必须是对象")
        return cls(type=ftype, window=window, params=dict(params))


@dataclass(frozen=True)
class RuleSpec:
    """结构化进/出场规则。

    condition 为运行时认识的预定义类型；params 承载参数；
    note 为人类可读的规则解释（Agent 澄清后与用户确认的那段话）。
    """

    condition: str
    params: dict[str, Any] = field(default_factory=dict)
    note: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "condition": self.condition,
            "params": dict(self.params),
            "note": self.note,
        }

    @classmethod
    def from_dict(cls, raw: Any, *, allowed: frozenset[str], label: str) -> RuleSpec:
        if not isinstance(raw, dict):
            raise ValueError(f"{label} 必须是对象")
        condition = str(raw.get("condition", ""))
        if condition not in allowed:
            raise ValueError(
                f"{label}.condition 不支持: {condition!r}（可选: {sorted(allowed)}）"
            )
        params = raw.get("params", {})
        if not isinstance(params, dict):
            raise ValueError(f"{label}.params 必须是对象")
        return cls(
            condition=condition,
            params=dict(params),
            note=str(raw.get("note", "")),
        )


@dataclass(frozen=True)
class ValidationSpec:
    """稳健性验证配置。"""

    walk_forward: bool = True
    regime_analysis: bool = True
    benchmark: str = "SPY"

    def to_dict(self) -> dict[str, Any]:
        return {
            "walk_forward": self.walk_forward,
            "regime_analysis": self.regime_analysis,
            "benchmark": self.benchmark,
        }

    @classmethod
    def from_dict(cls, raw: Any) -> ValidationSpec:
        if raw is None:
            return cls()
        if not isinstance(raw, dict):
            raise ValueError("validation 必须是对象")
        return cls(
            walk_forward=bool(raw.get("walk_forward", True)),
            regime_analysis=bool(raw.get("regime_analysis", True)),
            benchmark=str(raw.get("benchmark", "SPY")).upper(),
        )


@dataclass(frozen=True)
class ExperimentSpec:
    """一次可复现、可审计的投资实验。

    assumptions 记录 Agent 为使观点可执行而新增的全部假设，
    必须与用户原始观点（source.text）和回测结果严格分开。
    """

    id: str
    title: str
    hypothesis: str
    market: Market
    universe: list[str]
    date_range: DateRange
    entry_rule: RuleSpec
    exit_rule: RuleSpec
    frequency: Frequency = "1d"
    features: list[FeatureSpec] = field(default_factory=list)
    data_requirements: list[str] = field(default_factory=lambda: ["adjusted_ohlcv"])
    position_sizing: dict[str, Any] = field(
        default_factory=lambda: {"type": "equal_weight"}
    )
    cost_model: str = "us_equity_default"
    validation: ValidationSpec = field(default_factory=ValidationSpec)
    source: dict[str, Any] = field(default_factory=dict)
    assumptions: list[str] = field(default_factory=list)
    spec_version: int = SPEC_VERSION

    def to_dict(self) -> dict[str, Any]:
        return {
            "spec_version": self.spec_version,
            "id": self.id,
            "title": self.title,
            "source": dict(self.source),
            "hypothesis": self.hypothesis,
            "market": self.market,
            "universe": list(self.universe),
            "frequency": self.frequency,
            "date_range": self.date_range.to_dict(),
            "data_requirements": list(self.data_requirements),
            "features": [f.to_dict() for f in self.features],
            "entry_rule": self.entry_rule.to_dict(),
            "exit_rule": self.exit_rule.to_dict(),
            "position_sizing": dict(self.position_sizing),
            "cost_model": self.cost_model,
            "validation": self.validation.to_dict(),
            "assumptions": list(self.assumptions),
        }

    def to_json(self) -> str:
        return json.dumps(self.to_dict(), ensure_ascii=False, indent=2, default=str)

    @classmethod
    def from_dict(cls, raw: Any) -> ExperimentSpec:
        if not isinstance(raw, dict):
            raise ValueError("ExperimentSpec 必须是 JSON 对象")
        required = (
            "id",
            "title",
            "hypothesis",
            "market",
            "universe",
            "date_range",
            "entry_rule",
            "exit_rule",
        )
        missing = [name for name in required if name not in raw]
        if missing:
            raise ValueError(f"ExperimentSpec 缺少字段: {', '.join(missing)}")

        spec_id = str(raw["id"])
        if not _ID_RE.match(spec_id):
            raise ValueError("ExperimentSpec.id 只允许小写字母、数字、下划线和连字符")

        market = str(raw["market"]).upper()
        if market not in ("US", "CN"):
            raise ValueError("ExperimentSpec.market 必须是 US 或 CN")

        universe = raw["universe"]
        if (
            not isinstance(universe, list)
            or not universe
            or not all(isinstance(s, str) and s.strip() for s in universe)
        ):
            raise ValueError("universe 必须是非空字符串数组")
        universe = [s.strip().upper() for s in universe]

        frequency = str(raw.get("frequency", "1d"))
        if frequency != "1d":
            raise ValueError("第一阶段只支持 frequency=1d")

        features_raw = raw.get("features", [])
        if not isinstance(features_raw, list):
            raise ValueError("features 必须是数组")

        sizing = raw.get("position_sizing", {"type": "equal_weight"})
        if not isinstance(sizing, dict) or not sizing.get("type"):
            raise ValueError("position_sizing 必须包含 type")

        assumptions = raw.get("assumptions", [])
        if not isinstance(assumptions, list) or not all(
            isinstance(a, str) for a in assumptions
        ):
            raise ValueError("assumptions 必须是字符串数组")

        source = raw.get("source", {})
        if not isinstance(source, dict):
            raise ValueError("source 必须是对象")

        return cls(
            id=spec_id,
            title=str(raw["title"]),
            hypothesis=str(raw["hypothesis"]),
            market=market,  # type: ignore[arg-type]
            universe=list(universe),
            date_range=DateRange.from_dict(raw["date_range"]),
            entry_rule=RuleSpec.from_dict(
                raw["entry_rule"], allowed=ENTRY_CONDITIONS, label="entry_rule"
            ),
            exit_rule=RuleSpec.from_dict(
                raw["exit_rule"], allowed=EXIT_CONDITIONS, label="exit_rule"
            ),
            frequency="1d",
            features=[FeatureSpec.from_dict(f) for f in features_raw],
            data_requirements=[str(d) for d in raw.get("data_requirements", ["adjusted_ohlcv"])],
            position_sizing=dict(sizing),
            cost_model=str(raw.get("cost_model", "us_equity_default")),
            validation=ValidationSpec.from_dict(raw.get("validation")),
            source=dict(source),
            assumptions=list(assumptions),
            spec_version=int(raw.get("spec_version", SPEC_VERSION)),
        )

    @classmethod
    def from_json(cls, raw: str) -> ExperimentSpec:
        try:
            return cls.from_dict(json.loads(raw))
        except json.JSONDecodeError as exc:
            raise ValueError(f"ExperimentSpec JSON 无法解析: {exc}") from exc


def _is_iso_date(value: str) -> bool:
    return bool(re.match(r"^\d{4}-\d{2}-\d{2}$", value))
