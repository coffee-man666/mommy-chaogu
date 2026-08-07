"""MCP-facing deterministic research workflows.

The built-in AgentService owns its own LLM loop.  External coding agents already
have a model, so these tools deliberately do *not* call another LLM.  They
orchestrate the existing primitive tools and return a structured evidence pack
for the external agent to interpret.
"""

from __future__ import annotations

import hashlib
import json
import logging
import math
import re
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation
from typing import Any, Literal

from mommy_chaogu.agent.tools import ToolContext, ToolRegistry
from mommy_chaogu.agent.tools.base import ToolDef, _json

_log = logging.getLogger(__name__)

McpProfile = Literal["market-only", "personal"]
DEFAULT_MCP_PROFILE: McpProfile = "personal"

MARKET_ONLY_BASE_TOOLS: frozenset[str] = frozenset(
    {
        "get_quote",
        "get_quotes",
        "get_market_indexes",
        "get_sector_ranking",
        "search_sector",
        "get_sector_stocks",
        "get_money_flow_today",
        "get_money_flow_history",
        "get_bars",
        "search_news",
        "get_announcements",
        "get_longhuban",
        "get_fundamentals",
        "list_themes",
        "get_theme_stocks",
    }
)

WRITE_TOOL_NAMES: frozenset[str] = frozenset(
    {"backfill_history", "manage_watchlist", "manage_alert", "record_research_conclusion"}
)

_CODE_RE = re.compile(r"^(\^[A-Z]{1,6}|[A-Z]{1,6}|\d{6})$")


RESEARCH_TOOL_DEFS: tuple[ToolDef, ...] = (
    ToolDef(
        name="research_market_brief",
        description=(
            "获取确定性的 A 股市场概览证据包（大盘指数 + 板块排行），不调用内部 LLM。"
            "请基于 evidence 自行归纳结论，并明确区分事实与推断。"
        ),
        parameters={
            "type": "object",
            "properties": {
                "sector_limit": {
                    "type": "integer",
                    "description": "板块排行数量，默认 10，最大 30",
                    "default": 10,
                    "minimum": 1,
                    "maximum": 30,
                },
                "research_session_id": {"type": "string", "description": "重试同一研究时复用"},
            },
        },
    ),
    ToolDef(
        name="research_us_market",
        description=(
            "获取确定性的美股市场概览证据包（标普500/纳指综合/道指 + VIX + 10 年期美债利率），"
            "不调用内部 LLM。请基于 evidence 自行归纳结论，并明确区分事实与推断。"
        ),
        parameters={
            "type": "object",
            "properties": {"research_session_id": {"type": "string"}},
        },
    ),
    ToolDef(
        name="research_stock",
        description=(
            "获取单只 A 股的结构化研究证据包：报价、日 K、当日及历史资金流、基本面；"
            "personal 模式还会附带相关历史记忆。不调用内部 LLM。"
        ),
        parameters={
            "type": "object",
            "properties": {
                "code": {
                    "type": "string",
                    "pattern": "^([A-Z]{1,6}|\\d{6})$",
                    "description": "股票代码（A 股 6 位数字或美股字母）",
                },
                "days": {
                    "type": "integer",
                    "description": "K 线和资金流回看天数，默认 20，最大 60",
                    "default": 20,
                    "minimum": 5,
                    "maximum": 60,
                },
                "research_session_id": {"type": "string", "description": "重试同一研究时复用"},
            },
            "required": ["code"],
        },
    ),
    ToolDef(
        name="research_sector",
        description=(
            "按关键词搜索板块并返回板块排行和成分股证据包，不调用内部 LLM。"
            "适合回答某个行业或概念板块的表现。"
        ),
        parameters={
            "type": "object",
            "properties": {
                "keyword": {"type": "string", "description": "板块关键词，如半导体"},
                "limit": {
                    "type": "integer",
                    "description": "成分股数量，默认 10，最大 30",
                    "default": 10,
                    "minimum": 1,
                    "maximum": 30,
                },
                "research_session_id": {"type": "string", "description": "重试同一研究时复用"},
            },
            "required": ["keyword"],
        },
    ),
    ToolDef(
        name="research_money_flow",
        description=(
            "获取单只 A 股当日和历史主力资金流证据包，不调用内部 LLM。"
            "分析时优先使用相对流通市值的 bp 强度，不要只看绝对金额。"
        ),
        parameters={
            "type": "object",
            "properties": {
                "code": {
                    "type": "string",
                    "pattern": "^([A-Z]{1,6}|\\d{6})$",
                    "description": "股票代码（A 股 6 位数字或美股字母）",
                },
                "days": {
                    "type": "integer",
                    "description": "历史资金流天数，默认 10，最大 60",
                    "default": 10,
                    "minimum": 1,
                    "maximum": 60,
                },
                "research_session_id": {"type": "string", "description": "重试同一研究时复用"},
            },
            "required": ["code"],
        },
    ),
    ToolDef(
        name="research_portfolio",
        description=(
            "PERSONAL 数据：获取本地持仓、实时报价、组合风险和相关历史记忆。"
            "仅 personal profile 发布；结果会进入当前模型上下文。"
        ),
        parameters={"type": "object", "properties": {}},
    ),
    ToolDef(
        name="record_research_conclusion",
        description=(
            "PERSONAL 写操作：把外部 Agent 的研究结论写入本地记忆，可同时登记待验证预测。"
            "必须先获得用户明确同意再调用；仅 personal profile 发布。"
        ),
        parameters={
            "type": "object",
            "properties": {
                "summary": {"type": "string", "description": "要保存的结论"},
                "scope": {
                    "type": "string",
                    "enum": ["market", "sector", "stock", "portfolio"],
                    "description": "结论范围",
                },
                "code": {
                    "type": "string",
                    "pattern": "^([A-Z]{1,6}|\\d{6})$",
                    "description": "股票代码（A 股 6 位数字或美股字母）",
                },
                "name": {"type": "string", "description": "股票或板块名称"},
                "confidence": {
                    "type": "number",
                    "minimum": 0,
                    "maximum": 1,
                    "default": 0.5,
                    "description": "置信度 0-1",
                },
                "prediction": {"type": "string", "description": "可选预测文本"},
                "direction": {
                    "type": "string",
                    "enum": ["up", "down", "neutral"],
                    "description": "预测方向",
                },
                "timeframe": {
                    "type": "string",
                    "enum": ["1d", "3d", "5d", "10d", "20d", "60d"],
                    "description": "预测验证周期",
                },
                "rationale": {"type": "string", "description": "预测依据"},
                "target_price": {"type": "number", "description": "可选目标价"},
                "entry_price": {"type": "number", "description": "可选记录时价格"},
                "stop_loss": {"type": "number", "description": "可选止损参考价"},
                "research_session_id": {
                    "type": "string",
                    "description": "研究工具返回的 session id",
                },
                "idempotency_key": {"type": "string", "description": "重试写回时保持不变"},
                "analysis_type": {"type": "string", "description": "分析类型"},
                "evidence_as_of": {"type": "string", "description": "证据截止时间"},
                "data_coverage": {"type": "object", "description": "证据覆盖情况"},
                "save_conclusion": {"type": "boolean", "default": True},
            },
            "required": ["summary", "scope"],
        },
    ),
)

_RESEARCH_DEF_MAP = {tool.name: tool for tool in RESEARCH_TOOL_DEFS}
_MARKET_RESEARCH_NAMES = frozenset(
    {
        "research_market_brief",
        "research_us_market",
        "research_stock",
        "research_sector",
        "research_money_flow",
    }
)


def normalize_mcp_profile(value: str | None) -> McpProfile:
    """Validate and normalize an MCP privacy profile."""
    normalized = (value or DEFAULT_MCP_PROFILE).strip().lower()
    if normalized not in {"market-only", "personal"}:
        raise ValueError("MCP profile 必须是 market-only 或 personal")
    return normalized  # type: ignore[return-value]


def allowed_base_tool_names(profile: McpProfile) -> frozenset[str]:
    """Return primitive tools exposed by the selected privacy profile."""
    if profile == "market-only":
        return MARKET_ONLY_BASE_TOOLS
    return frozenset(ToolRegistry.tool_names())


def allowed_research_tool_names(profile: McpProfile) -> frozenset[str]:
    """Return high-level workflows exposed by the selected profile."""
    if profile == "market-only":
        return _MARKET_RESEARCH_NAMES
    return frozenset(_RESEARCH_DEF_MAP)


@dataclass(frozen=True)
class _Evidence:
    tool: str
    ok: bool
    data: Any = None
    error: str | None = None

    def as_dict(self) -> dict[str, Any]:
        payload: dict[str, Any] = {"tool": self.tool, "ok": self.ok}
        if self.ok:
            payload["data"] = self.data
        else:
            payload["error"] = self.error or "未知错误"
        return payload


class ResearchToolCatalog:
    """High-level MCP research workflows backed by ``ToolRegistry``."""

    def __init__(self, ctx: ToolContext, registry: ToolRegistry, profile: McpProfile) -> None:
        self._ctx = ctx
        self._registry = registry
        self.profile = profile

    def definitions(self) -> list[ToolDef]:
        allowed = allowed_research_tool_names(self.profile)
        return [tool for tool in RESEARCH_TOOL_DEFS if tool.name in allowed]

    def call(self, name: str, args: dict[str, Any]) -> str:
        if name not in allowed_research_tool_names(self.profile):
            return _json(
                {
                    "error": f"工具 {name} 未在 {self.profile} profile 中开放",
                    "hint": "如确需使用个人数据，请由用户运行 mommy connect <agent> --profile personal",
                }
            )
        handlers = {
            "research_market_brief": self._market_brief,
            "research_us_market": self._us_market_brief,
            "research_stock": self._stock,
            "research_sector": self._sector,
            "research_money_flow": self._money_flow,
            "research_portfolio": self._portfolio,
            "record_research_conclusion": self._record_conclusion,
        }
        handler = handlers.get(name)
        if handler is None:
            return _json({"error": f"未知研究工具: {name}"})
        try:
            return _json(handler(args))
        except (KeyError, TypeError, ValueError) as exc:
            return _json({"error": str(exc)})
        except Exception as exc:
            _log.exception("research tool %s failed", name)
            return _json({"error": f"研究工具执行失败: {exc}"})

    def _call(self, name: str, args: dict[str, Any]) -> _Evidence:
        raw = self._registry.call(name, args)
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            data = raw
        if isinstance(data, dict) and "error" in data:
            return _Evidence(tool=name, ok=False, error=str(data["error"]))
        return _Evidence(tool=name, ok=True, data=data)

    def _pack(
        self,
        research_type: str,
        evidence: list[_Evidence],
        framework: list[str],
        *,
        subject: dict[str, Any] | None = None,
        research_session_id: str | None = None,
    ) -> dict[str, Any]:
        session_id = research_session_id or str(uuid.uuid4())
        payload: dict[str, Any] = {
            "schema_version": 1,
            "research_type": research_type,
            "profile": self.profile,
            "generated_at": datetime.now(UTC).isoformat(),
            "subject": subject or {},
            "evidence": [item.as_dict() for item in evidence],
            "analysis_framework": framework,
            "instructions": [
                "先给结论，再列证据和风险",
                "只引用 ok=true 的证据；缺失数据必须明确说明",
                "区分工具事实与模型推断，不得编造实时数据",
            ],
        }
        ok_evidence = [item for item in evidence if item.ok and item.tool != "get_memory_context"]
        if self.profile == "personal" and ok_evidence:
            payload["research_session_id"] = session_id
            payload["memory_recorded"] = self._record_research_session(
                session_id, research_type, subject or {}, evidence
            )
        else:
            payload["memory_recorded"] = False
        return payload

    def _record_research_session(
        self,
        session_id: str,
        research_type: str,
        subject: dict[str, Any],
        evidence: list[_Evidence],
    ) -> bool:
        """写入事实型研究事件；不会把模型结论伪装成事实。"""
        db_path = self._ctx.resolved_agent_db
        if db_path is None:
            return False
        from mommy_chaogu.agent.episodic_memory import EpisodicMemory

        scope = "market"
        if subject.get("code"):
            scope = f"stock:{subject['code']}"
        elif subject.get("keyword"):
            scope = f"sector:{subject['keyword']}"
        elif research_type == "portfolio":
            scope = "portfolio"
        content_hash = hashlib.sha256(f"research-session:{session_id}".encode()).hexdigest()
        episodic = EpisodicMemory(db_path)
        if episodic.get_by_content_hash(scope, content_hash) is not None:
            return True
        coverage = {item.tool: item.ok for item in evidence}
        source_data = [
            {
                "tool": item.tool,
                "ok": item.ok,
                "error": item.error,
                "as_of": _evidence_as_of(item.data),
            }
            for item in evidence
        ]
        episodic.write(
            event_type="external_research_session",
            scope=scope,
            code=str(subject.get("code")) if subject.get("code") else None,
            name=str(subject.get("keyword")) if subject.get("keyword") else None,
            summary=f"外部研究 {research_type}：{scope}",
            data={
                "research_session_id": session_id,
                "research_type": research_type,
                "subject": subject,
                "evidence": source_data,
            },
            data_coverage=coverage,
            tags=["external-agent", "research-session"],
            source="mcp-external-agent",
            confidence=1.0,
            content_hash=content_hash,
        )
        return True

    @staticmethod
    def _int_arg(args: dict[str, Any], name: str, default: int, low: int, high: int) -> int:
        try:
            value = int(args.get(name, default))
        except (TypeError, ValueError):
            value = default
        return max(low, min(value, high))

    @staticmethod
    def _code(args: dict[str, Any]) -> str:
        code = str(args.get("code", "")).strip()
        if not _CODE_RE.fullmatch(code):
            raise ValueError("需要提供有效的股票代码")
        return code

    def _market_brief(self, args: dict[str, Any]) -> dict[str, Any]:
        limit = self._int_arg(args, "sector_limit", 10, 1, 30)
        evidence: list[_Evidence] = []
        if self.profile == "personal":
            evidence.append(self._call("get_memory_context", {"query": "市场"}))
        evidence.extend(
            [
                self._call("get_market_indexes", {}),
                self._call("get_sector_ranking", {"limit": limit}),
            ]
        )
        return self._pack(
            "market_brief",
            evidence,
            ["判断主要指数方向和市场广度", "识别领涨与领跌板块", "给出下一步观察点"],
            research_session_id=_optional_session_id(args),
        )

    def _us_market_brief(self, _args: dict[str, Any]) -> dict[str, Any]:
        """美股市场概览：三大指数 + VIX + 10 年期美债利率。"""
        evidence = [
            self._call("get_quote", {"code": "^GSPC"}),
            self._call("get_quote", {"code": "^IXIC"}),
            self._call("get_quote", {"code": "^DJI"}),
            self._call("get_quote", {"code": "^VIX"}),
            self._call("get_quote", {"code": "^TNX"}),
        ]
        return self._pack(
            "us_market_brief",
            evidence,
            [
                "判断三大指数方向是否一致，VIX 反映的恐慌程度与涨跌是否匹配",
                "看 10 年期美债利率（^TNX）与股指的联动方向",
                "只引用 ok=true 的证据；缺失的指数必须明确说明",
                "单日涨跌不能外推为趋势，列出使结论失效的风险条件",
            ],
            subject={"indexes": ["^GSPC", "^IXIC", "^DJI", "^VIX", "^TNX"]},
            research_session_id=_optional_session_id(_args),
        )

    def _stock(self, args: dict[str, Any]) -> dict[str, Any]:
        code = self._code(args)
        days = self._int_arg(args, "days", 20, 5, 60)
        evidence = []
        if self.profile == "personal":
            evidence.append(self._call("get_memory_context", {"query": code}))
        evidence.extend(
            [
                self._call("get_quote", {"code": code}),
                self._call("get_bars", {"code": code, "interval": "1d", "limit": days}),
                self._call("get_money_flow_today", {"code": code}),
                self._call("get_money_flow_history", {"code": code, "days": days}),
                self._call("get_fundamentals", {"code": code}),
            ]
        )
        return self._pack(
            "stock",
            evidence,
            [
                "先判断趋势强弱，再检查量价是否确认",
                "用主力净流入相对流通市值的 bp 判断资金强度",
                "用基本面交叉验证行情，不把单日异动外推为长期趋势",
                "列出使结论失效的风险条件",
            ],
            subject={"code": code, "days": days},
            research_session_id=_optional_session_id(args),
        )

    def _sector(self, args: dict[str, Any]) -> dict[str, Any]:
        keyword = str(args.get("keyword", "")).strip()
        if not keyword:
            raise ValueError("需要提供板块关键词")
        limit = self._int_arg(args, "limit", 10, 1, 30)
        search = self._call("search_sector", {"keyword": keyword})
        evidence: list[_Evidence] = []
        if self.profile == "personal":
            evidence.append(self._call("get_memory_context", {"query": keyword}))
        evidence.extend([search, self._call("get_sector_ranking", {"limit": 20})])
        board_code = _first_board_code(search.data) if search.ok else None
        if board_code:
            evidence.append(
                self._call(
                    "get_sector_stocks",
                    {"board_code": board_code, "limit": limit, "sort_by": "change_pct"},
                )
            )
        else:
            evidence.append(_Evidence("get_sector_stocks", False, error="没有匹配到板块代码"))
        return self._pack(
            "sector",
            evidence,
            ["判断板块相对大盘强弱", "检查上涨是否由少数龙头驱动", "列出领涨股与分化风险"],
            subject={"keyword": keyword, "board_code": board_code},
            research_session_id=_optional_session_id(args),
        )

    def _money_flow(self, args: dict[str, Any]) -> dict[str, Any]:
        code = self._code(args)
        days = self._int_arg(args, "days", 10, 1, 60)
        evidence: list[_Evidence] = []
        if self.profile == "personal":
            evidence.append(self._call("get_memory_context", {"query": code}))
        evidence.extend(
            [
                self._call("get_quote", {"code": code}),
                self._call("get_money_flow_today", {"code": code}),
                self._call("get_money_flow_history", {"code": code, "days": days}),
            ]
        )
        return self._pack(
            "money_flow",
            evidence,
            [
                "优先看 bp 强度：超过 5bp 值得关注，超过 10bp 属显著信号",
                "检查资金方向是否连续，以及是否与价格方向背离",
                "绝对金额只能作为辅助，不能跨市值直接比较",
            ],
            subject={"code": code, "days": days},
            research_session_id=_optional_session_id(args),
        )

    def _portfolio(self, _: dict[str, Any]) -> dict[str, Any]:
        portfolio = self._call("get_portfolio", {})
        evidence = [self._call("get_memory_context", {"query": "持仓"}), portfolio]
        codes = _portfolio_codes(portfolio.data) if portfolio.ok else []
        if codes:
            evidence.append(self._call("get_quotes", {"codes": codes}))
        evidence.append(self._call("get_portfolio_analysis", {}))
        return self._pack(
            "portfolio",
            evidence,
            [
                "先判断整体盈亏和仓位集中度",
                "区分个股风险、行业相关性风险和组合流动性风险",
                "不得在缺少成本价或仓位数据时推断收益",
            ],
            subject={"codes": codes},
            research_session_id=_optional_session_id(_),
        )

    def _record_conclusion(self, args: dict[str, Any]) -> dict[str, Any]:
        summary = str(args.get("summary", "")).strip()
        scope = str(args.get("scope", "")).strip()
        if not summary:
            raise ValueError("summary 不能为空")
        if args.get("save_conclusion") is False:
            return {"saved": False, "skipped": True, "message": "按请求未写入研究结论。"}
        if scope not in {"market", "sector", "stock", "portfolio"}:
            raise ValueError("scope 必须是 market、sector、stock 或 portfolio")
        code = str(args.get("code", "")).strip() or None
        if code is not None and not _CODE_RE.fullmatch(code):
            raise ValueError("code 必须是 6 位股票代码")
        confidence = float(args.get("confidence", 0.5))
        if not math.isfinite(confidence):
            raise ValueError("confidence 必须是 0 到 1 之间的有限数字")
        confidence = max(0.0, min(confidence, 1.0))
        db_path = self._ctx.resolved_agent_db
        if db_path is None:
            raise ValueError("记忆数据库未配置")

        prediction = str(args.get("prediction", "")).strip()
        direction: str | None = None
        timeframe: str | None = None
        target_price: Decimal | None = None
        entry_price: Decimal | None = None
        stop_loss: Decimal | None = None
        if prediction:
            direction = str(args.get("direction", "")).strip()
            timeframe = str(args.get("timeframe", "")).strip()
            if code is None:
                raise ValueError("保存预测时必须提供 code")
            if direction not in {"up", "down", "neutral"}:
                raise ValueError("保存预测时 direction 必须是 up、down 或 neutral")
            if timeframe not in {"1d", "3d", "5d", "10d", "20d", "60d"}:
                raise ValueError("保存预测时需要有效 timeframe")
            target_price = _optional_decimal(args.get("target_price"))
            entry_price = _optional_decimal(args.get("entry_price"))
            stop_loss = _optional_decimal(args.get("stop_loss"))

        from mommy_chaogu.agent.episodic_memory import EpisodicMemory

        episodic = EpisodicMemory(db_path)
        content_hash: str | None = None
        idempotency_key = str(args.get("idempotency_key", "")).strip()
        scope_key = f"stock:{code}" if scope == "stock" and code else scope
        if idempotency_key:
            content_hash = hashlib.sha256(
                f"research-conclusion:{idempotency_key}".encode()
            ).hexdigest()
            existing = episodic.get_by_content_hash(scope_key, content_hash)
            if existing is not None:
                return {
                    "saved": True,
                    "reused": True,
                    "event_id": existing["id"],
                    "prediction_id": existing.get("prediction_id"),
                    "message": "研究结论已存在，复用原记录。",
                }
        event_id = episodic.write(
            event_type="external_research",
            scope=f"stock:{code}" if scope == "stock" and code else scope,
            summary=summary,
            data={
                "rationale": args.get("rationale"),
                "research_session_id": args.get("research_session_id"),
                "analysis_type": args.get("analysis_type"),
                "evidence_as_of": args.get("evidence_as_of"),
                "data_coverage": args.get("data_coverage") or {},
            },
            code=code,
            name=str(args.get("name", "")).strip() or None,
            tags=["external-agent", "mcp"],
            source="mcp-external-agent",
            confidence=confidence,
            content_hash=content_hash,
        )

        prediction_id: int | None = None
        if prediction:
            assert code is not None and direction is not None and timeframe is not None
            from mommy_chaogu.agent.prediction_tracker import PredictionTracker

            tracker = PredictionTracker(db_path)
            prediction_idempotency = (
                f"research-conclusion:{idempotency_key}:prediction" if idempotency_key else None
            )
            if prediction_idempotency:
                existing_prediction = tracker.get_by_idempotency_key(prediction_idempotency)
                if existing_prediction is not None:
                    prediction_id = int(existing_prediction["id"])
                    episodic.update_prediction_id(event_id, prediction_id)
                    return {
                        "saved": True,
                        "reused": True,
                        "event_id": event_id,
                        "prediction_id": prediction_id,
                        "message": "研究结论已存在，复用原记录。",
                    }
            prediction_id = tracker.create(
                code=code,
                name=str(args.get("name", "")).strip() or None,
                prediction=prediction,
                direction=direction,
                timeframe=timeframe,
                rationale=str(args.get("rationale", "")).strip() or None,
                target_price=target_price,
                entry_price=entry_price,
                stop_loss=stop_loss,
                source_event_id=event_id,
                data_coverage=args.get("data_coverage") or None,
                idempotency_key=prediction_idempotency,
            )
            episodic.update_prediction_id(event_id, prediction_id)

        return {
            "saved": True,
            "event_id": event_id,
            "prediction_id": prediction_id,
            "message": "研究结论已保存在当前设备。",
        }


def _first_board_code(data: Any) -> str | None:
    if isinstance(data, list) and data and isinstance(data[0], dict):
        value = data[0].get("board_code") or data[0].get("code")
        return str(value) if value else None
    if isinstance(data, dict):
        value = data.get("board_code") or data.get("code")
        return str(value) if value else None
    return None


def _portfolio_codes(data: Any) -> list[str]:
    if not isinstance(data, dict):
        return []
    codes: list[str] = []
    for position in data.get("positions", []):
        if isinstance(position, dict):
            code = str(position.get("code", ""))
            if _CODE_RE.fullmatch(code):
                codes.append(code)
    return codes[:50]


def _optional_decimal(value: Any) -> Decimal | None:
    if value is None or value == "":
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"价格不是有效数字: {value}") from exc


def _optional_session_id(args: dict[str, Any]) -> str | None:
    value = str(args.get("research_session_id", "")).strip()
    return value or None


def _evidence_as_of(data: Any) -> str | None:
    if isinstance(data, dict):
        for key in ("timestamp", "as_of", "date", "trade_date"):
            value = data.get(key)
            if value:
                return str(value)
    return None


__all__ = [
    "DEFAULT_MCP_PROFILE",
    "MARKET_ONLY_BASE_TOOLS",
    "RESEARCH_TOOL_DEFS",
    "WRITE_TOOL_NAMES",
    "McpProfile",
    "ResearchToolCatalog",
    "allowed_base_tool_names",
    "allowed_research_tool_names",
    "normalize_mcp_profile",
]
