"""事实抽取：从对话中提取结构化 observations + predictions。

对话结束后调 LLM（JSON response mode）提取结构化信息，
写入 episodic_events 和 predictions 表。

降级原则：LLM 提取失败（网络/API 错误）→ 静默跳过，不影响主对话流程。
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from mommy_chaogu.agent.episodic_memory import EpisodicMemory
    from mommy_chaogu.agent.prediction_tracker import PredictionTracker
    from mommy_chaogu.market_data.adapter import MarketDataAdapter

_log = logging.getLogger(__name__)


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


def extract_from_conversation(
    user_message: str,
    assistant_response: str,
    client: Any,
    model: str,
) -> dict[str, Any] | None:
    """用 LLM 从对话中提取结构化信息。

    Args:
        user_message: 用户消息
        assistant_response: agent 的回复
        client: OpenAI client（兼容 deepseek/kimi）
        model: 模型名

    Returns:
        {"observations": [...], "predictions": [...]} 或 None（提取失败/无内容）
    """
    prompt = _EXTRACTION_PROMPT.format(
        user_msg=user_message[:500],
        assistant_msg=assistant_response[:1000],
    )

    try:
        response = client.chat.completions.create(
            model=model,
            messages=[
                {
                    "role": "system",
                    "content": (
                        "你是一个信息提取助手。从投资对话中提取结构化信息。"
                        "只返回 JSON，不要加任何其他文字。"
                    ),
                },
                {"role": "user", "content": prompt},
            ],
            temperature=0.0,
        )

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


def store_extraction(
    extraction: dict[str, Any],
    episodic: EpisodicMemory,
    tracker: PredictionTracker,
    adapter: MarketDataAdapter | None = None,
) -> None:
    """将提取结果写入 episodic_events 和 predictions。

    Args:
        extraction: extract_from_conversation 的返回值
        episodic: EpisodicMemory
        tracker: PredictionTracker
        adapter: MarketDataAdapter（可选，用于自动填 entry_price）
    """
    # 写 observations（按 code 记录 event_id，供 predictions 做 traceability 关联）
    event_ids_by_code: dict[str, int] = {}
    for obs in extraction.get("observations", []):
        try:
            code = obs.get("code")
            name = obs.get("name")
            event_id = episodic.write(
                event_type=obs.get("event_type", "analysis_record"),
                scope=obs.get("scope", "market"),
                code=code,
                name=name,
                summary=obs.get("summary", ""),
                data=obs.get("data", {}),
                tags=obs.get("tags"),
                data_coverage=obs.get("data_coverage"),
                source="agent",
                confidence=obs.get("confidence", 0.5),
            )
            if code:
                event_ids_by_code[code] = event_id
            _log.debug("extract: wrote observation #%d for %s", event_id, code)
        except Exception as e:
            _log.warning("extract: failed to write observation: %s", e)

    # 写 predictions（关联同 code 的源 observation 事件）
    for pred in extraction.get("predictions", []):
        try:
            code = pred.get("code", "")
            if not code:
                continue

            # 自动填 entry_price
            entry_price = None
            change_pct = None
            if adapter is not None:
                try:
                    quote = adapter.get_quote(code)
                    if quote is not None:
                        entry_price = float(getattr(quote, "price", 0)) or None
                        change_pct = float(getattr(quote, "change_pct", 0)) or None
                except Exception:
                    pass  # 拿不到报价不影响预测创建

            tracker.create(
                code=code,
                name=pred.get("name"),
                prediction=pred.get("prediction", ""),
                direction=pred.get("direction", "neutral"),
                timeframe=pred.get("timeframe", "5d"),
                rationale=pred.get("rationale"),
                target_price=pred.get("target_price"),
                entry_price=entry_price,
                change_pct_at_creation=change_pct,
                source_event_id=event_ids_by_code.get(code),
            )
            _log.debug("extract: wrote prediction for %s", code)
        except Exception as e:
            _log.warning("extract: failed to write prediction: %s", e)
