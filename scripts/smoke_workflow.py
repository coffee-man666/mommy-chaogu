#!/usr/bin/env python
"""Network smoke test for the workflow compiler (not part of CI).

Usage: ``uv run python scripts/smoke_workflow.py``
"""

from __future__ import annotations

import argparse
import json

from mommy_chaogu.cli_commands.agent import _build_llm_client
from mommy_chaogu.workflow.compiler import WorkflowCompiler
from mommy_chaogu.workflow.definitions import get_default_registry

GOLDEN_SAMPLES = (
    (
        "当自选股主力净流入超过0.5%时，检查业绩催化和K线放量上涨",
        ("get_watchlist", "screen_inflow_stocks", "check_earnings_catalyst", "check_kline_signal"),
    ),
    (
        "从持仓中找出资金流入超过1%的股票，再看最近的业绩公告",
        ("get_portfolio", "screen_inflow_stocks", "check_earnings_catalyst"),
    ),
    (
        "筛选指定股票的5日线上穿20日线信号，并保留前20条",
        ("check_kline_signal",),
    ),
)


def main() -> int:
    parser = argparse.ArgumentParser(description="工作流编译器网络冒烟")
    parser.add_argument("--opinion", action="append", help="额外观点；默认运行 3 条固定观点")
    args = parser.parse_args()
    client, model, _ = _build_llm_client()
    if client is None or model is None:
        print("未配置 LLM，跳过 network smoke")
        return 2

    def chat_raw(messages: list[dict[str, str]]) -> str:
        response = client.chat.completions.create(model=model, messages=messages, temperature=0)
        return str(response.choices[0].message.content or "")

    compiler = WorkflowCompiler(chat_raw, existing_workflows=get_default_registry().all_workflows())
    samples = tuple((opinion, ()) for opinion in args.opinion) if args.opinion else GOLDEN_SAMPLES
    exit_code = 0
    for index, (opinion, expected) in enumerate(samples, start=1):
        print(f"\n--- opinion {index} ---\n{opinion}")
        if expected:
            print(f"expected skeleton: {' → '.join(expected)}")
        try:
            result = compiler.compile(opinion)
        except Exception as exc:
            exit_code = 2
            print(
                json.dumps(
                    {
                        "kind": "error",
                        "errors": [f"network smoke 调用 LLM 失败: {type(exc).__name__}: {exc}"],
                        "guidance": "检查 AGENT_PROVIDER / AGENT_MODEL 与 provider 的模型列表。",
                    },
                    ensure_ascii=False,
                    indent=2,
                )
            )
            continue
        if result.spec is not None:
            if expected:
                actual = tuple(step.tool_name for step in result.spec.steps)
                print(f"golden skeleton match: {actual == expected}")
            print(json.dumps(result.spec.to_dict(), ensure_ascii=False, indent=2))
        elif result.questions:
            print(json.dumps({"kind": "questions", "questions": result.questions}, ensure_ascii=False, indent=2))
        else:
            print(json.dumps({"kind": "error", "errors": result.errors, "guidance": result.guidance}, ensure_ascii=False, indent=2))
            exit_code = 2
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
