"""agent command family."""

from __future__ import annotations

# Shared CLI dependencies are deliberately exported by cli_support.
# ruff: noqa: F403,F405
from mommy_chaogu.cli_support import *

# ============================================================
# mommy-agent — LLM agent 交互式 CLI
# ============================================================


def build_agent_parser() -> argparse.ArgumentParser:
    """构建 mommy-agent 的 argparse parser。"""
    p = argparse.ArgumentParser(
        prog="mommy-agent",
        description="妈妈炒股 - LLM agent（交互式对话 / 单次提问）",
    )
    p.add_argument(
        "query",
        nargs="*",
        help="提问内容（留空则进入交互式 REPL）",
    )
    p.add_argument(
        "--provider",
        default=None,
        help="LLM provider（deepseek / openai / kimi / zai / nova，默认读 .env）",
    )
    p.add_argument(
        "--model",
        default=None,
        help="模型名（默认由 provider 决定）",
    )
    p.add_argument(
        "--max-tool-calls",
        type=int,
        default=10,
        help="最大工具调用轮数（默认 10）",
    )
    return p


def _build_agent_context() -> object:
    """从项目默认配置构造 agent ToolContext。"""
    from mommy_chaogu.agent.tools import ToolContext
    from mommy_chaogu.cache import CachedMarketDataAdapter, CacheStore
    from mommy_chaogu.db_paths import AGENT_DB, MARKET_DB, PORTFOLIO_DB
    from mommy_chaogu.market_data import EfinanceAdapter, FallbackAdapter, TencentAdapter
    from mommy_chaogu.portfolio.store import PortfolioStore
    from mommy_chaogu.watchlist.store import WatchlistStore

    base = FallbackAdapter([EfinanceAdapter(), TencentAdapter()])
    store = CacheStore(MARKET_DB)
    adapter = CachedMarketDataAdapter(base, store)

    return ToolContext(
        adapter=adapter,
        watchlist_store=WatchlistStore(PORTFOLIO_DB),
        portfolio_store=PortfolioStore(PORTFOLIO_DB),
        db_path=AGENT_DB,
    )


def main_agent() -> NoReturn:
    """mommy-agent 入口：交互式 LLM 对话（带工具 + 记忆系统）。"""
    parser = build_agent_parser()
    args = parser.parse_args()

    from mommy_chaogu.agent.episodic_memory import EpisodicMemory
    from mommy_chaogu.agent.prediction_tracker import PredictionTracker
    from mommy_chaogu.agent.semantic_memory import SemanticMemory
    from mommy_chaogu.agent.service import AgentService
    from mommy_chaogu.agent.vector_search import VectorSearch
    from mommy_chaogu.db_paths import AGENT_DB

    ctx = _build_agent_context()
    vs = VectorSearch(AGENT_DB)
    agent = AgentService(
        ctx,
        provider=args.provider,
        model=args.model,
        max_tool_calls=args.max_tool_calls,
        episodic=EpisodicMemory(AGENT_DB),
        tracker=PredictionTracker(AGENT_DB),
        semantic=SemanticMemory(AGENT_DB),
        vector_search=vs,
    )

    query = " ".join(args.query).strip() if args.query else ""

    if query:
        # 单次提问模式
        resp = agent.chat(query)
        print(resp.text)
        sys.exit(0)

    # 交互式 REPL
    print("妈妈炒股 Agent — 输入问题，Ctrl+C 或输入 q 退出\n")
    try:
        while True:
            try:
                user_input = input("❯ ").strip()
            except EOFError:
                break
            if not user_input or user_input.lower() in ("q", "quit", "exit"):
                break
            resp = agent.chat(user_input)
            print(f"\n{resp.text}\n")
            if resp.tool_calls:
                tool_names = ", ".join(tc.name for tc in resp.tool_calls)
                print(f"[工具调用: {tool_names}]\n")
    except KeyboardInterrupt:
        print("\n再见！")
    sys.exit(0)
