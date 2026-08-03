"""事实抽取：从对话中提取结构化 observations + predictions。

对话结束后调 LLM（JSON response mode）提取结构化信息，
写入 episodic_events 和 predictions 表。

降级原则：LLM 提取失败（网络/API 错误）→ 静默跳过，不影响主对话流程。
"""

from __future__ import annotations

import hashlib
import json
import logging
import threading
from contextlib import suppress
from decimal import Decimal
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from mommy_chaogu.agent.episodic_memory import EpisodicMemory
    from mommy_chaogu.agent.prediction_tracker import PredictionTracker
    from mommy_chaogu.market_data.adapter import MarketDataAdapter

_log = logging.getLogger(__name__)

# token 截断限制。优先用 tiktoken 精确按 token 计数；
# tiktoken 不可用时降级为更大的字符限制（user 8000 / assistant 16000 chars）。
try:
    import tiktoken as _tiktoken

    _ENCODER = _tiktoken.get_encoding("cl100k_base")
    _HAS_TIKTOKEN = True
except Exception:  # pragma: no cover - tiktoken 不在依赖里，正常环境走这条分支
    _ENCODER = None
    _HAS_TIKTOKEN = False

_USER_LIMIT = 2000 if _HAS_TIKTOKEN else 8000
_ASSISTANT_LIMIT = 4000 if _HAS_TIKTOKEN else 16000

# data_coverage 各字段 → data dict 中对应的判据 key。
# 任一 key 在 data 中存在且非空，即认为该数据实际被使用。
_COVERAGE_FIELD_KEYS: dict[str, tuple[str, ...]] = {
    "quote": ("price", "change_pct", "quote", "last_price", "now"),
    "flow_today": ("flow_today", "flow", "net_flow"),
    "flow_5d": ("flow_5d", "flow_5day"),
    "news": ("news", "news_list"),
}


def _truncate_to_tokens(text: str, max_tokens: int) -> str:
    """按 token（或字符）上限截断文本，保留前 *max_tokens* 单位内容。

    tiktoken 可用时用 ``cl100k_base`` 精确按 token 切；不可用则按字符切
    （调用方传入更大的字符级限制作为降级）。
    """
    if _ENCODER is not None:
        tokens = _ENCODER.encode(text)
        if len(tokens) <= max_tokens:
            return text
        return _ENCODER.decode(tokens[:max_tokens])
    if len(text) <= max_tokens:
        return text
    return text[:max_tokens]


def _correct_data_coverage(
    reported: dict[str, bool] | None,
    data: dict[str, Any] | None,
    adapter: MarketDataAdapter | None,
    code: str | None,
) -> dict[str, bool]:
    """根据 data dict 实际内容和 adapter 推断，修正 LLM 自报的 data_coverage。

    诚实记录原则：
    - data 里有对应数据 → 标 true（即便 LLM 漏报）
    - LLM 报 true 但 data 里没有 → 改 false
    - adapter 能拿到 quote → quote 强制 true
    """
    data = data or {}
    coverage: dict[str, bool] = dict(reported or {})

    for field, keys in _COVERAGE_FIELD_KEYS.items():
        present = any(_has_value(data, k) for k in keys)
        if present:
            coverage[field] = True
        elif coverage.get(field) is True:
            coverage[field] = False

    if adapter is not None and code:
        try:
            quote = adapter.get_quote(code)
            if quote is not None and getattr(quote, "price", None):
                coverage["quote"] = True
        except Exception:
            pass  # 拿不到报价不影响 coverage 推断

    return coverage


def _has_value(data: dict[str, Any], key: str) -> bool:
    """data[key] 存在且非 None/空。"""
    return key in data and data[key] not in (None, "", [], {})


_EXTRACTION_PROMPT = """\
从以下对话中提取结构化投资信息。

对话:
  user: {user_msg}
  assistant: {assistant_msg}

提取规则:
1. 只提取与 A 股投资相关的观察和预测
2. 如果没有可提取的内容，返回空数组
3. data_coverage 标记该观察基于哪些数据（true=有数据，false=缺失）

返回 JSON（严格按此格式）:
{{
  "observations": [
    {{
      "event_type": "analysis_record",
      "scope": "stock:603662",
      "code": "603662",
      "name": "柯力传感",
      "summary": "一句话摘要",
      "data": {{"price": 80.0, "change_pct": 8.37}},
      "data_coverage": {{"quote": true, "flow_today": false, "flow_5d": false, "news": false}},
      "confidence": 0.7,
      "tags": ["底部反转", "放量"]
    }}
  ],
  "predictions": [
    {{
      "code": "603662",
      "name": "柯力传感",
      "prediction": "底部反转，短期看涨",
      "direction": "bullish",
      "timeframe": "5d",
      "target_price": 84.49,
      "rationale": "业绩催化+放量流入"
    }}
  ]
}}

注意:
- scope 格式: "stock:代码" / "sector:名称" / "market"
- direction: "bullish" / "bearish" / "neutral"
- timeframe: "1d" / "5d" / "20d" / "60d"
- 如果 assistant 没有做方向性判断，predictions 返回空数组
- 如果对话是纯闲聊，observations 和 predictions 都返回空数组
"""


def _accumulate_extract_usage(
    usage_out: dict[str, int] | None,
    usage_lock: threading.Lock | None,
    response: Any,
) -> None:
    """把提取调用的 token 计入调用方的共享统计容器（可选锁互斥）。

    对话后提取是一轮真实计费的 LLM 调用——不计会让 token 统计偏低
    （EVALUATION-2026-07-18 L6）。
    """
    if usage_out is None:
        return
    usage = getattr(response, "usage", None)
    if usage is None:
        return

    def _add() -> None:
        for key in ("prompt_tokens", "completion_tokens", "total_tokens"):
            val = getattr(usage, key, None)
            if val is not None:
                usage_out[key] = usage_out.get(key, 0) + int(val)

    if usage_lock is not None:
        with usage_lock:
            _add()
    else:
        _add()


def _create_with_retry(
    client: Any,
    *,
    model: str,
    messages: list[dict[str, Any]],
    timeout: float,
    max_retries: int,
) -> Any:
    """提取用的 LLM 调用：显式超时 + 瞬时错误指数退避重试。

    JSON 提取任务用 ``temperature=0``（稳定性优先）；限流时读
    Retry-After 响应头。非瞬时错误（认证 / 参数）直接抛出。
    """
    import time

    from openai import APIConnectionError, InternalServerError, RateLimitError

    retryable = (APIConnectionError, RateLimitError, InternalServerError)

    for attempt in range(max_retries + 1):
        try:
            return client.chat.completions.create(
                model=model,
                messages=messages,
                temperature=0,
                timeout=timeout,
            )
        except retryable as e:
            if attempt >= max_retries:
                raise
            delay = 1.0 * (2**attempt)
            if isinstance(e, RateLimitError):
                headers = getattr(getattr(e, "response", None), "headers", None)
                retry_after = headers.get("retry-after") if headers is not None else None
                if retry_after is not None:
                    with suppress(TypeError, ValueError):
                        delay = max(0.0, float(retry_after))
            _log.warning(
                "extract: LLM 调用失败（第 %d/%d 次）: %s — %.1fs 后重试",
                attempt + 1,
                max_retries + 1,
                e,
                delay,
            )
            time.sleep(delay)
    raise AssertionError("unreachable")  # pragma: no cover


def extract_from_conversation(
    user_message: str,
    assistant_response: str,
    client: Any,
    model: str,
    *,
    usage_out: dict[str, int] | None = None,
    usage_lock: threading.Lock | None = None,
    timeout: float = 60.0,
    max_retries: int = 2,
) -> dict[str, Any] | None:
    """用 LLM 从对话中提取结构化信息。

    Args:
        user_message: 用户消息
        assistant_response: agent 的回复
        client: OpenAI client（兼容 deepseek/kimi）
        model: 模型名
        usage_out: 可选，提取消耗的 token 累加进这个 dict
        usage_lock: 可选，累加 usage_out 时持有（与主线程统计互斥）
        timeout: 单次 LLM 调用超时（秒）
        max_retries: 瞬时错误重试次数

    Returns:
        {"observations": [...], "predictions": [...]} 或 None（提取失败/无内容）
    """
    prompt = _EXTRACTION_PROMPT.format(
        user_msg=_truncate_to_tokens(user_message, _USER_LIMIT),
        assistant_msg=_truncate_to_tokens(assistant_response, _ASSISTANT_LIMIT),
    )

    messages = [
        {
            "role": "system",
            "content": (
                "你是一个信息提取助手。从投资对话中提取结构化信息。"
                "只返回 JSON，不要加任何其他文字。"
            ),
        },
        {"role": "user", "content": prompt},
    ]

    try:
        response = _create_with_retry(
            client,
            model=model,
            messages=messages,
            timeout=timeout,
            max_retries=max_retries,
        )
        _accumulate_extract_usage(usage_out, usage_lock, response)

        content = response.choices[0].message.content or ""

        # 尝试解析 JSON（可能被 ```json ... ``` 包裹）
        content = content.strip()
        if content.startswith("```"):
            # 去掉 markdown code fence
            lines = content.split("\n")
            content = "\n".join(lines[1:-1]) if len(lines) > 2 else content

        result = json.loads(content)

        observations = result.get("observations", [])
        predictions = result.get("predictions", [])

        if not observations and not predictions:
            return None

        return {"observations": observations, "predictions": predictions}

    except json.JSONDecodeError as e:
        _log.warning("extract: LLM 返回无效 JSON: %s", e)
        return None
    except Exception as e:
        _log.warning("extract: LLM 调用失败: %s", e)
        return None


def _summary_hash(summary: str) -> str:
    """计算 summary 的 md5 hash，用于去重。"""
    return hashlib.md5(summary.encode("utf-8")).hexdigest()


def store_extraction(
    extraction: dict[str, Any],
    episodic: EpisodicMemory,
    tracker: PredictionTracker,
    adapter: MarketDataAdapter | None = None,
) -> list[dict[str, Any]]:
    """将提取结果写入 episodic_events 和 predictions。

    写入 observation 前会计算 summary 的 md5 hash，并检查同 scope +
    content_hash 是否已存在——存在则跳过（避免重复对话产生重复事件）。

    Args:
        extraction: extract_from_conversation 的返回值
        episodic: EpisodicMemory
        tracker: PredictionTracker
        adapter: MarketDataAdapter（可选，用于自动填 entry_price）

    Returns:
        本次创建的预测列表，每条 {"id", "code", "name"}（无预测时为空列表）。
    """
    # 写 observations（按 code 记录 event_id，供 predictions 做 traceability 关联；
    # 按 code 记录修正后的 coverage，供同 code 的 prediction 写入依据覆盖）
    event_ids_by_code: dict[str, int] = {}
    coverage_by_code: dict[str, dict[str, bool]] = {}
    for obs in extraction.get("observations", []):
        try:
            code = obs.get("code")
            name = obs.get("name")
            data = obs.get("data", {})
            scope = obs.get("scope", "market")
            summary = obs.get("summary", "")
            coverage = _correct_data_coverage(
                obs.get("data_coverage"),
                data,
                adapter,
                code,
            )
            if code:
                coverage_by_code[code] = coverage
            # 去重：同 scope + content_hash 已存在则跳过
            content_hash = _summary_hash(summary)
            if episodic.exists_by_hash(scope, content_hash):
                _log.debug("extract: skip duplicate observation (scope=%s)", scope)
                continue

            event_id = episodic.write(
                event_type=obs.get("event_type", "analysis_record"),
                scope=scope,
                code=code,
                name=name,
                summary=summary,
                data=data,
                tags=obs.get("tags"),
                data_coverage=coverage,
                source="agent",
                confidence=obs.get("confidence", 0.5),
                content_hash=content_hash,
            )
            if code:
                event_ids_by_code[code] = event_id
            _log.debug("extract: wrote observation #%d for %s", event_id, code)
        except Exception as e:
            _log.warning("extract: failed to write observation: %s", e)

    # 写 predictions（关联同 code 的源 observation 事件 + 依据覆盖）
    created: list[dict[str, Any]] = []
    for pred in extraction.get("predictions", []):
        try:
            code = pred.get("code", "")
            if not code:
                continue

            # 自动填 entry_price（价格保持 Decimal 精度，比率为 float）
            entry_price = None
            change_pct = None
            if adapter is not None:
                try:
                    quote = adapter.get_quote(code)
                    if quote is not None:
                        price = getattr(quote, "price", None)
                        entry_price = Decimal(str(price)) if price else None
                        pct = getattr(quote, "change_pct", None)
                        change_pct = float(pct) if pct else None
                except Exception:
                    pass  # 拿不到报价不影响预测创建

            pred_id = tracker.create(
                code=code,
                name=pred.get("name"),
                prediction=pred.get("prediction", ""),
                direction=pred.get("direction", "neutral"),
                timeframe=pred.get("timeframe", "5d"),
                rationale=pred.get("rationale"),
                target_price=pred.get("target_price"),
                entry_price=entry_price,
                change_pct_at_creation=change_pct,
                data_coverage=coverage_by_code.get(code),
                source_event_id=event_ids_by_code.get(code),
            )
            created.append({"id": pred_id, "code": code, "name": pred.get("name")})
            _log.debug("extract: wrote prediction #%d for %s", pred_id, code)
        except Exception as e:
            _log.warning("extract: failed to write prediction: %s", e)
    return created
