"""Agent-first 投研实验室：实验（Experiment）领域层。

独立于 workflow 的通用编排语义，专门表达「一个可证伪的投资研究实验」：
universe / features / entry / exit / sizing / costs / validation。

参见 docs/AGENT-FIRST-RESEARCH-LAB-RFC.md 与 docs/GOLDEN-SCENARIO-SPIKE.md。
"""

from mommy_chaogu.experiment.spec import (
    SPEC_VERSION,
    DateRange,
    ExperimentSpec,
    FeatureSpec,
    RuleSpec,
    ValidationSpec,
)

__all__ = [
    "SPEC_VERSION",
    "DateRange",
    "ExperimentSpec",
    "FeatureSpec",
    "RuleSpec",
    "ValidationSpec",
]
