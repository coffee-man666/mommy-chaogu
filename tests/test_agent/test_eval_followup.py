"""终审补测：重试 Retry-After / embed 降级 / detect_provider 优先级 / VectorSearch 自建。

锁定全量终审中发现的"新增但无测试覆盖"的行为分支。
"""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from mommy_chaogu.agent import llm as llm_provider
from mommy_chaogu.agent.service import AgentService
from mommy_chaogu.agent.tools import ToolContext


@pytest.fixture
def mock_ctx() -> ToolContext:
    adp = MagicMock()
    adp.get_quote.return_value = None
    return ToolContext(adapter=adp)


class TestRetryDelay:
    """_retry_delay：限流读 Retry-After，否则指数退避（service + extractor 两处）。"""

    @patch("openai.OpenAI")
    def test_retry_after_header_respected(
        self, _mock_openai: MagicMock, mock_ctx: ToolContext
    ) -> None:
        svc = AgentService(mock_ctx, api_key="sk-test")
        from openai import RateLimitError

        response = MagicMock()
        response.headers = {"retry-after": "7.5"}
        err = RateLimitError("rate limited", response=response, body=None)
        assert svc._retry_delay(err, attempt=0) == 7.5

    @patch("openai.OpenAI")
    def test_retry_after_invalid_falls_back_to_backoff(
        self, _mock_openai: MagicMock, mock_ctx: ToolContext
    ) -> None:
        svc = AgentService(mock_ctx, api_key="sk-test", retry_base_delay=1.0)
        from openai import RateLimitError

        response = MagicMock()
        response.headers = {"retry-after": "not-a-number"}
        err = RateLimitError("rate limited", response=response, body=None)
        delay = svc._retry_delay(err, attempt=0)
        # 指数退避 + jitter ∈ [1.0, 1.5)
        assert 1.0 <= delay < 1.6

    @patch("openai.OpenAI")
    def test_no_retry_after_uses_backoff(
        self, _mock_openai: MagicMock, mock_ctx: ToolContext
    ) -> None:
        svc = AgentService(mock_ctx, api_key="sk-test", retry_base_delay=1.0)
        from openai import RateLimitError

        response = MagicMock()
        response.headers = {}
        err = RateLimitError("rate limited", response=response, body=None)
        delay = svc._retry_delay(err, attempt=2)
        # 2^2 * 1.0 + jitter ∈ [4.0, 4.6)
        assert 4.0 <= delay < 4.6

    def test_extractor_retry_after(self) -> None:
        """extractor 的本地重试也读 Retry-After（through behavior）。"""
        from openai import RateLimitError

        from mommy_chaogu.agent.extractor import _create_with_retry

        client = MagicMock()
        response = MagicMock()
        response.headers = {"retry-after": "0"}
        err = RateLimitError("rl", response=response, body=None)
        ok = MagicMock()
        client.chat.completions.create.side_effect = [err, ok]

        result = _create_with_retry(
            client,
            model="m",
            messages=[{"role": "user", "content": "x"}],
            timeout=1.0,
            max_retries=1,
        )
        assert result is ok
        assert client.chat.completions.create.call_count == 2

    def test_extractor_non_retryable_raises_immediately(self) -> None:
        from mommy_chaogu.agent.extractor import _create_with_retry

        client = MagicMock()
        client.chat.completions.create.side_effect = ValueError("bad request")

        with pytest.raises(ValueError, match="bad request"):
            _create_with_retry(client, model="m", messages=[], timeout=1.0, max_retries=3)
        assert client.chat.completions.create.call_count == 1  # 不重试


class TestEmbedPendingTrigger:
    """embed_pending_events：装配/降级/容错三条路径。"""

    def test_no_vector_search_skips(self) -> None:
        from mommy_chaogu.agent.memory_pipeline import MemoryPipeline

        pipe = MemoryPipeline(episodic=None, tracker=None, semantic=None)
        pipe.embed_pending_events()  # 不抛异常即通过

    def test_exception_tolerated(self) -> None:
        from mommy_chaogu.agent.memory_pipeline import MemoryPipeline

        vs = MagicMock()
        vs.embed_pending.side_effect = RuntimeError("vec 表不存在")
        pipe = MemoryPipeline(episodic=None, tracker=None, semantic=None, vector_search=vs)
        pipe.embed_pending_events()  # 容错不抛
        vs.embed_pending.assert_called_once()

    def test_record_analysis_triggers_embed(self, tmp_path: Path) -> None:
        from mommy_chaogu.agent.episodic_memory import EpisodicMemory
        from mommy_chaogu.agent.memory_pipeline import MemoryPipeline
        from mommy_chaogu.agent.prediction_tracker import PredictionTracker

        episodic = EpisodicMemory(tmp_path / "a.db")
        tracker = PredictionTracker(tmp_path / "a.db")
        vs = MagicMock()
        client = MagicMock()

        pipe = MemoryPipeline(episodic, tracker, None, vector_search=vs, client=client, model="m")
        with (
            patch("mommy_chaogu.agent.memory_pipeline.extract_from_conversation") as mock_extract,
            patch("mommy_chaogu.agent.memory_pipeline.store_extraction"),
        ):
            mock_extract.return_value = {"observations": [{"code": "603662"}], "predictions": []}
            pipe.record_analysis("u", "a")

        vs.embed_pending.assert_called_once()

    def test_consolidate_triggers_embed(self, tmp_path: Path) -> None:
        from mommy_chaogu.agent.episodic_memory import EpisodicMemory
        from mommy_chaogu.agent.memory_pipeline import MemoryPipeline
        from mommy_chaogu.agent.prediction_tracker import PredictionTracker
        from mommy_chaogu.agent.semantic_memory import SemanticMemory

        db = tmp_path / "a.db"
        vs = MagicMock()
        pipe = MemoryPipeline(
            EpisodicMemory(db),
            PredictionTracker(db),
            SemanticMemory(db),
            vector_search=vs,
            client=MagicMock(),
            model="m",
        )
        with patch("mommy_chaogu.agent.memory_pipeline.MemoryConsolidator") as mock_cons:
            mock_cons.return_value.consolidate_all.return_value = {}
            pipe.consolidate()

        vs.embed_pending.assert_called_once()


class TestDetectProvider:
    """detect_provider：AGENT_PROVIDER 显式覆盖优先，多 key 按声明序。"""

    def test_explicit_agent_provider_wins(self, monkeypatch: pytest.MonkeyPatch) -> None:
        for env in ("DEEPSEEK_API_KEY", "ZAI_API_KEY"):
            monkeypatch.setenv(env, "sk-x")
        monkeypatch.setenv("AGENT_PROVIDER", "zai")
        assert llm_provider.detect_provider() == "zai"

    def test_explicit_without_key_falls_through(self, monkeypatch: pytest.MonkeyPatch) -> None:
        # AGENT_PROVIDER=zai 但 ZAI_API_KEY 没配 → 按声明序找有 key 的
        monkeypatch.setenv("AGENT_PROVIDER", "zai")
        monkeypatch.delenv("ZAI_API_KEY", raising=False)
        monkeypatch.setenv("OPENAI_API_KEY", "sk-x")
        assert llm_provider.detect_provider() == "openai"

    def test_no_keys_returns_none(self, monkeypatch: pytest.MonkeyPatch) -> None:
        for cfg in llm_provider.SUPPORTED_PROVIDERS.values():
            monkeypatch.delenv(cfg["env_key"], raising=False)
        monkeypatch.delenv("AGENT_PROVIDER", raising=False)
        assert llm_provider.detect_provider() is None


class TestVectorSearchAutoWiring:
    """AgentService 自建 VectorSearch：有 embedding 模型装配，无则降级。"""

    @patch("openai.OpenAI")
    def test_openai_provider_builds_vector_search(
        self, _mock_openai: MagicMock, tmp_path: Path
    ) -> None:
        from mommy_chaogu.agent.episodic_memory import EpisodicMemory
        from mommy_chaogu.agent.prediction_tracker import PredictionTracker

        ctx = ToolContext(adapter=MagicMock())
        svc = AgentService(
            ctx,
            provider="openai",
            api_key="sk-test",
            episodic=EpisodicMemory(tmp_path / "a.db"),
            tracker=PredictionTracker(tmp_path / "a.db"),
        )
        pipeline = svc._memory_service._pipeline
        assert pipeline is not None
        assert pipeline._vector_search is not None

    @patch("openai.OpenAI")
    def test_deepseek_provider_stays_degraded(
        self, _mock_openai: MagicMock, tmp_path: Path
    ) -> None:
        from mommy_chaogu.agent.episodic_memory import EpisodicMemory
        from mommy_chaogu.agent.prediction_tracker import PredictionTracker

        ctx = ToolContext(adapter=MagicMock())
        svc = AgentService(
            ctx,
            provider="deepseek",
            api_key="sk-test",
            episodic=EpisodicMemory(tmp_path / "a.db"),
            tracker=PredictionTracker(tmp_path / "a.db"),
        )
        pipeline = svc._memory_service._pipeline
        assert pipeline is not None
        assert pipeline._vector_search is None  # 无 embedding 接口，显式降级

    @patch("openai.OpenAI")
    def test_explicit_vector_search_not_overridden(
        self, _mock_openai: MagicMock, tmp_path: Path
    ) -> None:
        from mommy_chaogu.agent.episodic_memory import EpisodicMemory
        from mommy_chaogu.agent.prediction_tracker import PredictionTracker

        custom_vs = MagicMock()
        ctx = ToolContext(adapter=MagicMock())
        svc = AgentService(
            ctx,
            provider="openai",
            api_key="sk-test",
            episodic=EpisodicMemory(tmp_path / "a.db"),
            tracker=PredictionTracker(tmp_path / "a.db"),
            vector_search=custom_vs,
        )
        assert svc._memory_service._pipeline._vector_search is custom_vs  # type: ignore[union-attr]


class TestHistoryBudget:
    """L2：跨轮历史注入有字符预算，最旧的消息先被丢弃。"""

    @patch("openai.OpenAI")
    def test_history_trimmed_to_budget(
        self, _mock_openai: MagicMock, mock_ctx: ToolContext
    ) -> None:
        svc = AgentService(mock_ctx, api_key="sk-test")
        messages: list[dict[str, Any]] = []
        items = [{"role": "user", "content": "x" * 3000} for _ in range(4)]  # 12k 字符
        svc._append_history(messages, items, budget=6000)
        # 预算 6000：能装下最新 2 条（3000×2），最旧 2 条被丢弃
        assert len(messages) == 2

    @patch("openai.OpenAI")
    def test_latest_message_always_kept(
        self, _mock_openai: MagicMock, mock_ctx: ToolContext
    ) -> None:
        svc = AgentService(mock_ctx, api_key="sk-test")
        messages: list[dict[str, Any]] = []
        items = [
            {"role": "user", "content": "old"},
            {"role": "assistant", "content": "y" * 10000},  # 单条就超预算
        ]
        svc._append_history(messages, items, budget=100)
        assert len(messages) == 1
        assert messages[0]["role"] == "assistant"  # 最新一条保留


class TestTruncateUtf8Boundary:
    """_truncate_result 切在 UTF-8 多字节边界上不产生乱码。"""

    def test_multibyte_cut_has_no_replacement_char(self) -> None:
        from mommy_chaogu.agent.tools.registry import MAX_RESULT_BYTES, _truncate_result

        # 前缀 + 大量 3 字节中文字符，截断点必落在某个中文字符中间
        s = "ab" + "汉" * 4000
        out = _truncate_result(s, max_bytes=MAX_RESULT_BYTES)
        assert "truncated" in out
        assert "�" not in out  # errors="ignore" 吃掉半个字符，不留替换符
