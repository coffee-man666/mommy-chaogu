"""Human-readable Strategy Card contract.

The card deliberately describes a user's method.  It is not an execution DSL:
the host Agent interprets the method, while the backend validates provenance,
capability labels and the small set of monitor rules the application really
supports today.
"""

from __future__ import annotations

import math
import re
from decimal import Decimal
from enum import StrEnum
from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_CONDITION_ID_RE = re.compile(r"^[a-z0-9][a-z0-9_-]{0,63}$")
_MAX_CARD_BYTES = 5000


class SourceType(StrEnum):
    TEXT = "text"
    FILE = "file"
    URL = "url"
    CONVERSATION = "conversation"
    OTHER = "other"


class SourceHashScope(StrEnum):
    FULL_SOURCE = "full_source"
    SUPPLIED_EXCERPT = "supplied_excerpt"


class AutomationStatus(StrEnum):
    SUPPORTED = "supported"
    MANUAL = "manual"
    UNAVAILABLE = "unavailable"


class ConditionCategory(StrEnum):
    OBSERVATION = "observation"
    ENTRY = "entry"
    EXIT = "exit"
    RISK = "risk"
    CONTEXT = "context"
    INVALIDATION = "invalidation"


class MonitorCondition(StrEnum):
    PRICE_ABOVE = "price_above"
    PRICE_BELOW = "price_below"
    CHANGE_PCT_ABOVE = "change_pct_above"
    CHANGE_PCT_BELOW = "change_pct_below"


class _CardModel(BaseModel):
    model_config = ConfigDict(extra="forbid", str_strip_whitespace=True)


class StrategySource(_CardModel):
    """Where the method came from, without silently claiming more provenance."""

    type: SourceType
    title: str = Field(min_length=1, max_length=200)
    reference: str = Field(
        min_length=1,
        max_length=2000,
        description="URL, file path, report citation, or a plain description of the supplied text",
    )
    content_hash: str | None = Field(
        default=None,
        description="SHA-256 only when the host actually hashed the full source or supplied excerpt",
    )
    hash_scope: SourceHashScope | None = None
    excerpts: list[str] = Field(min_length=1, max_length=5)

    @field_validator("content_hash")
    @classmethod
    def _valid_hash(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = value.lower()
        if not _SHA256_RE.fullmatch(normalized):
            raise ValueError("content_hash 必须是 64 位 SHA-256 十六进制字符串")
        return normalized

    @field_validator("excerpts")
    @classmethod
    def _valid_excerpts(cls, values: list[str]) -> list[str]:
        cleaned = [item.strip() for item in values if item.strip()]
        if len(cleaned) != len(values):
            raise ValueError("来源摘录不能为空")
        if any(len(item) > 1000 for item in cleaned):
            raise ValueError("单条来源摘录不能超过 1000 个字符")
        return cleaned

    @model_validator(mode="after")
    def _hash_scope_matches(self) -> Self:
        if (self.content_hash is None) != (self.hash_scope is None):
            raise ValueError("content_hash 与 hash_scope 必须同时提供；无法确认时两者都省略")
        return self


class MonitorRule(_CardModel):
    """A monitor expression already supported by the existing alert system."""

    condition: MonitorCondition
    threshold: Decimal

    @field_validator("threshold")
    @classmethod
    def _finite_threshold(cls, value: Decimal) -> Decimal:
        if not math.isfinite(float(value)):
            raise ValueError("监控阈值必须是有限数字")
        return value


class StrategyCondition(_CardModel):
    id: str = Field(min_length=1, max_length=64)
    category: ConditionCategory
    statement: str = Field(min_length=1, max_length=1000)
    automation: AutomationStatus
    reason: str = Field(
        min_length=1,
        max_length=1000,
        description="Why this condition is supported, manual, or unavailable today",
    )
    evidence_tools: list[str] = Field(default_factory=list, max_length=12)
    monitor_rule: MonitorRule | None = None

    @field_validator("id")
    @classmethod
    def _valid_id(cls, value: str) -> str:
        if not _CONDITION_ID_RE.fullmatch(value):
            raise ValueError("条件 id 只允许小写字母、数字、下划线和连字符")
        return value

    @field_validator("evidence_tools")
    @classmethod
    def _unique_tools(cls, values: list[str]) -> list[str]:
        cleaned = [item.strip() for item in values if item.strip()]
        if len(cleaned) != len(values):
            raise ValueError("evidence_tools 不能包含空值")
        if len(set(cleaned)) != len(cleaned):
            raise ValueError("evidence_tools 不能重复")
        return cleaned

    @model_validator(mode="after")
    def _monitor_is_truthful(self) -> Self:
        if self.automation == AutomationStatus.SUPPORTED and not self.evidence_tools:
            raise ValueError("supported 条件必须说明当前使用哪个 evidence tool 检查")
        if self.monitor_rule is not None and self.automation != AutomationStatus.SUPPORTED:
            raise ValueError("只有 supported 条件可以包含 monitor_rule")
        return self


class StrategyCard(_CardModel):
    """The versioned, user-approved document saved by the application."""

    schema_version: Literal[1] = 1
    title: str = Field(min_length=1, max_length=200)
    source: StrategySource
    original_intent: str = Field(min_length=1, max_length=2000)
    summary: str = Field(min_length=1, max_length=4000)
    applies_to: list[str] = Field(min_length=1, max_length=20)
    conditions: list[StrategyCondition] = Field(min_length=1, max_length=30)
    assumptions: list[str] = Field(default_factory=list, max_length=20)
    limitations: list[str] = Field(default_factory=list, max_length=20)
    user_revisions: list[str] = Field(default_factory=list, max_length=30)

    @field_validator("applies_to", "assumptions", "limitations", "user_revisions")
    @classmethod
    def _clean_text_lists(cls, values: list[str]) -> list[str]:
        cleaned = [item.strip() for item in values if item.strip()]
        if len(cleaned) != len(values):
            raise ValueError("策略卡列表字段不能包含空值")
        return cleaned

    @model_validator(mode="after")
    def _unique_condition_ids(self) -> Self:
        ids = [item.id for item in self.conditions]
        if len(ids) != len(set(ids)):
            raise ValueError("策略条件 id 必须唯一")
        if len(self.model_dump_json().encode("utf-8")) > _MAX_CARD_BYTES:
            raise ValueError("策略卡过长；请保留决策相关内容，或把不同方法拆成多张卡")
        return self

    def condition(self, condition_id: str) -> StrategyCondition | None:
        return next((item for item in self.conditions if item.id == condition_id), None)
