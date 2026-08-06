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
        help="LLM provider（deepseek / openai / kimi / zai / minimax，默认读 .env）",
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
    from mommy_chaogu.market_data import create_adapter_chain
    from mommy_chaogu.portfolio.store import PortfolioStore
    from mommy_chaogu.watchlist.store import WatchlistStore

    base = create_adapter_chain()
    store = CacheStore(MARKET_DB)
    adapter = CachedMarketDataAdapter(base, store)

    return ToolContext(
        adapter=adapter,
        watchlist_store=WatchlistStore(PORTFOLIO_DB),
        portfolio_store=PortfolioStore(PORTFOLIO_DB),
        agent_db=AGENT_DB,
        market_db=MARKET_DB,
        portfolio_db=PORTFOLIO_DB,
    )


def _build_llm_client(
    provider: str | None = None,
    model: str | None = None,
) -> tuple[object | None, str | None, str | None]:
    """容错地构造 OpenAI 兼容 client，返回 (client, model, embedding_model)。

    任何一步失败（provider 未知 / 无 API key / 构造抛异常）都返回
    ``(None, None, None)``，调用方必须容忍 None 并走降级路径。
    ``embedding_model`` 为 None 表示该 provider 没有 OpenAI 兼容
    embedding 接口（如默认的 deepseek），向量检索应显式降级，
    不要把聊天模型名当 embedding 模型传。
    """
    try:
        from mommy_chaogu.agent import llm
        from mommy_chaogu.config import load_config

        cfg = load_config()
        resolved_provider = (provider or cfg.agent.provider).strip().lower()
        config = llm.provider_config(resolved_provider)
        api_key = os.environ.get(config["env_key"], "") or cfg.agent.api_key
        if not api_key:
            return None, None, None

        client = llm.create_client(resolved_provider, api_key)
        resolved_model = model or cfg.agent.model or config["default_model"]
        return client, str(resolved_model), llm.embedding_model_for(resolved_provider)
    except Exception:
        return None, None, None


def run_verify(db: Path, market_db: Path | None = None) -> dict[str, int]:
    """装配依赖并验证所有到期预测，返回统计 dict。

    逻辑与 ``scripts/cron_verify.py`` 一致，但行情缓存写 market.db
    （与缓存层读取一致），不再污染 agent.db。
    """
    from mommy_chaogu.agent.episodic_memory import EpisodicMemory
    from mommy_chaogu.agent.prediction_tracker import PredictionTracker
    from mommy_chaogu.agent.verify_engine import verify_pending
    from mommy_chaogu.cache import CachedMarketDataAdapter, CacheStore
    from mommy_chaogu.db_paths import MARKET_DB
    from mommy_chaogu.market_data import create_adapter_chain

    tracker = PredictionTracker(db)
    episodic = EpisodicMemory(db)

    store = CacheStore(market_db or MARKET_DB)
    base = create_adapter_chain()
    adapter = CachedMarketDataAdapter(base, store)

    return verify_pending(
        tracker=tracker,
        episodic=episodic,
        adapter=adapter,
        cache_store=store,
    )


def _run_verify(argv: list[str]) -> NoReturn:
    """mommy-agent verify：验证到期预测（cron_verify.sh 依赖）。"""
    p = argparse.ArgumentParser(
        prog="mommy-agent verify",
        description="验证到期预测（A 股收盘后由 cron 调用）",
    )
    p.add_argument("--db", default=None, help="agent 数据库路径（默认 data/agent.db）")
    args = p.parse_args(argv)

    db = Path(args.db) if args.db else AGENT_DB
    print("🔍 验证到期预测...")
    results = run_verify(db)
    print(f"验证 {results['total']} 条预测")
    print(f"  ✅ hit: {results['hit']}")
    print(f"  ❌ missed: {results['missed']}")
    print(f"  ⚠️  data_unavailable: {results['data_unavailable']}")
    print(f"  ⚪ unverifiable: {results.get('unverifiable', 0)}")
    print(f"  ⏰ expired: {results['expired']}")
    decided = results["hit"] + results["missed"]
    if decided > 0:
        print(f"命中率: {results['hit'] / decided * 100:.0f}%")
    sys.exit(0)


def _run_consolidate(argv: list[str]) -> NoReturn:
    """mommy-agent consolidate：提炼语义知识（cron_consolidate.sh 依赖）。"""
    p = argparse.ArgumentParser(
        prog="mommy-agent consolidate",
        description="从 episodic + predictions 提炼语义知识（需要 LLM）",
    )
    p.add_argument("--db", default=None, help="agent 数据库路径（默认 data/agent.db）")
    p.add_argument("--provider", default=None, help="LLM provider（默认读 .env）")
    p.add_argument("--model", default=None, help="模型名（默认由 provider 决定）")
    args = p.parse_args(argv)

    from mommy_chaogu.agent.consolidator import MemoryConsolidator
    from mommy_chaogu.agent.episodic_memory import EpisodicMemory
    from mommy_chaogu.agent.prediction_tracker import PredictionTracker
    from mommy_chaogu.agent.semantic_memory import SemanticMemory

    client, model, embedding_model = _build_llm_client(args.provider, args.model)
    if client is None or model is None:
        print(
            "❌ 未配置 LLM API key，无法提炼知识（consolidate 需要 LLM）",
            file=sys.stderr,
        )
        sys.exit(1)

    db = Path(args.db) if args.db else AGENT_DB
    episodic = EpisodicMemory(db)
    consolidator = MemoryConsolidator(
        episodic,
        SemanticMemory(db),
        PredictionTracker(db),
        client,
        model,
    )
    print("🧠 提炼语义知识...")
    results = consolidator.consolidate_all()
    print(f"  板块叙事: {results['sector_theses']}")
    print(f"  市场状态: {results['market_regime']}")
    print(f"  规律归纳: {results['patterns']}")

    # 提炼后顺带为存量事件补 embedding（向量子系统的定期生产触发点；
    # provider 无 embedding 接口时跳过）
    if embedding_model is not None:
        from mommy_chaogu.agent.vector_search import VectorSearch

        try:
            vs = VectorSearch(episodic, client, model=embedding_model)
            embed_results = vs.embed_pending()
            print(f"  事件 embedding: {embed_results}")
        except Exception as e:
            print(f"⚠️ embedding 生成失败（不影响提炼结果）: {e}", file=sys.stderr)
    sys.exit(0)


def main_agent() -> NoReturn:
    """mommy-agent 入口：交互式 LLM 对话（带工具 + 记忆系统）。"""
    # 维护子命令在 chat 解析前拦截——否则 "verify"/"consolidate"
    # 会被当成提问内容发给 LLM。
    argv = sys.argv[1:]
    if argv and argv[0] == "verify":
        _run_verify(argv[1:])
    elif argv and argv[0] == "consolidate":
        _run_consolidate(argv[1:])

    parser = build_agent_parser()
    args = parser.parse_args()

    from mommy_chaogu.agent.episodic_memory import EpisodicMemory
    from mommy_chaogu.agent.prediction_tracker import PredictionTracker
    from mommy_chaogu.agent.semantic_memory import SemanticMemory
    from mommy_chaogu.agent.service import AgentService
    from mommy_chaogu.agent.vector_search import VectorSearch
    from mommy_chaogu.config import load_config
    from mommy_chaogu.db_paths import AGENT_DB

    ctx = _build_agent_context()
    episodic = EpisodicMemory(AGENT_DB)

    # provider/api_key 解析链与 _build_llm_client 对齐：CLI 参数 >
    # config.toml > AGENT_PROVIDER 环境变量（AgentService 内部再兜底）。
    # 否则只在 config.toml 配 provider 的用户会在这里被解析成默认
    # deepseek，与 VectorSearch 的 provider 分裂。
    cfg = load_config()

    # VectorSearch 需要 (episodic, client) + 专用 embedding 模型。
    # provider 无 embedding 接口（embedding_model=None）/ 无 key /
    # 初始化失败时 vs 保持 None，走关键词降级路径，不影响对话。
    vs = None
    client, _model, embedding_model = _build_llm_client(args.provider, args.model)
    if client is not None and embedding_model is not None:
        try:
            vs = VectorSearch(episodic, client, model=embedding_model)
        except Exception as e:
            print(f"⚠️ 向量检索初始化失败，降级为关键词搜索: {e}", file=sys.stderr)

    agent = AgentService(
        ctx,
        provider=args.provider or cfg.agent.provider,
        model=args.model or cfg.agent.model,
        api_key=cfg.agent.api_key or None,
        max_tool_calls=args.max_tool_calls,
        episodic=episodic,
        tracker=PredictionTracker(AGENT_DB),
        semantic=SemanticMemory(AGENT_DB),
        vector_search=vs,
    )

    query = " ".join(args.query).strip() if args.query else ""

    if query:
        # 单次提问模式
        resp = agent.chat(query)
        print(resp.text)
        # P6：对话后提取在后台 daemon 线程跑——exit 前必须等它完成，
        # 否则进程退出时提取被静默丢弃（单发模式唯一的消息轮次）。
        agent.flush(timeout=30)
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
    # 退出前等最后一轮的后台提取完成（daemon 线程随进程退出会被丢弃）
    agent.flush(timeout=10)
    sys.exit(0)
