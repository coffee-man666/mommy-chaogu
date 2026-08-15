"""自然语言运行时的统一装配工厂（CLI / TUI / Web 三入口共享）。

之前三个入口各自内联一遍 ToolContext→ToolRegistry→AgentService→
Summarizer→WorkflowExecutor→NLRouter 装配，且 ``_AgentSummarizer``
在 cli.py 与 web/routes/agent.py 逐字重复；用户自定义工作流
（WorkflowStore，``mommy workflow add`` 保存）只在 CLI merge，
TUI / Web 看不到。本模块把装配收敛为 ``build_nl_runtime()`` 单一工厂：

- 内置 registry（``get_default_registry()``）+ WorkflowStore 自定义
  工作流 merge（容错链与原 CLI 实现一致：坏 spec 跳过、不影响内置）；
- AgentService→LLMSummarizer 适配器只定义一次（``AgentSummarizer``）；
- 入口差异通过参数注入：context / tool_registry / agent_service /
  llm_summarizer / provider / workflow_store / agent_db / build_agent。

入口特有语义仍在各自入口（不在工厂内）：
- CLI：hit recorder（increment_hit）与进程退出 close WorkflowStore；
- TUI：探测链 provider 一致性（detect_provider 显式传 AgentService）、
  ConversationMemory、AgentBridge.route 静默降级；
- Web：lru_cache 单例 + setup 后 reload_agent_caches() 热重建、
  无 key 时 agent=None 降级提示。
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

from mommy_chaogu.agent.tools import ToolContext, ToolRegistry
from mommy_chaogu.workflow.engine import LLMSummarizer, WorkflowExecutor, WorkflowRegistry
from mommy_chaogu.workflow.router import NLRouter

if TYPE_CHECKING:
    from mommy_chaogu.agent.service import AgentService
    from mommy_chaogu.workflow.store import WorkflowStore

_log = logging.getLogger(__name__)


class AgentSummarizer:
    """AgentService → LLMSummarizer 适配器（三入口共享的单一定义）。"""

    def __init__(self, svc: AgentService) -> None:
        self._svc = svc

    def summarize(self, template: str, context: str) -> str:
        prompt = template.format(context=context)
        resp = self._svc.chat_raw([{"role": "user", "content": prompt}])
        return resp.text


@dataclass
class NLRuntime:
    """自然语言入口运行时（工厂产物）。

    Attributes:
        router: 意图路由（内置 + 自定义工作流 merge 后的 registry）。
        executor: 工作流执行器（可选 LLM 总结）。
        tool_registry: 工具注册表。
        agent_service: LLM agent；未配置 API key 时为 None（入口据此降级）。
        workflow_store: 自定义工作流存储。调用方注入的归调用方管理生命周期
            （如 CLI 退出时 close）；工厂自建的随本对象被 GC 后由
            EngineOwner 的 weakref finalizer 释放连接池。
    """

    router: NLRouter
    executor: WorkflowExecutor
    tool_registry: ToolRegistry
    agent_service: AgentService | None
    workflow_store: WorkflowStore | None


def merge_custom_workflows(registry: WorkflowRegistry, store: WorkflowStore) -> int:
    """把 WorkflowStore 里的自定义工作流合并进 registry。

    容错链与原 CLI 装配一致：validate_spec 产生 blocking issue（id 冲突 /
    trigger 冲突 / 非法正则 / 工具不存在等）或 spec_to_workflow 转换失败
    的 spec 逐条跳过，不影响其余 spec 与内置工作流。返回成功合并的数量。
    """
    from mommy_chaogu.workflow.spec_runtime import spec_to_workflow
    from mommy_chaogu.workflow.validator import blocking_issues, validate_spec

    merged = 0
    for custom_spec, _meta in store.load_all():
        try:
            issues = validate_spec(custom_spec, existing_workflows=registry.all_workflows())
            if blocking_issues(issues):
                continue
            if registry.get(custom_spec.id) is None:
                registry.register(spec_to_workflow(custom_spec))
                merged += 1
        except (TypeError, ValueError):
            continue
    return merged


def build_nl_runtime(
    *,
    context: ToolContext | None = None,
    tool_registry: ToolRegistry | None = None,
    agent_service: AgentService | None = None,
    llm_summarizer: LLMSummarizer | None = None,
    provider: str | None = None,
    workflow_store: WorkflowStore | None = None,
    agent_db: Path | None = None,
    build_agent: bool = True,
) -> NLRuntime:
    """装配自然语言入口运行时。

    装配顺序：ToolRegistry →（可选）AgentService →（可选）LLM summarizer
    → WorkflowExecutor → builtin registry + 自定义工作流 merge → NLRouter。

    Args:
        context: 工具层共享依赖。缺省时构建 CLI 风格默认 context
            （adapter 链 + 三库路径）。
        tool_registry: 注入已构建的工具注册表（如 Web 用 deps 单例 context）。
        agent_service: 注入入口自建的 agent（TUI 的探测链 / Web 的 deps
            单例）；未注入且 ``build_agent`` 时工厂自建。
        llm_summarizer: 注入自定义总结器；缺省且有 agent 时用
            ``AgentSummarizer`` 包装。
        provider: 工厂自建 agent 时显式传给 AgentService 的 provider
            （TUI 的 detect_provider 探测结果）。
        workflow_store: 注入调用方管理的存储（CLI 需要 increment_hit /
            close）。缺省时按 ``agent_db``（或 context 的 agent_db）自建，
            自建失败仅告警、退化为内置工作流。
        agent_db: 自定义工作流存储路径（优先于 context 的 agent_db）。
        build_agent: False 时跳过 agent 自建（仅需路由/执行的入口）。
    """
    from mommy_chaogu.workflow.definitions import get_default_registry

    ctx = context
    if ctx is None and tool_registry is None:
        ctx = _default_context()
    if tool_registry is None:
        assert ctx is not None  # 上一行保证二选一存在
        tool_registry = ToolRegistry(ctx)

    if agent_service is None and build_agent:
        agent_service = _build_agent_service(
            ctx if ctx is not None else _default_context(),
            provider=provider,
        )

    if llm_summarizer is None and agent_service is not None:
        llm_summarizer = AgentSummarizer(agent_service)

    executor = WorkflowExecutor(tool_registry, llm_summarizer=llm_summarizer)

    registry = WorkflowRegistry()
    for builtin in get_default_registry().all_workflows():
        registry.register(builtin)

    store = workflow_store
    if store is None:
        db: Path | None
        if agent_db is not None:
            db = agent_db
        elif ctx is not None:
            db = ctx.resolved_agent_db
        else:
            db = None
        if db is not None:
            store = _open_workflow_store(db)
    if store is not None:
        merge_custom_workflows(registry, store)

    return NLRuntime(
        router=NLRouter(registry, executor=executor),
        executor=executor,
        tool_registry=tool_registry,
        agent_service=agent_service,
        workflow_store=store,
    )


def _default_context() -> ToolContext:
    """CLI 风格的默认 ToolContext：adapter 链 + 三库路径 + 读写 store。"""
    from mommy_chaogu.cache import CachedMarketDataAdapter, CacheStore
    from mommy_chaogu.db_paths import AGENT_DB, MARKET_DB, PORTFOLIO_DB
    from mommy_chaogu.market_data import create_adapter_chain
    from mommy_chaogu.portfolio.store import PortfolioStore
    from mommy_chaogu.watchlist.store import WatchlistStore

    adapter = CachedMarketDataAdapter(create_adapter_chain(), CacheStore(MARKET_DB))
    return ToolContext(
        adapter=adapter,
        watchlist_store=WatchlistStore(PORTFOLIO_DB),
        portfolio_store=PortfolioStore(PORTFOLIO_DB),
        agent_db=AGENT_DB,
        market_db=MARKET_DB,
        portfolio_db=PORTFOLIO_DB,
    )


def _build_agent_service(ctx: ToolContext, provider: str | None) -> AgentService | None:
    """按 context 构建 AgentService；无 key（ValueError）或记忆库初始化
    失败（OSError）时返回 None——工作流仍可执行（没有 LLM 总结）。"""
    from mommy_chaogu.agent.episodic_memory import EpisodicMemory
    from mommy_chaogu.agent.prediction_tracker import PredictionTracker
    from mommy_chaogu.agent.semantic_memory import SemanticMemory
    from mommy_chaogu.agent.service import AgentService

    try:
        agent_db = ctx.resolved_agent_db
        return AgentService(
            ctx,
            provider=provider,
            episodic=EpisodicMemory(agent_db) if agent_db is not None else None,
            tracker=PredictionTracker(agent_db) if agent_db is not None else None,
            semantic=SemanticMemory(agent_db) if agent_db is not None else None,
            # vector_search 不显式传：AgentService 在 provider 有 embedding
            # 接口时自动装配，无接口时保持关键词降级
        )
    except (ValueError, OSError) as e:
        _log.info("AgentService 不可用（未配置 API key 或记忆库初始化失败）: %s", e)
        return None


def _open_workflow_store(db: Path) -> WorkflowStore | None:
    """自建 WorkflowStore；初始化失败仅告警（merge 是尽力而为的增强）。"""
    from mommy_chaogu.workflow.store import WorkflowStore

    try:
        return WorkflowStore(db)
    except Exception as e:
        _log.warning("WorkflowStore 初始化失败，仅使用内置工作流: %s", e)
        return None
